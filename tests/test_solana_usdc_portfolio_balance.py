"""Regression guards for Portfolio Solana USDC reads."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'dashboard.py').read_text()


def section(a,b):
    x=SRC.index(a); y=SRC.index(b,x); return SRC[x:y]


def test_usdc_balance_uses_rpc_fallback_pool():
    b=section('def _get_solana_usdc_balance', "@app.route('/api/wallet/usdc-summary'")
    assert 'CLAIM_SOL_RPCS' in b
    assert '_PROXY_RPCS' in b
    assert '[SOLANA_RPC]' in b


def test_empty_rpc_answer_does_not_end_fallback_search():
    b=section('def _get_solana_usdc_balance', "@app.route('/api/wallet/usdc-summary'")
    assert 'if not accounts:' in b
    assert 'confirmed_empty = True' in b
    assert 'continue' in b[b.index('if not accounts:'):b.index('total = 0.0')]
    assert 'return total' in b


def test_all_usdc_token_accounts_are_summed():
    b=section('def _get_solana_usdc_balance', "@app.route('/api/wallet/usdc-summary'")
    assert 'for account in accounts:' in b
    assert 'total +=' in b
    assert 'accounts[0]' not in b
    assert "uiAmountString" in b


def test_wallet_token_scanner_aggregates_duplicate_mints():
    b=section('def _fetch_wallet_tokens', "@app.route('/api/wallet/tokens'")
    assert '_raw_by_mint: dict = {}' in b
    assert "existing['amount'] += ui_amount" in b
    assert 'mint in _seen_mints' not in b[b.index('for acc in _prog_accounts:'):b.index("print(f'[wallet-tokens] total SPL")]


def test_total_rpc_failure_raises_instead_of_false_zero():
    b=section('def _get_solana_usdc_balance', "@app.route('/api/wallet/usdc-summary'")
    assert "raise RuntimeError(" in b
    assert "if confirmed_empty:" in b
    tail=b[b.index('if confirmed_empty:'):]
    assert 'return 0.0' in tail
    assert 'raise RuntimeError' in tail


def test_wallet_ui_labels_trading_wallet_scope():
    html=(ROOT/'templates'/'wallet.html').read_text()
    assert 'OrcAgent Trading Wallet' in html
    assert 'Connected Phantom wallet is separate from this trading wallet.' in html


if __name__=='__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS',name)
    print('ALL SOLANA USDC PORTFOLIO REGRESSIONS PASSED')
