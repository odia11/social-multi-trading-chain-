"""Regression checks for zero/low-SOL USDC-funded BUYs on Solana."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / 'solana_gasless_trading.py').read_text(encoding='utf-8')
entry = (ROOT / 'app_entry.py').read_text(encoding='utf-8')

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

check('Solana gasless adapter is installed in production entrypoint',
      'from solana_gasless_trading import install as _install_solana_gasless_trading' in entry
      and '_install_solana_gasless_trading(_dashboard)' in entry)
check('platform sponsor remains disabled before dashboard import',
      "os.environ['ORCAGENT_FRONTS_GAS'] = '0'" in entry
      and entry.index("os.environ['ORCAGENT_FRONTS_GAS'] = '0'") < entry.index('import dashboard as _dashboard'))
check('Solana BUY spends canonical USDC',
      "_USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'" in src)
check('Jupiter API key gates the gasless route instead of an OrcAgent payer key',
      "os.getenv('JUPITER_API_KEY'" in src and 'payerPrivateKey' not in src
      and 'SOL_GAS_SPONSOR_PRIVATE_KEY' not in src)
check('gasless path uses Jupiter order and execute endpoints',
      "_API + '/order'" in src and "_API + '/execute'" in src)
check('only USDC-funded BUY is intercepted; other Solana actions keep existing executor',
      "str(action).lower() != 'buy'" in src and "str(base).upper() != 'USDC'" in src
      and 'return original(' in src)
check('a low-SOL wallet refuses a non-gasless Jupiter order',
      "low_sol and not bool(data.get('gasless'))" in src
      and 'No SOL will be requested or paid by OrcAgent.' in src)
check('below-provider-minimum zero-SOL order is refused rather than subsidized',
      'code == 3' in src and "below Jupiter's current gasless minimum" in src)
check('returned transaction preserves any provider payer signature and adds user signature',
      'signatures = list(tx.signatures)' in src
      and 'signatures[index] = kp.sign_message' in src
      and 'VersionedTransaction.populate(tx.message, signatures)' in src)
check('execute retry reuses same signed transaction/requestId',
      "payload = {'signedTransaction': signed_tx, 'requestId': order.get('requestId')}" in src)
check('successful route requires Jupiter success plus transaction signature',
      "str(data.get('status') or '').lower() == 'success'" in src
      and "data.get('signature')" in src)
check('private key is never logged', 'print(' not in src and 'logger.' not in src)

raise SystemExit(0 if all(checks) else 1)
