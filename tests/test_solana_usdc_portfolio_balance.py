"""Regression guards for Portfolio Solana USDC reads."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'dashboard.py').read_text()


def section(a,b):
    x=SRC.index(a); y=SRC.index(b,x); return SRC[x:y]


def test_usdc_balance_uses_rpc_fallback_pool():
    b=section('def _solana_balance_rpc_pool', "@app.route('/api/wallet/usdc-summary'")
    assert 'CLAIM_SOL_RPCS' in b
    assert '_PROXY_RPCS' in b
    assert '[SOLANA_RPC]' in b


def test_empty_mint_query_falls_back_to_program_account_scan():
    b=section('def _get_solana_usdc_balance', "@app.route('/api/wallet/usdc-summary'")
    assert "{'programId': program_id}" in b
    assert 'TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID' in b
    assert '_sum_usdc_from_entries' in b


def test_all_usdc_token_accounts_are_summed():
    b=section('def _sum_usdc_from_entries', 'def _get_solana_usdc_balance')
    assert 'for account in entries or []:' in b
    assert 'total +=' in b
    assert "uiAmountString" in b


def test_wallet_token_scanner_aggregates_duplicate_mints():
    b=section('def _fetch_wallet_tokens', "@app.route('/api/wallet/tokens'")
    assert '_raw_by_mint: dict = {}' in b
    assert "existing['amount'] += ui_amount" in b
    assert 'mint in _seen_mints' not in b[b.index('for acc in _prog_accounts:'):b.index("print(f'[wallet-tokens] total verified SPL")]


def test_verified_empty_token_scan_is_authoritative_and_does_not_hit_stale_db():
    b=section('def _fetch_wallet_tokens', "@app.route('/api/wallet/tokens'")
    assert "_prog_accounts = _rpc_value" in b
    assert "if _prog_accounts:" not in b
    assert "RPC empty — falling back to user_tokens DB" not in b
    assert "SELECT token_address, symbol, amount, avg_price FROM user_tokens" not in b


def test_wallet_token_scan_fails_closed_only_when_every_rpc_is_invalid():
    b=section('def _fetch_wallet_tokens', "@app.route('/api/wallet/tokens'")
    assert "_prog_accounts = None" in b
    assert "if _prog_accounts is None:" in b
    # When every RPC fails the indexed scan, the scan no longer errors out: it
    # reads the known mints directly and says the inventory is incomplete,
    # rather than showing stale DB rows as on-chain holdings.
    assert "_indexed_incomplete = True" in b and "'inventory_complete': not _indexed_incomplete" in b
    assert "non-JSON response" in b and "invalid result shape" in b


def test_wallet_token_logs_do_not_print_full_wallet_address():
    b=section('def _fetch_wallet_tokens', "@app.route('/api/wallet/tokens'")
    assert "_short_onchain" in b
    assert "onchain_wallet={onchain_wallet!r}" not in b


def test_total_rpc_failure_raises_instead_of_false_zero():
    b=section('def _get_solana_usdc_balance', "@app.route('/api/wallet/usdc-summary'")
    assert 'if fallback_valid or saw_valid:' in b
    assert "raise RuntimeError(" in b
    assert 'Solana USDC balance unavailable' in b


def test_wallet_ui_labels_trading_wallet_scope():
    html=(ROOT/'templates'/'wallet.html').read_text()
    assert 'OrcAgent Trading Wallet' in html
    assert 'Connected Phantom wallet is separate from this trading wallet.' not in html


def test_native_sol_reader_never_swallows_rpc_failure_as_zero():
    b=section('def _fetch_wallet_tokens', "@app.route('/api/wallet/tokens'")
    assert '_get_user_sol(onchain_wallet)' in b
    sol=b[b.index('# ── SOL balance ──'):b.index('# ── SOL price')]
    assert "sol_balance = 0.0" not in sol
    assert "raise RuntimeError('SOL balance unavailable from verified RPC')" in sol


def test_wallet_balance_uses_same_resilient_sol_reader():
    b=section('def api_wallet_balance', '_sol_usdc_balance_cache')
    assert '_get_user_sol(balance_wallet)' in b
    assert 'CLAIM_SOL_RPCS' not in b


def test_indexer_outage_can_use_exact_canonical_usdc_account():
    b=section('def _get_solana_usdc_balance', "@app.route('/api/wallet/usdc-summary'")
    assert '_get_bot_solana_balances(key)' in b
    assert 'Indexed token-account methods can all be throttled at once' in b


if __name__=='__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS',name)
    print('ALL SOLANA USDC PORTFOLIO REGRESSIONS PASSED')
