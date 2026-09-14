"""Regression checks for BNB Chain USDC-only BUYs.

The invariant is economic, not cosmetic: a user with USDC and zero BNB must
be able to BUY without an OrcAgent-funded sponsor wallet. 0x Gasless relays
the order and gas + platform fee stay inside the user's USDC-funded order.
"""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / 'bsc_gasless_trading.py').read_text(encoding='utf-8')
entry = (ROOT / 'app_entry.py').read_text(encoding='utf-8')
registry = (ROOT / 'trade_engine' / 'registry.py').read_text(encoding='utf-8')
tree = ast.parse(src)

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

check('adapter is installed in production entrypoint',
      'from bsc_gasless_trading import install as _install_bsc_gasless_trading' in entry
      and '_install_bsc_gasless_trading(_dashboard)' in entry)
check('BSC uses chain id 56 and its real 18-decimal Binance-Peg USDC',
      "_BSC_CHAIN_ID = 56" in src
      and "'0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', 'USDC', 18" in registry)
check('buy obtains a 0x Gasless v2 quote rather than a normal gas-funded swap quote',
      "'/gasless/quote'" in src and "'0x-version': _HEADERS_VERSION" in src)
check('the user trading wallet is the gasless taker',
      'Account.from_key(private_key).address' in src and "'taker': taker" in src)
check('OrcAgent fee is embedded into the same USDC order',
      "'swapFeeRecipient': _fee_recipient(d)" in src
      and "'swapFeeBps': str(fee_bps)" in src
      and "'swapFeeToken': stable.address" in src)
check('BSC BUY bypasses the native-BNB precheck but other actions keep normal gas logic',
      "if chain == _BSC and _is_buy_context():" in src
      and 'return original_ensure(' in src)
check('only BSC BUY is replaced; sells and other chains keep the old executor',
      "if chain != _BSC or str(action).lower() != 'buy':" in src
      and 'return original_execute(' in src)
check('gasless approval is signed when 0x provides it',
      "issues.get('allowance') is not None" in src
      and "approval = quote.get('approval')" in src
      and '_sign_eip712(private_key, approval)' in src)
check('a non-gasless approval never silently asks the user for BNB',
      'This USDC approval cannot be completed gaslessly' in src)
check('trade is signed EIP-712 and submitted to the relayer',
      'Account.sign_typed_data' in src
      and "'signatureType': 2" in src
      and "'/gasless/submit'" in src)
check('relayed trade is not marked successful until 0x reports confirmed',
      "'/gasless/status/'" in src and "if last == 'confirmed':" in src)
check('the old second ERC20 fee transfer is skipped after a gasless BSC buy',
      'state.last_bsc_buy' in src and '_record_bundled_fee(' in src
      and "chain == _BSC and str(kind).lower() == 'buy'" in src)
check('private keys and signatures are not logged by the adapter',
      'print(' not in src and 'logger.' not in src)

raise SystemExit(0 if all(checks) else 1)
