"""Home feed "Trending now" hero card (trending_hero.py + home-trending-hero.js).

- a token appears automatically when it trends (real volume, liquidity,
  price move, more buyers than sellers) and passes the scam filter;
- it stays while it is still trending (looser STAY bar, no flicker) and the
  card disappears (token: null) when nothing trends any more;
- members can vote bull/bear and like it; tapping again takes it back;
  guests cannot; only a token that was actually the hero can be voted on.
"""
import os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0'})
import app_entry  # noqa: E402
import trending_hero as th  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

WOJAK = 'WojakMint1111111111111111111111111111111pump'
PEPE = 'PepeMint11111111111111111111111111111111pump'
def tok(mint, sym, change=184.2, vol=482_000, liq=90_000, mcap=1_800_000, buys=1204, sells=38, price=0.00184):
    return {'mint': mint, 'symbol': sym, 'name': sym + ' Coin', 'chain': 'solana', 'pair_address': 'Pair' + mint[:30],
            'price_usd': price, 'price_change_24h': change, 'volume_24h': vol, 'liquidity_usd': liq,
            'market_cap': mcap, 'buys_24h': buys, 'sells_24h': sells, 'image_url': ''}

scanner = []
d._get_scanner_cached = lambda: scanner
d._scanner_get_safety = lambda mint, chain='solana', include_lp=False: {'ok': True, 'scam': mint.startswith('Scam')}
d._scanner_token_passes_scam_filter = lambda t, s: not s.get('scam')
th._surging = lambda _d: {}
def fresh():
    th._state['at'] = 0.0

# ── selection rules (pure) ──
check('a hot, liquid, buy-heavy token qualifies', th.qualifies(tok(WOJAK, 'WOJAK')))
check('a small move does not', not th.qualifies(tok(WOJAK, 'WOJAK', change=8)))
check('thin volume does not', not th.qualifies(tok(WOJAK, 'WOJAK', vol=9_000)))
check('more sellers than buyers does not', not th.qualifies(tok(WOJAK, 'WOJAK', buys=100, sells=300)))
check('100% buys (honeypot shape) does not', not th.qualifies(tok(WOJAK, 'WOJAK', buys=500, sells=0)))
check('a zero price does not', not th.qualifies(tok(WOJAK, 'WOJAK', price=0)))

# ── endpoint: appears, stays, disappears ──
BASE, CSRF = 'https://orcagent.fun', 'tok' * 10
H = {'X-CSRF-Token': CSRF}
guest = app.test_client()
def hero(c=None):
    fresh()
    return (c or guest).get('/api/home/trending-hero', base_url=BASE).get_json()

scanner[:] = []
r = hero()
check('no trending token -> no card', r['ok'] and r['token'] is None)

scanner[:] = [tok('ScamMint1111111111111111111111111111111pump', 'SCAM', vol=9_000_000), tok(WOJAK, 'WOJAK'),
              tok(PEPE, 'PEPE', vol=60_000)]
r = hero()
check('a trending token appears automatically', r['token'] and r['token']['symbol'] == 'WOJAK')
check('...a scam-flagged token is never promoted, however big', r['token']['mint'] != 'ScamMint1111111111111111111111111111111pump')
check('...with the card data the UI needs', all(k in r['token'] for k in
      ('price_usd', 'price_change_24h', 'volume_24h', 'buys_24h', 'sells_24h', 'chain', 'pair_address')))
check('...and zeroed social counts', r['social'] == {'bull': 0, 'bear': 0, 'likes': 0, 'my_vote': 0, 'liked': False})

# PEPE now out-trades WOJAK, but WOJAK is still (loosely) trending: it stays.
scanner[:] = [tok(PEPE, 'PEPE', vol=5_000_000), tok(WOJAK, 'WOJAK', change=18, vol=40_000)]
check('the current hero stays while still trending (no flicker)', hero()['token']['symbol'] == 'WOJAK')
# WOJAK cools off completely -> the next trending token takes over.
scanner[:] = [tok(PEPE, 'PEPE', vol=5_000_000), tok(WOJAK, 'WOJAK', change=4, vol=10_000)]
check('when it stops trending the next one takes over', hero()['token']['symbol'] == 'PEPE')
# Nothing trends any more -> the card disappears.
scanner[:] = [tok(PEPE, 'PEPE', change=3, vol=5_000)]
check('when nothing trends the card disappears', hero()['token'] is None)

# ── votes and likes ──
scanner[:] = [tok(WOJAK, 'WOJAK')]
hero()
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
member = app.test_client()
with member.session_transaction(base_url=BASE) as s:
    s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = CSRF
def vote(v, mint=WOJAK, c=member):
    return c.post('/api/home/trending-hero/vote', json={'mint': mint, 'vote': v}, headers=H, base_url=BASE)
def like(mint=WOJAK, c=member):
    return c.post('/api/home/trending-hero/like', json={'mint': mint}, headers=H, base_url=BASE)

r = vote('bull').get_json()
check('a member can vote bullish', r['ok'] and r['social']['bull'] == 1 and r['social']['my_vote'] == 1)
r = vote('bear').get_json()
check('switching to bearish moves the vote (one vote each)', r['social']['bull'] == 0 and r['social']['bear'] == 1)
r = vote('bear').get_json()
check('tapping the same vote again takes it back', r['social']['bear'] == 0 and r['social']['my_vote'] == 0)
r = like().get_json()
check('a member can like the token', r['ok'] and r['social']['likes'] == 1 and r['social']['liked'])
r = like().get_json()
check('liking again takes it back', r['social']['likes'] == 0 and not r['social']['liked'])
vote('bull'); like()
r = hero(member)
check('the card shows my vote and like', r['social']['my_vote'] == 1 and r['social']['liked'])
r = hero()
check('...and guests see the counts without a personal vote', r['social']['bull'] == 1 and r['social']['my_vote'] == 0)

check('guests cannot vote', vote('bull', c=guest).status_code in (401, 403))
check('an invalid vote is refused', vote('moon').status_code == 400)
check('a token that was never the hero cannot be voted on',
      vote('bull', mint='Rand0mMint111111111111111111111111111111pump').status_code == 409)
check('garbage mints are refused', like(mint='<script>').status_code == 409)

# ── assets are on the home page ──
html = open(os.path.join(os.path.dirname(__file__), '..', 'dashboard.html')).read()
check('home loads the hero script and styles',
      '/static/home-trending-hero.js?v=__ASSET_VER__' in html and '/static/home-trending-hero.css?v=__ASSET_VER__' in html)
raise SystemExit(0 if all(checks) else 1)
