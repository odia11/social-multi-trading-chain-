"""Verifies phone alerts for surging tokens.

The throttling is what these tests are mostly about. This is the only
notification in the app that fires from the market rather than from
something the user did, and a market scanner produces a lot of
"interesting" in a busy hour. An alert that buzzes too often gets muted or
uninstalled, so the caps matter more than the happy path.

Extracted from the live source; push delivery and the database mocked."""
import re, sqlite3, sys, tempfile, threading, time

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC  = open(REPO + '/dashboard.py').read()
RADAR = open(REPO + '/surge_radar.py').read()

def extract_func(name, src=SRC):
    m = re.search(rf'^def {re.escape(name)}\(.*?\n(?=\S|\Z)', src, re.M | re.S)
    assert m, f'could not find {name}'
    return m.group(0)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

# ── a temp DB with one opted-in subscriber and several who are not ──
tmpdb = tempfile.mktemp(suffix='.db')
c = sqlite3.connect(tmpdb)
c.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, pref_surge_alerts INTEGER DEFAULT 0)')
c.execute('CREATE TABLE push_subscriptions (id INTEGER PRIMARY KEY, user_id INTEGER)')
c.execute('INSERT INTO users VALUES (1, 1)')   # opted in, has a phone
c.execute('INSERT INTO users VALUES (2, 0)')   # has a phone, did NOT opt in
c.execute('INSERT INTO users VALUES (3, 1)')   # opted in, no phone registered
c.execute('INSERT INTO push_subscriptions VALUES (1, 1)')
c.execute('INSERT INTO push_subscriptions VALUES (2, 1)')  # same user, second device
c.execute('INSERT INTO push_subscriptions VALUES (3, 2)')
c.commit(); c.close()

pushed = []
CHAIN_NAMES = eval(re.search(r'SURGE_ALERT_CHAIN_NAMES = (\{.*?\})\n\n', SRC, re.S).group(1))

def build():
    ns = {'sqlite3': sqlite3, 'SURGE_ALERT_CHAIN_NAMES': CHAIN_NAMES, 'urllib': __import__('urllib.parse'), 'threading': threading, 'time': time, 'DB_FILE': tmpdb,
          'SURGE_ALERT_MAX_PER_HOUR': 10, 'SURGE_ALERT_REPEAT_HOURS': 6,
          'SURGE_ALERT_FOLLOWUP_GAIN': 15.0, 'SURGE_ALERT_MAX_FOLLOWUPS': 6,
          'SURGE_ALERT_MIN_GAP': 180, 'SURGE_ALERT_MAX_FOLLOWUPS_PER_HOUR': 8,
          '_surge_alert_lock': threading.Lock(),
          '_surge_alerts_sent': [], '_surge_followups_sent': [], '_surge_alerted_mints': {},
          '_send_push_notifications_bulk': lambda ids, t, b, u: pushed.append((sorted(ids), t, b, u)),
          'print': lambda *a, **k: None}
    exec(extract_func('_surge_price'), ns)
    exec(extract_func('_surge_alert_allowed'), ns)
    exec(extract_func('_surge_alert_recipients'), ns)
    exec(extract_func('_surge_fmt_usd'), ns)
    exec(extract_func('_surge_alert_text'), ns)
    exec(extract_func('notify_surge'), ns)
    return ns

def surge(**kw):
    s = {'mint': 'MINT1', 'symbol': 'FSD', 'chain': 'robinhood', 'vol_ratio': 19.0,
         'volume_5m': 19000.0, 'txns_5m': 237, 'buy_pct': 62.0, 'price_change_5m': 18.24,
         'liquidity_usd': 128400.0, 'market_cap': 2410000.0, 'name': 'Fast Sad Dog',
         'price_usd': 1.00}
    s.update(kw); return s

# ════════════════════════════════════════════════════════════════
# 1. Who gets it
# ════════════════════════════════════════════════════════════════
ns = build(); pushed.clear()
ns['notify_surge'](surge())
check('a big surge is pushed', len(pushed) == 1)
check('only users who opted in receive it', pushed and pushed[0][0] == [1])
check('a user who did not opt in is never included', pushed and 2 not in pushed[0][0])
check('a user who opted in but has no phone registered is skipped, not pushed into the void',
      pushed and 3 not in pushed[0][0])
