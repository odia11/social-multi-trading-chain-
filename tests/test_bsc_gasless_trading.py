"""Regression checks for USDC/USDG-only BUYs on every OrcAgent EVM chain."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / 'bsc_gasless_trading.py').read_text(encoding='utf-8')
entry = (ROOT / 'app_entry.py').read_text(encoding='utf-8')
registry = (ROOT / 'trade_engine' / 'registry.py').read_text(encoding='utf-8')

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

check('adapter remains installed in production entrypoint',
      'from bsc_gasless_trading import install as _install_evm_gasless_trading' in entry
      and '_install_evm_gasless_trading(_dashboard)' in entry)
for chain, cid in [('bsc', 56), ('base', 8453), ('arbitrum', 42161),
                   ('polygon', 137), ('robinhood', 4663)]:
    check(f'{chain} is registered with chain id {cid}',
          f"'{chain}': Chain('{chain}', 'evm', {cid}" in registry)
check('BSC keeps its real 18-decimal Binance-Peg USDC',
      "'0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', 'USDC', 18" in registry)
check('Robinhood uses its real USDG asset rather than pretending it is USDC',
      "'robinhood', '0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168', 'USDG'" in registry)
check('unverified stable decimals are read from the deployed ERC20 contract',
      "contract.functions.decimals().call()" in src and 'verify_decimals(' in src)
check('every EVM buy derives chain metadata from the central registry',
      "d.te_registry.get_chain(chain_name)" in src and "chain.kind != 'evm'" in src)
check('every EVM buy obtains a 0x Gasless v2 quote',
      "'/gasless/quote'" in src and "'0x-version': _HEADERS_VERSION" in src)
check('the user trading wallet is always the gasless taker',
      'Account.from_key(private_key).address' in src and "'taker': taker" in src)
check('OrcAgent fee is embedded in the same stablecoin-funded order',
      "'swapFeeRecipient': _fee_recipient(d, chain_name)" in src
      and "'swapFeeBps': str(fee_bps)" in src
      and "'swapFeeToken': stable.address" in src)
check('all supported EVM BUYs and SELLs reach gasless execution before native-gas gating',
      "if _supported(chain) and (_is_buy_context() or _is_sell_context()):" in src
      and 'return original_ensure(' in src)
check('supported EVM BUYs and SELLs both use the gasless adapter',
      "action not in {'buy', 'sell'}" in src
      and '_gasless_sell_quote(' in src
      and 'return original_execute(' in src)
check('gasless approval is signed when 0x provides it',
      "issues.get('allowance') is not None" in src
      and "approval = quote.get('approval')" in src
      and '_sign_eip712(private_key, approval)' in src)
check('missing gasless approval never silently falls back to native gas',
      'cannot be completed gaslessly' in src and 'will be requested or spent' in src)
check('trade is signed EIP-712 and submitted with the real chain id',
      'Account.sign_typed_data' in src and "'signatureType': 2" in src
      and "'chainId': int(chain.chain_id)" in src and "'/gasless/submit'" in src)
check('relayed trade is not successful until 0x reports confirmed',
      "f'/gasless/status/{trade_hash}'" in src and "if last == 'confirmed':" in src
      and "if last in {'failed', 'reverted', 'cancelled', 'canceled'}:" in src)
check('bundled fee marker is chain-scoped and avoids a second ERC20 fee transfer',
      'state.last_evm_buy' in src and "marker.get('chain') == chain" in src
      and '_record_bundled_fee(' in src)
check('private keys and signatures are never logged by the adapter',
      'print(' not in src and 'logger.' not in src)

raise SystemExit(0 if all(checks) else 1)
