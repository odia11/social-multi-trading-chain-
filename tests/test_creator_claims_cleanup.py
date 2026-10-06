"""Creator Earnings: stuck claims, expired attempts and SOL payouts.

- A claim prepared but never approved in Phantom kept "Claim Now" on "Check
  pending" forever (the button only opened history) and blocked every new
  claim. It is now retired ('expired_unverified') when opening Creator
  Earnings -- but only after the chain was searched for it and Solana says
  its blockhash expired; a fresh claim, one whose blockhash is still valid,
  a signed/submitted one, or anything the chain cannot be asked about, stays.
- A late approval of a retired claim is still accepted on confirmation.
- Expired attempts are folded into one line instead of a list of "Needs
  review" rows, and don't count as claims.
- Claims paid out in SOL are part of "Total claimed".
Mocked Solana RPC; never signs or sends.
"""
import base64, os, sqlite3, subprocess, sys, time, json
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT))
from test_token_launch import setup  # noqa: E402
import token_launch  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.hash import Hash  # noqa: E402
from solders.message import Message  # noqa: E402
from solders.system_program import transfer, TransferParams  # noqa: E402
from solders.transaction import Transaction  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

def tx_b64(blockhash: Hash) -> str:
    payer = Keypair()
    ix = transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=Keypair().pubkey(), lamports=1))
    tx = Transaction.new_unsigned(Message.new_with_blockhash([ix], payer.pubkey(), blockhash))
    return base64.b64encode(bytes(tx)).decode()

tmp, app, d = setup()
wallet = str(Keypair().pubkey())
client = app.test_client()
with client.session_transaction() as s:
    s['wallet'] = wallet; s['csrf_token'] = 'test-csrf'

EXPIRED, STILL_VALID = Hash.new_unique(), Hash.new_unique()
now = int(time.time())
with sqlite3.connect(d.DB_FILE) as conn:
    for lid, sym, asset in (('a' * 32, 'SUN', 'USDC'), ('b' * 32, 'GOLDEN', 'SOL'), ('c' * 32, 'ABYS', 'SOL')):
        conn.execute('''INSERT INTO token_launches (id,wallet,client_nonce,name,symbol,description,icon_webp,
            reward_mode,quote_asset,mint,status,launch_signature,created_at,finalized_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (lid, wallet, 'nonce-' + lid[:10] + '-0000', sym, sym, 'x', b'img', 'creator', asset,
             str(Keypair().pubkey()), 'live', 'x' * 88, now - 86400, now - 86400))
    def claim(cid, lid, asset, status, age, bh, sig='', received=''):
        conn.execute('''INSERT INTO token_reward_claims (id,launch_id,wallet,mint,quote_asset,reward_mode,
            accrued_raw,transaction_b64,signature,status,created_at,confirmed_at,received_raw)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (cid, lid, wallet, 'm', asset, 'creator', '772156', tx_b64(bh), sig, status, now - age,
             now - age if status == 'confirmed' else 0, received))
    claim('1' * 32, 'a' * 32, 'USDC', 'prepared', 600, EXPIRED)             # never approved, expired  -> retire
    claim('2' * 32, 'b' * 32, 'SOL', 'prepared', 900, EXPIRED)              # never approved, expired  -> retire
    claim('3' * 32, 'a' * 32, 'USDC', 'prepared', 30, EXPIRED)              # fresh (<2 min)           -> keep
    claim('4' * 32, 'b' * 32, 'SOL', 'prepared', 700, STILL_VALID)          # blockhash still valid    -> keep
    claim('5' * 32, 'a' * 32, 'USDC', 'submitted', 800, EXPIRED, 's' * 88)  # signed & sent            -> keep
    claim('6' * 32, 'c' * 32, 'SOL', 'confirmed', 5000, EXPIRED, 'q' * 88, '12500000')  # 0.0125 SOL paid
    claim('7' * 32, 'c' * 32, 'SOL', 'prepared', 1000, EXPIRED)             # approved, but never reached us -> keep
LANDED_SIG = '5' * 87

state = {'history_down': False}
def run_earnings():
    with patch('token_launch.requests.post') as rpc:
        rpc.return_value.raise_for_status = lambda: None
        def reply():
            body = rpc.call_args.kwargs['json']; method = body['method']
            if method == 'getSignaturesForAddress':
                if state['history_down']:
                    raise token_launch.requests.RequestException('rpc down')
                # The wallet's history holds the SOL claim '7' that did settle.
                return {'result': [{'signature': LANDED_SIG, 'blockTime': now - 1000 + 20, 'err': None}]}
            if method == 'getTransaction':
                # Claim '7' has a matching transaction in the wallet's history
                # that cannot be read right now: it must not be called expired.
                raise token_launch.requests.RequestException('tx lookup down')
            if method == 'isBlockhashValid':
                return {'result': {'value': body['params'][0] == str(STILL_VALID)}}
            raise AssertionError('Unexpected Solana RPC method ' + method)
        rpc.return_value.json = reply
        return client.get('/api/token-launch/creator-earnings').get_json()

