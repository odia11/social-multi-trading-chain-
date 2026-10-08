"""Withdrawing a token from Portfolio builds exactly the transfer asked for.

The withdrawal was only checked by reading its source. This runs the real
_solana_transfer() against a fake Solana network with a throwaway test key
and decodes the transaction it signs and sends:

- the amount is converted with the token's on-chain decimals, rounded down;
- the recipient's token account is created when it does not exist yet;
- the transfer is a TransferChecked of exactly that amount to that account;
- a send above the on-chain balance, to yourself, with too little SOL for the
  network fee, or to an invalid address is refused before anything is signed.
"""
import base64, contextlib, os, sys, types
from decimal import Decimal
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
import portfolio_token_withdraw as w
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction

checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- %s' % detail) if detail and not cond else ''))

owner = Keypair()                      # a throwaway key made for this test
recipient = str(Keypair().pubkey())
MINT = str(Keypair().pubkey())
SOURCE = str(Keypair().pubkey())
TOKEN_PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'   # SPL Token

STATE = {}
def reset(balance_raw=5_000_000, decimals=6, sol_lamports=10_000_000, dest_exists=False):
    STATE.update(balance_raw=balance_raw, decimals=decimals, sol=sol_lamports, dest_exists=dest_exists, sent=[])

def fake_rpc(d, method, params, require_nonempty=False, preferred_url=None):
    if method == 'getAccountInfo':
        return ({'value': {'data': ['', 'base64']}} if STATE['dest_exists'] else {'value': None}), 'rpc'
    if method == 'getBalance':
        return {'value': STATE['sol']}, 'rpc'
    if method == 'getMinimumBalanceForRentExemption':
        return 2_039_280, 'rpc'
    if method == 'getLatestBlockhash':
        return {'value': {'blockhash': '4sGjMW1sUnHzSxGspuhpqLDx6wiyjNtZAMdL4VZHirAn'}}, 'rpc'
    if method == 'sendTransaction':
        STATE['sent'].append(params[0])
        return 'sig' + str(len(STATE['sent'])), 'rpc'
    raise AssertionError('unexpected RPC ' + method)

def fake_accounts(d, owner_text, token_address):
    return [{'pubkey': SOURCE, 'account': {'owner': TOKEN_PROGRAM, 'data': {'parsed': {'info': {
        'tokenAmount': {'amount': str(STATE['balance_raw']), 'decimals': STATE['decimals']}}}}}}]

w._rpc_urls = lambda d: ['rpc']
w._rpc_call_any = fake_rpc
w._solana_source_accounts = fake_accounts
w._wallet_keys = lambda d, wallet: ('encrypted-test-key',)
w._fee_payer_rent_lamports = lambda d: 890_880

@contextlib.contextmanager
def use_key(enc, wallet):
    yield str(owner)
d = types.SimpleNamespace(_get_trading_wallet_address=lambda wallet: str(owner.pubkey()), _use_key=use_key,
                          USDC_MINT='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v')

def send(amount, to=recipient):
    return w._solana_transfer(d, 'login-wallet', MINT, to, Decimal(amount), allow_user_funded_gas=False)

def decode(sent):
    return Transaction.from_bytes(base64.b64decode(sent))

ATA = 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'
expected_ata, _ = Pubkey.find_program_address(
    [bytes(Pubkey.from_string(recipient)), bytes(Pubkey.from_string(TOKEN_PROGRAM)), bytes(Pubkey.from_string(MINT))],
    Pubkey.from_string(ATA))

# A send of 1.2345678 with 6 decimals: 1_234_567 raw (rounded down).
reset()
sig, sent_amount = send('1.2345678')
tx = decode(STATE['sent'][0])
keys = [str(k) for k in tx.message.account_keys]
ix = tx.message.instructions
programs = [keys[i.program_id_index] for i in ix]
transfer = ix[-1]
data = bytes(transfer.data)
check('the amount is converted with the on-chain decimals, rounded down',
      data[0] == 12 and int.from_bytes(data[1:9], 'little') == 1_234_567 and data[9] == 6 and sent_amount == 1.234567,
      str((data[:1], int.from_bytes(data[1:9], 'little'), sent_amount)))
check("the recipient's token account is created first when it does not exist",
      programs == [ATA, TOKEN_PROGRAM] and str(expected_ata) in keys)
accs = [keys[i] for i in transfer.accounts]
check('...and the transfer goes from your token account to exactly that account',
      accs[0] == SOURCE and accs[1] == MINT and accs[2] == str(expected_ata) and accs[3] == str(owner.pubkey()))
check('the transaction is signed by your trading wallet and pays its own fee',
      keys[0] == str(owner.pubkey()) and tx.verify() is None and sig == 'sig1')

reset(dest_exists=True)
send('2')
programs = [str(decode(STATE['sent'][0]).message.account_keys[i.program_id_index]) for i in decode(STATE['sent'][0]).message.instructions]
check('an existing token account is not created again', programs == [TOKEN_PROGRAM])

def refused(amount, to=recipient, **state):
    reset(**state)
    try:
        send(amount, to)
    except ValueError as e:
        return str(e) if not STATE['sent'] else ''
    return ''
check('more than the on-chain balance is refused, nothing signed',
      'higher than your on-chain token balance' in refused('5.000001'))
check('a send to your own trading wallet is refused', 'same as your trading wallet' in refused('1', to=str(owner.pubkey())))
check('too little SOL for the fee and the new token account is refused',
      'Not enough SOL' in refused('1', sol_lamports=1_000_000))
check('an invalid address is refused', 'Invalid Solana' in refused('1', to='not-an-address'))
check('a token you do not hold is refused', 'not available' in refused('1', balance_raw=0))

print('%d/%d' % (sum(checks), len(checks)))
raise SystemExit(0 if all(checks) else 1)
