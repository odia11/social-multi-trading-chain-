"""Portfolio shows the same, correct numbers everywhere.

One fixed wallet: 30 USDC + 0.5 SOL at $150 + $20 of another token, all on
Solana -- $125 in total. (It used to hold 10 USDC on Base as well; the app is
Solana-only now, so EVM balances are not counted -- see the stub below.) The header, mobile Home, Wallet page
and profile already used the multi-chain /api/portfolio/snapshot; three
places did their own maths and showed something else:

- the desktop Home "Portfolio" card read sol_price from /api/wallet/balance,
  which returns sol_price_usd, so SOL always counted as $0 ($60, not $135);
- the in-app wallet overview read /api/wallet/total, which sums Solana
  tokens only, so USDC on the EVM chains was missing ($125);
- the bot page's Capital was the Solana trading wallet's USDC only, while
  the bot also trades with USDC on its EVM chains.
All of them now read the snapshot.
"""
import os, sqlite3, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

wallet = str(Keypair().pubkey()); uid = d.get_or_create_user(wallet)
c = sqlite3.connect(d.DB_FILE)
c.execute('UPDATE users SET bsc_wallet_address=? WHERE id=?', ('0x' + 'ab' * 20, uid)); c.commit(); c.close()
d._sol_price_usd = 150.0
d._get_trading_wallet_address = lambda w: str(Keypair().pubkey())
d._get_user_sol = lambda a: 0.5
d._get_solana_usdc_balance = lambda a: 30.0
d.get_evm_usdc_balance = lambda a, chain: 10.0 if chain == 'base' else 0.0
d._fetch_wallet_tokens = lambda w, o=None: {'ts': time.time(), 'total_usd': 125.0, 'total_sol': 0.8333, 'tokens': [
    {'mint': d.SOL_MINT, 'symbol': 'SOL', 'amount': 0.5, 'price_usd': 150.0, 'value_usd': 75.0},
    {'mint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 'symbol': 'USDC', 'amount': 30.0, 'price_usd': 1.0, 'value_usd': 30.0},
    {'mint': 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263', 'symbol': 'BONK', 'amount': 1e6, 'price_usd': 2e-5, 'value_usd': 20.0}]}

client = app.test_client()
BASE = 'https://orcagent.fun'
with client.session_transaction(base_url=BASE) as s:
    s['wallet'] = wallet; s['user_id'] = uid; s['csrf_token'] = 'x' * 30
snap = client.get('/api/portfolio/snapshot', base_url=BASE).get_json()
check('the snapshot totals the Solana wallet: $30 USDC + $75 SOL + $20 other = $125, '
      'and an EVM balance is not counted (Solana-only)',
      snap['ok'] and snap['total_usd'] == 125 and snap['stable']['total_usdc'] == 30
      and snap['stable']['evm_chains'] == {}
      and snap['sol']['value_usd'] == 75 and snap['other_assets_value_usd'] == 20
      and snap['available_to_trade_usdc'] == 30)
prof = client.get(f'/api/profile/{uid}/portfolio-balance', base_url=BASE).get_json()
check('the profile card shows that same total (in SOL: 0.8333 x $150 = $125)',
      prof['ok'] and abs(prof['portfolio_value_sol_approx'] * 150.0 - 125.0) < 0.01)

home = read('static', 'home-desktop.js')
check('desktop Home "Portfolio" card reads the snapshot (it showed SOL as $0)',
      "fetch('/api/portfolio/snapshot'" in home and 'money(num(s.total_usd))' in home
      and 'b.sol_price' not in home and "fetch('/api/wallet/balance'" not in home)
dash = read('static', 'dashboard.js')
check('the in-app wallet overview total reads the snapshot (it missed EVM USDC)',
      "fetch('/api/portfolio/snapshot').then(r=>r.json()).catch(()=>null)" in dash
      and "fetch('/api/wallet/total')" not in dash)
bot = read('templates', 'auto_trading_bot.html')
check('the bot page Capital is the SOL it can trade with, from the same snapshot '
      '(0.5 SOL less the network reserve)',
      'async function loadCapital(ov)' in bot and 's.available_to_trade_sol' in bot
      and 'loadCapital(ov)])' in bot and abs(snap['available_to_trade_sol'] - 0.495) < 1e-9)
for name, src in (('header', read('static', 'header-stable-balance.js')),
                  ('mobile Home', read('static', 'home-mobile.js')),
                  ('Wallet page', read('templates', 'wallet.html'))):
    check(f'{name} keeps reading the same snapshot', '/api/portfolio/snapshot' in src)
wal = read('templates', 'wallet.html')
check('large token amounts are readable on the Wallet page (1,000,000 not 1000000.0000)',
      "amt.toLocaleString('en-US',{maximumFractionDigits:amt>=1000?2:4})" in wal)
raise SystemExit(0 if all(checks) else 1)
