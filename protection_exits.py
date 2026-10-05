"""Protected exits: consistent units, durable trigger intents and independent sales."""
import math
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_SELL_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix='protected-sell')
_FEED_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='exit-price')
_GUARD = threading.Lock()
_INTENT_LOCK = threading.RLock()
_BUSY = set()
_STORES = set()
_PRICE_CONDITION = threading.Condition()
_PRICE_REVISION = 0

def price_revision():
    with _PRICE_CONDITION:
        return _PRICE_REVISION

def price_updated():
    global _PRICE_REVISION
    with _PRICE_CONDITION:
        _PRICE_REVISION += 1
        _PRICE_CONDITION.notify_all()

def wait_for_price(revision, timeout, stop_event=None):
    # All monitors see the same tick. No clearing a shared Event, no busy polling.
    with _PRICE_CONDITION:
        return _PRICE_CONDITION.wait_for(
            lambda: _PRICE_REVISION != revision or
                    (stop_event is not None and stop_event.is_set()),
            timeout=max(0, timeout))



def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def market_price(pos, usd_price, sol_usd):
    price = positive(usd_price)
    if pos.get('chain', 'solana') == 'solana' and pos.get('base', 'SOL') == 'SOL':
        sol_usd = positive(sol_usd)
        return price / sol_usd if sol_usd else 0.0
    return price


def _connect(db):
    with _GUARD:
        if db not in _STORES:
            with sqlite3.connect(db, timeout=3) as c:
                c.execute("""CREATE TABLE IF NOT EXISTS protection_exit_intents (
                    user_id INTEGER NOT NULL, wallet TEXT NOT NULL, mint TEXT NOT NULL,
                    chain TEXT NOT NULL, opened_at REAL NOT NULL, reason TEXT NOT NULL,
                    trigger_price REAL NOT NULL, triggered_at REAL NOT NULL,
                    PRIMARY KEY(user_id, wallet, mint, chain, opened_at))""")
                c.execute("""CREATE TABLE IF NOT EXISTS protection_stage_intents (
                    user_id INTEGER NOT NULL,wallet TEXT NOT NULL,mint TEXT NOT NULL,
                    chain TEXT NOT NULL,opened_at REAL NOT NULL,data TEXT NOT NULL,
                    PRIMARY KEY(user_id,wallet,mint,chain,opened_at))""")
                c.execute("""CREATE TABLE IF NOT EXISTS protection_stage_state (
                    user_id INTEGER NOT NULL,wallet TEXT NOT NULL,mint TEXT NOT NULL,
                    chain TEXT NOT NULL,opened_at REAL NOT NULL,
                    tp1_hit INTEGER NOT NULL DEFAULT 0,tp2_hit INTEGER NOT NULL DEFAULT 0,
                    trail_peak REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(user_id,wallet,mint,chain,opened_at))""")
            _STORES.add(db)
    return sqlite3.connect(db, timeout=3)


def _identity(uid, wallet, mint, pos):
    return (uid, wallet, mint, pos.get('chain', 'solana'), float(pos.get('opened_at') or 0))


def pending(db, uid, wallet, mint, pos):
    if pos.get('protect') is False or pos.get('source') == 'manual':
        return None
    if '_protection_intent' in pos:
        return pos['_protection_intent']
    try:
        with _connect(db) as c:
            row = c.execute("""SELECT reason, trigger_price, triggered_at FROM protection_exit_intents
                WHERE user_id=? AND wallet=? AND mint=? AND chain=? AND opened_at=?""",
                _identity(uid, wallet, mint, pos)).fetchone()
        intent = dict(reason=row[0], price=row[1], triggered_at=row[2]) if row else None
        pos['_protection_intent'] = intent
        return intent
    except sqlite3.Error:
        # Do not memoize a failed read; recovery will be retried next pass.
        return None


def latch(db, uid, wallet, mint, pos, reason, price):
    with _INTENT_LOCK:
        return _latch(db, uid, wallet, mint, pos, reason, price)


def _latch(db, uid, wallet, mint, pos, reason, price):
    intent = pending(db, uid, wallet, mint, pos)
    if intent and not pos.get('_protection_persist_failed'):
        return intent
    intent = intent or dict(reason=reason, price=positive(price), triggered_at=time.time())
    pos['_protection_intent'] = intent
    try:
        with _connect(db) as c:
            c.execute("""INSERT OR IGNORE INTO protection_exit_intents
                VALUES (?,?,?,?,?,?,?,?)""",
                _identity(uid, wallet, mint, pos) +
                (intent['reason'], intent['price'], intent['triggered_at']))
            row = c.execute("""SELECT reason,trigger_price,triggered_at FROM protection_exit_intents
                WHERE user_id=? AND wallet=? AND mint=? AND chain=? AND opened_at=?""",
                _identity(uid, wallet, mint, pos)).fetchone()
        intent = dict(reason=row[0], price=row[1], triggered_at=row[2])
        pos['_protection_intent'] = intent
        pos.pop('_protection_persist_failed', None)
    except sqlite3.Error:
        # A full disk must not stop an urgent exit. Keep the intent in RAM and
        # expose the persistence failure rather than silently dropping a hit.
        pos['_protection_persist_failed'] = True
    return intent


