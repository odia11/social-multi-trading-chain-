"""SOL and SPL Portfolio sends stay Solana-only, fail over RPCs and do not self-send."""
from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
D=(ROOT/'dashboard.py').read_text()
W=(ROOT/'static/portfolio-token-send.js').read_text()
T=(ROOT/'portfolio_token_withdraw.py').read_text()

checks=[]
def check(label, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+label)

send=D[D.index('def send_sol_fee'):D.index('# ── OPTIONAL, SELF-DECLARED PROFILE FLAG')]
route=D[D.index("@app.route('/api/wallet/send'"):D.index('# Two-entry RPC list')]
withdraw=T[T.index("@app.post('/api/wallet/send-token')"):T.index("marker = 'data-orca-token-withdraw")]

check('native SOL send uses multiple configured RPCs rather than one public endpoint',
      "CLAIM_SOL_RPCS" in send and "_PROXY_RPCS" in send and "for rpc in ordered" in send)
check('native send uses confirmed preflight and does not skip it',
      "'preflightCommitment': 'confirmed'" in send and "'skipPreflight': False" in send)
check('same signed SOL transaction can fall through transport failures',
      "resp.status_code != 200" in send and "continue" in send)
check('a real simulation/insufficient-funds rejection is not hidden by another RPC',
      "'simulation failed'" in send and "'insufficient'" in send and "raise RuntimeError" in send)
check('native send rejects its own trading wallet, not only the login wallet',
      "trading_wallet = _get_trading_wallet_address(wallet) or wallet" in route
      and "to_addr in (wallet, trading_wallet)" in route)
check('send errors are redacted before reaching logs or the browser',
      "_redact_keys(_scrub_url_secrets(str(e)))" in route)
check('portfolio Send can transfer every verified SPL asset including USDC',
      "'/api/wallet/send-token'" in W and "state.assets" in W and "token_address:a.token" in W)
check('token transfer validates on-chain balance before signing',
      "send_raw > balance_raw" in T and "higher than your on-chain token balance" in T)
check('token transfer rejects a self-send to the trading wallet',
      "owner_text == to_address" in T)
check('token withdrawal is CSRF-protected, rate-limited and duplicate guarded',
      "_csrf_ok(d)" in withdraw and "_rate_ok('withdraw_wallet:' + wallet" in withdraw
      and "already submitted recently" in withdraw)
check('token withdrawal can create user-funded Solana gas without reducing outgoing USDC',
      "allow_user_funded_gas=True" in withdraw
      and "reserved = amount if token_address == d.USDC_MINT" in T)
check('all active send UI/route chains are Solana only',
      "var CHAIN={solana:'Solana'}" in W and "chain != 'solana'" in withdraw)

ast.parse(D)
ast.parse(T)
check('send backends parse', True)

raise SystemExit(0 if all(checks) else 1)
