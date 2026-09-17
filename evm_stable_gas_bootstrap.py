"""User-funded EVM gas bootstrap through 0x Gasless.

A user who already owns the chain's stablecoin must not also need to deposit
BNB/ETH/POL before OrcAgent can move their money.  When native gas is low,
this adapter first tries a gasless swap from the user's own USDC/USDG into the
chain's native token.  0x relays that swap and takes its network cost from the
sell-token-funded order.

No OrcAgent wallet is used and no platform trading fee is added to this
plumbing swap.  If 0x cannot serve it (for example a token cannot be approved
gaslessly), the pre-existing user-funded fallback remains available.
"""
from __future__ import annotations

import os
from decimal import Decimal

import requests
from eth_account import Account

from bsc_gasless_trading import (
    _API,
    _api_headers,
    _evm_chain,
    _json_response,
    _submit_and_wait,
    _to_stable_raw,
)

_NATIVE_TOKEN = '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'
_MIN_GASLESS_STABLE = Decimal('1')


def _native_quote(d, private_key: str, chain_name: str, amount_stable: Decimal):
    """Firm 0x Gasless quote: stablecoin -> native token, with no OrcAgent fee."""
    chain = _evm_chain(d, chain_name)
    stable = chain.stable
    taker = Account.from_key(private_key).address
    params = {
        'chainId': str(chain.chain_id),
        'sellToken': stable.address,
        'buyToken': _NATIVE_TOKEN,
        'sellAmount': str(_to_stable_raw(d, chain_name, amount_stable, stable)),
        'taker': taker,
    }
    # Deliberately no swapFeeRecipient/swapFeeBps/swapFeeToken here.  This is
    # gas plumbing funded by the user, not a second platform-fee-bearing trade.
    resp = requests.get(_API + '/gasless/quote', params=params,
                        headers=_api_headers(d), timeout=15)
    quote = _json_response(resp, f'0x gasless gas-bootstrap quote ({chain.display_name})')
    if quote.get('liquidityAvailable') is False:
        raise RuntimeError(f'No gasless {chain.display_name} stable-to-gas route is available')
    if not quote.get('trade'):
        raise RuntimeError(f'0x gasless gas-bootstrap quote for {chain.display_name} has no trade')
    return quote, chain


def install(d):
    if getattr(d, '_orca_stable_gas_bootstrap_installed', False):
        return
    d._orca_stable_gas_bootstrap_installed = True

    previous_ensure = d._ensure_evm_gas

    def ensure_from_stable(user_id, wallet, private_key, evm_address, chain,
                           auto_buy_token_address=None, auto_buy_requested_usdc=None):
        try:
            meta = d.te_registry.get_chain(chain)
            if meta.kind != 'evm':
                return previous_ensure(
                    user_id, wallet, private_key, evm_address, chain,
                    auto_buy_token_address, auto_buy_requested_usdc)

            signer = Account.from_key(private_key).address
            if signer.lower() != str(evm_address or '').lower():
                return False, 'EVM trading key does not match the gas destination wallet', None

            # SERIALIZED, like every other rung of this ladder.
            #
            # dashboard._get_evm_gas_lock exists for exactly the race this
            # wrapper would otherwise reopen: "a live trade's own pre-trade
            # check racing the periodic background sweep in gas_manager.py --
            # can't both see the same stale low balance and each fire off
            # their own top-up/bootstrap, wasting the user's USDC or SOL on a
            # redundant swap". The old ladder took that lock; this ran in
            # front of it and did not, so two callers could each spend the
            # user's stablecoin on gas they only needed once.
            #
            # The lock is released before previous_ensure() below, because
            # that function takes the same lock and threading.Lock is not
            # reentrant. A caller arriving right after a successful swap
            # re-reads the balance inside the lock and simply finds enough.
            with d._get_evm_gas_lock(wallet, chain):
                w3 = d._get_web3(chain)
                addr = w3.to_checksum_address(evm_address)
                have_wei = int(w3.eth.get_balance(addr))
                need_wei = int(w3.eth.gas_price) * int(d.GAS_TOPUP_TX_GAS_UNITS)
                if have_wei >= need_wei:
                    return True, '', None

                stable_balance = Decimal(str(d.get_evm_usdc_balance(evm_address, chain)))
                configured = Decimal(str(getattr(d, 'GAS_TOPUP_USDC_AMOUNT', 2.0) or 2.0))
                amount = min(configured, stable_balance)

                # 0x documents roughly $1 as the practical minimum on non-mainnet
                # chains.  Do not burn the user's last cents on a quote that is
                # expected to be rejected as SELL_AMOUNT_TOO_SMALL.
                if amount >= _MIN_GASLESS_STABLE:
                    quote, quote_chain = _native_quote(d, private_key, chain, amount)
                    tx_hash = _submit_and_wait(d, private_key, quote, quote_chain)

                    # Confirmation from 0x is not enough by itself. Re-read the
                    # chain and only claim success when the native balance really
                    # covers OrcAgent's normal gas threshold.
                    after_wei = int(w3.eth.get_balance(addr))
                    if after_wei >= need_wei:
                        print(f'[stable-gas] {chain} funded from user stablecoin via 0x gasless '
                              f'(tx {str(tx_hash)[:18]}...)', flush=True)
                        return True, '', None

                    # A confirmed small top-up may still be below the conservative
                    # threshold.  The old ladder can now use the non-zero native
                    # balance for its ordinary same-chain top-up if necessary.
                    print(f'[stable-gas] {chain} gasless top-up confirmed but remains below '
                          f'threshold; continuing user-funded gas ladder', flush=True)
        except Exception as exc:
            redact = getattr(d, '_redact_keys', lambda x: x)
            print(f'[stable-gas] {chain} gasless stable-to-native bootstrap unavailable: '
                  f'{redact(str(exc))[:300]}', flush=True)

        # Existing fallback is intentionally retained. In production
        # ORCAGENT_FRONTS_GAS=0, so it cannot use platform money; it may use
        # the user's own SOL bridge only when the gasless stable route cannot
        # be used.
        return previous_ensure(
            user_id, wallet, private_key, evm_address, chain,
            auto_buy_token_address, auto_buy_requested_usdc)

    d._ensure_evm_gas = ensure_from_stable
    d._orca_stable_gas_bootstrap_ensure = ensure_from_stable
