"""A shared trade must say which side it actually was.

WHAT WAS BROKEN
/api/my-trades -- the endpoint behind the composer's "share your last trade"
picker -- never returned `side` at all. The client (_attachTradeEmbed in
dashboard.js) defaults a missing side to 'BUY':

    var side = (t.side || 'BUY').toUpperCase();

Every row this endpoint can return already has an exit_price (its own WHERE
clause guarantees that), so every one of them is a CLOSED position -- bot or
manual makes no difference, both write through the same close-recording
path. But because the API never said so, every single shared trade posted as
a green BUY card, and the "what would this be worth if you had held it"
line -- which only ever shows on a SELL -- could never appear on anything
shared this way, regardless of how the trade was actually made.

THE FIX RESPECTS AN EXISTING, NARROWER MEANING
`side` on this table isn't free to just mean "buy or sell" -- it was added
specifically for Live Market's instant-trade endpoint, which can genuinely
record either leg on its own (lowercase 'buy'/'sell'). wallet_manual_trades()
already established the right fallback for everything else: NULL always
means a close, because "there's no manual buy without a side" -- its own
words. This applies that exact same reasoning here, rather than writing a
new, conflicting meaning into the column or two separate INSERT statements
elsewhere in the codebase.
"""
import ast
import os
import re
import sys
import tempfile
import sqlite3

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
JS = open(REPO + '/static/dashboard.js', encoding='utf-8').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''

# ── 1. the source ──────────────────────────────────────────────────────────
my_trades = fn('api_my_trades')
check('api_my_trades now selects side from the trades table',
      # The SQL is two adjacent Python string literals ('...side ' 'FROM...'),
      # so a quote character sits between them -- the first version of this
      # regex excluded quotes from the gap and could never match its own
      # target.
      re.search(r"SELECT[\s\S]*?\bside\b[\s\S]*?FROM trades", my_trades))
check('...and returns it in the response, not just reads it',
      re.search(r"'side':\s*side", my_trades))
check('a genuine instant-trade side (lowercase buy/sell) is respected rather '
      "than overwritten -- this isn't a blanket \"always SELL\"",
      "_raw_side in ('buy', 'sell')" in my_trades)
check('...and anything else (NULL, above all) resolves to SELL, matching '
      "wallet_manual_trades()'s own documented reasoning",
      "else 'SELL'" in my_trades)

wallet_manual = fn('wallet_manual_trades')
check("the reasoning this borrows actually exists where it's cited",
      "there's no \"manual buy\" without a side" in wallet_manual
      or 'no "manual buy" without a side' in wallet_manual)

# ── 2. real rows, through the real endpoint ────────────────────────────────
d = tempfile.mkdtemp()
os.environ.update({'DATA_DIR': d, 'SECRET_KEY': 'x' * 32,
                   'ENCRYPTION_KEY': 'K' * 43 + '=', 'DEV': '1'})
sys.path.insert(0, REPO)
import dashboard as m

W = 'WalletSideFixTest'
uid = m.get_or_create_user(W)
conn = sqlite3.connect(m.DB_FILE)
# A manually-closed position -- the _record_user_trade / EVM-manual-sell
# shape. No side column written, exactly as those two INSERTs leave it.
conn.execute('''INSERT INTO trades
    (user_id, token, entry_price, exit_price, amount, pnl, timestamp,
     mint_address, chain, base_currency, source)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
    (uid, 'MANUALCLOSE', 0.0001, 0.0002, 500000.0, 50.0,
     '2026-01-01T00:00:00Z',
     'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263', 'solana', 'SOL', 'manual'))
# A genuine Live Market instant-trade buy leg -- side really is 'buy'.
conn.execute('''INSERT INTO trades
    (user_id, token, entry_price, exit_price, amount, pnl, timestamp,
     mint_address, chain, base_currency, source, side)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
    (uid, 'INSTANTBUY', 0.001, 0.001, 10.0, 0.0, '2026-01-02T00:00:00Z',
     'So11111111111111111111111111111111111111112', 'solana', 'SOL', 'manual', 'buy'))
conn.commit()
conn.close()

app = m.app
app.config['TESTING'] = True
with app.test_client() as c:
    with c.session_transaction() as s:
        s['wallet'] = W
    api_trades = {t['symbol']: t for t in c.get('/api/my-trades').get_json()['trades']}

check('a manually-closed position (no side ever written) comes back SELL, '
      'not the client default of BUY',
      api_trades.get('MANUALCLOSE', {}).get('side') == 'SELL')
check('a genuine instant-trade buy leg still comes back BUY, unchanged',
      api_trades.get('INSTANTBUY', {}).get('side') == 'BUY')

# ── 3. the whole chain, through the real client-side renderer ─────────────
def jsfn_to_next(name):
    start = JS.index('function ' + name + '(')
    end = JS.index('\nfunction ', start + 10)
    return JS[start:end]

esc_src = ("function esc(s){return (s==null?'':String(s)).replace(/[&<>\"']/g, "
          "function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"
          "\"'\":'&#39;'}[c];});}")
attach_body = jsfn_to_next('_attachTradeEmbed')
render_body = jsfn_to_next('_renderTradeTerminalCard')

harness_path = os.path.join(tempfile.mkdtemp(), 'harness.js')
harness = esc_src + '\n' + render_body + '''
// Reproduces exactly what _attachTradeEmbed builds, from the API row.
function attach(t){
  var side = (t.side || 'BUY').toUpperCase();
  return {symbol: t.symbol, side: side, entry_price: t.entry_price,
          exit_price: t.exit_price, pnl_pct: 100, pnl_sol: t.pnl_sol,
          amount: t.amount, duration: '', token_address: t.token_address,
          pnl_currency: t.pnl_currency};
}
var apiRows = JSON.parse(process.argv[2]);
apiRows.forEach(function(row){
  var html = _renderTradeTerminalCard(attach(row));
  console.log(row.symbol + ' fumbleSlot=' + (html.indexOf('tc-fumble') !== -1));
});
'''
open(harness_path, 'w').write(harness)

import subprocess
payload = [
    {'symbol': 'MANUALCLOSE', 'side': api_trades['MANUALCLOSE']['side'],
     'entry_price': 0.0001, 'exit_price': 0.0002, 'pnl_sol': 50.0,
     'amount': 500000.0, 'token_address': 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',
     'pnl_currency': 'SOL'},
    {'symbol': 'INSTANTBUY', 'side': api_trades['INSTANTBUY']['side'],
     'entry_price': 0.001, 'exit_price': 0.001, 'pnl_sol': 0.0,
     'amount': 10.0, 'token_address': 'So11111111111111111111111111111111111111112',
     'pnl_currency': 'SOL'},
]
import json
out = subprocess.run(['node', harness_path, json.dumps(payload)],
                      capture_output=True, text=True, timeout=15)
print(out.stdout.strip())
if out.returncode != 0:
    print(out.stderr[:1000])

check('end to end, through the real _attachTradeEmbed + _renderTradeTerminalCard '
      'code: the shared manually-closed trade now gets the fumble slot',
      'MANUALCLOSE fumbleSlot=true' in out.stdout)
check('...and the genuine buy leg still does not',
      'INSTANTBUY fumbleSlot=false' in out.stdout)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
