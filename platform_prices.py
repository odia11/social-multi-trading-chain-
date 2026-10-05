"""Public price answers from Live Market's DexScreener source and native majors."""
import datetime as dt
import math
import re
import threading
import time
from collections import OrderedDict, deque
from urllib.parse import quote
import requests

ADDRESS = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')
MAJORS = {'sol':('solana','SOL'),'solana':('solana','SOL'),
          'btc':('bitcoin','BTC'),'bitcoin':('bitcoin','BTC')}
_CACHE = OrderedDict()
_LOCK = threading.Lock()
_CALLS = deque()
UNAVAILABLE = "I can't retrieve a current price right now. Please try again shortly. I won't use an old or guessed price."
MARKET = 'https://orcagent.fun/live-market'

def query(message):
    text = message.strip()
    if re.search(r'predict|tomorrow|next week|will .*reach|forecast|voorspel|morgen',text,re.I):
        return None
    if not re.search(r'\b(?:price|prices|prijs|prijzen|koers|koersen|worth|trading at)\b',text,re.I):
        return None
    currency = 'eur' if re.search(r'\beur\b|euro|€',text,re.I) else 'usd'
    if re.search(r'\b(?:gbp|jpy|aed|in sol|in btc)\b',text,re.I):
        return dict(kind='currency',currency=currency)
    address = ADDRESS.search(text)
    if address:
        return dict(kind='token',value=address[0],currency=currency)
    symbols = re.findall(r'\$([A-Za-z][A-Za-z0-9_+.-]{0,24})',text)
    terms = list(dict.fromkeys(s.upper() for s in symbols)) if symbols else list(dict.fromkeys(
        MAJORS[s.lower()][1] for s in re.findall(r'\b(?:solana|bitcoin|sol|btc)\b',text,re.I)))
    if terms:
        if all(t.lower() in MAJORS for t in terms):
            return dict(kind='major',values=list(dict.fromkeys(MAJORS[t.lower()][0] for t in terms)),currency=currency)
        return dict(kind='search',value=terms[0],currency=currency) if len(terms)==1 else dict(kind='clarify',currency=currency)
    patterns = [
        r'(?:price|prijs|koers)(?:\s+(?:is|of|for|van|voor))+\s+([a-zA-Z][a-zA-Z0-9_+.-]{1,24})(?:\s+token)?(?:\s+(?:now|today|vandaag|nu|in usd|in eur))?[?!. ]*$',
        r'(?:what is|what.s|wat is)\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_+.-]{1,24})\s+(?:price|prijs|koers)[?!. ]*$',
    ]
    patterns.append(r'^\s*([a-zA-Z][a-zA-Z0-9_+.-]{1,24})\s+(?:price|prijs|koers)(?:\s+(?:now|today|in usd|in eur))?[?!. ]*$')
    for pattern in patterns:
        found = re.search(pattern,text,re.I)
        if found and found[1].lower() not in ('the','token','trade','platform','gas','fee'):
            return dict(kind='search',value=found[1].upper(),currency=currency)
    named = re.search(r'(?:price|prijs|koers)\s+(?:of|for|van|voor)\s+([a-zA-Z][a-zA-Z0-9 _+.-]{1,63})[?!. ]*$', text, re.I)
    if named:
        name = re.sub(r'\s+(?:token|now|today|vandaag|nu|in usd|in eur)[?!. ]*$', '', named[1], flags=re.I).strip(' ?!.')
        if name and name.lower() not in ('the token','the trade','the platform'):
            return dict(kind='search',value=name.upper(),currency=currency)
    return None

def positive(value):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>0 else 0
    except (TypeError,ValueError):
        return 0

def _label(value):
    return re.sub(r'[^A-Za-z0-9 _+.-]','',str(value or 'Token'))[:24] or 'Token'

def _pairs(body,q):
    if not isinstance(body,dict):
        return []
    best={}
    for pair in body.get('pairs') or []:
        if not isinstance(pair,dict) or pair.get('chainId')!='solana':
            continue
        base=pair.get('baseToken') or {}
        mint=base.get('address') or ''
        if not isinstance(mint,str) or not ADDRESS.fullmatch(mint):
            continue
        if q['kind']=='token' and mint!=q['value']:
            continue
        if q['kind']=='search' and not any(str(base.get(k) or '').upper()==q['value'].upper() for k in ('symbol','name')):
            continue
        liquidity=positive((pair.get('liquidity') or {}).get('usd'))
        price=positive(pair.get('priceUsd'))
        if not price or not liquidity:
            continue
        if mint not in best or liquidity>best[mint]['liquidity']:
            best[mint]=dict(mint=mint,symbol=_label(base.get('symbol')),price=price,liquidity=liquidity)
    return sorted(best.values(),key=lambda v:v['liquidity'],reverse=True)

