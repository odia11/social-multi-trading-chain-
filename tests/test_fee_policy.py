from pathlib import Path
import re

d = Path('dashboard.py').read_text()
g = Path('gas_manager.py').read_text()

checks = {
    'transaction fee is exactly 0.75%': bool(re.search(r'FEE_RATE_TXN\s*=\s*0\.0075\b', d)),
    'legacy performance fee disabled': bool(re.search(r'FEE_RATE_DEFAULT\s*=\s*0\.0\b', d)),
    'legacy fee hook returns zero': "def _get_fee_rate():" in d and "return 0.0" in d[d.index("def _get_fee_rate():"):d.index("FEE_WALLET", d.index("def _get_fee_rate():"))],
    'solana fees always use fee wallet': 'def _sol_fee_recipient() -> str:' in d and 'return FEE_WALLET' in d[d.index('def _sol_fee_recipient() -> str:'):d.index('def _sponsor_solana_gas', d.index('def _sol_fee_recipient() -> str:'))],
    'evm fees always use revenue wallet': 'def _evm_fee_recipient(chain: str) -> str:' in d and 'return EVM_CHAIN_FEE_WALLET' in d[d.index('def _evm_fee_recipient(chain: str) -> str:'):d.index('def _charge_evm_txn_fee', d.index('def _evm_fee_recipient(chain: str) -> str:'))],
    'sponsor auto-refill disabled': 'def _refill_sponsor_wallet():' in g and 'return' in g[g.index('def _refill_sponsor_wallet():'):g.index('def sweep_once()', g.index('def _refill_sponsor_wallet():'))],
    'no hardcoded 5% pending-fee math': 'SUM(t.pnl * 0.05)' not in d,
    'recovery does not derive gross profit from fee rate': "total_fee / _get_fee_rate()" not in d,
}
for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ': ' + name)
    if not ok:
        raise SystemExit(1)
print(f'{len(checks)}/{len(checks)} checks passed')
