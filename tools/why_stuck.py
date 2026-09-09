#!/usr/bin/env python3
"""Why can this wallet not send or trade on this chain?

Read-only. Signs nothing, sends nothing, prints no key.

    venv/bin/python tools/why_stuck.py [wallet] [chain]

Written because answering that question was taking a round trip per guess:
is the user's wallet out of gas, is the sponsor empty, is an RPC down, is
fronting off? Each of those produces the same refusal on screen, and the
journal only tells you about the attempt you happened to make. This looks at
all of them at once and says which it is.

The wallet defaults to OWNER_WALLET; the chain to every EVM chain configured.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, BAD, WARN = '\033[32m✓\033[0m', '\033[31m✗\033[0m', '\033[33m•\033[0m'


def main():
    import sqlite3
    import dashboard as d

    wallet = (sys.argv[1] if len(sys.argv) > 1 else '').strip()
    only   = (sys.argv[2] if len(sys.argv) > 2 else '').strip().lower()
    if not wallet:
        wallet = (os.getenv('OWNER_WALLET', '').split(',')[0] or '').strip()
    if not wallet:
        print('No wallet given and OWNER_WALLET is not set.')
        print('Usage: venv/bin/python tools/why_stuck.py <wallet> [chain]')
        return 2

    print(f'Wallet {wallet[:6]}…{wallet[-4:]}')
    print('=' * 68)

    conn = sqlite3.connect(d.DB_FILE)
    try:
        row = conn.execute(
            'SELECT id, bsc_wallet_address, encrypted_private_key_bsc '
            'FROM users WHERE wallet_address=?', (wallet,)).fetchone()
    finally:
        conn.close()
    if not row:
        print(f'{BAD} no such user in the database')
        return 1
    _uid, evm_address, enc = row[0], row[1], row[2]
    if not enc:
        print(f'{BAD} this user has no EVM trading key — nothing can send on any '
              f'EVM chain until one is saved in Settings')
        return 1
    print(f'EVM trading wallet: {evm_address or "(none derived)"}')

    # ── the rule, first: everything below reads differently without it ──
    fronting = bool(getattr(d, 'ORCAGENT_FRONTS_GAS', False))
    print(f'\nFronting gas: {"ON" if fronting else "OFF"}')
    sponsor = d._gas_sponsor_address() if fronting else ''
    if fronting and not sponsor:
        print(f'{BAD} GAS_SPONSOR_PRIVATE_KEY is not set, so nothing can be '
              f'fronted despite the rule being on')
    elif fronting:
        print(f'Sponsor wallet: {sponsor}')

    chains = [only] if only else list(d.EVM_CHAINS)
    verdicts = []
    for chain in chains:
        if chain not in d.EVM_CHAINS:
            print(f'\n{BAD} unknown chain {chain!r}')
            continue
        sym = d.EVM_CHAINS[chain]['native_symbol']
        print(f'\n── {d.SURGE_ALERT_CHAIN_NAMES.get(chain, chain)} ──')
        try:
            w3 = d._get_web3(chain)
            need = w3.eth.gas_price * d.GAS_TOPUP_TX_GAS_UNITS
        except Exception as e:
            print(f'{BAD} RPC unreachable ({type(e).__name__}: {e})')
            print(f'    Nothing can be read or sent on this chain. Check its '
                  f'RPC URL in /etc/orcagent.env.')
            verdicts.append((chain, 'RPC down'))
            continue

        try:
            user_native = w3.eth.get_balance(w3.to_checksum_address(evm_address))
        except Exception as e:
            print(f'{BAD} could not read the wallet balance ({type(e).__name__})')
            verdicts.append((chain, 'balance unreadable'))
            continue
        try:
            user_usdc = d.get_evm_usdc_balance(evm_address, chain)
        except Exception:
            user_usdc = None

        print(f'   your wallet: {user_native / 1e18:.6f} {sym}'
              + (f' · {user_usdc:.4f} {d.user_currency_label(chain)}'
                 if user_usdc is not None else ''))

        # Enough to pay for a transfer outright?
        if user_native >= need:
            print(f'{OK} has enough {sym} to send — this chain is not the problem')
            verdicts.append((chain, 'ready'))
            continue

        # Not enough. Which of the three ways out is available?
        print(f'{WARN} not enough {sym} for a transaction '
              f'(needs about {need / 1e18:.6f})')

        if user_native > 0 and (user_usdc or 0) > 0:
            print(f'{OK} but it can buy its own gas: it holds both a little {sym} '
                  f'and some {d.user_currency_label(chain)}, so the top-up swap '
                  f'can be broadcast')
            verdicts.append((chain, 'self-funds'))
            continue

        if user_native <= 0:
            print(f'   at literal zero, so it cannot broadcast anything itself — '
                  f'not even a swap to buy gas')

        if not fronting:
            print(f'{BAD} fronting is off, so the only way in is to send a little '
                  f'{sym} to {evm_address} on this chain')
            verdicts.append((chain, 'needs a manual top-up'))
            continue
        if not sponsor:
            verdicts.append((chain, 'no sponsor key'))
            continue

        try:
            sponsor_native = w3.eth.get_balance(w3.to_checksum_address(sponsor))
        except Exception as e:
            print(f'{BAD} could not read the sponsor balance ({type(e).__name__})')
            verdicts.append((chain, 'sponsor unreadable'))
            continue
        grant = need * d.GAS_SPONSOR_TX_MULTIPLIER
        print(f'   sponsor:     {sponsor_native / 1e18:.6f} {sym} '
              f'({int(sponsor_native // grant) if grant else 0} users)')
        if sponsor_native < grant:
            print(f'{BAD} the sponsor cannot fund even one wallet here. '
                  f'THIS is the blocker.')
            print(f'    Send {(grant * getattr(d, "GAS_SPONSOR_TARGET_GRANTS", 30) - sponsor_native) / 1e18:.6f} '
                  f'{sym} to {sponsor}')
            print(f'    (or {grant / 1e18:.6f} {sym} to {evm_address} to unblock '
                  f'just this wallet)')
            verdicts.append((chain, 'sponsor empty'))
            continue

        # The sponsor could pay. So if a user is still stuck, it is the
        # anti-farming gate -- which is a policy, not a fault.
        if (user_usdc or 0) < d.GAS_SPONSOR_MIN_USDC:
            print(f'{WARN} the sponsor has funds, but this wallet holds less than '
                  f'{d.GAS_SPONSOR_MIN_USDC:.0f} {d.user_currency_label(chain)} '
                  f'and has no open position here, so a grant is withheld by '
                  f'design (anti-farming). Deposit something to trade with first.')
            verdicts.append((chain, 'below the grant threshold'))
            continue

        print(f'{OK} the sponsor can fund this wallet — a buy or send should '
              f'activate it')
        verdicts.append((chain, 'should work'))

    print('\n' + '=' * 68)
    for chain, verdict in verdicts:
        print(f'  {chain:<12} {verdict}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        print('\nThis script only reads. Nothing was signed or sent.')
        sys.exit(1)
