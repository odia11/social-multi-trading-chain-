#!/usr/bin/env python3
"""Check, from the server itself, everything this app depends on outside it.

WHY THIS EXISTS
The development sandbox has no route to 0x, Jupiter, DexScreener or any RPC,
so the adapters the trade engine is built on have never run against a live
API. Every claim about them is therefore theory. This script is the missing
half: it runs where the app runs, calls the real services with the real keys,
and prints what it found.

Run it on the server:

    cd /path/to/the/app && python3 tools/verify_live.py

It is READ-ONLY. It quotes, reads balances and prices, and stops there --
nothing is signed, nothing is sent, no key is ever printed. The one thing it
proves about money is arithmetic: that a quote's parts add up to the ceiling
the user would have been shown.

Exit code is 0 when everything essential passed, 1 otherwise, so it can also
be used as a post-deploy check.
"""
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, BAD, WARN = '  OK  ', ' FAIL ', ' WARN '
results = []


def report(status, name, detail=''):
    results.append((status, name))
    line = f'[{status}] {name}'
    if detail:
        line += f'\n         {detail}'
    print(line, flush=True)


def section(title):
    print(f'\n── {title} ' + '─' * max(0, 60 - len(title)), flush=True)


def attempt(name, fn, essential=True):
    """Run one check. A raised exception is a failure with its reason, never a
    traceback that stops the rest of the report."""
    t0 = time.time()
    try:
        detail = fn()
        ms = int((time.time() - t0) * 1000)
        report(OK, f'{name} ({ms} ms)', detail or '')
        return True
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        report(BAD if essential else WARN, f'{name} ({ms} ms)',
               f'{type(e).__name__}: {e}')
        return False


