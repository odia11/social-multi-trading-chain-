"""Regression coverage for EIP-1559 fee headroom on EVM approvals/swaps."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "dashboard.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)
FN = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "_evm_tx_fee_fields")
ns = {}
exec(compile(ast.Module(body=[FN], type_ignores=[]), "<fee-helper>", "exec"), ns)
fee_fields = ns["_evm_tx_fee_fields"]

class Eth:
    gas_price = 110
    max_priority_fee = 10
    def get_block(self, _):
        return {"baseFeePerGas": 100}

class W3:
    eth = Eth()

def test_robinhood_uses_eip1559_headroom():
    got = fee_fields(W3(), "robinhood", 105)
    assert got["type"] == 2
    assert got["maxPriorityFeePerGas"] == 10
    assert got["maxFeePerGas"] >= 210
    assert "gasPrice" not in got

def test_bsc_keeps_buffered_legacy_gas_price():
    got = fee_fields(W3(), "bsc", 105)
    assert got == {"gasPrice": 138}

def test_allowance_and_swap_paths_use_shared_fee_builder():
    allowance_block = SRC[SRC.index("def _ensure_evm_allowance"):SRC.index("def _ensure_bsc_allowance")]
    assert "**_evm_tx_fee_fields(w3, chain)" in allowance_block
    assert "'gasPrice': w3.eth.gas_price" not in allowance_block
    assert SRC.count("**_evm_tx_fee_fields(w3, chain, txn.get('gasPrice'))") >= 3

if __name__ == "__main__":
    for name in sorted(n for n in globals() if n.startswith("test_")):
        globals()[name]()
        print("PASS", name)
    print("ALL EVM FEE FIELD REGRESSIONS PASSED")