def _major(q, get):
    rows = []
    try:
        r = get('https://api.coingecko.com/api/v3/simple/price',
                params=dict(ids=','.join(q['values']),vs_currencies=q['currency'],
                            include_last_updated_at='true'),timeout=1.5,allow_redirects=False)
        body = r.json() if r.status_code==200 else {}
        for coin in q['values']:
            value = body.get(coin) or {}
            stamp = positive(value.get('last_updated_at'))
            price = positive(value.get(q['currency']))
            if price and stamp and -5<=time.time()-stamp<=120:
                rows.append(dict(symbol='SOL' if coin=='solana' else 'BTC',price=price,observed=stamp))
        if len(rows)==len(q['values']):
            return dict(kind='prices',rows=rows,currency=q['currency'],source='CoinGecko')
    except (requests.RequestException,ValueError,TypeError,KeyError,AttributeError):
        pass
    # Independent native markets; never use a copied Solana ticker for BTC/SOL.
    from concurrent.futures import ThreadPoolExecutor
    def ticker(coin):
        symbol = 'SOL' if coin=='solana' else 'BTC'
        try:
            r = get('https://api.exchange.coinbase.com/products/'+symbol+'-'+q['currency'].upper()+'/ticker',
                    timeout=1.5,allow_redirects=False)
            body = r.json() if r.status_code==200 else {}
            stamp = dt.datetime.fromisoformat(str(body.get('time','')).replace('Z','+00:00'))
            if stamp.tzinfo is None:
                return None
            observed = stamp.timestamp()
            price = positive(body.get('price'))
            if price and -5<=time.time()-observed<=120:
                return dict(symbol=symbol,price=price,observed=observed)
        except (requests.RequestException,ValueError,TypeError,KeyError,AttributeError):
            pass
        return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(ticker,q['values']))
    if rows and all(rows):
        return dict(kind='prices',rows=rows,currency=q['currency'],source='Coinbase')
    print('[platform-price] native sources unavailable or stale',flush=True)
    return None

def fetch(q,dex_get=None,get=None):
    """Bounded lookup outside the feed write transaction."""
    get=get or requests.get
    key=repr(sorted(q.items()))
    now=time.time()
    if not _LOCK.acquire(timeout=3.5):
        return None
    try:
        hit=_CACHE.get(key)
        if hit and now-hit[0]<hit[1] and (not hit[2] or hit[2].get('kind')!='prices' or all(now-v['observed']<=120 for v in hit[2]['rows'])):
            return hit[2]
        while _CALLS and now-_CALLS[0]>=60:
            _CALLS.popleft()
        if len(_CALLS)>=40:
            return None
        _CALLS.append(now)
        result=None
        try:
            if q['kind']=='major':
                result = _major(q,get)
            elif q['kind'] in ('token','search'):
                if q['currency']!='usd':
                    return dict(kind='token_currency')
                url=('https://api.dexscreener.com/latest/dex/tokens/'+q['value'] if q['kind']=='token'
                     else 'https://api.dexscreener.com/latest/dex/search?q='+quote(q['value'],safe=''))
                r=dex_get(url,timeout=2,ttl_override=0) if dex_get else get(url,timeout=2,allow_redirects=False)
                body=r.json() if r is not None and r.status_code==200 else {}
                rows=_pairs(body,q)
                if len(rows)>1:
                    result=dict(kind='choice',symbol=rows[0]['symbol'] if len({v['symbol'].upper() for v in rows})==1 else None,count=len(rows))
                elif rows:
                    rows[0]['observed']=time.time()
                    result=dict(kind='prices',rows=rows,currency='usd',source='DexScreener')
        except (requests.RequestException,ValueError,TypeError,KeyError,AttributeError):
            result=None
        ttl=30 if q['kind']=='major' and result else (20 if result else 5)
        _CACHE[key]=(time.time(),ttl,result)
        _CACHE.move_to_end(key)
        while len(_CACHE)>256:
            _CACHE.popitem(last=False)
        return result
    finally:
        _LOCK.release()

def render(q,snapshot):
    if q['kind'] in ('currency','clarify'):
        return 'market_price','Ask for one token by name, $ticker or Solana contract address. SOL/BTC support USD and EUR; Live Market token prices are in USD.'
    if not snapshot:
        return 'market_price',UNAVAILABLE
    if snapshot['kind']=='token_currency':
        return 'market_price','Live Market token prices are in USD. Ask with its $ticker or Solana contract address for its USD price.'
    if snapshot['kind']=='choice':
        if not snapshot.get('symbol'):
            return 'market_price','Several Solana tokens match that name. Reply with the exact contract address to get the right price. '+MARKET
        symbol=_label(snapshot['symbol']).upper()
        return 'token_choice','Do you mean $'+symbol+'? Several Solana tokens match. Choose the right contract below, then send your price question.'
    lines=[]
    for row in snapshot['rows']:
        price=row['price']
        formatted=(f'{price:,.2f}' if price>=1 else (f'{price:.6g}' if price<1e-8 else f'{price:.10f}'.rstrip('0').rstrip('.')))
        stamp=dt.datetime.fromtimestamp(row['observed'],dt.timezone.utc).strftime('%H:%M:%S UTC')
        if time.time()-row['observed']>120:
            return 'market_price',UNAVAILABLE
        lines.append(f"{row['symbol']}: {formatted} {snapshot['currency'].upper()} · {stamp}")
    text=' | '.join(lines)+f". Source: {snapshot['source']}"+(' (retrieved).' if snapshot['source']=='DexScreener' else ' (updated).')
    if snapshot['source']=='DexScreener':
        text+=' Solana contract: '+snapshot['rows'][0]['mint']+'. '+MARKET
    return 'market_price',text