def clear(db, uid, wallet, mint, pos):
    with _connect(db) as c:
        c.execute("""DELETE FROM protection_exit_intents WHERE
            user_id=? AND wallet=? AND mint=? AND chain=? AND opened_at=?""",
            _identity(uid, wallet, mint, pos))
        c.execute("""DELETE FROM protection_stage_intents WHERE
            user_id=? AND wallet=? AND mint=? AND chain=? AND opened_at=?""",
            _identity(uid,wallet,mint,pos))
        c.execute("""DELETE FROM protection_stage_state WHERE
            user_id=? AND wallet=? AND mint=? AND chain=? AND opened_at=?""",
            _identity(uid,wallet,mint,pos))


def dispatch(ctx, uid, us, wallet, mint, pos, price, symbol, reason,
             notify, enc_sol, enc_evm, **record):
    # Persist the crossing BEFORE scheduling. A rebound or process restart
    # cannot turn an already-triggered stop-market exit off again.
    intent = latch(ctx['DB_FILE'], uid, wallet, mint, pos, reason, price)
    if pos.get('_protection_persist_failed'):
        latch(ctx['DB_FILE'], uid, wallet, mint, pos, intent['reason'], intent['price'])
    key = (ctx['DB_FILE'],) + _identity(uid, wallet, mint, pos)
    with _GUARD:
        if key in _BUSY or time.monotonic() < pos.get('_exit_retry_at', 0):
            return False
        _BUSY.add(key)

    def sell():
        try:
            current = us['positions'].get(mint) or {}
            if positive(current.get('amount')) == 0 or _identity(uid, wallet, mint, current) != key[1:]:
                return
            # This callback holds the shared manual/automatic sell lock until
            # the confirmed position close. Other mints execute independently.
            ok, _, _ = ctx['_bot_execute_exit'](
                uid, us, wallet, mint, current, positive(price) or intent['price'],
                symbol, current['amount'], current.get('spend', 0),
                intent['reason'], notify, enc_sol, enc_evm, True, **record)
            if ok:
                clear(ctx['DB_FILE'], uid, wallet, mint, current)
            else:
                current['_sell_fails'] = current.get('_sell_fails', 0) + 1
                current['_exit_retry_at'] = time.monotonic() + 1.0
                if current['_sell_fails'] == 1 or current['_sell_fails'] % 30 == 0:
                    ctx['add_user_log'](wallet, 'Exit not confirmed — position remains open; retry queued')
                if current['_sell_fails'] == ctx.get('EXIT_SELL_FAIL_ALERT', 5):
                    ctx['_send_push_notification'](
                        uid, 'Could not sell ' + str(symbol)[:24] + ' yet',
                        intent['reason'] + ' — sale is not confirmed. Retrying; you can sell manually.',
                        '/bot-overview', tag='sellfail-' + mint[:16])
        except Exception as exc:
            pos['_exit_retry_at'] = time.monotonic() + 1.0
            print('[protected-exit] user=%s mint=%s error=%s' % (uid, mint, type(exc).__name__), flush=True)
        finally:
            with _GUARD:
                _BUSY.discard(key)
    try:
        _SELL_POOL.submit(sell)
        return True
    except RuntimeError:
        with _GUARD:
            _BUSY.discard(key)
        return False


def prices(ctx, mints):
    """Shared nonblocking feed. Source I/O never stops threshold evaluation."""
    now = time.time()
    with ctx['_exit_price_lock']:
        for mint, chain in mints.items():
            ctx['_exit_watched'][mint] = (chain or 'solana', now + ctx['_EXIT_WATCH_TTL'])
        for mint in list(ctx['_exit_watched']):
            if ctx['_exit_watched'][mint][1] < now:
                del ctx['_exit_watched'][mint]
                ctx['_exit_price_cache'].pop(mint, None)
        due = {m:c for m,(c,_) in ctx['_exit_watched'].items()
               if now - ctx['_exit_price_cache'].get(m, (0, 0))[0] >= ctx['_EXIT_PRICE_TTL']}
    if due and ctx['_exit_fetch_lock'].acquire(blocking=False):
        def refresh():
            try:
                started = time.time()
                got = ctx['_exit_fetch_prices'](due)
                stamp = time.time()
                with ctx['_exit_price_lock']:
                    for mint, price in got.items():
                        if mint in due and positive(price) and ctx['_exit_price_cache'].get(mint,(0,0))[0] < started:
                            ctx['_exit_price_cache'][mint] = (stamp, float(price))
                if got:
                    price_updated()
            except Exception as exc:
                print('[exit-price] ' + type(exc).__name__, flush=True)
            finally:
                ctx['_exit_fetch_lock'].release()
        try:
            _FEED_POOL.submit(refresh)
        except RuntimeError:
            ctx['_exit_fetch_lock'].release()
    with ctx['_exit_price_lock']:
        return {m:v[1] for m in mints
                if (v:=ctx['_exit_price_cache'].get(m))
                and now-v[0] <= ctx['_EXIT_PRICE_MAX_AGE'] and positive(v[1])}

