"""Make autonomous EVM entries obey OrcAgent's USDC-first trading invariant.

The legacy multi-chain bot scanner was added before OrcAgent switched EVM BUYs
onto the shared 0x Gasless / USDC execution flow.  It still had an early
``native balance <= 0`` return, so a perfectly funded USDC wallet could press
Start Trading, scan Base/BSC/Arbitrum/Polygon/Robinhood, and then silently skip
every BUY before the gasless execution layer was even reached.

Keep the existing scanner unchanged whenever the wallet already has native gas
(it may contain newer scoring refinements).  Only take over the exact case the
old gate cannot handle: no native balance / unavailable balance.  The fallback
uses the same market/safety gates and delegates execution to ``_evm_buy_flow``
so autonomous BUYs share the exact same USDC ceiling, gasless/bridge handling,
fees, position tracking and copy-trade hooks as a Live Market BUY.
"""

import threading


def install(d):
    if getattr(d, '_multichain_auto_bot_installed', False):
        return
    d._multichain_auto_bot_installed = True

    original = getattr(d, '_bot_scan_evm_entry', None)
    if not callable(original):
        # Fail loudly at startup rather than pretending multi-chain auto-entry
        # is installed while the underlying bot implementation is missing.
        raise RuntimeError('OrcAgent multi-chain bot scanner is unavailable')

    def _response_json(resp):
        """Normalize Flask Response / (Response, status) / dict results."""
        if isinstance(resp, tuple):
            resp = resp[0]
        if isinstance(resp, dict):
            return resp
        try:
            return resp.get_json(silent=True) or {}
        except TypeError:
            try:
                return resp.get_json() or {}
            except Exception:
                return {}
        except Exception:
            return {}

    pending_auto_buys = {}  # wallet + chain + mint -> wall-clock expiry
    pending_lock = threading.Lock()  # atomically reserve before network I/O

    def _gasless_entry(user_id, wallet, positions, chain, enc_blob_evm,
                       evm_address, min_trade_usdc, blacklisted,
                       m5_min, m5_max, pref_scam_filter, short):
        # One unresolved bridge per wallet/chain: otherwise a 2s loop could
        # queue multiple expensive buys before the first balance arrives.
        now = d.time.time()
        with pending_lock:
            for key, expiry in list(pending_auto_buys.items()):
                if expiry <= now:
                    pending_auto_buys.pop(key, None)
            if any(w == wallet and c == chain and expiry > now
                   for (w, c, _mint), expiry in pending_auto_buys.items()):
                return False
            reserved = set(pending_auto_buys)
        # Candidate universe is already multi-chain. Keep one pass per chain so
        # max_positions remains a per-chain ceiling in user_trader_loop().
        try:
            candidates = [
                t for t in d._get_scanner_cached()
                if t.get('chain') == chain
                and t.get('mint')
                and t.get('mint') not in blacklisted
                and positions.get(t.get('mint'), {}).get('amount', 0) == 0
                and d._bot_gainers_eligible(t)
                and (wallet, chain, t.get('mint')) not in reserved
            ]
        except Exception as exc:
            print(f'[bot-{chain}] {short} scanner failed: {exc}', flush=True)
            return False
        if not candidates:
            return False

        try:
            ai_filters = d.get_ai_active_filters()
        except Exception:
            ai_filters = {'min_liquidity_usd': 0, 'min_pair_age_minutes': 0}
        try:
            min_mcap = d._min_marketcap_for_stake(min_trade_usdc)
        except Exception:
            min_mcap = 0

        now_ts = d.time.time()
        qualifying = []
        for token in candidates:
            if float(token.get('market_cap') or 0) < float(min_mcap or 0):
                continue
            if float(token.get('liquidity_usd') or 0) < float(ai_filters.get('min_liquidity_usd') or 0):
                continue
            created = token.get('pair_created_at') or 0
            age_min = (now_ts - created / 1000.0) / 60.0 if created > 0 else 0
            if created > 0 and age_min < float(ai_filters.get('min_pair_age_minutes') or 0):
                continue
            qualifying.append(token)
        if not qualifying:
            return False

        qualifying.sort(key=lambda t: float(t.get('price_change_24h') or 0), reverse=True)
        for token in qualifying[:5]:
            mint = token['mint']
            symbol = token.get('symbol') or mint[:8]
            try:
                td = d.get_token_data(mint, fast=True, chain=chain)
            except Exception:
                td = None
            if not td or not td.get('price') or not d._bot_gainers_eligible(td):
                continue

            m5 = float(td.get('change5m') or 0)
            h1 = float(td.get('change1h') or 0)
            v5m = float(td.get('volume5m') or 0)
            v1h = float(td.get('volume1h') or 0)
            momentum_ok = ((m5 >= m5_min or h1 >= m5_min) if m5_max is None
                           else (m5_min <= m5 <= m5_max or m5_min <= h1 <= m5_max))
            fast_pump = d._fast_pump_check(mint, chain=chain)
            if (not (momentum_ok or fast_pump) or h1 >= 50
                    or not (v5m > 0 and v1h > 0 and v5m > v1h / 12.0)):
                continue

            if pref_scam_filter:
                try:
                    hp = d._check_evm_honeypot(mint, chain)
                except Exception:
                    hp = {'ok': False, 'is_honeypot': True, 'sell_tax': 100}
                if hp.get('no_provider'):
                    if float(token.get('liquidity_usd') or 0) < (
                            float(ai_filters.get('min_liquidity_usd') or 0)
                            * d.NO_HONEYPOT_PROVIDER_LIQ_MULT):
                        continue
                elif not hp.get('ok') or hp.get('is_honeypot'):
                    d.add_user_log(wallet, f'[bot-{chain}] SKIPPING {symbol} — honeypot check failed')
                    continue
                if float(hp.get('sell_tax') or 0) >= 15:
                    d.add_user_log(wallet, f'[bot-{chain}] SKIPPING {symbol} — sell tax too high')
                    continue

            # Reserve before any bridge/swap network call. Two bot threads can
            # scan the same wallet concurrently after a restart or duplicate start.
            order_key = (wallet, chain, mint)
            with pending_lock:
                now = d.time.time()
                if any(w == wallet and c == chain and expiry > now
                       for (w, c, _), expiry in pending_auto_buys.items()):
                    return False
                pending_auto_buys[order_key] = now + 1800
            d.add_user_log(wallet, f'[bot-{chain}] Best: {symbol} — BUYING with USDC')
            try:
                # user_trader_loop runs in a plain background Thread. The
                # shared buy flow returns Flask JSON responses, so it needs an
                # application context even though there is no HTTP request.
                # Without this, the first real qualifying EVM candidate dies
                # at jsonify() with "Working outside of application context".
                app = getattr(d, 'app', None)
                if app is not None and hasattr(app, 'app_context'):
                    with app.app_context():
                        resp = d._evm_buy_flow(
                            wallet,
                            {'token_address': mint, 'amount_usdc': float(min_trade_usdc)},
                            chain,
                            wallet_label='EVM',
                        )
                else:
                    # Keeps the adapter unit-testable with a light namespace.
                    resp = d._evm_buy_flow(
                        wallet,
                        {'token_address': mint, 'amount_usdc': float(min_trade_usdc)},
                        chain,
                        wallet_label='EVM',
                    )
                body = _response_json(resp)
            except Exception as exc:
                with pending_lock:
                    pending_auto_buys.pop(order_key, None)
                d.add_user_log(wallet, f'[bot-{chain}] BUY failed — {symbol}: {type(exc).__name__}')
                continue

            if body.get('ok'):
                with pending_lock:
                    pending_auto_buys[order_key] = d.time.time() + 60
                return True
            # A bridge/gasless preparation may intentionally return pending.
            # That is not a failed strategy signal; the existing completion
            # worker will execute the requested BUY once funding settles.
            if body.get('pending'):
                with pending_lock:
                    pending_auto_buys[order_key] = d.time.time() + 1800
                d.add_user_log(wallet, f'[bot-{chain}] {symbol} — funding/bridge pending; suppress duplicate BUY attempts')
                return True
            with pending_lock:
                pending_auto_buys.pop(order_key, None)
            d.add_user_log(wallet, f'[bot-{chain}] BUY failed — {symbol}: {body.get("msg") or body.get("error") or "execution refused"}')
        return False

    def scan(user_id, wallet, positions, chain, enc_blob_evm,
             min_trade_usdc, blacklisted, m5_min, m5_max,
             pref_scam_filter, short):
        # Native gas must never be a prerequisite for reaching OrcAgent's
        # gasless execution layer. If it exists, keep using the mature legacy
        # scanner. If it does not, run the equivalent scan and hand the BUY to
        # the shared USDC execution flow.
        # Match dashboard._bot_scan_evm_entry's public signature exactly.
        # The EVM address is implementation detail, so derive it from the
        # encrypted trading key only for this balance check and never persist
        # the decrypted key across scans.
        evm_address = ''
        try:
            with d._use_key(enc_blob_evm, wallet) as private_key:
                evm_address = d._EvmAccount.from_key(private_key).address
            native = d.get_evm_native_balance(evm_address, chain)
        except Exception:
            # If address derivation or the native-balance RPC is unavailable,
            # fall through to the USDC/gasless execution path. That path
            # performs its own authenticated key handling and balance checks.
            native = 0
        if native and native > 0:
            # The native-funded route executes its own swap internally. Guard
            # that entire path too, not just USDC-only/gasless submissions.
            order_key = (wallet, chain, '__native_scan__')
            with pending_lock:
                now = d.time.time()
                if any(w == wallet and c == chain and expiry > now
                       for (w, c, _), expiry in pending_auto_buys.items()):
                    return False
                pending_auto_buys[order_key] = now + 1800
            try:
                bought = original(user_id, wallet, positions, chain, enc_blob_evm,
                                  min_trade_usdc, blacklisted,
                                  m5_min, m5_max, pref_scam_filter, short)
            except Exception:
                with pending_lock:
                    pending_auto_buys.pop(order_key, None)
                raise
            with pending_lock:
                if bought:
                    pending_auto_buys[order_key] = d.time.time() + 60
                else:
                    pending_auto_buys.pop(order_key, None)
            return bought
        return _gasless_entry(user_id, wallet, positions, chain, enc_blob_evm,
                              evm_address, min_trade_usdc, blacklisted,
                              m5_min, m5_max, pref_scam_filter, short)

    d._bot_scan_evm_entry = scan
