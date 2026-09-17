"""The transaction that actually spends money, driven with the live route.

This is the last function before a signature: it re-checks the spender, sets
the ERC-20 allowance, and broadcasts what 0x returned. Everything else in the
cross-chain path can be wrong and recovered from. An allowance cannot -- it is
a standing permission on the user's token, and the August 2025 0x exploit
drained approvals that were pointed at the wrong contract.

So this drives the real sender with the real $30 route and a fake chain,
recording every argument it would have used. Nothing here has a node, a key
or a network: web3, the account and the token contract are all stand-ins that
capture what was asked of them.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


FX = os.path.join(REPO, 'tests', 'fixtures', '0x', 'quote_base_to_solana.json')
if not os.path.isfile(FX):
    print('NOTE  the live Base -> Solana fixture is not present; nothing to send.')
    sys.exit(0)


PROBE = r'''
import contextlib, json, os, sys
import dashboard as d
from trade_engine import crosschain as X

FX = os.path.join(os.path.dirname(os.path.abspath(d.__file__)),
                  'tests', 'fixtures', '0x', 'quote_base_to_solana.json')
fx = json.load(open(FX))
data = fx['response']

WALLET = 'W1'
EVM = '0xABf40AADf960e20B4283dc5A06387A429Ba02456'

route = X.ZeroExCrossChain(lambda **kw: data, lambda **kw: {}).get_quote(
    source_chain='base', destination_chain='solana',
    source_amount_raw=30_000_000, origin_address=EVM,
    destination_address=fx['destination_address'])

seen = {'approve': None, 'signed': None, 'sent': None, 'allowance_read': None}


class FakeFn:
    def __init__(self, name, args):
        self.name, self.args = name, args
    def call(self):
        if self.name == 'allowance':
            seen['allowance_read'] = self.args
            return 0                      # nothing approved yet
        raise AssertionError('unexpected call ' + self.name)
    def build_transaction(self, base):
        seen['approve'] = {'args': self.args, 'base': dict(base)}
        tx = dict(base); tx['to'] = 'TOKEN'; tx['data'] = '0xapprove'
        return tx


class FakeFns:
    def __getattr__(self, name):
        return lambda *args: FakeFn(name, list(args))


class FakeContract:
    def __init__(self, address):
        self.address = address
        self.functions = FakeFns()


class FakeEth:
    gas_price = 8_000_000
    def contract(self, address=None, abi=None):
        return FakeContract(address)
    def get_transaction_count(self, addr):
        return 7
    def estimate_gas(self, tx):
        return 60_000
    def send_raw_transaction(self, raw):
        seen['sent'] = raw
        class H:
            def hex(self_inner):
                return '0xBROADCAST'
        return H()
    def wait_for_transaction_receipt(self, h, timeout=90):
        class R:
            status = 1
        return R()


class FakeW3:
    eth = FakeEth()
    def to_checksum_address(self, a):
        return a


class FakeSigned:
    raw_transaction = b'RAW'


class FakeAcct:
    address = EVM
    @staticmethod
    def from_key(pk):
        return FakeAcct()
    def sign_transaction(self, tx):
        seen['signed'] = dict(tx)
        return FakeSigned()


d._get_web3 = lambda chain: FakeW3()
d._EvmAccount = FakeAcct
d._cc_taker_address = lambda w, c: EVM

@contextlib.contextmanager
def fake_key(blob, wallet):
    yield '0x' + 'ab' * 32
d._use_key = fake_key

send = d._te_cc_source_sender('ENCRYPTED', WALLET, 'base')
outcome = send(route)

out = {
    'submitted': outcome.submitted,
    'tx_hash': outcome.tx_hash,
    'error': outcome.error,
    'approve_spender': (seen['approve'] or {}).get('args', [None])[0],
    'approve_amount': str((seen['approve'] or {}).get('args', [None, None])[1]),
    'approve_chain_id': (seen['approve'] or {}).get('base', {}).get('chainId'),
    'allowance_read': [str(a) for a in (seen['allowance_read'] or [])],
    'signed': {k: (str(v) if not isinstance(v, (int, str)) else v)
               for k, v in (seen['signed'] or {}).items()},
    'sent': str(seen['sent']),
    'live_calldata': data['quotes'][0]['transaction']['details']['data'],
    'allowance_target': route.allowance_target,
}

# ── and the same route with a spender it must never approve ──
import dataclasses
bad = dataclasses.replace(route, allowance_target=X.ZEROX_SETTLER_REGISTRY)
seen['approve'] = None
bad_outcome = send(bad)
out['settler_submitted'] = bad_outcome.submitted
out['settler_error'] = bad_outcome.error
out['settler_approved_anything'] = seen['approve'] is not None

print('@@@' + json.dumps(out, default=str))
'''

from cryptography.fernet import Fernet                        # noqa: E402
env = dict(os.environ)
env.update({'ENCRYPTION_KEY': Fernet.generate_key().decode(),
            'SECRET_KEY': 'x' * 32, 'DATA_DIR': tempfile.mkdtemp(), 'DEV': '1'})
p = subprocess.run([sys.executable, '-c', PROBE], cwd=REPO, env=env,
                   capture_output=True, text=True, timeout=300)
if '@@@' not in p.stdout:
    print(p.stdout[-3000:]); print(p.stderr[-3000:])
    sys.exit('probe did not report')
R = json.loads(p.stdout.split('@@@', 1)[1].splitlines()[0])

ALLOWANCE_HOLDER = '0x0000000000001ff3684f28c67538d4d072c22734'

check('the live route broadcasts, and reports the hash it got back',
      R['submitted'] is True and R['tx_hash'] == '0xBROADCAST'
      and not R['error'])

# ── the approval: the one thing that cannot be undone ────────────────────
check('the allowance goes to the AllowanceHolder contract 0x published, which '
      'is the address the route nominated',
      (R['approve_spender'] or '').lower() == ALLOWANCE_HOLDER
      and (R['allowance_target'] or '').lower() == ALLOWANCE_HOLDER)
check('...for EXACTLY the 30000000 this trade sells. Not unlimited, not '
      'rounded up, not the uint256 maximum — an approval is a standing '
      'permission and this one expires with the trade that needed it',
      R['approve_amount'] == '30000000')
check('...which is the same number the calldata pulls, so the approval cannot '
      'be larger than the transaction it exists for',
      R['approve_amount'] == '30000000'
      and R['live_calldata'][10 + 128:10 + 192].lstrip('0') == '1c9c380')
check('...on Base, by chain id, so an approval can never be signed for the '
      'wrong network', R['approve_chain_id'] == 8453)
check('...and it is only written after READING what is already approved, so a '
      'wallet that has an allowance does not pay for a second one',
      R['allowance_read'] and len(R['allowance_read']) == 2)

# ── the transaction itself ───────────────────────────────────────────────
signed = R['signed']
check('the transaction signed is the one 0x returned: its calldata, unedited',
      signed.get('data') == R['live_calldata'])
check('...to the contract 0x named, with no native value attached',
      (signed.get('to') or '').lower() == ALLOWANCE_HOLDER
      and int(signed.get('value') or 0) == 0)
check('...with the provider\'s own gas limit and price rather than numbers '
      'this repository made up',
      int(signed.get('gas') or 0) == 148484
      and int(signed.get('gasPrice') or 0) == 8204025)
check('...on Base', int(signed.get('chainId') or 0) == 8453)
check('...and it really was broadcast, once', R['sent'] == "b'RAW'")

# ── the refusal that matters most ────────────────────────────────────────
check('a route asking to approve the SETTLER registry is refused at this last '
      'gate, after the quote-time check has already passed it — because this '
      'is the line after which an approval is real',
      R['settler_submitted'] is False)
check('...and NOTHING is approved on the way to refusing', 
      R['settler_approved_anything'] is False)
check('...with a reason that says it is the spender being refused, not the '
      'trade failing for some unrelated cause',
      'spender' in (R['settler_error'] or '').lower())

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
