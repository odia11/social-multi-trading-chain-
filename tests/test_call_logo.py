"""A called token gets its logo, and a tile without one stays neat.

Seen on a call for $超级天柴 (a new BSC meme): no picture, and the tile
showed the first four characters of the symbol, which wrapped onto two lines
and ran out of the tile.

- A call kept the logo it was made with; a token without one at that moment
  (DexScreener has no profile for most brand-new memes) stayed without one
  forever. Calls without a logo now get one as soon as a source has it: the
  pairs the peak loop already fetches, then GeckoTerminal for a few tokens per
  round, and right after the call is made.
- GeckoTerminal's generic "missing.png" is not a logo.
- Without a logo the tile shows up to three Latin letters, or two characters
  of a wider script, on one line.
"""
import json, os, sqlite3, subprocess, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

GT_MISSING = 'https://assets.geckoterminal.com/missing.png'
check("GeckoTerminal's generic missing.png is not a token's logo",
      d._call_token_row('m', 'S', 'N', 'bsc', 1, 0, GT_MISSING)['image_url'] == ''
      and d._call_token_row('m', 'S', 'N', 'bsc', 1, 0, 'https://cdn.example/logo.png')['image_url'])

w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
bsc_new, bsc_old, sol_dex, bsc_none = ('0x' + c * 40 for c in 'abcd')
c = sqlite3.connect(d.DB_FILE)
for mint, chain, img in ((bsc_new, 'bsc', ''), (bsc_old, 'bsc', 'https://cdn.example/kept.png'),
                         (sol_dex, 'solana', ''), (bsc_none, 'bsc', '')):
    c.execute('INSERT INTO token_calls (user_id, wallet, mint, symbol, token_name, price_at_call, mcap_at_call, '
              'peak_price, chain, image_url) VALUES (?,?,?,?,?,?,?,?,?,?)',
              (uid, w, mint, '超级天柴', 'Super Inu', 1.0, 0, 1.0, chain, img))
c.commit(); c.close()
def logo(mint):
    c = sqlite3.connect(d.DB_FILE)
    r = c.execute('SELECT image_url FROM token_calls WHERE mint=?', (mint,)).fetchone()[0]
    c.close(); return r

asked = []
class R:
    def __init__(self, body): self.status_code, self._b = 200, body
    def json(self): return self._b
def fake_get(url, *a, **k):
    asked.append(url)
    if bsc_new.lower() in url.lower():
        return R({'data': {'attributes': {'image_url': 'https://assets.geckoterminal.com/super-inu.png'}}})
    return R({'data': {'attributes': {'image_url': GT_MISSING}}})
d.requests.get = fake_get
d._gt_try_take = lambda reserve=0: True
chain_of = {bsc_new: 'bsc', bsc_old: 'bsc', sol_dex: 'solana', bsc_none: 'bsc'}
found = d._call_fill_images([bsc_new, sol_dex, bsc_none], chain_of,
                            {sol_dex: 'https://dd.dexscreener.com/ds-data/tokens/solana/x.png'})
check('a call made without a logo gets the one GeckoTerminal has', logo(bsc_new) == 'https://assets.geckoterminal.com/super-inu.png')
check('...or the one DexScreener already returned to the peak loop, with no extra request',
      logo(sol_dex).startswith('https://dd.dexscreener.com/') and not any(sol_dex.lower() in u.lower() for u in asked))
check('...a token that still has none stays empty (missing.png is not written)', logo(bsc_none) == '')
check('a call that already has a logo keeps it', logo(bsc_old) == 'https://cdn.example/kept.png')
n = len(asked)
d._call_fill_images([bsc_none], chain_of)
check('a token without a logo is not asked about again every round (retry after a while)', len(asked) == n)

src = read('dashboard.py')
loop = src[src.index('def _calls_peak_loop():'):src.index("@app.route('/api/leaderboard'")]
check('the peak loop collects logos from the pairs it already fetches and fills calls without one',
      "image_by_mint[m] = p['info']['imageUrl']" in loop and '_call_fill_images(no_logo, chain_of, image_by_mint)' in loop)
check('a new call without a logo asks right away, in the background',
      "threading.Thread(target=_call_fill_images, args=([mint], {mint: chain})" in src)

js = read('static', 'feed-calls.js')
fn = js[js.index('  function tileInitials(sym){'):js.index('  function parseTs(ts){')]
out = subprocess.run(['node', '-e', fn + ';console.log(JSON.stringify([tileInitials("超级天柴"),'
                      'tileInitials("$popcat"),tileInitials("🐸FROG"),tileInitials("")]))'],
                     capture_output=True, text=True).stdout
got = json.loads(out or '[]')
check('without a logo: two characters of a wide script on one line, not four wrapping out of the tile',
      got and got[0] == {'text': '超级', 'wide': True})
check('...three letters of a Latin symbol, an emoji kept whole, "?" when there is nothing',
      got and got[1]['text'] == 'POP' and got[2]['text'] == '🐸F' and got[3]['text'] == '?')
css = read('static', 'feed-calls.css')
check('...and the tile never wraps its text', '.fcall-tile>span{white-space:nowrap' in css
      and "(ini.wide ? ' wide' : '')" in js)
raise SystemExit(0 if all(checks) else 1)