def stop_hit(price, entry, fraction):
    price, entry = positive(price), positive(entry)
    target = entry * (1 - float(fraction))
    return bool(price and entry and target > 0 and
                (price <= target or math.isclose(price, target, rel_tol=1e-12)))


def profit_hit(price, entry, fraction):
    price, entry = positive(price), positive(entry)
    target = entry * (1 + float(fraction))
    return bool(price and entry and (price >= target or math.isclose(price, target, rel_tol=1e-12)))


def fetch_prices(ctx, mints):
    """Jupiter and DexScreener race concurrently; publish each completed batch."""
    from concurrent.futures import as_completed
    sol = [m for m,c in mints.items() if (c or 'solana') == 'solana']
    key = (ctx['os'].getenv('JUPITER_API_KEY', '') or '').strip()
    host = 'https://api.jup.ag' if key else 'https://lite-api.jup.ag'
    headers = {'Accept':'application/json', 'User-Agent':'OrcAgent/1.0'}
    if key:
        headers['x-api-key'] = key

    def jupiter(chunk):
        try:
            r = ctx['requests'].get(host+'/price/v3?ids='+','.join(chunk), headers=headers, timeout=1.5)
            body = r.json() if r.status_code == 200 else {}
            return {m:positive(v.get('usdPrice')) for m,v in body.items()
                    if m in chunk and isinstance(v,dict) and positive(v.get('usdPrice'))}
        except Exception:
            return {}

    def dex(chunk):
        try:
            r = ctx['_dex_get']('https://api.dexscreener.com/latest/dex/tokens/'+','.join(chunk),
                                timeout=1.5, ttl_override=ctx['_EXIT_PRICE_TTL'])
            best = {}
            for p in ((r.json().get('pairs') or []) if r else []):
                m = (p.get('baseToken') or {}).get('address')
                price = positive(p.get('priceUsd'))
                liq = positive((p.get('liquidity') or {}).get('usd'))
                if m in chunk and p.get('chainId') == 'solana' and price and liq >= best.get(m,(-1,0))[0]:
                    best[m] = (liq,price)
            return {m:v[1] for m,v in best.items()}
        except Exception:
            return {}

    def publish(got):
        stamp = time.time()
        with ctx['_exit_price_lock']:
            for m,p in got.items():
                ctx['_exit_price_cache'][m] = (stamp,p)
        if got:
            price_updated()

    found = {}
    jobs = [(jupiter,sol[i:i+50]) for i in range(0,len(sol),50)]
    jobs += [(dex,sol[i:i+30]) for i in range(0,len(sol),30)]
    if jobs:
        with ThreadPoolExecutor(max_workers=min(6,len(jobs))) as pool:
            for f in as_completed([pool.submit(fn,chunk) for fn,chunk in jobs]):
                got = f.result()
                # Retain the first valid response for a mint in this cycle;
                # do not alternate between differently timed provider ticks.
                got = {m:p for m,p in got.items() if m not in found}
                publish(got)
                found.update(got)
    missing = [m for m in sol if m not in found]
    for i in range(0,len(missing),30):
        chunk = missing[i:i+30]
        try:
            r = ctx['requests'].get(
                'https://api.geckoterminal.com/api/v2/simple/networks/solana/token_price/'+','.join(chunk),
                headers={'Accept':'application/json'}, timeout=1.5)
            body = r.json() if r.status_code == 200 else {}
            values = ((body.get('data') or {}).get('attributes') or {}).get('token_prices') or {}
            # Solana addresses are case-sensitive. Never lower-case identities.
            got = {m:positive(values[m]) for m in chunk if m in values and positive(values[m])}
            publish(got)
            found.update(got)
        except Exception:
            pass
    return found