check('a user with two devices is listed once, not twice', pushed and pushed[0][0].count(1) == 1)

title, body = pushed[0][1], pushed[0][2]
check('the title is the ticker and the price move, nothing else — a phone truncates '
      'a title from the right, so a third field is a field thrown away',
      title == '$FSD +18.2% (5m)')
check('the title leads with the price move, not a verb',
      'surging' not in title and 'usual' not in title)
check('the price move names the period it covers', '(5m)' in title)
check('the title fits in the ~25 characters a phone banner shows', len(title) <= 25)
check("the body opens with the token's full name, not just the ticker again",
      body.startswith('Fast Sad Dog · '))
check('the body names the chain the way the platform does, not as a raw key',
      'Robinhood Chain' in body and 'robinhood' not in body)
check('market cap and liquidity come before the surge evidence — they answer '
      '"is this real or is this dust", which is asked first',
      body.index('$2.4M mcap') < body.index('$128K liquidity') < body.index('19.0x volume'))
check('the body still carries the surge evidence: ratio, volume, trades, buy share',
      '19.0x volume · $19K (5m)' in body and '237 trades' in body and '62% buys' in body)
check('the fields are separated so the eye can jump, not written as a sentence',
      body.count(' · ') >= 6 and ',' not in body)
check('it links to Live Market rather than straight into a buy screen — this reports '
      'activity, it does not recommend a trade', pushed[0][3].startswith('/live-market'))
check('...and deep-links to the token itself, so the alert is one tap from the card '
      'instead of dropping you in a list to hunt through',
      pushed[0][3] == '/live-market?mint=MINT1')

# The parameter name is the whole point of a deep link: Live Market reads
# ?mint= (live-market-pro.js), and so do the navbar search, the wallet, the
# calls page and the trade notifications. Any other name lands on the page
# and silently does nothing.
check('the deep-link uses the parameter Live Market actually reads',
      "/live-market?mint={urllib.parse.quote" in SRC and 'live-market?addr=' not in SRC)
check('every deep link in the app agrees on that name',
      "'/live-market?mint=' + mint" in SRC)

ns2 = build(); pushed.clear()
ns2['notify_surge'](surge(mint='So1111/11+11 22'))
check('a mint is URL-encoded rather than pasted raw into the link',
      '/' not in pushed[0][3].split('mint=')[1] and '+' not in pushed[0][3].split('mint=')[1])

ns2 = build(); pushed.clear()
ns2['notify_surge'](surge(mint=''))
check('a surge with no mint still links to Live Market instead of a broken URL — '
      'and still sends, rather than dying on a NameError inside the try',
      len(pushed) == 1 and pushed[0][3] == '/live-market')

# ════════════════════════════════════════════════════════════════
# 2. The alert bar IS the strip's bar — no second, stricter filter
#
# This is the whole point of the feature as asked for: what the SURGING NOW
# strip shows is what reaches the phone. A surge only ever gets here after
# surge_radar has already accepted it, so anything rejected in dashboard.py on
# the surge's own numbers would be a token the user can see on the page but
# never gets told about — exactly the split these checks exist to prevent.
# ════════════════════════════════════════════════════════════════
ns = build(); pushed.clear()
ns['notify_surge'](surge(vol_ratio=3.1, volume_5m=3100.0, txns_5m=26))
check('a surge at the strip\'s own minimum (3x, $3k, 26 txns) DOES buzz a phone',
      len(pushed) == 1)

ns = build(); pushed.clear()
ns['notify_surge'](surge(vol_ratio=3.0, volume_5m=3000.0, txns_5m=25))
check('exactly on the strip\'s floors is still sent — dashboard.py adds no bar of its own',
      len(pushed) == 1)

check('no volume-ratio threshold survives in the alert path', 'SURGE_ALERT_MIN_VOL_RATIO' not in SRC)
check('no 5-minute-volume threshold survives either', 'SURGE_ALERT_MIN_VOLUME_5M' not in SRC)

