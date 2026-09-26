"""Sponsored gas, repaid in the same trade (sponsored_gas.py).

Where 0x Gasless cannot take an EVM buy (Robinhood Chain, a token without a
gasless route) a USDC/USDG-only wallet could not buy at all. Now:
- the sponsor fronts exactly the missing native gas, and only after the real
  route has been priced (no route / no balance -> nothing is sent);
- the user's wallet pays it back in the stablecoin BEFORE the swap, and the
  swap is what is left of the amount entered (the amount is the ceiling);
  a gas reserve the trade engine already set aside pays first;
- a trade that Gasless submitted (or may have) is never tried again;
- an unpaid grant is settled before anything new is fronted;
- a sell that cannot pay for its approval is fronted and repaid from the
  proceeds;
- it can be switched off, and refuses cleanly when fees are unusually high
  or the sponsor wallet is empty.
Runs against a simulated chain: no network, no real keys.
"""
import os, sqlite3, sys, tempfile, threading, types
from decimal import Decimal
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import sponsored_gas as sg  # noqa: E402
from eth_account import Account  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

SPONSOR = Account.create(); USER = Account.create()
TOKEN = '0x' + '7' * 40
GWEI = 10 ** 9

# ── a tiny simulated EVM chain ──
class Tx(bytes):
    pass
class Chain:
    def __init__(self):
        self.native = {}; self.events = []; self.fail_receipts = False
        self.gas_price = GWEI // 100         # 0.01 gwei, like Robinhood Chain
        self.eth = self
    # web3 surface used by the module
    def to_checksum_address(self, a): return a
    def get_balance(self, a): return self.native.get(a.lower(), 0)
    def get_transaction_count(self, a): return 0
    def estimate_gas(self, tx): return 40_000        # a rollup transfer costs more than 21000
    def wait_for_transaction_receipt(self, h, timeout=90):
        return types.SimpleNamespace(status=0 if self.fail_receipts else 1)
    def contract(self, address, abi):
        fn = lambda default: types.SimpleNamespace(estimate_gas=lambda _o: default, call=lambda: 6)
        return types.SimpleNamespace(functions=types.SimpleNamespace(
            decimals=lambda: fn(6), approve=lambda s, a: fn(55_000), transfer=lambda t, a: fn(65_000)))
chain = Chain()

db = os.path.join(tempfile.mkdtemp(), 't.db')
c = sqlite3.connect(db)
c.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, wallet_address TEXT)')
c.execute("INSERT INTO users (id, wallet_address) VALUES (7, 'SoLWallet111')")
c.execute('''CREATE TABLE gas_sponsorships (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, wallet TEXT,
  chain TEXT, to_address TEXT, amount_native REAL, amount_usd REAL DEFAULT 0, tx_hash TEXT DEFAULT '',
  status TEXT DEFAULT 'sent', error_msg TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  trade_id TEXT DEFAULT '', recovered_usd REAL DEFAULT 0)''')
c.commit(); c.close()

state = {'usdg': 20.0, 'quote': None, 'gasless': (False, '0x gasless quote (Robinhood Chain) failed (HTTP 400): chain not supported', ''),
         'repay_fail': False, 'eth_usd': Decimal('4000')}
def send(raw):
    # A signed sponsor transfer: credit the user, debit the sponsor.
    import rlp
    f = rlp.decode(bytes(raw)[1:])      # EIP-1559: chainId, nonce, tip, maxFee, gas, to, value, ...
    value = int.from_bytes(f[6], 'big')
    to_hex = '0x' + f[5].hex()
    chain.native[to_hex.lower()] = chain.native.get(to_hex.lower(), 0) + value
    chain.native[SPONSOR.address.lower()] -= value
    chain.events.append(('grant', value))
    return Tx(raw[:32])
chain.send_raw_transaction = send

def quote(sell, buy, raw, taker, ch, apply_platform_fee=False):
    return state['quote'] if state['quote'] is not None else {
        'issues': {'allowance': {'spender': '0x' + 'a' * 40}},
        'transaction': {'gas': '900000'}}
def send_usdc(pk, to, amount, ch):
    if state['repay_fail']:
        raise RuntimeError('insufficient funds for gas')
    chain.events.append(('repay', round(amount, 6), to)); state['usdg'] -= amount
    return '0xrepay' + str(len(chain.events))
def raw_execute(wallet, pk, action, token, amount_str, ch):
    chain.events.append((action, amount_str)); return True, '', '0xswap'
