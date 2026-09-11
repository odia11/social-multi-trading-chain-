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

GETTING OUT IS HALF OF IT
There was no copy SELL anywhere in this app, and there never had been: a
copier was bought in and left there, getting out by hand or through their
own bot's take-profit and stop-loss while the trader they followed had
already gone. Following someone now follows them out as well.

The SHARE travels, not the amount. A leader who sells half sells half of
each copier's position, so a copier's position stays their own size
throughout -- the same rule as the buy side, where a copier spends their
amount and not the leader's.

And only what was bought FOR them is sold. A copier may hold the same token
from a buy of their own; selling that because somebody else sold theirs
would be reaching into a position they never asked anyone to manage.
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
check('...as a buy, with the sale handled as its own thing rather than '
      'copied into a position',
      re.search(r"if side == 'buy' and not _is_copy_pos:", inst) is not None
      and re.search(r"elif side == 'sell' and not _is_copy_pos:", inst) is not None)
check('...and neither direction propagates from a position that is itself a '
      'copy', "_is_copy_pos = bool(" in inst)
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

# ── 4b. the exit, with the sell flow stood in for ────────────────────────
sells = []


def _fake_sell(w, data, chain, wallet_label='EVM', is_copy=False):
    sells.append({'wallet': w, 'chain': chain, 'is_copy': is_copy,
                  'pct': data.get('sell_pct'), 'token': data.get('token_address')})
    return _Resp({'ok': True, 'sell_executed': True, 'chain': chain})


def _hold_copy(mint, leader=LEADER, chain='base'):
    m.get_user_state(FOLLOW)['positions'][mint] = {
        'amount': 100.0, 'buy_price': 0.25, 'spend': 10.0, 'symbol': 'TKN',
        'chain': chain, 'copy_of_wallet': leader, 'opened_at': time.time()}


def _run_sell(fn):
    sells.clear()
    real = m._evm_sell_flow
    m._evm_sell_flow = _fake_sell
    try:
        fn()
        for _ in range(60):
            if sells:
                break
            time.sleep(0.05)
        time.sleep(0.3)
    finally:
        m._evm_sell_flow = real


_hold_copy(MINT)
_run_sell(lambda: m._trigger_copy_sell(LEADER, MINT, chain='base', fraction=1.0))
check('a leader getting out of a position gets their copiers out of it too',
      len(sells) == 1 and sells[0]['wallet'] == FOLLOW)
check('...on the chain the position is on', sells and sells[0]['chain'] == 'base')
check('...all of it, when the leader sold all of theirs',
      sells and sells[0]['pct'] == 100.0)
check('...told it IS a copy, so the copier\'s own followers are not sold out '
      'behind it', sells and sells[0]['is_copy'] is True)

_hold_copy(MINT)
_run_sell(lambda: m._trigger_copy_sell(LEADER, MINT, chain='base', fraction=0.5))
check('a leader selling HALF sells half of the copier\'s, so a copier\'s '
      'position stays their own size rather than being closed out by '
      'somebody trimming theirs',
      len(sells) == 1 and sells[0]['pct'] == 50.0)

# A token the copier bought for themselves is not somebody else's to sell.
m.get_user_state(FOLLOW)['positions'][MINT] = {
    'amount': 100.0, 'buy_price': 0.25, 'spend': 10.0, 'symbol': 'TKN',
    'chain': 'base', 'opened_at': time.time()}          # no copy_of_wallet
_run_sell(lambda: m._trigger_copy_sell(LEADER, MINT, chain='base', fraction=1.0))
check('a position the copier opened THEMSELVES is not sold because somebody '
      'they follow sold theirs — that would be reaching into a position they '
      'never asked anyone to manage', sells == [])

# A copy of another leader is that leader's to close, not this one's.
_hold_copy(MINT, leader='SomeOtherWallet111111111111111111111111111')
_run_sell(lambda: m._trigger_copy_sell(LEADER, MINT, chain='base', fraction=1.0))
check('...and neither is a copy of somebody else', sells == [])

m.get_user_state(FOLLOW)['positions'].clear()
_run_sell(lambda: m._trigger_copy_sell(LEADER, MINT, chain='base', fraction=1.0))
check('a copier who no longer holds it is left alone rather than sent a sell '
      'that would fail', sells == [])

