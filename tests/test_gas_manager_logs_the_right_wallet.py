"""The gas sweep has to name the address it actually looked at.

WHAT WENT WRONG
Every check in the EVM sweep runs against the EVM address -- the balance
precheck, the USDC read, the top-up itself. Every log line named the SESSION
wallet instead, which on this app is a base58 Solana address. So the log read:

    [gas-manager] bsc wallet HC5ahspS... not rebalanced this cycle: this
    wallet has no BNB for network fees yet

A Solana address, in a line about BNB, next to the words "this wallet". The
behaviour was right and the sentence was wrong, and the sentence is what
somebody reads when they are trying to work out whether the gas check is
looking at the wrong wallet. It cost exactly that investigation.

So: the address that was read, then whose it is.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


SRC = open(os.path.join(REPO, 'gas_manager.py')).read()

# Every gas-manager log line that talks about a wallet.
lines = [l.strip() for l in SRC.split('\n') if "[gas-manager]" in l]
check('the sweep still logs what it does', len(lines) >= 6)

# ── the mislabel is gone ─────────────────────────────────────────────────
check('no gas line says "wallet <session wallet>" any more — that phrasing '
      'put a Solana address in a sentence about BNB',
      not any(re.search(r"wallet %s\.\.\.'", l) for l in lines))

# ── the EVM sweep names the EVM address ──────────────────────────────────
evm_block = SRC.split('def _sweep_user_chain', 1)[1].split('\ndef ', 1)[0]
evm_logs = [l for l in evm_block.split('\n') if '[gas-manager]' in l]
check('every line in the EVM sweep names the EVM address it checked',
      evm_logs and all('evm_address[:10]' in l or 'evm_address[:10]' in
                       evm_block.split(l, 1)[1][:200] for l in evm_logs))
check('...and still says which user it belongs to, so a person can find them',
      evm_block.count('wallet[:8]') >= 5)
check('...while the checks themselves were always right and are untouched',
      '_needs_gas_precheck(evm_address, chain)' in evm_block
      and '_ensure_evm_gas(user_id, wallet, pk, evm_address, chain)' in evm_block)

# ── the Solana sweep has the same shape ──────────────────────────────────
sol_block = SRC.split('def _sweep_solana', 1)[1].split('\ndef ', 1)[0] \
            if 'def _sweep_solana' in SRC else SRC
check('the Solana sweep names the TRADING address it read the balance of, '
      'not the session wallet it was found under',
      'trading_address[:10]' in SRC
      and 'solana wallet %s...' not in SRC)

# ── and its key parse cannot panic either ────────────────────────────────
check('the sweep parses its key through the guarded helper, so a corrupted '
      'blob is an error here too rather than a Rust panic in a background '
      'thread nobody is watching',
      '_app._sol_keypair_from_base58(' in SRC
      and 'from_base58_string(' not in SRC)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