def statuses():
    with sqlite3.connect(d.DB_FILE) as conn:
        return dict(conn.execute('SELECT substr(id,1,1), status FROM token_reward_claims').fetchall())

# ── chain unreachable: nothing is retired on a guess ──
state['history_down'] = True
run_earnings()
check('if the chain cannot be searched, nothing is retired', statuses()['1'] == 'prepared' and statuses()['2'] == 'prepared')

# ── normal ──
state['history_down'] = False
data = run_earnings()
st = statuses()
check('a never-approved claim whose blockhash expired is retired', st['1'] == 'expired_unverified' and st['2'] == 'expired_unverified')
check('a fresh claim (under two minutes) is left alone', st['3'] == 'prepared')
check('a claim whose blockhash is still valid is left alone', st['4'] == 'prepared')
check('a signed / submitted claim is left alone', st['5'] == 'submitted')
check('a SOL claim with a possible match on-chain is never called expired', st['7'] == 'prepared')
check('the page is told how many expired', data['expired_claims'] == 2 and data['pending_claims'] == 4)
check('SOL payouts are part of the claimed total', data['verified_claimed_raw'].get('SOL') == '12500000')

# ── the server source: prepare no longer blocked by a stale claim of another token; late confirm accepted ──
src = (ROOT / 'token_launch.py').read_text()
check('a stale claim of another token no longer blocks a new claim',
      "and expire_stale_claims(wallet)" in src and "not _pending_claim(wallet,row['quote_asset'])" in src)
check('a late approval of a retired claim is still confirmed',
      "if claim['status'] not in ('prepared','submitted','expired_unverified'):" in src
      and "AND status IN ('prepared','submitted','expired_unverified')" in src
      and "_settle_reward_claim_signature(dict(claim),sig)" in src)

# ── the page (its own functions, run in node) ──
js = (ROOT / 'static' / 'token-launch.js').read_text()
check('"Check pending" re-checks first and frees Claim Now when nothing waits',
      "creatorEarnings=await call('/api/token-launch/creator-earnings');renderCreatorEarnings()" in js
      and "if(btn.dataset.mode==='claim'){status('Nothing is waiting any more" in js)
check('only a waiting USDC claim turns Claim Now into "Check pending"',
      "return c.quote_asset==='USDC'&&(c.status==='prepared'||c.status==='submitted')" in js)
check('expired attempts read "Expired", not "Needs review"', "expired_unverified:'Expired'" in js and 'Needs review' not in js)
harness = r"""
var out={};function el(id){return out[id]||(out[id]={textContent:'',children:[],hidden:false,
  replaceChildren:function(){this.children=[]},appendChild:function(c){this.children.push(c)},dataset:{},set innerHTML(v){this._html=v}})}
var document={getElementById:el,createElement:function(t){var o={tag:t,children:[],className:'',textContent:'',
  appendChild:function(c){this.children.push(c)}};return o},querySelector:function(){return null}};
""" + js[js.index("function $("):js.index("async function refreshAvailableFees")] + r"""
mine=[{status:'live',reward_mode:'creator',quote_asset:'USDC',id:'x'}];
creatorEarnings=%s;
renderCreatorEarnings();
var hist=out['tl-global-claim-history'].children, recent=out['tl-recent-earnings'].children;
console.log(JSON.stringify({claimed:out['tl-claimed-usdc'].textContent,fiat:out['tl-claimed-fiat'].textContent,
  count:out['tl-claim-count'].textContent,note:out['tl-claim-count-note'].textContent,
  histRows:hist.filter(function(c){return c.className==='tl-claim-row'}).length,
  histNote:(hist.find(function(c){return c.className==='tl-claim-expired-note'})||{}).textContent||'',
  recentRows:recent.filter(function(c){return c.className==='tl-claim-row'}).length,
  recentNote:recent.some(function(c){return c.className==='tl-claim-expired-note'})}));
""" % json.dumps(data)
res = json.loads(subprocess.run(['node', '-e', harness], capture_output=True, text=True, timeout=30).stdout or '{}')
check('Total claimed shows the SOL payout too', res.get('fiat', '').endswith('+ 0.012500000 SOL'))
check('expired attempts do not count as claims', res.get('count') == '5' and '2 expired' in res.get('note', ''))
check('...and are one quiet line in history, not rows',
      res.get('histRows') == 5 and 'expired without approval in Phantom' in res.get('histNote', ''))
check('recent earnings list only real claims', res.get('recentRows') == 3 and not res.get('recentNote'))
tmp.cleanup()
raise SystemExit(0 if all(checks) else 1)