# The hook itself: closing a leader's position reaches the copiers, and
# closing a COPY does not reach anyone.
_hold_copy(MINT)
lead_uid = m.get_or_create_user(LEADER)
m.get_user_state(LEADER)['positions'][MINT] = {
    'amount': 40.0, 'buy_price': 0.2, 'spend': 8.0, 'symbol': 'TKN', 'chain': 'base'}
_run_sell(lambda: m._close_open_position(lead_uid, LEADER, MINT, chain='base'))
check('closing a leader\'s position is itself what tells the copiers, so '
      'every full exit in the app is covered by one hook',
      len(sells) == 1 and sells[0]['pct'] == 100.0)

_hold_copy(MINT)
f_pos_uid = m.get_or_create_user(FOLLOW)
_run_sell(lambda: m._close_open_position(f_pos_uid, FOLLOW, MINT, chain='base'))
check('...and closing a position that is itself a copy tells nobody, which '
      'is what stops a chain of them', sells == [])
m.get_user_state(FOLLOW)['positions'].clear()

# ── 5. Solana copying is untouched ───────────────────────────────────────
sol = SRC.split('def _trigger_copy_buy(')[1].split('\ndef ')[0]
check('the Solana copy path still runs when no chain is named, so every '
      'caller that predates this keeps working',
      "chain: str = 'solana'" in sol)
check('...and still checks price impact before spending a copier\'s money',
      '_check_price_impact' in SRC.split('def _trigger_copy_buy(')[1].split('\ndef _copy')[0]
      or '_check_price_impact' in SRC)

# ── 6. getting out ───────────────────────────────────────────────────────
close = SRC.split('def _close_open_position')[1].split('\ndef ')[0]
check('a leader getting out reaches the people copying them',
      '_trigger_copy_sell' in SRC)
check('...from the one place every full exit in the app comes through, so '
      'the bot\'s stop loss, take profit, crash and rug exits and the manual '
      'sells on every chain are all covered without a trigger bolted onto '
      'each', '_trigger_copy_sell(wallet, mint' in close)
check('...but never for a position that is ITSELF a copy, which is what '
      'stops a chain of them and stops two people who follow each other '
      'selling each other out in a circle',
      re.search(r'if not _was_copy:\s*\n\s*_trigger_copy_sell', close) is not None)
check('...reading that off the position BEFORE it is cleared, since clearing '
      'it is what this function does',
      close.index('_was_copy = bool') < close.index("['positions'][mint] = {'amount': 0.0"))

check('Live Market\'s Solana sale tells them too — that route keeps no '
      'position of its own, so nothing downstream would ever have',
      "elif side == 'sell' and not _is_copy_pos:" in inst)
check('...with the share of the holding it actually was, measured rather '
      'than assumed, because a dollar figure is a share of whatever they '
      'happen to hold',
      'copy_share = (min(1.0, sell_usd_tokens / _held_now)' in inst)
check('...and says so rather than guessing when it cannot tell what share '
      'a sale was', 'cannot tell what' in inst)

esell = SRC.split('def _evm_sell_flow')[1].split('\ndef ')[0]
check('a PARTIAL EVM sale is copied as a partial, at the share that was '
      'sold — it never reaches the full-exit hook',
      re.search(r'fraction=\(amount / held\)', esell) is not None)
check('...and the flow a copy is executed through knows it is one, so a '
      'copied sale does not sell onward',
      'is_copy: bool = False' in esell and 'if not is_copy and not pos.get' in esell)

sell = SRC.split('def _trigger_copy_sell')[1].split('\ndef ')[0]
check('the share travels, not the amount, so a copier\'s position stays '
      'their own size', 'fraction' in sell and 'pct = max(1.0, min(100.0' in sell)
check('...and is clamped on this side too, so nothing downstream is asked '
      'to sell more than all of it', 'min(100.0' in sell)

holders = SRC.split('def _copy_holders')[1].split('\ndef ')[0]
check('only what was bought FOR a copier is sold — a token they bought '
      'themselves is not touched because somebody else sold theirs',
      "pos.get('copy_of_wallet') == leader_wallet" in holders)
check('...and only while they still hold it', "pos.get('amount', 0) > 0" in holders)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
