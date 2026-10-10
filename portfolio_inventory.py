"""Complete, owner-scoped Solana holdings reads with coalesced RPC work."""
import copy
import math
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_CACHE = {}
_LOCKS = {}
_GUARD = threading.Lock()
_TTL = 10.0
_USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
_USDT = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'

def num(value):
    try:
        f = float(value or 0)
        return f if math.isfinite(f) else 0
    except (ValueError, TypeError):
        return 0

def _program_accounts(d, owner, program):
    # Bound provider attempts and timeouts. Both programs run concurrently;
    # a slow Token-2022 scan never postpones the start of the legacy scan.
    pool = list(dict.fromkeys(x for x in
        [d.SOLANA_RPC] + list(d._PROXY_RPCS) if x))[:3]
    for endpoint in pool:
        try:
            r = d.requests.post(endpoint, json={'jsonrpc':'2.0','id':1,
                'method':'getTokenAccountsByOwner',
                'params':[owner,{'programId':program},
                          {'encoding':'jsonParsed','commitment':'confirmed'}]}, timeout=4)
            if r.status_code != 200:
                continue
            body = r.json()
            result = body.get('result') if isinstance(body, dict) else None
            rows = result.get('value') if isinstance(result, dict) else None
            if not body.get('error') and isinstance(rows, list):
                return rows
        except Exception:
            continue
    raise RuntimeError('token account index temporarily unavailable')

def _parse(accounts, owner):
    """Sum raw integer balances across accounts of the same mint."""
    tokens = {}
    for a in accounts:
        info = ((a.get('account') or {}).get('data') or {}).get('parsed',{}).get('info') or {}
        # Reject a malformed/foreign response rather than calling it empty.
        if info.get('owner') != owner:
            raise RuntimeError('token account owner mismatch')
        mint = info.get('mint')
        ta = info.get('tokenAmount') or {}
        if not mint or 'amount' not in ta or 'decimals' not in ta:
            raise RuntimeError('incomplete token account response')
        raw, decimals = int(ta['amount']), int(ta['decimals'])
        if raw < 0 or not 0 <= decimals <= 36:
            raise RuntimeError('invalid token amount')
        if raw == 0:
            continue
        row = tokens.setdefault(mint, {'mint':mint,'raw':0,'decimals':decimals})
        if row['decimals'] != decimals:
            raise RuntimeError('inconsistent token decimals')
        row['raw'] += raw
    return [{'mint':m,'amount':r['raw']/10**r['decimals'],'decimals':r['decimals']}
            for m,r in tokens.items()]

def _prices(d, mints):
    def batch(names):
        try:
            r = d._dex_get('https://api.dexscreener.com/latest/dex/tokens/'+','.join(names), timeout=4)
            pairs = (r.json().get('pairs') or []) if r and r.status_code == 200 else []
            out = {}
            for pair in pairs:
                base = pair.get('baseToken') or {}
                mint = base.get('address')
                price = num(pair.get('priceUsd'))
                liquidity = num((pair.get('liquidity') or {}).get('usd'))
                if pair.get('chainId') != 'solana' or mint not in names or price <= 0:
                    continue
                if mint in out and out[mint]['liquidity'] >= liquidity:
                    continue
                out[mint] = dict(symbol=base.get('symbol') or mint[:6],
                    name=base.get('name') or '',price_usd=price,liquidity=liquidity,
                    logo_url=(pair.get('info') or {}).get('imageUrl') or '',
                    price_change_24h=num((pair.get('priceChange') or {}).get('h24')))
            return out
        except Exception:
            return {}
    out = {}
    batches = [mints[i:i+30] for i in range(0,len(mints),30)]
    if batches:
        with ThreadPoolExecutor(max_workers=min(3,len(batches))) as ex:
            for result in ex.map(batch,batches):
                out.update(result)
    return out

# Jupiter's token index often has the verified mint's icon and USD quote before
# DexScreener has a usable pool. Cache short-lived results across wallet polls;
# never infer identity from a ticker or use an unrelated pair's price.
_JUPITER_CACHE = {}
_JUPITER_LOCK = threading.Lock()
_BASE58 = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')