def pending_stage(db, uid, wallet, mint, pos):
    import json
    if not pos.get('_stage_state_loaded'):
        try:
            with _connect(db) as c:
                state = c.execute("""SELECT tp1_hit,tp2_hit,trail_peak FROM protection_stage_state
                    WHERE user_id=? AND wallet=? AND mint=? AND chain=? AND opened_at=?""",
                    _identity(uid,wallet,mint,pos)).fetchone()
            if state:
                pos.update(tp1_hit=bool(state[0]),tp2_hit=bool(state[1]),trail_peak=state[2])
            pos['_stage_state_loaded'] = True
        except sqlite3.Error:
            pass
    if '_stage_pending' in pos:
        return pos['_stage_pending']
    try:
        with _connect(db) as c:
            row = c.execute("""SELECT data FROM protection_stage_intents WHERE
                user_id=? AND wallet=? AND mint=? AND chain=? AND opened_at=?""",
                _identity(uid,wallet,mint,pos)).fetchone()
        pos['_stage_pending'] = json.loads(row[0]) if row else None
        return pos['_stage_pending']
    except (sqlite3.Error,ValueError):
        return None


def dispatch_stage(ctx, uid, us, wallet, mint, pos, price, symbol, reason,
                   notify, enc_sol, enc_evm, stage, fraction):
    import json
    intent = pending_stage(ctx['DB_FILE'],uid,wallet,mint,pos)
    if not intent:
        intent = dict(stage=stage,fraction=fraction,price=price,reason=reason)
        with _connect(ctx['DB_FILE']) as c:
            c.execute("""INSERT OR IGNORE INTO protection_stage_intents VALUES (?,?,?,?,?,?)""",
                _identity(uid,wallet,mint,pos)+(json.dumps(intent),))
        pos['_stage_pending'] = intent
    key = (ctx['DB_FILE'],) + _identity(uid,wallet,mint,pos)
    with _GUARD:
        if key in _BUSY or time.monotonic()<pos.get('_exit_retry_at',0):
            return False
        _BUSY.add(key)

    def sell():
        lock = ctx['_get_sell_lock'](wallet,mint,pos.get('chain','solana'))
        try:
            if not lock.acquire(blocking=False):
                return
            try:
                current = us['positions'].get(mint) or {}
                if _identity(uid,wallet,mint,current)!=key[1:] or positive(current.get('amount'))==0:
                    return
                # A hard stop already latched by the watcher takes precedence.
                if pending(ctx['DB_FILE'],uid,wallet,mint,current):
                    return
                enc = enc_sol if current.get('chain','solana')=='solana' else enc_evm
                if not enc:
                    return
                amount = current['amount'] * intent['fraction']
                spend = current.get('spend',0) * intent['fraction']
                record={k:current.get(k) for k in ('sl_pct','tp_pct','sl_price','tp_price',
                        'entry_liquidity','entry_lp_locked_pct','entry_mint_authority_active',
                        'entry_freeze_authority_active','entry_score','highest_price','lowest_price')}
                ok,_,sold = ctx['_bot_execute_exit_locked'](
                    uid,us,wallet,mint,current,positive(price) or intent['price'],symbol,
                    amount,spend,intent['reason'],notify,enc,current.get('chain','solana'),False,record)
                if not ok:
                    current['_exit_retry_at']=time.monotonic()+1
                    return
                old_amount = current['amount']
                sold = min(old_amount,positive(sold))
                current['amount'] = max(0,old_amount-sold)
                current['spend'] = max(0,current.get('spend',0)*(1-sold/old_amount))
                current[intent['stage']+'_hit'] = True
                current['trail_peak'] = positive(price) or intent['price']
                current['_stage_pending'] = None
                ctx['_upsert_open_position'](uid,wallet,mint,current,
                    source=current.get('source','bot'),copy_of_wallet=current.get('copy_of_wallet'),
                    chain=current.get('chain','solana'))
                with _connect(ctx['DB_FILE']) as c:
                    c.execute("""INSERT OR REPLACE INTO protection_stage_state
                        VALUES (?,?,?,?,?,?,?,?)""",
                        _identity(uid,wallet,mint,current) +
                        (int(bool(current.get('tp1_hit'))),int(bool(current.get('tp2_hit'))),
                         current['trail_peak']))
                    c.execute("""DELETE FROM protection_stage_intents WHERE
                        user_id=? AND wallet=? AND mint=? AND chain=? AND opened_at=?""",
                        _identity(uid,wallet,mint,current))
            finally:
                lock.release()
        except Exception as exc:
            pos['_exit_retry_at']=time.monotonic()+1
            print('[protected-stage] '+type(exc).__name__,flush=True)
        finally:
            with _GUARD:
                _BUSY.discard(key)
    try:
        _SELL_POOL.submit(sell)
        return True
    except RuntimeError:
        with _GUARD:
            _BUSY.discard(key)
        return False
