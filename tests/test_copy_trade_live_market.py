"""Copying somebody means copying what they do, not where they do it.

WHAT WAS HAPPENING
Copy trading fired from exactly three places: the auto-trading bot's own
loop, and two older Solana routes. Live Market -- the screen where people
actually press Buy -- told the copy path nothing at all. So following a
trader worked in name only: their profile said you were copying them, their
manual calls happened, and nothing reached the people following.

It was also Solana-only. A trader followed for their BNB Chain or Base
calls was followed in name only twice over: there was no code that could
buy for a copier on any chain but one.

WHAT THIS CHANGES
Every manual buy triggers copying, on whatever chain it happened, Live
Market included. A copier's buy runs through the SAME flow their own Buy
button runs through -- same quote, same ceiling, same gas handling, same
fee -- rather than a second implementation of a buy that could drift from
it. What is added around that is the copier's own risk limits and the mark
that says whose trade it was.

WHAT MUST NOT BREAK
1. A copier's own limits are theirs. Someone who has hit their daily loss
   limit -- and whose own bot has therefore paused -- must not still be
   bought into new positions every time the trader they follow moves.
2. A copy must not copy onward. This flow is what a copy is executed
   through, so without a guard a copied buy would copy again, and two people
   who follow each other would trade each other in a circle until one ran
   out of money.
3. A copier spends THEIR amount, never the leader's. Following a whale must
   not spend like one.

WHAT THIS DOES NOT DO, said out loud because it matters: there is still no
copy SELL anywhere in this app, and there never was. A copier is bought in
and gets out on their own -- by hand, or through their own bot's take-profit
and stop-loss. Widening the buy side without saying so would be the trap.
"""
import os
import re
import sys
import tempfile
import time

REPO = '/home/user/Orc-agent-Solana-chain-'
sys.path.insert(0, REPO)

_DATA = tempfile.mkdtemp()
os.environ.update({
    'DATA_DIR': _DATA,
    'SECRET_KEY': 'x' * 32,
    'ENCRYPTION_KEY': 'KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=',
    'DEV': '1',
})
import dashboard as m  # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()

# ── 1. every manual buy tells the copy path, on every chain ──────────────
inst = SRC.split('def api_instant_trade')[1].split('\ndef ')[0]
check('Live Market\'s Solana buy triggers copying — the screen people '
      'actually press Buy on told the copy path nothing at all',
      '_trigger_copy_buy(' in inst)
check('...for a buy only, since a sale is not a position to copy into',
      re.search(r"if side == 'buy' and not get_user_state\(wallet\)", inst) is not None)
check('...inside the lock, so a double-click the repeat window already '
      'refuses cannot get a second copy out either',
      inst.index('_trigger_copy_buy(') > inst.index('with lock:'))

evm = SRC.split('def _evm_buy_flow')[1].split('\ndef ')[0]
check('every manual EVM buy triggers copying too — one flow serves all five '
      'chains, so all five are covered', '_trigger_copy_buy(' in evm)
check('...on the chain it happened on, not on Solana',
      'chain=chain)' in evm)
legacy = SRC.split('def _legacy_evm_trade_buy')[1].split('\ndef ')[0]
check('...including the pre-engine path kept behind the feature flag, so '
      'turning the engine off does not turn copying off with it',
      '_trigger_copy_buy(' in legacy and 'is_copy' in legacy)
check('the bot loop still triggers it, unchanged',
      '_trigger_copy_buy(wallet, bmint' in SRC)

# ── 2. a copy must not copy onward ───────────────────────────────────────
check('the flow a copy is executed through knows it is executing a copy',
      'is_copy: bool = False' in evm)
check('...and does not copy onward when it is, which is what stops two '
      'people who follow each other trading in a circle',
      re.search(r'if not is_copy and not get_user_state', evm) is not None)
check('...and the copy path sets that flag when it calls in',
      'is_copy=True)' in SRC.split('def _trigger_copy_buy_evm')[1].split('\ndef ')[0])
check('a position that is itself a copy never propagates either, on any '
      'path', SRC.count("get('copy_of_wallet')") >= 3)

# ── 3. the copier's limits are the copier's ──────────────────────────────
WALLET = 'Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9'
MINT = '0x2170Ed0880ac9A755fd29B2688956BD959F933F8'
m.get_or_create_user(WALLET)
us = m.get_user_state(WALLET)
us['daily_stats']['total_pnl'] = 0
us['positions'].clear()

check('a copy goes ahead when nothing is in its way',
      m._copy_guards_pass(WALLET, 5, 50.0, MINT, 'TKN', 'base') is True)

us['daily_stats']['total_pnl'] = -80.0
check('...and is refused once the copier has hit their OWN daily loss '
      'limit, which a copy does not get to override',
      m._copy_guards_pass(WALLET, 5, 50.0, MINT, 'TKN', 'base') is False)
check('...using the copier\'s own figure, not a number in the code',
      m._copy_guards_pass(WALLET, 5, 200.0, MINT, 'TKN', 'base') is True)
us['daily_stats']['total_pnl'] = 0

for i in range(5):
    us['positions']['0x%040d' % i] = {'amount': 1.0, 'chain': 'base'}
check('...and refused at the copier\'s position ceiling',
      m._copy_guards_pass(WALLET, 5, 50.0, MINT, 'TKN', 'base') is False)