def _jupiter_details(d, mints):
    valid = list(dict.fromkeys(m for m in mints if isinstance(m, str)
                              and 32 <= len(m) <= 44 and set(m) <= _BASE58))
    if not valid:
        return {}
    now = time.monotonic()
    found, pending = {}, []
    with _JUPITER_LOCK:
        for mint in valid:
            cached = _JUPITER_CACHE.get(mint)
            if cached and now < cached[0]:
                if cached[1]:
                    found[mint] = dict(cached[1])
            else:
                pending.append(mint)
    if not pending:
        return found

    def batch(names):
        for host in ('https://lite-api.jup.ag', 'https://api.jup.ag'):
            try:
                url = host + '/tokens/v2/search?query=' + ','.join(names)
                r = d.requests.get(url, timeout=4,
                    headers={'Accept': 'application/json', 'User-Agent': 'OrcAgent/1.0'})
                if r.status_code != 200:
                    continue
                rows = r.json()
                if not isinstance(rows, list):
                    continue
                results = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    mint = row.get('id')
                    if mint not in names:
                        continue
                    price = num(row.get('usdPrice'))
                    icon = row.get('icon') or ''
                    if not (isinstance(icon, str) and icon.startswith('https://')
                            and len(icon) <= 2048):
                        icon = ''
                    results[mint] = dict(
                        symbol=str(row.get('symbol') or mint[:6])[:32],
                        name=str(row.get('name') or '')[:160],
                        logo_url=icon, price_usd=price)
                return results
            except Exception:
                continue
        return {}

    chunks = [pending[i:i+50] for i in range(0, len(pending), 50)]
    with ThreadPoolExecutor(max_workers=min(3, len(chunks))) as ex:
        for names, results in zip(chunks, ex.map(batch, chunks)):
            with _JUPITER_LOCK:
                for mint in names:
                    data = results.get(mint, {})
                    # Unlisted mints are retried quickly as new markets appear.
                    ttl = 30 if data.get('price_usd') else 18
                    _JUPITER_CACHE[mint] = (time.monotonic() + ttl, data)
                    if data:
                        found[mint] = dict(data)
                if len(_JUPITER_CACHE) > 5000:
                    expired = [k for k, (expires, _) in _JUPITER_CACHE.items()
                               if expires < time.monotonic()]
                    for k in expired:
                        _JUPITER_CACHE.pop(k, None)
    return found