fn = extract_func('_surge_alert_allowed')
check('the gate reads no market number at all — only the clock and the caps',
      'vol_ratio' not in fn and 'volume_5m' not in fn and 'txns_5m' not in fn)

# ════════════════════════════════════════════════════════════════
# 2b. How the numbers are written
#
# A notification is glanced at, not read. Characters spent on "4,257" instead
# of "4.3K" are a fact further down that gets truncated away, and a field the
# radar could not measure must be dropped rather than printed as a zero --
# "$0 liquidity" reads as a broken alert, not as missing data.
# ════════════════════════════════════════════════════════════════
ns = build()
fmt, text = ns['_surge_fmt_usd'], ns['_surge_alert_text']

check('thousands are compact', fmt(4257) == '$4.3K')
check('hundreds of thousands drop the decimal that adds nothing', fmt(128400) == '$128K')
check('a round thousand does not print a pointless .0', fmt(96000) == '$96K')
check('a round million does not either', fmt(1000000) == '$1M')
check('millions are compact', fmt(2410000) == '$2.4M')
check('billions are compact', fmt(1240000000) == '$1.2B')
check('small amounts stay exact rather than becoming $0.9K', fmt(980) == '$980')
check('a missing amount does not crash the formatter', fmt(None) == '$0' and fmt('') == '$0')

t, b = text({'symbol': 'wif', 'chain': 'solana', 'vol_ratio': 3.1, 'volume_5m': 3120.0,
             'txns_5m': 26, 'buy_pct': 50.0})
check('a lowercase ticker is upper-cased', t.startswith('$WIF'))
check('an unmeasured price move is left out, not printed as +0.0%', '%' not in t)
check('unmeasured liquidity and market cap are left out, not printed as $0',
      'liquidity' not in b and 'mcap' not in b)
check('...and the title still says what happened rather than trailing off', t == '$WIF surge')
check('what IS measured still shows', '$3.1K (5m)' in b and '26 trades' in b)

# ── the name: shown when it adds something, dropped when it does not ──
_, b = text({'symbol': 'STONKCAT', 'name': 'STONKCAT', 'chain': 'solana', 'vol_ratio': 7.4})
check('a name that only repeats the ticker is dropped — DexScreener falls back to the '
      'ticker when a pair has no name, and a line saying nothing costs a real one',
      b.startswith('Solana'))

_, b = text({'symbol': 'X', 'name': 'A Very Long Community Token Name Indeed',
             'chain': 'solana', 'vol_ratio': 3.0})
check('a very long name is trimmed rather than eating the whole body',
      b.startswith('A Very Long Community Tok… · Solana'))

t, _ = text({'symbol': 'VERYLONGTICKERNAME', 'chain': 'solana', 'vol_ratio': 3.0,
             'price_change_5m': -8.2})
check('an over-long ticker is trimmed in the title so the percentage still fits',
      t == '$VERYLONGTIC… -8.2% (5m)' and len(t) <= 25)

t, _ = text({'symbol': 'X', 'chain': 'base', 'vol_ratio': 5.0, 'price_change_5m': 0.04})
check('a move that rounds to zero is dropped rather than shown as +0.0%', '%' not in t)

t, _ = text({'symbol': 'X', 'chain': 'base', 'vol_ratio': 5.0, 'price_change_5m': -4.5})
check('a fall is shown with its sign, not as a bare number', '-4.5%' in t)

# ── the fallback: DexScreener has no m5 figure, the radar measured one ──
t, _ = text({'symbol': 'X', 'chain': 'base', 'vol_ratio': 5.0, 'price_change_5m': 0,
             'price_change_obs': 31.7, 'obs_seconds': 540})
check('when DexScreener has no 5m move, the radar\'s own measurement is used '
      'rather than showing no percentage at all', '+31.7%' in t)
check('...and it is labelled with the period it actually covers, never borrowed as 5m',
      t == '$X +31.7% (9m)')

t, _ = text({'symbol': 'X', 'chain': 'base', 'vol_ratio': 5.0, 'price_change_5m': 12.0,
             'price_change_obs': 99.9, 'obs_seconds': 540})
