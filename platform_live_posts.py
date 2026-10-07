"""OrcAgent's live feed posts: calls and trending tokens, never the same twice.

Every 30-minute slot (platform_assistant.publish_due) asks candidates() for
the posts it could make right now, best first:

  1. a call that just reached 2x/3x/5x/10x since it was made,
  2. a call made in the last few hours that has not been featured yet,
  3. then, taking turns by slot: a trending token on Live Market, the best
     call of the day, the most called token, the best caller of the week,
     and a market pulse.

Every number comes from data the app already shows publicly (Live Market,
calls, the feed). Nothing about balances, wallets or private messages.

Never the same:
  - each subject has a cooldown (a trending token at most once per 6 hours,
    a call featured once, a milestone once, ...), tracked as the topic of
    the publication receipt in platform_assistant_events;
  - several phrasings per kind, and the caller refuses any text OrcAgent
    has already posted, word for word.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math

HOUR = 3600
TRENDING_COOLDOWN = 6 * HOUR
TRENDING_MIN_CHANGE = 5.0
MOST_CALLED_COOLDOWN = 24 * HOUR
NEW_CALL_WINDOW = 3 * HOUR
MILESTONES = (2, 3, 5, 10)
MILESTONE_WINDOW_DAYS = 7
BEST_CALL_MIN = 1.2
NFA = 'Not financial advice.'
ROTATION = ('trending', 'best_call', 'trending', 'most_called', 'trending', 'pulse', 'trending', 'top_caller')


def usd(v):
    v = float(v or 0)
    for div, unit in ((1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
        if abs(v) >= div:
            return '$%s%s' % (('%.2f' % (v / div)).rstrip('0').rstrip('.'), unit)
    return '$%.2f' % v


def price(v):
    """A token price with four significant digits: $152.00, $0.1240, $0.0002070."""
    v = float(v or 0)
    if v >= 1:
        return '$%.2f' % v
    if v <= 0:
        return '$0'
    decimals = min(12, -math.floor(math.log10(v)) + 3)
    return '$%.*f' % (decimals, v)


def pct(v):
    return '%+.1f%%' % float(v or 0)


def mult(v):
    return ('%.2f' % v).rstrip('0').rstrip('.') + 'x'


def _pick(options, seed):
    """A phrasing chosen by the subject, so the same subject reads differently
    from a different one, and each option is tried if an earlier one was
    already used word for word."""
    n = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    return [options[(n + i) % len(options)] for i in range(len(options))]


def _since(c, topic_like, now):
    row = c.execute("SELECT MAX(created_at) FROM platform_assistant_events WHERE kind='post' AND topic LIKE ?",
                    (topic_like,)).fetchone()
    return now - row[0] if row and row[0] else None


def _posted(c, topic):
    return c.execute("SELECT 1 FROM platform_assistant_events WHERE kind='post' AND topic=?",
                     (topic,)).fetchone() is not None


def _calls(c, where, args=()):
    try:
        return c.execute(
            'SELECT tc.id, tc.mint, tc.symbol, tc.token_name, tc.price_at_call, tc.mcap_at_call, '
            'tc.peak_price, tc.last_price, tc.note, tc.timestamp, u.username, u.id, '
            "COALESCE(tc.image_url, '') "

            'FROM token_calls tc JOIN users u ON u.id = tc.user_id '
            "WHERE tc.price_at_call > 0 AND COALESCE(u.username,'') != '' AND " + where, args).fetchall()
    except Exception:
        return []


def _call_media(event, cid, mint, sym, name, p0, mc0, peak, last, note, ts, user, img, **extra):
    data = {'id': cid, 'mint': mint, 'symbol': sym or '', 'token_name': name or '', 'price_at_call': p0,
            'mcap_at_call': mc0 or 0, 'peak_price': peak or p0, 'last_price': last or p0, 'note': _note(note, 160),
            'timestamp': ts or '', 'user': user, 'image_url': img or '', 'event': event}
    data.update(extra)
    return {'kind': 'call', 'data': data}


def _call_embed(call_id):
    return '\n__CALL__' + json.dumps({'id': call_id})


def _chart_embed(t):
    return '\n__CHART__' + json.dumps({
        'symbol': t.get('symbol') or '', 'name': t.get('name') or '',
        'price': t.get('price_usd'), 'chg24h': t.get('price_change_24h'),
        'vol24h': t.get('volume_24h'), 'liq': t.get('liquidity_usd'),
        'buys': t.get('buys_24h'), 'sells': t.get('sells_24h'),
        'mint': t.get('mint') or '', 'pairAddress': t.get('pair_address') or '',
        'chain': 'solana', 'image': t.get('image_url') or '', 'banner': t.get('banner_url') or ''})


def _note(text, limit=120):
    text = ' '.join(str(text or '').split())
    for marker in ('__CALL__', '__CHART__', '__TRADE__'):
        text = text.split(marker)[0].strip()
    if len(text) > limit:
        text = text[:limit].rsplit(' ', 1)[0] + '…'
    return text


# ── kinds ───────────────────────────────────────────────────────────────

def milestone(c, now):
    since = (dt.datetime.utcfromtimestamp(now) - dt.timedelta(days=MILESTONE_WINDOW_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    out = []
    for cid, mint, sym, name, p0, mc0, peak, last, note, ts, user, uid, img in _calls(c, 'tc.timestamp >= ?', (since,)):
        x = (peak or 0) / p0
        hit = [m for m in MILESTONES if x >= m]
        if not hit:
            continue
        m = hit[-1]
        topic = 'milestone:%d:%d' % (cid, m)
        if _posted(c, topic):
            continue
        sym = sym or 'this token'
        texts = [
            '$%s just hit %dx since @%s called it at a %s market cap. Open the call to see the entry and the reasoning. %s' % (sym, m, user, usd(mc0), NFA),
            '%dx on the call: @%s called $%s at %s, and it has now reached %s at its peak. %s' % (m, user, sym, usd(mc0), usd((mc0 or 0) * x), NFA),
            'Call milestone: $%s, called by @%s, is up %dx from the recorded entry. Calls keep their entry, so the result is there for everyone to check. %s' % (sym, user, m, NFA),
        ]
        media = _call_media('milestone', cid, mint, sym, name, p0, mc0, peak, last, note, ts, user, img, milestone=m)
        out.append((topic, _pick(texts, topic), media, _call_embed(cid), x))
    out.sort(key=lambda o: -o[4])
    return [o[:4] for o in out]


def new_calls(c, now):
    since = (dt.datetime.utcfromtimestamp(now - NEW_CALL_WINDOW)).strftime('%Y-%m-%d %H:%M:%S')
    out = []
    for cid, mint, sym, name, p0, mc0, peak, last, note, ts, user, uid, img in _calls(c, 'tc.timestamp >= ? ORDER BY tc.timestamp DESC', (since,)):
        topic = 'call:%d' % cid
        if _posted(c, topic):
            continue
        sym = sym or 'a token'
        why = _note(note)
        quoted = (' “%s”' % why) if why else ''
        texts = [
            'New call from @%s: $%s at a %s market cap.%s Open the call for the chart and the reasoning.' % (user, sym, usd(mc0), quoted),
            '@%s just called $%s at %s.%s The entry is recorded, so you can follow how it does from here.' % (user, sym, usd(mc0), quoted),
            'Fresh on the Calls tab: @%s on $%s, called at a %s market cap.%s What do you think?' % (user, sym, usd(mc0), quoted),
        ]
        media = _call_media('new', cid, mint, sym, name, p0, mc0, peak, last, note, ts, user, img)
        out.append((topic, _pick(texts, topic), media, _call_embed(cid)))
    return out


def trending(c, now, tokens):
    out = []
    for t in tokens or []:
        mint, sym = t.get('mint'), t.get('symbol')
        if not mint or not sym or float(t.get('price_usd') or 0) <= 0:
            continue
        since = _since(c, 'trending:%s' % mint, now)
        if since is not None and since < TRENDING_COOLDOWN:
            continue
        chg = float(t.get('price_change_24h') or 0)
        if chg < TRENDING_MIN_CHANGE:
            continue  # a token that is falling is not "trending" in a post
        buys, sells = int(t.get('buys_24h') or 0), int(t.get('sells_24h') or 0)
        share = round(100 * buys / (buys + sells)) if buys + sells else None
        texts = [
            '$%s is trending on Live Market: %s in 24 hours, %s traded and %s in liquidity. Look at the chart before you decide. %s' % (sym, pct(chg), usd(t.get('volume_24h')), usd(t.get('liquidity_usd')), NFA),
            'Trending now: $%s at a %s market cap, %s over the last day.%s %s' % (sym, usd(t.get('market_cap')), pct(chg), (' %d%% of its trades today were buys.' % share) if share is not None else '', NFA),
            'On the move on Live Market: $%s trades at %s, %s in 24 hours with %s in volume. %s' % (sym, price(t.get('price_usd')), pct(chg), usd(t.get('volume_24h')), NFA),
        ]
        topic = 'trending:%s' % mint
        out.append((topic, _pick(texts, topic + str(int(now // HOUR))), {'kind': 'trending', 'data': dict(t)}, _chart_embed(t)))
    return out


def best_call(c, now):
    if (_since(c, 'best:%', now) or 1e12) < 4 * HOUR:
        return []
    day = dt.datetime.utcfromtimestamp(now).strftime('%Y-%m-%d')
    rows = _calls(c, 'date(tc.timestamp) = ?', (day,))
    if not rows:
        return []
    top = max(rows, key=lambda r: (r[6] or 0) / r[4])
    cid, mint, sym, name, p0, mc0, peak, last, note, ts, user, uid, img = top
    x = (peak or 0) / p0
    if x < BEST_CALL_MIN:
        return []
    topic = 'best:%d:%d' % (cid, int(x * 4))
    if _posted(c, topic):
        return []
    sym = sym or 'a token'
    texts = [
        'Best call of the day so far: @%s called $%s at a %s market cap. It has reached %s since. %s' % (user, sym, usd(mc0), mult(x), NFA),
        'Today\'s top call: $%s by @%s, up %s at its peak from a %s entry. Read the reasoning on the call. %s' % (sym, user, mult(x), usd(mc0), NFA),
        '@%s leads today\'s calls: $%s, called at %s and %s at its best since. %s' % (user, sym, usd(mc0), mult(x), NFA),
    ]
    media = _call_media('best', cid, mint, sym, name, p0, mc0, peak, last, note, ts, user, img)
    return [(topic, _pick(texts, topic), media, _call_embed(cid))]


def most_called(c, now):
    if (_since(c, 'mostcalled:%', now) or 1e12) < 6 * HOUR:
        return []
    since = (dt.datetime.utcfromtimestamp(now - 24 * HOUR)).strftime('%Y-%m-%d %H:%M:%S')
    try:
        row = c.execute('SELECT mint, MAX(symbol), COUNT(DISTINCT user_id) n FROM token_calls '
                        'WHERE timestamp >= ? GROUP BY mint ORDER BY n DESC LIMIT 1', (since,)).fetchone()
    except Exception:
        row = None
    if not row or row[2] < 2:
        return []
    mint, sym, n = row
    topic = 'mostcalled:%s' % mint
    if (_since(c, topic, now) or 1e12) < MOST_CALLED_COOLDOWN:
        return []
    sym = sym or 'one token'
    texts = [
        'Most called token in the last 24 hours: $%s, called by %d different traders. Compare their reasoning on the Calls tab.' % (sym, n),
        '%d traders called $%s in the last day. Open the Calls tab to see who called it, when, and why.' % (n, sym),
    ]
    return [(topic, _pick(texts, topic), None, '')]


def top_caller(c, now):
    if (_since(c, 'topcaller:%', now) or 1e12) < 12 * HOUR:
        return []
    since = (dt.datetime.utcfromtimestamp(now - 7 * 24 * HOUR)).strftime('%Y-%m-%d %H:%M:%S')
    rows = _calls(c, 'tc.timestamp >= ?', (since,))
    by_user = {}
    for cid, mint, sym, name, p0, mc0, peak, last, note, ts, user, uid, img in rows:
        x = (peak or 0) / p0
        u = by_user.setdefault(uid, {'user': user, 'n': 0, 'best': 0, 'sym': '', 'wins': 0})
        u['n'] += 1
        u['wins'] += x >= 1.5
        if x > u['best']:
            u['best'], u['sym'] = x, sym or ''
    good = [u for u in by_user.values() if u['n'] >= 2 and u['best'] >= 1.5]
    if not good:
        return []
    u = max(good, key=lambda u: (u['wins'], u['best']))
    week = dt.datetime.utcfromtimestamp(now).strftime('%G-%V')
    topic = 'topcaller:%s:%s' % (u['user'].lower(), week)
    if _posted(c, topic):
        return []
    texts = [
        'Top caller this week: @%s. %d calls in 7 days, the best one $%s at %s since the call. Follow them from their profile.' % (u['user'], u['n'], u['sym'], mult(u['best'])),
        'This week\'s sharpest caller so far is @%s: %d of their %d calls reached 1.5x or more, led by $%s at %s.' % (u['user'], u['wins'], u['n'], u['sym'], mult(u['best'])),
    ]
    return [(topic, _pick(texts, topic), None, '')]


def pulse(c, now, tokens, sol_usd):
    if (_since(c, 'pulse:%', now) or 1e12) < 6 * HOUR:
        return []
    ts = [t for t in (tokens or []) if t.get('symbol')][:12]
    if len(ts) < 4 or not sol_usd:
        return []
    up = sum(1 for t in ts if float(t.get('price_change_24h') or 0) > 0)
    top = max(ts, key=lambda t: float(t.get('price_change_24h') or 0))
    topic = 'pulse:%d' % int(now // HOUR)
    texts = [
        'Market pulse: SOL is at %s. %d of the %d trending tokens on Live Market are up over 24 hours. Biggest move: $%s, %s. %s' % (price(sol_usd), up, len(ts), top['symbol'], pct(top.get('price_change_24h')), NFA),
        'Quick look at Solana: SOL %s, and %d of %d trending tokens are green today. $%s leads with %s. %s' % (price(sol_usd), up, len(ts), top['symbol'], pct(top.get('price_change_24h')), NFA),
    ]
    return [(topic, _pick(texts, topic), None, '')]


def candidates(c, now, slot_index, tokens=None, sol_usd=0.0):
    """Every post that could go out now, best first:
    (topic, [phrasings], picture spec or None, live-card embed or '').
    The post carries the picture; only when no picture could be made does
    it carry the live card instead."""
    out = []
    out += milestone(c, now)
    out += new_calls(c, now)
    kinds = {
        'trending': lambda: trending(c, now, tokens),
        'best_call': lambda: best_call(c, now),
        'most_called': lambda: most_called(c, now),
        'top_caller': lambda: top_caller(c, now),
        'pulse': lambda: pulse(c, now, tokens, sol_usd),
    }
    start = slot_index % len(ROTATION)
    seen = set()
    for k in ROTATION[start:] + ROTATION[:start]:
        if k in seen:
            continue
        seen.add(k)
        try:
            out += kinds[k]()
        except Exception:
            continue
    return out
