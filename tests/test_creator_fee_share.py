"""OrcAgent's 20% share of NEW tokens' creator fees.

- A new creator or community launch is saved with 2000 bps for OrcAgent;
  the creator keeps the rest (minus any community share). Holder Rewards
  tokens and launches from before this change stay at 0.
- The split is installed ON-CHAIN as fee-sharing shareholders, with the
  same second wallet approval the community split already used: the real
  launch builder asks for that finalization, and its transaction names the
  OrcAgent wallet with 2000 bps.
- The on-chain check expects exactly creator 8000 + OrcAgent 2000 (or
  creator + community + OrcAgent), so a launch whose split was changed
  never becomes live.
- Claims on such a token are distributions to every shareholder, never
  the creator's wallet-wide vault; old 100% creator tokens keep that vault.
Uses the real Node transaction builder with mocked RPC; nothing is sent.
"""
import base64, os, sqlite3, sys
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT))
from test_token_launch import setup, icon, public_simulated_reply  # noqa: E402
import token_launch  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.transaction import Transaction  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

ORC = 'HC5ahspSox3XRmDbzXjXVoAASuY89RCmGUKwp87FRJS5'
check('the default OrcAgent share is 20% of creator fees (2000 bps)', token_launch.ORCAGENT_CREATOR_FEE_BPS == 2000)

tmp, app, d = setup()
d.FEE_WALLET = ORC
wallet, community = str(Keypair().pubkey()), str(Keypair().pubkey())
client = app.test_client()
with client.session_transaction() as s:
    s['wallet'] = wallet; s['csrf_token'] = 'test-csrf'
H = {'X-CSRF-Token': 'test-csrf'}
P = '/api/token-launch/'
n = [0]
def draft(mode, **extra):
    n[0] += 1
    body = {'client_nonce': 'fee-share-nonce-%06d' % n[0], 'name': 'Share Token', 'symbol': 'SHR',
            'description': '', 'image_data': icon(), 'reward_mode': mode, 'quote_asset': 'USDC', **extra}
    return client.post(P + 'draft', json=body, headers=H)

r = draft('creator'); row = r.get_json()['draft']
check('a new creator launch is saved with OrcAgent 20% / creator 80%',
      r.status_code == 201 and row['orcagent_bps'] == 2000 and row['creator_bps'] == 8000)
creator_id = row['id']
r = draft('community', community_wallet=community, community_bps=1500); crow = r.get_json()['draft']
check('a community launch: creator 65% · community 15% · OrcAgent 20%',
      crow['orcagent_bps'] == 2000 and crow['community_bps'] == 1500 and crow['creator_bps'] == 6500)
r = draft('community', community_wallet=community, community_bps=8000)
check('a community share that would leave the creator nothing is refused, naming OrcAgent\'s 20%',
      r.status_code == 400 and 'OrcAgent receives 20%' in r.get_json()['msg'])
r = draft('holder'); hrow = r.get_json()['draft']
check('a Holder Rewards launch has no OrcAgent share', hrow['orcagent_bps'] == 0)

shared, orc_bps = app._orca_launch_shared, app._orca_launch_orc_bps
old = {'reward_mode': 'creator', 'orcagent_bps': 0, 'quote_asset': 'USDC'}
check('a token launched before this change keeps 0% and its wallet-wide creator claim',
      orc_bps(old) == 0 and not shared(old))
check('a new creator token is a fee-sharing token (paid out by distribution)',
      shared({'reward_mode': 'creator', 'orcagent_bps': 2000}))
exp = app._orca_expected_shares
check('on-chain the split must be exactly creator 8000 + OrcAgent 2000',
      exp(wallet, '', 0, 2000) == {wallet: 8000, ORC: 2000})
check('...or creator 6500 + community 1500 + OrcAgent 2000',
      exp(wallet, community, 1500, 2000) == {wallet: 6500, community: 1500, ORC: 2000})

# ── the real builder: create asks for the split approval; the split names OrcAgent ──
blockhash = str(Keypair().pubkey())
with patch.dict(os.environ, {'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED': '1'}):
    with patch('token_launch.requests.post') as post:
        post.return_value.raise_for_status = lambda: None
        post.return_value.json = lambda: public_simulated_reply(post.call_args.kwargs['json']['method'], blockhash)
        r = client.post(P + creator_id + '/prepare', json={}, headers=H)
        built = r.get_json() or {}
        check('the creator launch needs the second approval that locks the split',
              r.status_code == 200 and built.get('needs_finalization') is True, )
        mint = built.get('mint', '')
        with sqlite3.connect(d.DB_FILE) as conn:
            conn.execute("UPDATE token_launches SET status='pending_shares', launch_signature=? WHERE id=?",
                         ('5' * 88, creator_id))
        r = client.post(P + creator_id + '/prepare-finalize', json={}, headers=H)
        fin = r.get_json() or {}
        ok = r.status_code == 200 and 'transaction_b64' in fin
        tx = Transaction.from_bytes(base64.b64decode(fin['transaction_b64'])) if ok else None
        data = b''.join(bytes(ix.data) for ix in tx.message.instructions) if tx else b''
        keys = [str(k) for k in tx.message.account_keys] if tx else []
        check('the split transaction pays OrcAgent 2000 bps and the creator 8000 bps',
              ok and (ORC in keys or bytes(Pubkey.from_string(ORC)) in data)
              and (2000).to_bytes(2, 'little') in data and (8000).to_bytes(2, 'little') in data)
        check('...for one wallet approval, within Solana\'s size limit',
              ok and len(base64.b64decode(fin['transaction_b64'])) <= 1232 and len(tx.signatures) == 1)

# ── the page shows it before approval ──
page = client.get('/token-launch').get_data(as_text=True)
check('the launch page shows the $0 launch fee and 20% of creator fees (not of volume) before approval',
      '<strong>$0</strong>' in page and 'OrcAgent share of creator fees' in page
      and 'not of trading volume' in page and 'orcagentBps:2000' in page)
check('no launch-protocol branding on the page or in its script', 'Pump' not in page
      and 'Pump' not in (ROOT / 'static' / 'token-launch.js').read_text())
js = (ROOT / 'static' / 'token-launch.js').read_text()
import re, subprocess  # noqa: E402
helpers = re.search(r'function money\(n\).*?\n', js).group(0) + re.search(r'function splitText\(row\)\{.*?\n\}\n', js, re.S).group(0)
out = subprocess.run(['node', '-e', helpers + 'console.log(splitText({orcagent_bps:2000,reward_mode:"creator",community_bps:0}));'
                      'console.log(splitText({orcagent_bps:2000,reward_mode:"community",community_bps:1500,community_wallet:"C"}))'],
                     capture_output=True, text=True, timeout=20).stdout.split('\n')
check('the second approval names the whole split, OrcAgent included',
      out[0] == '80% creator / 20% OrcAgent' and out[1] == '65% creator / 15% community (C) / 20% OrcAgent'
      and "Final split of the creator fees: '+splitText(row)" in js)
tmp.cleanup()
raise SystemExit(0 if all(checks) else 1)
