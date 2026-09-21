from pathlib import Path
from decimal import Decimal
from trade_engine.costs import price_trade

d = Path('dashboard.py').read_text()
s = Path('orcagent_solana.py').read_text()
b = Path('bsc_gasless_trading.py').read_text()

q = price_trade(Decimal('100'), Decimal('0.0075'), ())
assert q.token_purchase_usd == Decimal('99.25'), q
fee = next(c.usd for c in q.costs if c.kind == 'platform_fee')
assert fee == Decimal('0.75'), fee

checks = {
    'only fee rate is 0.75%': 'FEE_RATE_TXN     = 0.0075' in d,
    'performance fee disabled': 'FEE_RATE_DEFAULT = 0.0' in d,
    'Solana supports bundled SOL and USDC input buys':
        'input_mint in (SOL_MINT, USDC_MINT)' in s,
    'Solana USDC fee uses SPL TransferChecked':
        "data=bytes([12]) + struct.pack('<Q', fee_lamports) + bytes([6])" in s,
    'Solana has no fee-less retry':
        'retrying once without it' not in s and 'normal buy, no fee this time' not in s,
    'EVM normal swaps request embedded platform fee':
        "apply_platform_fee=True" in d,
    '0x fee recipient is revenue wallet':
        "'swapFeeRecipient': EVM_CHAIN_FEE_WALLET" in d,
    '0x fee is exactly 75 bps':
        "'swapFeeBps': str(int(round(FEE_RATE_TXN * 10000)))" in d,
    '0x fee token is chain stablecoin':
        "'swapFeeToken': _fee_token" in d,
    'gasless swaps use same fee bps':
        "'swapFeeBps': str(fee_bps)" in b,
    'gasless swaps use normal fee resolver':
        "'swapFeeRecipient': _fee_recipient(d, chain_name)" in b,
    'no automatic sponsor fee routing':
        "def _evm_fee_recipient(chain: str) -> str:\n    \"\"\"All EVM platform fees go directly to the normal revenue fee wallet.\"\"\"\n    return EVM_CHAIN_FEE_WALLET" in d,
    'all expected EVM chains configured':
        all(("'"+c+"':") in d for c in ('bsc','base','arbitrum','polygon','robinhood')),
}
for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ': ' + name)
    assert ok, name
print(f'{len(checks)}/{len(checks)} checks passed')
print('PASS: $100 gross => $0.75 fee + $99.25 token purchase')
