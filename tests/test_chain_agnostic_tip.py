"""Regression coverage for automatic USDC profile tips."""
import os
import sys
import types
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import portfolio_token_withdraw as tip

BACKEND = (ROOT / 'portfolio_token_withdraw.py').read_text()
PROFILE = (ROOT / 'templates' / 'profile.html').read_text()


def test_profile_no_longer_hardcodes_solana_tip_route():
    section = PROFILE[PROFILE.index('function _sendTip()'):PROFILE.index('</script>', PROFILE.index('function _sendTip()'))]
    assert "fetch('/api/tip'" in section
    assert "chain:'solana'" not in section
    assert '_tipMint' not in PROFILE
    assert '_tipRecipient' not in PROFILE
    assert 'Automatic USDC routing' in PROFILE


def test_browser_sends_identity_not_recipient_address():
    section = PROFILE[PROFILE.index('function _sendTip()'):PROFILE.index('</script>', PROFILE.index('function _sendTip()'))]
    assert 'recipient_user_id:_tipPeerId' in section
    assert 'to_address' not in section
    assert 'token_address' not in section


def test_backend_resolves_recipient_server_side():
    assert "@app.post('/api/tip')" in BACKEND
    assert '_user_tip_wallets(d, recipient_user_id)' in BACKEND
    assert "SELECT wallet_address, COALESCE(bsc_wallet_address" in BACKEND
    assert "body.get('to_address')" not in BACKEND[BACKEND.index("@app.post('/api/tip')"):BACKEND.index("@app.post('/api/wallet/send-token')")]


def test_duplicate_guard_is_chain_independent():
    route = BACKEND[BACKEND.index("@app.post('/api/tip')"):BACKEND.index("@app.post('/api/wallet/send-token')")]
    assert "key = ('tip', sender_wallet, recipient_user_id, str(amount.normalize()))" in route
    assert "_RECENT.get(key, 0) < 45" in route


def test_evm_selector_prefers_funded_actual_usdc_chains():
    d = types.SimpleNamespace()
    d.EVM_CHAINS = {
        'base': {'usdc':'0xbase', 'usdc_symbol':'USDC'},
        'bsc': {'usdc':'0xbsc', 'usdc_symbol':'USDC'},
        'robinhood': {'usdc':'0xusdg', 'usdc_symbol':'USDG'},
    }
    d.get_evm_usdc_balance = lambda addr, chain: {'base':5, 'bsc':20, 'robinhood':100}[chain]
    d.get_evm_native_balance = lambda addr, chain: {'base':0, 'bsc':0.01, 'robinhood':1}[chain]
    old = tip._wallet_keys
    try:
        tip._wallet_keys = lambda d, wallet: ('solenc','evmenc','0xsender')
        ready, needs = tip._tip_evm_candidates(d, 'sender', Decimal('4'), '0xrecipient')
    finally:
        tip._wallet_keys = old
    assert [x['chain'] for x in ready] == ['bsc']
    assert [x['chain'] for x in needs] == ['base']
    assert all(x['chain'] != 'robinhood' for x in ready + needs)


def test_zero_gas_fallback_uses_sender_own_stablecoin():
    route = BACKEND[BACKEND.index("@app.post('/api/tip')"):BACKEND.index("@app.post('/api/wallet/send-token')")]
    assert "candidate['balance'] < amount + topup_amount" in route
    assert "getattr(d, '_gasless_evm_native_topup', None)" in route
    assert 'with d._use_key(enc, sender_wallet) as private_key:' in route
    assert 'topup(private_key, chain)' in route


def test_success_is_audited_and_notifies_recipient():
    assert 'CREATE TABLE IF NOT EXISTS tip_transactions' in BACKEND
    assert "'You received %.2f USDC tip.'" in BACKEND
    assert "'confirmed'" in BACKEND


if __name__ == '__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL CHAIN-AGNOSTIC TIP REGRESSIONS PASSED')
