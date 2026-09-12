"""Regression guards for automatic EVM -> Solana bridge-then-buy.

This feature deliberately extends the existing bridge state machine instead
of adding a second provider/ledger. These checks protect the boundaries that
matter when real money moves: the entered amount remains an all-in ceiling,
source gas belongs to the user, an in-flight move is never duplicated,
settlement is followed by a fresh destination balance read, and every old EVM
destination still delegates to the original continuation unchanged.
"""
import pathlib
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = (ROOT / 'evm_to_solana_bridge.py').read_text(encoding='utf-8')
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')
PROC = (ROOT / 'Procfile').read_text(encoding='utf-8')
START = (ROOT / 'start.sh').read_text(encoding='utf-8')
SERVICE = (ROOT / 'deploy' / 'orcagent.service').read_text(encoding='utf-8')


def check(message, condition):
    assert condition, message
    print('PASS ' + message)


check('the extension reuses the existing cross-chain executor rather than a new provider',
      '_execute_cross_chain_bridge(' in SRC
      and 'requests.post(' not in SRC and 'requests.get(' not in SRC)
check('Solana is the real bridge destination and its actual USDC mint is passed to the executor',
      "source_chain, 'solana', source_token, appmod.USDC_MINT" in SRC)
check('the buy is attached to the bridge row for settlement-time continuation',
      'auto_buy_token_address=token_address' in SRC
      and 'auto_buy_requested_usdc=bridge_amount' in SRC)
check('a repeated click reuses an already pending/processing reverse bridge',
      "auto_buy_status IN ('pending','processing')" in SRC
      and '_existing_pending_bridge' in SRC)
check('source selection is EVM-only and requires the user wallet to fund its own gas',
      'for chain, cfg in' in SRC and '_source_needs_sponsored_gas' in SRC
      and 'skipping {chain}: source wallet cannot pay its own bridge gas' in SRC)
check('the extension never invokes a sponsor or gas top-up action',
      '_sponsor_evm_gas(' not in SRC and '_sponsor_solana_gas(' not in SRC
      and '_ensure_evm_gas(' not in SRC and '_ensure_solana_gas(' not in SRC)
check('source gas is priced with the existing live USD estimator',
      '_te_gas_usd' in SRC and '_source_gas_budget_usd' in SRC)
check('source gas is reserved from, never added on top of, the entered ceiling',
      'bridge_amount = float(max_spend_usd) - gas_budget' in SRC
      and 'requested * (1.0 + ' not in SRC)
check('0x receives only that reduced bridge amount',
      "source_chain, 'solana', source_token, appmod.USDC_MINT,\n            bridge_amount" in SRC)
check('after settlement the REAL Solana USDC balance is re-read',
      '_get_solana_usdc_balance(trading_wallet)' in SRC)
check('the post-bridge purchase can never exceed the amount budgeted for the bridge',
      'min(float(requested_usdc or 0), solana_usdc)' in SRC)
check('the reverse continuation requires user-owned SOL gas before invoking Jupiter flow',
      '_get_user_sol(trading_wallet)' in SRC and 'SOL_NETWORK_RESERVE' in SRC
      and 'needs SOL for its own network fee' in SRC)
check('the existing shared Solana buy/Jupiter flow executes the continuation',
      'appmod._solana_buy_flow' in SRC and "kwargs['requested_usdc'] = spend" in SRC)
check('the status-loop idempotency contract is preserved when finishing the attached buy',
      "WHERE id=? AND auto_buy_status='processing'" in SRC)
check('every non-Solana continuation delegates to the original implementation',
      "if str(dest_chain).lower() != 'solana'" in SRC
      and 'return original_continuation(' in SRC)
check('only the exact existing insufficient-Solana-USDC refusal may trigger a reverse bridge',
      "response.status_code == 400 and 'Not enough USDC' in reason" in SRC)
check('Live Market keeps using its existing pending bridge contract',
      "'ok': True, 'pending': True, 'bridge_id':" in SRC)

# Production/container/legacy launch paths must all install the extension.
check('the WSGI entry imports dashboard first and installs the adapter once',
      'import dashboard as _dashboard' in ENTRY
      and '_install_evm_to_solana_bridge(_dashboard)' in ENTRY)
check('every process launcher serves app_entry:app',
      'app_entry:app' in PROC and 'app_entry:app' in START and 'app_entry:app' in SERVICE)

# Exercise the source picker without importing dashboard.py or touching a
# network. The route with the best amount left after its gas reserve wins, a
# source requiring sponsored gas is excluded, and Solana is never considered.
import evm_to_solana_bridge as ext  # noqa: E402

balances = {'bsc': 120.0, 'base': 180.0, 'arbitrum': 160.0}
needs_sponsor = {'bsc': False, 'base': True, 'arbitrum': False}
gas_usd = {'bsc': 0.40, 'base': 0.20, 'arbitrum': 0.30}
fake = types.SimpleNamespace(
    SOLANA_MIN_SPEND_USDC=1.0,
    EVM_CHAINS={
        'bsc': {'usdc': 'BSC_USDC'},
        'base': {'usdc': 'BASE_USDC'},
        'arbitrum': {'usdc': 'ARB_USDC'},
    },
    get_evm_usdc_balance=lambda _addr, chain: balances[chain],
    _te_needs_sponsored_gas=lambda chain, _addr: needs_sponsor[chain],
    _te_gas_usd=lambda chain: gas_usd[chain],
)
source = ext._pick_evm_source(fake, '0xabc', 100.0)
# Base would leave $99.75 but needs sponsored gas and is therefore forbidden.
# Arbitrum reserves $0.375 (0.30 * 1.25), leaving $99.625 for the bridge.
check('a richer route that needs platform-sponsored gas is skipped',
      source == ('arbitrum', 'ARB_USDC', 160.0, 99.625, 0.375))
check('the bridge plus reserved source gas never exceeds the entered ceiling',
      abs(source[3] + source[4] - 100.0) < 1e-9)

balances['arbitrum'] = 99.50  # below its $99.625 bridge budget
source2 = ext._pick_evm_source(fake, '0xabc', 100.0)
check('a source must actually hold the USDC amount left after reserving its gas',
      source2 == ('bsc', 'BSC_USDC', 120.0, 99.5, 0.5))

needs_sponsor['bsc'] = True
source3 = ext._pick_evm_source(fake, '0xabc', 100.0)
check('no source is returned when every sufficiently funded EVM chain needs sponsored gas',
      source3 is None)

print('\n23/23 checks passed')
