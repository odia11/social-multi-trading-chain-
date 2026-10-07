"""Swap latency contract: fewer RPCs without weakening confirmation safety."""
import ast
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
D=(ROOT/'dashboard.py').read_text()
O=(ROOT/'orcagent_solana.py').read_text()
W=(ROOT/'templates/wallet.html').read_text()

checks=[]
def check(label,cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+label)

# Base-asset decimals are protocol constants and must never cost an RPC.
tree=ast.parse(D)
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_get_token_decimals_rpc')
src=ast.get_source_segment(D,fn)
class NoPost:
    def post(self,*a,**kw): raise AssertionError('base decimals made an RPC call')
ns={'SOL_MINT':'SOL','USDC_MINT':'USDC','requests':NoPost()}
exec(src,ns)
check('SOL decimals are local and need no RPC',ns['_get_token_decimals_rpc']('SOL')==9)
check('USDC decimals are local and need no RPC',ns['_get_token_decimals_rpc']('USDC')==6)

# The route's fresh SOL read is passed into the gas check instead of fetching
# the same balance once more immediately before spawning the swap engine.
convert=D[D.index("def api_wallet_convert():"):D.index("@app.route('/api/wallet/convert-sol-usdc'")]
check('wallet convert reuses its fresh SOL balance for gas readiness',
      convert.count('known_sol_balance=current_sol')==2)
check('legacy SOL->USDC route also reuses its fresh SOL balance',
      "capture=capture, known_sol_balance=current_sol" in D)
ensure=D[D.index('def _ensure_solana_gas'):D.index('GAS_SPONSOR_REFILL_BELOW_GRANTS')]
check('gas helper accepts an already-verified balance',
      'known_sol_balance: float = None' in ensure and '_known_checked' in ensure)

# Confirmation is polled quickly at first, but the full 90s safety window stays
# intact so an ambiguous transaction is never retried while still valid.
check('full anti-double-spend confirmation window is unchanged',
      'CONFIRM_TIMEOUT_S = 90.0' in O)
check('normal confirmation polling is sub-second',
      'CONFIRM_POLL_INTERVAL_S = 0.25' in O and 'elapsed < 5.0 else 1.0' in O)
check('post-confirm balance reconciliation is faster but still retries',
      'attempts: int = 12, delay_s: float = 0.4' in O)

# Engine-level base mint decimals also avoid getTokenSupply.
import orcagent_solana as eng
with patch.object(eng,'_rpc_post',side_effect=AssertionError('unexpected decimals RPC')):
    check('engine SOL decimals are local',eng.get_token_decimals(eng.SOL_MINT)==9)
    check('engine USDC decimals are local',eng.get_token_decimals(eng.USDC_MINT)==6)

# A normal second-poll confirmation should use the new fast cadence.
statuses=iter([
    {'result':{'value':[None]}},
    {'result':{'value':[{'err':None,'confirmationStatus':'confirmed'}]}}
])
with patch.object(eng,'_rpc_post',side_effect=lambda *a,**kw: next(statuses)), \
     patch.object(eng.time,'sleep') as sleep:
    out=eng._confirm_transaction('fixture',timeout_s=5)
check('confirmation remains authoritative',out['confirmed'] is True and out['status']=='confirmed')
check('first confirmation retry waits only 0.25s',
      bool(sleep.call_args_list) and sleep.call_args_list[0].args[0]==0.25)

# The UI performs one forced authoritative portfolio snapshot immediately after
# success instead of sleeping 1.5 seconds and then firing several reads.
refresh=W[W.index('function _refreshAfterConfirmedSwap()'):W.index('function _convertConfirm()')]
check('confirmed swap forces one immediate authoritative snapshot',
      '_getPortfolioSnapshot(true)' in refresh and '_paintPortfolioSnapshotInstant(snap)' in refresh)
check('post-swap refresh does not separately force the token endpoint',
      'loadTokens(true)' not in refresh)
confirm=W[W.index('function _convertConfirm()'):W.index('// ── swap modal')]
check('success refresh has no old 1500ms delay',
      '_refreshAfterConfirmedSwap()' in confirm and '},1500)' not in confirm)

raise SystemExit(0 if all(checks) else 1)