check('DexScreener\'s figure wins when it exists, so the alert agrees with the site',
      '+12.0% (5m)' in t and '99.9' not in t)

t, _ = text({'symbol': 'X', 'chain': 'base', 'vol_ratio': 5.0,
             'price_change_obs': 8.0, 'obs_seconds': 20})
check('a sub-minute observation window still reads as 1m, not 0m', '(1m)' in t)

t, _ = text({'symbol': 'X', 'chain': 'base', 'vol_ratio': 5.0,
             'price_change_5m': 0, 'price_change_obs': 0})
check('with no price move measurable from either source, no percentage is invented',
      '%' not in t)

for key, label in CHAIN_NAMES.items():
    _, b = text({'symbol': 'X', 'chain': key, 'vol_ratio': 3.0})
    check(f'{key} is written as "{label}"', b.startswith(label))

_, b = text({'symbol': 'X', 'chain': 'somenewchain', 'vol_ratio': 3.0})
check('a chain nobody has mapped yet still reads as a name, not a crash',
      b.startswith('Somenewchain'))

t, b = text({})
check('a surge dict with nothing in it produces text rather than an exception',
      t.startswith('$') and b)

# ════════════════════════════════════════════════════════════════
# 3. The caps
# ════════════════════════════════════════════════════════════════
ns = build(); pushed.clear()
for i in range(20):
    ns['notify_surge'](surge(mint=f'M{i}', symbol=f'T{i}'))
check('at most 10 alerts go out in an hour, no matter how busy the market is', len(pushed) == 10)

ns = build(); pushed.clear()
for _ in range(5):
    ns['notify_surge'](surge())          # the same token, over and over
check('the same token alerts once, not every time it is re-detected', len(pushed) == 1)

ns = build(); pushed.clear()
ns['notify_surge'](surge(mint='A', symbol='AAA'))
ns['notify_surge'](surge(mint='B', symbol='BBB'))
check('two genuinely different tokens both get through', len(pushed) == 2)

# The cap must be claimed when the decision is made, not after sending --
# otherwise a burst arriving together all passes a cap with room for one.
ns = build(); pushed.clear()
ns['_surge_alerts_sent'].extend([time.time()] * 9)   # 9 of the 10 already used this hour
for i in range(5):
    ns['notify_surge'](surge(mint=f'X{i}', symbol=f'X{i}'))
check('a burst cannot all slip through the last remaining slot at once', len(pushed) == 1)

# An hour later the budget is available again.
ns = build(); pushed.clear()
ns['_surge_alerts_sent'].extend([time.time() - 3700] * 10)  # a full hour's worth, but over an hour ago
ns['notify_surge'](surge())
check('the hourly cap is a rolling window, not a permanent lockout', len(pushed) == 1)

# ...and the same token becomes alertable again after the repeat window.
ns = build(); pushed.clear()
ns['_surge_alerted_mints']['MINT1'] = {'ts': time.time() - (7 * 3600), 'price': 1.0,
                                       'followups': 0}
ns['notify_surge'](surge())
check('a token that surges again much later is a new episode, not a follow-up',
      len(pushed) == 1 and 'more' not in pushed[0][1])

# ════════════════════════════════════════════════════════════════
# 3b. Saying it AGAIN when it keeps climbing
#
# The rule is that a repeat is earned by PRICE, never by the radar still
# seeing the same surge. Every live surge is re-offered on every 30-second
# sweep, so "still detected" would mean a buzz twice a minute forever. The
# token has to be materially above the price at the LAST alert -- and because
# each alert resets that baseline, the requirement compounds.
# ════════════════════════════════════════════════════════════════
def climbed(ns, mint='MINT1', ago=400, **kw):
    # Age the token's last alert past the minimum gap, so only price is being
    # tested. Without this every follow-up check would just re-test the gap.
    ns['_surge_alerted_mints'][mint]['ts'] = time.time() - ago
    return ns['notify_surge'](surge(mint=mint, **kw))

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=1.00))
ns['notify_surge'](surge(price_usd=1.00))
check('being re-offered every sweep at the same price does not buzz twice — '
      'this runs every 30 seconds, so "still surging" can never be the reason',
      len(pushed) == 1)

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=1.00))
climbed(ns, price_usd=1.10)
check('a 10% further climb is not enough for a second buzz', len(pushed) == 1)

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=1.00))
climbed(ns, price_usd=1.20)
check('a 20% further climb IS worth saying again', len(pushed) == 2)
check('the repeat leads with how much further it has come, not the same '
      '5-minute window again', pushed[1][1] == '$FSD +20% more')