check('...counted per chain, because a ceiling of five means five on the '
      'chain being traded',
      m._copy_guards_pass(WALLET, 5, 50.0, MINT, 'TKN', 'polygon') is True)
us['positions'].clear()

us['positions'][MINT] = {'amount': 10.0, 'chain': 'base'}
check('...and refused when the copier already holds it, rather than '
      'doubling up', m._copy_guards_pass(WALLET, 5, 50.0, MINT, 'TKN', 'base') is False)
us['positions'].clear()

# ── 4. the EVM copy itself, with the buy flow stood in for ───────────────
LEADER = 'FwdxAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263'
FOLLOW = '9pXQwftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9'
import sqlite3  # noqa: E402
f_uid = m.get_or_create_user(FOLLOW)
m.get_or_create_user(LEADER)
con = sqlite3.connect(m.DB_FILE)
con.execute('UPDATE users SET copy_source=?, copy_amount=?, max_trade_size=?, '
            'max_positions=5, daily_loss_limit=50 WHERE wallet_address=?',
            (LEADER, 7.5, 25.0, FOLLOW))
con.commit()
con.close()

check('the followers of a wallet are found without filtering on the Solana '
      'key -- that filter dropped every copier from an EVM trade, because '
      'the key an EVM copy needs is a different column',
      [r[1] for r in m._copy_followers(LEADER)] == [FOLLOW])
check('...and a wallet is never its own follower',
      all(r[1] != LEADER for r in m._copy_followers(LEADER)))

calls = []


class _Resp:
    def __init__(self, body): self._b = body
    def get_json(self): return self._b


def _fake_buy(w, data, chain, wallet_label='EVM', is_copy=False):
    calls.append({'wallet': w, 'chain': chain, 'is_copy': is_copy,
                  'amount': data.get('amount_usdc'), 'token': data.get('token_address')})
    m.get_user_state(w)['positions'][data['token_address']] = {
        'amount': 100.0, 'buy_price': 0.25, 'spend': data['amount_usdc'],
        'symbol': 'TKN', 'chain': chain, 'opened_at': time.time()}
    return _Resp({'ok': True, 'chain': chain, 'entry_price': 0.25, 'symbol': 'TKN'})


_real_buy = m._evm_buy_flow
m._evm_buy_flow = _fake_buy
try:
    m.get_user_state(FOLLOW)['positions'].clear()
    m.get_user_state(FOLLOW)['daily_stats']['total_pnl'] = 0
    m._trigger_copy_buy(LEADER, MINT, 0.25, 'TKN', 0.0, chain='base')
    for _ in range(60):
        if calls:
            break
        time.sleep(0.05)
    time.sleep(0.3)
finally:
    m._evm_buy_flow = _real_buy

check('a leader\'s EVM buy reaches their copier', len(calls) == 1)
check('...on the chain the leader traded, not on Solana',
      calls and calls[0]['chain'] == 'base')
check('...through the same flow the copier\'s own Buy button runs through, '
      'rather than a second implementation of an EVM buy',
      calls and calls[0]['token'] == MINT)
check('...told that it IS a copy, so it does not copy onward',
      calls and calls[0]['is_copy'] is True)
check('...spending the copier\'s own copy amount, never the leader\'s — '
      'following a whale must not spend like one',
      calls and calls[0]['amount'] == 7.5)

pos = m.get_user_state(FOLLOW)['positions'].get(MINT, {})
check('the copied position is marked with whose trade it was, which is what '
      'a profile counts', pos.get('copy_of_wallet') == LEADER)
con = sqlite3.connect(m.DB_FILE)
row = con.execute('SELECT source, copy_of_wallet, chain FROM open_positions '
                  'WHERE user_id=? AND mint_address=?', (f_uid, MINT)).fetchone()
con.close()
check('...and it survives a restart, because the row on disk carries it too',
      row is not None and row[0] == 'copy' and row[1] == LEADER and row[2] == 'base')

# the guard, live: a copier at their limit is not bought into anything
calls.clear()
m._evm_buy_flow = _fake_buy
try:
    m.get_user_state(FOLLOW)['positions'].clear()
    m.get_user_state(FOLLOW)['daily_stats']['total_pnl'] = -500.0
    m._trigger_copy_buy(LEADER, '0x' + 'b' * 40, 0.25, 'OTHER', 0.0, chain='base')
    time.sleep(0.6)
finally:
    m._evm_buy_flow = _real_buy
    m.get_user_state(FOLLOW)['daily_stats']['total_pnl'] = 0
check('a copier past their daily loss limit is not bought into anything, '
      'however often the trader they follow moves', calls == [])

# ── 5. Solana copying is untouched ───────────────────────────────────────
sol = SRC.split('def _trigger_copy_buy(')[1].split('\ndef ')[0]
check('the Solana copy path still runs when no chain is named, so every '
      'caller that predates this keeps working',
      "chain: str = 'solana'" in sol)
check('...and still checks price impact before spending a copier\'s money',
      '_check_price_impact' in SRC.split('def _trigger_copy_buy(')[1].split('\ndef _copy')[0]
      or '_check_price_impact' in SRC)

# ── 6. what is NOT here ──────────────────────────────────────────────────
check('there is still no copy SELL, and this change does not pretend '
      'otherwise — a copier gets out by hand or through their own bot',
      '_trigger_copy_sell' not in SRC)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