def fetch(d, wallet, owner=None):
    owner = owner or wallet
    key = (d.DB_FILE, wallet, owner)
    with _GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    request_started = time.monotonic()
    with lock:
        previous = _CACHE.get(key)
        # A legacy cache pop is the existing force-refresh contract used after
        # swaps/transfers. Coalesce simultaneous forced readers too.
        cache_present = d._wallet_tokens_cache.get(wallet,{}).get('owner') == owner
        if previous and ((cache_present and time.time()-previous['ts'] < _TTL)
                         or previous.get('_finished',0) >= request_started):
            return copy.deepcopy(previous)
        with ThreadPoolExecutor(max_workers=3) as ex:
            native = ex.submit(d._get_user_sol, owner)
            scans = [ex.submit(_program_accounts,d,owner,p)
                     for p in (d.TOKEN_PROGRAM_ID,d.TOKEN_2022_PROGRAM_ID)]
            accounts, failures = [], []
            for f in scans:
                try: accounts.extend(f.result())
                except Exception: failures.append('full_token_index')
            try:
                raw_sol = float(native.result())
                sol = raw_sol if math.isfinite(raw_sol) and raw_sol >= 0 else None
            except Exception: sol = None
        if failures or sol is None:
            if previous:
                stale = copy.deepcopy(previous)
                stale.update(stale=True,inventory_complete=False,
                             unavailable=sorted(set(failures+(['native_sol'] if sol is None else []))))
                # Never replace the complete cache with a partial discovery.
                return stale
            raise RuntimeError('complete wallet inventory unavailable')
        spl = _parse(accounts, owner)
        mints = [d.SOL_MINT] + [r['mint'] for r in spl]
        prices = _prices(d, mints)
        # DexScreener provides market liquidity/price; Jupiter fills in
        # missing token images, symbols and newly indexed token prices.
        needs_details = [mint for mint in mints
                         if not prices.get(mint, {}).get('logo_url')
                         or not num(prices.get(mint, {}).get('price_usd'))]
        for mint, detail in _jupiter_details(d, needs_details).items():
            market = prices.setdefault(mint, {})
            for field in ('symbol', 'name', 'logo_url'):
                if not market.get(field) and detail.get(field):
                    market[field] = detail[field]
            if not num(market.get('price_usd')) and num(detail.get('price_usd')):
                market['price_usd'] = num(detail['price_usd'])
        old = {r['mint']:r for r in (previous or {}).get('tokens',[])}
        hints = {}
        try:
            with sqlite3.connect(d.DB_FILE) as c:
                uid = c.execute('SELECT id FROM users WHERE wallet_address=?',(wallet,)).fetchone()
                if uid:
                    hints = {r[0]:num(r[1]) for r in c.execute(
                        'SELECT token_address,avg_price FROM user_tokens WHERE user_id=?',(uid[0],))}
        except sqlite3.Error:
            pass
        assets, unpriced, outdated = [], [], []
        for r in [{'mint':d.SOL_MINT,'amount':sol,'decimals':9,'is_native':True}] + spl:
            mint = r['mint']
            meta = dict(prices.get(mint) or {})
            price = num(meta.get('price_usd'))
            if mint == _USDC:
                meta.update(symbol='USDC',name='USD Coin'); price=1
            elif mint == _USDT:
                meta.update(symbol='USDT',name='Tether USD'); price=1
            elif mint == d.SOL_MINT:
                meta.update(symbol='SOL' if r.get('is_native') else 'WSOL',
                            name='Solana' if r.get('is_native') else 'Wrapped SOL')
                price = price or num(d._sol_price_usd)
            if not price and num((old.get(mint) or {}).get('price_usd')) > 0:
                # Preserve the last real price during an API outage while still
                # keeping a newly discovered icon/name from the live index.
                live_meta = meta
                meta = dict(old[mint])
                meta.update({k: v for k, v in live_meta.items() if v})
                price = num(old[mint].get('price_usd'))
                outdated.append(mint)
            if not meta.get('logo_url') and old.get(mint, {}).get('logo_url'):
                meta['logo_url'] = old[mint]['logo_url']
            if not price and r['amount'] > 0:
                unpriced.append(mint)
            assets.append(dict(r, is_native=bool(r.get('is_native')),
                asset_id='solana:native' if r.get('is_native') else 'solana:mint:'+mint, symbol=meta.get('symbol') or mint[:6],
                name=meta.get('name') or '', logo_url=meta.get('logo_url') or '',
                price_usd=price, value_usd=r['amount']*price,
                price_change_24h=num(meta.get('price_change_24h')), avg_price=hints.get(mint,0),
                price_known=price>0,price_stale=mint in outdated,chain='solana'))
        assets.sort(key=lambda r:(-r['value_usd'],r['mint']))
        sol_price = next(r['price_usd'] for r in assets if r.get('is_native'))
        total = sum(r['value_usd'] for r in assets)
        out = dict(ts=time.time(),owner=owner,tokens=assets,total_usd=total,
                   total_sol=total/sol_price if sol_price>0 else None,
                   inventory_complete=True,verified_fallback=False,stale=False,
                   valuation_complete=not unpriced and not outdated,
                   unpriced_mints=unpriced,stale_price_mints=outdated,
                   _finished=time.monotonic())
        _CACHE[key] = copy.deepcopy(out)
        d._wallet_tokens_cache[wallet] = copy.deepcopy(out)
        return out

def install(d):
    d._fetch_wallet_tokens = lambda wallet,onchain_wallet=None: fetch(d,wallet,onchain_wallet)