def main():
    print('OrcAgent — live dependency check')
    print('=' * 68)

    # ── configuration, without printing any of it ──
    section('configuration')

    def cfg():
        import dashboard as d
        missing = [k for k in ('ENCRYPTION_KEY', 'SECRET_KEY') if not os.getenv(k)]
        if missing:
            raise RuntimeError(f'missing required variables: {", ".join(missing)}')
        # Presence only. A value is never printed, here or anywhere below.
        present = [k for k in ('ZEROX_API_KEY', 'GAS_SPONSOR_PRIVATE_KEY',
                               'SOL_GAS_SPONSOR_PRIVATE_KEY', 'JUPITER_PROXY',
                               'HELIUS_API_KEY', 'PUBLIC_HOST', 'DATA_DIR')
                   if os.getenv(k)]
        absent = [k for k in ('ZEROX_API_KEY', 'GAS_SPONSOR_PRIVATE_KEY',
                              'SOL_GAS_SPONSOR_PRIVATE_KEY')
                  if not os.getenv(k)]
        out = f'set: {", ".join(present) or "none"}'
        if absent:
            out += f'\n         not set: {", ".join(absent)}'
        out += (f'\n         production={d.IS_PRODUCTION} host={d.PUBLIC_HOST} '
                f'data_dir={d._DATA_DIR}')
        return out

    attempt('app imports and configuration reads', cfg)

    def storage():
        import dashboard as d
        return d._storage_breakdown()

    attempt('storage', storage)

    # ── the chains ──
    section('EVM chains — RPC')
    import dashboard as d

    for chain in list(d.EVM_CHAINS):
        def rpc(chain=chain):
            try:
                w3 = d._get_web3(chain)
                block = w3.eth.block_number
                gas = w3.eth.gas_price
            except Exception as e:
                # Public endpoints increasingly refuse datacenter addresses, and
                # a server move changes yours. Naming the variable to set turns
                # this from a puzzle into one line in the env file.
                url = d.EVM_CHAINS[chain].get('rpc_url', '?')
                raise RuntimeError(
                    f'{type(e).__name__}: {e}\n         endpoint: {url}\n'
                    f'         set {chain.upper()}_RPC_URL in /etc/orcagent.env '
                    f'to a provider that accepts this server') from None
            return f'block {block}, gas {gas / 1e9:.3f} gwei'
        attempt(f'{chain}: RPC reachable', rpc)

    section('0x — swap quotes')
    if not os.getenv('ZEROX_API_KEY'):
        report(BAD, '0x', 'ZEROX_API_KEY is not set — no EVM trade can be priced')
    else:
        for chain in list(d.EVM_CHAINS):
            def price(chain=chain):
                usd = d._te_native_price_usd(chain)
                return f'1 {d.EVM_CHAINS[chain]["native_symbol"]} = ${usd}'
            attempt(f'{chain}: native price via 0x', price)

            def gas_usd(chain=chain):
                return f'one swap costs about ${d._te_gas_usd(chain)}'
            attempt(f'{chain}: gas priced in USD', gas_usd)

    section('Solana')

    def sol_price():
        """Fetch it the way the app does, rather than reading the global.

        _sol_price_usd is only assigned inside the scanner loop, which runs
        every 120 seconds in a background thread. A script that has just
        imported the module always sees 0 there -- so checking that global
        reported a failure that said nothing about whether the price feed
        works. It checks the feed itself now, and hands the result to the
        module so the Solana gas figures below have something to work with.
        """
        r = d._dex_get('https://api.dexscreener.com/latest/dex/tokens/' + d.SOL_MINT,
                       timeout=8)
        if not r or r.status_code != 200:
            raise RuntimeError(f'price feed returned HTTP '
                               f'{getattr(r, "status_code", "no response")}')
        pairs = r.json().get('pairs') or []
        p = next((x for x in pairs
                  if (x.get('quoteToken') or {}).get('address') == d.USDC_MINT),
                 pairs[0] if pairs else None)
        price = float((p or {}).get('priceUsd', 0) or 0)
        if price <= 1:
            raise RuntimeError('no usable SOL/USDC pair in the feed response')
        d._sol_price_usd = price
        return f'SOL = ${price:.2f}'
    attempt('SOL price feed', sol_price)

    def jupiter():
        q = d._jupiter_quote(d.SOL_MINT, d.USDC_MINT, 100_000_000)   # 0.1 SOL
        out = q.get('outAmount')
        if not out:
            raise RuntimeError(f'no route returned: {str(q)[:200]}')
        return f'0.1 SOL routes to {int(out) / 1e6:.4f} USDC'
    attempt('Jupiter quote', jupiter)

    def dexscreener():
        r = d._dex_get('https://api.dexscreener.com/latest/dex/tokens/'
                       + d.SOL_MINT, timeout=10)
        if not r or r.status_code != 200:
            raise RuntimeError(f'HTTP {getattr(r, "status_code", "no response")}')
        return f'{len(r.json().get("pairs") or [])} pairs returned'
    attempt('DexScreener', dexscreener)

    # ── the thing that has never been tested: a real priced trade ──
    section('trade engine — a real quote, priced end to end')
    from decimal import Decimal

    # A quote is built FOR somebody, and 0x rejects a taker that is not a real
    # address -- which is how the native-token sentinel being passed here
    # produced a 400 on every chain. Use a wallet that actually exists: the
    # gas sponsor if configured, otherwise any user's EVM address.
    taker = ''
    try:
        taker = d._gas_sponsor_address() or ''
    except Exception:
        pass
    if not taker:
        try:
            conn = __import__('sqlite3').connect(d.DB_FILE)
            try:
                row = conn.execute(
                    "SELECT bsc_wallet_address FROM users WHERE bsc_wallet_address "
                    "IS NOT NULL AND bsc_wallet_address != '' LIMIT 1").fetchone()
                taker = (row or [''])[0] or ''
            finally:
                conn.close()
        except Exception:
            pass
    if not taker:
        report(WARN, 'no wallet to quote for',
               'a quote is built for a specific address, and there is no gas '
               'sponsor and no user wallet to use — so the ceiling check below '
               'is skipped rather than run against a made-up taker')

    # Buy the chain's NATIVE token with the stable the trade is funded from.
    # This used to quote the chain's own USDC -- which is what build_quote
    # SELLS -- so every request asked 0x to route USDC into USDC and was
    # refused, identically, on all five chains. A token cannot be routed to
    # itself; native is the one pair guaranteed to exist everywhere.
    priced_any = False
    for chain, cfg_ in d.EVM_CHAINS.items():
        token = d.BNB_NATIVE_ADDR      # the native-token sentinel, valid as a BUY token
        if not os.getenv('ZEROX_API_KEY') or not taker:
            continue

        def quote(chain=chain, token=token):
            nonlocal priced_any
            q = d.build_quote(
                d.QuoteRequest(user_id=0, wallet='verify', source_chain=chain,
                               destination_chain=chain, token_address=token,
                               max_spend_usd=Decimal('100'),
                               taker_address=taker),
                swap_provider=d._te_swap_provider(chain),
                gas_estimator=d._te_gas_usd,
                fee_rate=Decimal(str(d.FEE_RATE_TXN)),
                gas_is_sponsored=lambda c: False,
            )
            b = q.to_dict()
            purchase = Decimal(b['token_purchase_usd'])
            costs = sum(Decimal(v) for v in b['costs_by_kind'].values())
            total = purchase + costs
            # THE CLAIM THIS WHOLE REWRITE RESTS ON: a $100 trade costs $100.
            if total > Decimal('100'):
                raise AssertionError(
                    f'CEILING BROKEN: purchase ${purchase} + costs ${costs} '
                    f'= ${total}, above the $100 the user entered')
            priced_any = True
            lines = ' · '.join(f'{k} ${v}' for k, v in b['costs_by_kind'].items())
            return (f'$100 max -> buys ${purchase} of '
                    f'{d.EVM_CHAINS[chain]["native_symbol"]}   [{lines}]\n'
                    f'         total ${total} — within the ceiling'
                    + ('' if b['can_execute'] else
                       f"\n         NOT EXECUTABLE: {b['reject_reason']}"))

        attempt(f'{chain}: $100 quote adds up', quote)

    if not priced_any:
        report(WARN, 'no chain could be priced',
               'without a working 0x key, an RPC and a wallet to quote for, no '
               'EVM trade can be priced')

    # ── the wallets that have to hold something ──
    section('sponsor wallets')

    # Whether an empty sponsor wallet is a problem depends entirely on the
    # rule, so the rule is reported first and the balance checks read it.
    _fronting = bool(getattr(d, 'ORCAGENT_FRONTS_GAS', False))
    if _fronting:
        report(OK, 'OrcAgent fronts gas',
               'a user holding only USDC can trade on an EVM chain without first '
               'acquiring its gas token — the sponsor puts up the native token and '
               'the trade\'s own quote charges the user for it. These wallets need '
               'a few euros each; that is float, and it comes back.')
    else:
        report(OK, 'this deployment fronts nothing',
               'ORCAGENT_FRONTS_GAS is off, so users fund their own gas and the '
               'sponsor wallets are meant to be empty — a low balance here is not '
               'a problem to fix')

    # What counts as "enough" to keep fronting: a few dollars per chain, which
    # is dozens of first transactions. Below it the next user to arrive with
    # only USDC falls through to the slow bridge, which is the failure this is
    # here to catch BEFORE a user hits it.
    #
    # Per SYMBOL, not per bucket. Grouping BNB with POL was wrong in both
    # directions at once: one BNB is worth hundreds of times one POL, so a
    # single figure either nags forever about a BSC wallet holding plenty, or
    # calls a Polygon wallet funded when it holds fifteen cents. These are
    # each roughly the same few dollars in their own token.
    SPONSOR_MIN = {
        'ETH': 0.002,     # Base, Arbitrum, Robinhood Chain
        'BNB': 0.01,
        'POL': 20.0,
        'MATIC': 20.0,
    }
    SPONSOR_MIN_DEFAULT = 0.002       # an unknown native token is priced like ETH
    SPONSOR_LOW_SOL = 0.05

    def evm_sponsor():
        if not _fronting:
            return 'not used (ORCAGENT_FRONTS_GAS is off)'
        addr = d._gas_sponsor_address()
        if not addr:
            raise RuntimeError('GAS_SPONSOR_PRIVATE_KEY is not set, but this '
                               'deployment fronts gas — every EVM wallet at zero '
                               'falls through to the slower SOL bootstrap bridge')
        out, empty, unreadable = [], [], []
        for chain in d.EVM_CHAINS:
            try:
                bal = d.get_evm_native_balance(addr, chain)
                sym = d.EVM_CHAINS[chain]['native_symbol']
                low = SPONSOR_MIN.get(sym, SPONSOR_MIN_DEFAULT)
                out.append(f'{chain} {bal:.5f} {sym}' + ('  ← low' if bal < low else ''))
                if bal < low:
                    # Says how much, not just which: "send BNB" leaves the
                    # person guessing at an amount, and guessing low is the
                    # one that leaves the wallet still unable to do its job.
                    empty.append(f'{chain} (send ~{low:g} {sym})')
            except Exception as e:
                out.append(f'{chain} unreadable ({type(e).__name__})')
                unreadable.append(chain)
        line = f'{addr}\n         ' + ' · '.join(out)
        if empty:
            # Raised, not returned: the wallet being readable is not the
            # thing being checked — its being able to do its job is.
            raise RuntimeError(line + '\n         top these up: ' + ', '.join(empty))
        return line
    attempt('EVM gas sponsor is funded', evm_sponsor, essential=False)

    def sol_sponsor():
        if not _fronting:
            return 'not used (ORCAGENT_FRONTS_GAS is off)'
        addr = d._sol_gas_sponsor_address()
        if not addr:
            raise RuntimeError('SOL_GAS_SPONSOR_PRIVATE_KEY is not set — users need '
                               'their own SOL for network fees')
        bal = d._get_user_sol(addr)
        line = f'{addr}  {bal:.5f} SOL'
        if bal < SPONSOR_LOW_SOL:
            raise RuntimeError(line + f'\n         below {SPONSOR_LOW_SOL} SOL — '
                               f'send a little SOL to this address')
        return line
    attempt('Solana gas sponsor is funded', sol_sponsor, essential=False)

    # ── what it all means ──
    section('summary')
    failed = [n for s, n in results if s == BAD]
    warned = [n for s, n in results if s == WARN]
    print(f'{len(results) - len(failed) - len(warned)} passed · '
          f'{len(warned)} warning · {len(failed)} failed')
    for n in failed:
        print(f'  FAILED:  {n}')
    for n in warned:
        print(f'  warning: {n}')
    if not failed:
        print('\nEverything the app trades through is reachable from this server.')
    else:
        print('\nThe failures above are things the app needs at runtime. A trade '
              'that depends on one of them will fail for a real user.')
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        print('\nThe check itself could not run. That is usually a missing '
              'ENCRYPTION_KEY/SECRET_KEY, or being run from the wrong directory.')
        sys.exit(1)