check('the repeat says plainly that it is a repeat', pushed[1][2].startswith('Still climbing · '))

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=1.00))
climbed(ns, price_usd=1.20)     # baseline moves to 1.20
climbed(ns, price_usd=1.30)     # +8% on 1.20 -- would have been +30% on 1.00
check('the baseline moves to the price of the LAST alert, so the bar compounds '
      'instead of re-firing on the same original move', len(pushed) == 2)
climbed(ns, price_usd=1.40)     # +17% on 1.20
check('...and a genuine further climb from that new baseline still gets through',
      len(pushed) == 3)

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=1.00))
for i in range(1, 14):
    climbed(ns, price_usd=1.00 * (1.3 ** i))
check('a token that runs and runs is followed 6 times, then left alone', len(pushed) == 7)

# The three budgets are separate, because a first alert, "still running" and
# "gave it back" answer different questions and must not spend each other's room.
ns = build(); pushed.clear()
ns['_surge_alerts_sent'].extend([time.time()] * 10)   # NEW-surge budget spent
ns['_surge_alerted_mints']['MINT1'] = {'ts': time.time() - 400, 'price': 1.0,
                                       'followups': 0}
ns['notify_surge'](surge(price_usd=1.30))
check('a hour full of new surges cannot silence a token that is still running',
      len(pushed) == 1 and pushed[0][1] == '$FSD +30% more')

ns = build(); pushed.clear()
ns['_surge_followups_sent'].extend([time.time()] * 8)  # follow-up budget spent
ns['notify_surge'](surge(mint='NEW1', symbol='NEW', price_usd=1.00))
check('...and a runaway token spending its own budget cannot crowd out a genuinely '
      'new surge', len(pushed) == 1)

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=1.00))
ns['_surge_followups_sent'].extend([time.time()] * 8)
climbed(ns, price_usd=2.00)
check('follow-ups are still capped across all tokens, so several runners at once '
      'do not add up to a stream', len(pushed) == 1)

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=1.00))
ns['notify_surge'](surge(price_usd=5.00))   # 5x, but seconds later
check('even a 5x climb waits out the minimum gap — no machine-gunning one token',
      len(pushed) == 1)

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=0))
climbed(ns, price_usd=1.20)
check('a token whose price never came through cannot produce a follow-up out of '
      'a division by zero', len(pushed) == 1)

# ════════════════════════════════════════════════════════════════
# 3c. Rises only — a fall never reaches a phone
#
# There is deliberately no second kind of alert for a token giving its gains
# back. A buzz from this app means one thing, and these check nothing can
# quietly reintroduce a second meaning.
# ════════════════════════════════════════════════════════════════
check('there is no drop notifier at all', 'def notify_surge_drop' not in SRC)
check('nor a gate for one', 'def _surge_drop_allowed' not in SRC)
check('nor a threshold left behind for one to be rebuilt against',
      'SURGE_ALERT_DROP_PCT' not in SRC and 'SURGE_ALERT_MAX_DROPS_PER_HOUR' not in SRC)
check('nor a per-token drop flag or drop baseline in the alert state',
      "'dropped'" not in SRC and 'peak_price' not in extract_func('_surge_alert_allowed'))
check('the radar asks the app for nothing but surges', 'notify_surge_drop' not in RADAR
      and 'surge_alert_tracked_mints' not in RADAR)

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=1.00))
for px in (0.90, 0.70, 0.50, 0.20, 0.01):
    ns['_surge_alerted_mints']['MINT1']['ts'] = time.time() - 400
    ns['notify_surge'](surge(price_usd=px))