def gasless(wallet, pk, action, token, amount_str, ch):
    chain.events.append(('gasless', action)); return state['gasless']

d = types.SimpleNamespace(
    DB_FILE=db, GAS_SPONSOR_PRIVATE_KEY=SPONSOR.key.hex(), EVM_CHAINS={'robinhood': {
        'chain_id': 4663, 'native_symbol': 'ETH', 'usdc_symbol': 'USDG', 'usdc': '0x' + '5' * 40}},
    _gas_sponsor_lock=threading.Lock(), _ERC20_MIN_ABI=[], _ERC20_FULL_ABI=[],
    _get_web3=lambda ch: chain, _redact_keys=lambda s: s,
    _evm_tx_fee_fields=lambda w3, ch, q=None: {'type': 2, 'maxFeePerGas': 2 * chain.gas_price,
                                                'maxPriorityFeePerGas': chain.gas_price // 10},
    _te_native_price_usd=lambda ch: state['eth_usd'],
    get_evm_usdc_balance=lambda a, ch: state['usdg'], _get_0x_quote=quote, _send_evm_usdc_fee=send_usdc,
    _execute_evm_swap=gasless, _execute_evm_swap_signed=raw_execute)
sg.install(d)
buy = lambda amt='10': d._execute_evm_swap('SoLWallet111', USER.key.hex(), 'buy', TOKEN, amt, 'robinhood')
def reset(eth_user=0, eth_sponsor=10 ** 18, usdg=20.0):
    chain.events.clear(); chain.native = {USER.address.lower(): eth_user, SPONSOR.address.lower(): eth_sponsor}
    state.update(usdg=usdg, quote=None, repay_fail=False)
def rows():
    c = sqlite3.connect(db); r = c.execute('SELECT amount_usd, recovered_usd, trade_id, amount_native FROM gas_sponsorships ORDER BY id').fetchall(); c.close(); return r
def owed_total():
    return sum(a for _i, a in sg.owed(d, 7, 'robinhood'))

# ── a Robinhood buy with only USDG and no ETH ──
reset()
ok, msg, tx = buy('10')
kinds = [e[0] for e in chain.events]
check('Gasless is tried first', kinds[0] == 'gasless')
check('then gas is fronted, repaid, and only then the swap runs', kinds[1:] == ['grant', 'repay', 'buy'], )
units = 900_000 + 55_000 + 65_000
need = int(Decimal(units) * sg.GAS_MARGIN) * 2 * chain.gas_price
check('...the grant is exactly the missing gas (approve + swap + repayment, with margin)', chain.events[1][1] == need)
repay = chain.events[2][1]
expect = float(sg._cents_up((Decimal(need) + 50_000 * chain.gas_price) / Decimal(10) ** 18 * Decimal('4000')))
check('...repaid in USDG at the ETH price, rounded up to the cent', repay == expect and chain.events[2][2] == SPONSOR.address)
check('...the swap is the amount entered minus the repayment (ceiling kept)',
      Decimal(chain.events[3][1]) == Decimal('10') - Decimal(str(repay)))
check('...and the buy succeeds', ok and tx == '0xswap')
r = rows()[-1]
check('the grant is recorded as repaid float, not a subsidy', r[0] == r[1] == repay and r[2] == 'sponsored:buy' and r[3] > 0)

# ── the trade engine already reserved gas out of the ceiling ──
reset()
d._EVM_GAS_RESERVE.usd = Decimal('0.50')
buy('10')
d._EVM_GAS_RESERVE.usd = 0
check('a gas reserve set aside by the engine pays the fee; the purchase is not cut',
      chain.events[-1] == ('buy', '10.000000'))

# ── never a second try of something Gasless submitted ──
reset(); state['gasless'] = (False, '0x gasless trade was submitted but not confirmed within 75s', '')
buy(); check('a possibly-submitted gasless trade is not retried', [e[0] for e in chain.events] == ['gasless'])
reset(); state['gasless'] = (False, 'reverted', '0xabc')
buy(); check('a gasless trade with a hash is not retried', [e[0] for e in chain.events] == ['gasless'])
reset(); state['gasless'] = (True, '', '0xgood')
check('a successful gasless buy costs the sponsor nothing', buy()[0] and [e[0] for e in chain.events] == ['gasless'])
state['gasless'] = (False, 'No gasless Robinhood Chain liquidity route is available for this token', '')

# ── nothing is fronted when the trade cannot happen ──
reset(usdg=5.0)
ok, msg, _ = buy('10')
check('not enough USDG -> nothing fronted', not ok and 'Insufficient USDG' in msg and 'grant' not in [e[0] for e in chain.events])
reset(); state['quote'] = {'issues': {}, 'transaction': None}
ok, msg, _ = buy('10')
check('no route -> nothing fronted', not ok and 'No liquidity route' in msg and 'grant' not in [e[0] for e in chain.events])
reset(eth_user=10 ** 17)
buy('10')
check('a wallet that already has enough ETH is not fronted or charged', [e[0] for e in chain.events] == ['gasless', 'buy']
      and chain.events[-1] == ('buy', '10.000000'))

# ── limits ──
reset(); state['eth_usd'] = Decimal('90000000')
ok, msg, _ = buy('10')
check('unusually high fees are refused, nothing sent', not ok and 'unusually high' in msg and 'grant' not in [e[0] for e in chain.events])
state['eth_usd'] = Decimal('4000')
reset(eth_sponsor=0)
ok, msg, _ = buy('10')
check('an empty sponsor wallet refuses cleanly, nothing swapped', not ok and 'out of ETH' in msg and 'buy' not in [e[0] for e in chain.events])
reset(); ok, msg, _ = buy('0.6')
check('an amount too small to cover the fee is refused before anything is sent',
      not ok and 'too small' in msg and [e[0] for e in chain.events] == ['gasless'])
check('...and nothing is owed', owed_total() == 0)

# ── a failed repayment is owed, and settled first next time ──
reset(); state['repay_fail'] = True
ok, msg, _ = buy('10')
check('if repayment fails nothing is bought', not ok and 'nothing was bought' in msg and 'buy' not in [e[0] for e in chain.events])
debt = owed_total()
check('...and the grant stays owed', debt > 0)
reset(); state['repay_fail'] = False
buy('10')
rep = [e for e in chain.events if e[0] == 'repay']
check('the next buy settles the old debt together with its own grant',
      len(rep) == 1 and Decimal(str(rep[0][1])) > debt and owed_total() == 0)
check('...and the debt is not taken out of the purchase', Decimal(chain.events[-1][1]) == Decimal('10') - (Decimal(str(rep[0][1])) - debt))

# ── sells ──
reset(); chain.native[USER.address.lower()] = 0
state['gasless'] = (False, 'This token needs a one-time on-chain approval before it can be sold. Automatic gas setup could not complete', '')
ok, msg, tx = d._execute_evm_swap('SoLWallet111', USER.key.hex(), 'sell', TOKEN, '1234.5', 'robinhood')
check('a sell that cannot pay for its approval is fronted, sold, then repaid from the proceeds',
      [e[0] for e in chain.events] == ['gasless', 'grant', 'sell', 'repay'] and ok and owed_total() == 0)
check('...the grant is recorded as a sell grant', rows()[-1][2] == 'sponsored:sell')

# ── switch ──
os.environ['ORCAGENT_SPONSORED_GAS'] = '0'
reset(); state['gasless'] = (False, '0x gasless quote (Robinhood Chain) failed (HTTP 400): x', '')
ok, msg, _ = buy('10')
check('ORCAGENT_SPONSORED_GAS=0 turns it off', not ok and [e[0] for e in chain.events] == ['gasless'])
os.environ.pop('ORCAGENT_SPONSORED_GAS')

# ── wiring in the app ──
root = os.path.join(os.path.dirname(__file__), '..')
entry = open(os.path.join(root, 'app_entry.py')).read()
check('installed right after the 0x Gasless adapter',
      entry.index('_install_evm_gasless_trading(_dashboard)') < entry.index('_install_sponsored_gas(_dashboard)')
      < entry.index('_install_multichain_auto_bot(_dashboard)'))
check("the sponsor's own transfer is estimated (rollups need more than 21000 gas)",
      sg._transfer_gas(chain, 'a', 'b', 1) == 50_000)
check('the legacy unrecovered sponsor rail stays off', "os.environ['ORCAGENT_FRONTS_GAS'] = '0'" in entry)
dash = open(os.path.join(root, 'dashboard.py')).read()
check('the trade engine passes its gas reserve', '_EVM_GAS_RESERVE.usd = plan.gas_usd' in dash)
raise SystemExit(0 if all(checks) else 1)