check('a token collapsing to a hundredth of its alerted price sends nothing further '
      '— every later sweep is refused because a fall is not a rise', len(pushed) == 1)

ns = build(); pushed.clear()
ns['notify_surge'](surge(price_usd=1.00))
ns['_surge_alerted_mints']['MINT1']['ts'] = time.time() - 400
ns['notify_surge'](surge(price_usd=0.40))       # crashed
ns['_surge_alerted_mints']['MINT1']['ts'] = time.time() - 400
ns['notify_surge'](surge(price_usd=0.90))       # bounced hard off the bottom
check('a hard bounce off the bottom is still below where the user was told, so it '
      'stays silent — the baseline is the last alert, never the crash', len(pushed) == 1)

ns['_surge_alerted_mints']['MINT1']['ts'] = time.time() - 400
ns['notify_surge'](surge(price_usd=1.20))
check('...and once it genuinely beats that last alert, it is news again',
      len(pushed) == 2 and pushed[1][1] == '$FSD +20% more')

check('every alert body that is not a first alert says it is a continued climb, '
      'so no notification text can describe a fall',
      all('Still climbing' in p[2] for p in pushed[1:]))

# ── what the radar has to feed for any of this to work ──
check('the radar re-offers every live surge, not only newly-detected ones — '
      'otherwise a climbing token could never earn a second alert',
      'for s in active:' in RADAR and '_app.notify_surge(s)' in RADAR)
check('the radar copies the surges under its lock and notifies outside it, so '
      'sqlite and the push service never run while the sampler is locked',
      RADAR.index('active = [dict(s) for s in _surges.values()]') < RADAR.index('for s in active:'))
check('the radar itself refuses to call a falling token a surge, so a fall never '
      'even reaches the alert path', 'A surge must be a RISE' in RADAR)

# ════════════════════════════════════════════════════════════════
# 4. It must never disturb the radar that feeds it
# ════════════════════════════════════════════════════════════════
ns = build(); pushed.clear()
ns['_send_push_notifications_bulk'] = lambda *a: (_ for _ in ()).throw(RuntimeError('push service down'))
ns['notify_surge'](surge())
check('a failing push service is swallowed rather than raised into the radar', True)

ns = build(); pushed.clear()
ns['DB_FILE'] = '/nonexistent/nope.db'
ns['notify_surge'](surge())
check('a database failure is swallowed too', True)

# ════════════════════════════════════════════════════════════════
# 5. Opt-in, wiring, and the settings toggle
# ════════════════════════════════════════════════════════════════
check('the preference defaults to OFF — a market alert should never start arriving unasked',
      "ADD COLUMN pref_surge_alerts INTEGER DEFAULT 0" in SRC)
check('the radar calls the notifier only for newly-detected surges',
      '_app.notify_surge(s)' in open(REPO + '/surge_radar.py').read())
check('a failing alert cannot stop the radar sampling',
      'surge alert failed' in open(REPO + '/surge_radar.py').read())

st = open(REPO + '/templates/settings.html').read()
check('there is a toggle in Settings', 'pref-surge' in st and 'Surge Alerts' in st)
check('the toggle saves through the existing preference route', "_savePref('surge_alerts'" in st)
check('the toggle reflects the saved value on load', 'surge.checked =!!d.pref_surge_alerts' in st)
check('the settings API accepts the preference', "if 'pref_surge_alerts' in data:" in SRC)
check('...and returns it', "'pref_surge_alerts':" in SRC)
check('the toggle tells the user it mirrors the Live Market strip, not some stricter bar',
      'SURGING NOW' in st)
# The sub-labels in this list are one short line each; a paragraph here would
# wrap to three and make the row taller than every other toggle on the page.
_subs = re.findall(r'st-tog-sub">([^<]+)<', st)
_surge_sub = [x for x in _subs if 'SURGING NOW' in x][0]
check('the sub-label stays as short as the other toggles on the page',
      len(_surge_sub) <= max(len(x) for x in _subs if 'SURGING NOW' not in x) + 5)
check('the radar no longer claims it only alerts for "the big ones"',
      'big ones only' not in open(REPO + '/surge_radar.py').read())

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
