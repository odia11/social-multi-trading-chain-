"""Selling did not have to be all of it.

WHAT WAS HAPPENING
Every sell route closed the WHOLE position. There was no way to take half
off the table and let the rest run, on any chain, which is the most ordinary
thing a trader does -- and the Sell button was the only control on the
screen with no amount attached to it.

HOW THE AMOUNT IS DECIDED
The browser sends a SHARE, never a quantity. How many tokens that is gets
worked out on this side, from the position the server itself has tracked
(EVM) or from the balance the chain itself reports (Solana). So a tampered
request can only ever ask for a different slice of your own holding -- it
cannot name a number of tokens, cannot reach past what is held, and cannot
reach anybody else's. That was already true of a full close and stays true
of a partial one.

The share is checked rather than clamped. "-5", "nan", "150", "" and
"abc" are all broken callers, not small ones, and a route that quietly
turned any of them into some other number would be guessing at what
somebody meant to do with their own money.

WHAT MUST NOT BREAK
1. A request with no share at all still means the whole position. Every
   caller that predates this -- the bot's stop-loss and take-profit exits,
   the wallet page, the older routes -- keeps meaning what it always meant.
2. A partial sale must LEAVE the rest open. Closing the position would make
   tokens the user still holds vanish from their portfolio, which is the
   bug the Solana route already carried a comment about.
3. Anything from 99.5% up is a full close. Half a percent of a position left
   behind is dust: it costs more in gas to sell than it is worth, so it
   would sit there forever looking like a holding.
"""
import os
import re
import sys
import tempfile

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


# ── 1. what the server accepts as a share ────────────────────────────────
check('no share at all means the whole position, so every caller that '
      'predates this keeps meaning what it meant',
      m._sell_fraction({}) == (1.0, True)
      and m._sell_fraction({'sell_pct': None}) == (1.0, True)
      and m._sell_fraction({'sell_pct': ''}) == (1.0, True))
check('a half is a half, and leaves the position open',
      m._sell_fraction({'sell_pct': 50}) == (0.5, False))
check('...and so is the string a browser actually sends',
      m._sell_fraction({'sell_pct': '50'}) == (0.5, False))
check('100 is a full close', m._sell_fraction({'sell_pct': 100}) == (1.0, True))
check('anything from 99.5 up is a full close too, rather than leaving dust '
      'that costs more in gas to sell than it is worth',
      m._sell_fraction({'sell_pct': 99.5}) == (1.0, True)
      and m._sell_fraction({'sell_pct': 99.9}) == (1.0, True))
check('...and 99 is still a partial, so the rule has an edge rather than a '
      'slope', m._sell_fraction({'sell_pct': 99})[1] is False)

# Refused, not clamped: a route that quietly turned -5 into something else
# would be guessing at what somebody meant to do with their own money.
for bad, label in [(-5, 'a negative share'), (0, 'nothing at all'),
                   (150, 'more than the whole position'),
                   (float('nan'), 'not a number'),
                   (float('inf'), 'infinity'),
                   ('abc', 'letters'), ('50%', 'a percent sign'),
                   ([50], 'a list'), ({}, 'an object')]:
    try:
        m._sell_fraction({'sell_pct': bad})
        ok = False
    except ValueError:
        ok = True
    except Exception:
        ok = False
    check(f'refused: {label}', ok)

# NaN is the one that slips past a one-sided check, so it is worth saying
# out loud that both ends are tested rather than only the obvious one.
src = open(REPO + '/dashboard.py', encoding='utf-8').read()
frac_src = src.split('def _sell_fraction')[1].split('\ndef ')[0]
check('the bounds are checked on both sides, which is what stops NaN -- it '
      'fails every comparison, so a single `pct > 100` would let it through',
      'not (pct > 0)' in frac_src and 'not (pct <= 100)' in frac_src)
check('the share is read from the request rather than a token amount, so the '
      'client never names a quantity',
      "data.get('sell_pct'" in frac_src and 'amount_token' not in frac_src)

# ── 2. what a partial sale leaves behind ─────────────────────────────────
WALLET = 'Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9'
MINT = 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263'
uid = m.get_or_create_user(WALLET)
pos = m.get_user_state(WALLET)['positions'].setdefault(MINT, {})
pos.update({'amount': 1000.0, 'buy_price': 0.02, 'spend': 20.0, 'symbol': 'WIF'})
m._upsert_open_position(uid, WALLET, MINT, pos, source='manual')

m._reduce_open_position(uid, WALLET, MINT, 400.0)
left = m.get_user_state(WALLET)['positions'][MINT]
check('a partial sale leaves the rest of the position open rather than '
      'closing it', abs(left['amount'] - 600.0) < 1e-9)
check('...with the entry price untouched, because the tokens still held were '
      'bought at the price they were always bought at',
      abs(left['buy_price'] - 0.02) < 1e-12)
check('...and the money that went into it cut by the share that left, so '
      'what remains still reports what it actually cost',
      abs(left['spend'] - 12.0) < 1e-6)

import sqlite3  # noqa: E402
con = sqlite3.connect(m.DB_FILE)
row = con.execute('SELECT amount, spend, buy_price FROM open_positions '
                  'WHERE user_id=? AND mint_address=?', (uid, MINT)).fetchone()
con.close()
check('...and it survives a restart, because the row on disk was reduced too',
      row is not None and abs(row[0] - 600.0) < 1e-9 and abs(row[1] - 12.0) < 1e-6)

m._reduce_open_position(uid, WALLET, MINT, 600.0)
con = sqlite3.connect(m.DB_FILE)
gone = con.execute('SELECT COUNT(*) FROM open_positions '
                   'WHERE user_id=? AND mint_address=?', (uid, MINT)).fetchone()[0]
con.close()
check('selling the rest closes it, rather than leaving a row with nothing '
      'in it', gone == 0)
check('...and the in-memory position agrees',
      not m.get_user_state(WALLET)['positions'][MINT].get('amount', 0) > 0)

pos2 = m.get_user_state(WALLET)['positions'].setdefault(MINT, {})
pos2.update({'amount': 10.0, 'buy_price': 1.0, 'spend': 10.0, 'symbol': 'WIF'})
m._upsert_open_position(uid, WALLET, MINT, pos2, source='manual')
m._reduce_open_position(uid, WALLET, MINT, 99.0)   # more than is there
con = sqlite3.connect(m.DB_FILE)
over = con.execute('SELECT COUNT(*) FROM open_positions '
                   'WHERE user_id=? AND mint_address=?', (uid, MINT)).fetchone()[0]
con.close()
check('taking more off than is there closes it instead of leaving a '
      'negative holding', over == 0)

# ── 3. the routes ────────────────────────────────────────────────────────
evm = src.split('def _evm_sell_flow')[1].split('\ndef ')[0]
check('the EVM sell route reads the share', '_sell_fraction(data)' in evm)
check('...and refuses a bad one with a 400 rather than trading on it',
      re.search(r'except ValueError as e:\s*\n\s*return jsonify\('
                r"\{'ok': False, 'msg': str\(e\)\}\), 400", evm) is not None)
check('...and the quantity is a share OF the tracked holding, worked out '
      'server-side', 'amount = held if full_close else held * frac' in evm)
check('...so nothing the client sends is ever used as a token amount',
      "data.get('amount'" not in evm and "data.get('amount_token'" not in evm)
check('...a full sell still closes the position', '_close_open_position(' in evm)
check('...and a partial one reduces it instead',
      '_reduce_open_position(' in evm
      and re.search(r'if full_close:\s*\n\s*_close_open_position', evm) is not None)
check('...the caller is told what was actually sold and whether anything is '
      'left', "'sold_pct'" in evm and "'position_closed': full_close" in evm)

inst = src.split('def api_instant_trade')[1].split('\ndef ')[0]
check('the Solana route reads the share too, so the button behaves the same '
      'on every chain', '_sell_fraction(data)' in inst)
check('...and sends it down as a share rather than resolving it here, '
      'because the on-chain balance is known further down',
      "f'{sell_frac * 100:g}%'" in inst)
check('...while a full sell still says "everything held", the branch that '
      'avoids leaving dust behind',
      "str(amount_token) if amount_token > 0 else '0'" in inst)
# The holding is zeroed only by a full close. A share leaves amount_token at
# 0 and would have walked straight into that branch.
check('a partial sale does not zero the portfolio holding the way the old '
      'quantity check would have', 'elif sell_full and amount_token <= 0:' in inst)

sol = open(REPO + '/orcagent_solana.py', encoding='utf-8').read()
check('the Solana swap resolves a share against the RAW on-chain integer, '
      'not a float round-trip that would leave dust',
      'int(raw_balance * sell_pct / 100)' in sol)
check('...and 100% still uses the raw balance directly rather than computing '
      'it', 'sell_pct is not None and sell_pct < 100' in sol)
check('...a percentage on a BUY is refused rather than silently treated as '
      'an amount', "a percentage amount is only meaningful for a sell" in sol)
check('...and an out-of-range share is refused there too, so the check does '
      'not live only in the web layer',
      'sell percentage must be above 0 and at most 100' in sol)

# ── 4. the screen ────────────────────────────────────────────────────────
JS = open(REPO + '/static/live-market-pro.js', encoding='utf-8').read()
HTML = open(REPO + '/templates/live_market_pro.html', encoding='utf-8').read()
check('the sell sheet offers shares to sell', 'data-spct="25"' in HTML
      and 'data-spct="50"' in HTML and 'data-spct="75"' in HTML
      and 'data-spct="100"' in HTML)
check('...on the same row the buy sheet uses for shares to spend, relabelled '
      'rather than duplicated', 'function _paintPcts' in JS
      and '.pt-sheet.sell-mode .pt-sheet-pcts{display:none}' not in HTML)
check('...starting at the whole position, so opening the sheet and sliding '
      'does what it always did', 'var _sellPct = 100;' in JS
      and '_sellPct = 100;' in JS.split('function _openSheet')[1][:400])
check('...saying which share is selected', ".pt-pct.on{" in HTML)
check('the screen says what it is about to do',
      "'Sell ' + _sellPct + '%'" in JS and "'Slide to sell ' + _sellPct + '%'" in JS)
check('...and that the rest is kept', 'keeps the rest' in JS)
check('the request carries a share and no quantity',
      'sell_pct:pct' in JS
      and re.search(r"amount_token", JS.split('function handleSell')[1]) is None)
check('...bounded on this side as well, so a broken screen cannot send '
      'nonsense in the first place',
      'Math.min(100, Math.max(1, Number(_sellPct) || 100))' in JS)
check('a partial sale is reported as one rather than as "Sold $X"',
      "d.position_closed === false" in JS and 'sold_pct' in JS)

# ── 5. the fee box ───────────────────────────────────────────────────────
check('what a trade costs is on the screen, folded away',
      '<details class="pt-fees"' in HTML)
check('...as a real disclosure, so it opens with a keyboard and announces '
      'itself without any code of ours',
      '<summary class="pt-fees-sum">' in HTML)
check('...with the total on the folded row, so it says what it costs '
      'without being opened', 'id="pt-fees-amt"' in HTML
      and 'pt-fees-amt' in JS)
check('...folded again for the next token, rather than staying open from the '
      'last one', 'box.open = false' in JS)
check('the buy breakdown still renders into the id scheduleQuote() writes '
      'to, unchanged', 'id="pt-quote-sheet"' in HTML)
check('...and the total shown is the quote\'s own spend minus what it buys, '
      'not a figure of the page\'s own',
      re.search(r'spend - gets', JS) is not None)
check('a stale total is cleared when the amount changes, so the folded row '
      'never quotes the previous amount',
      re.search(r"feeAmt && _sheetMode !== 'sell'\) feeAmt\.textContent = ''", JS)
      is not None)
# A sell is not quoted -- what it returns is known when it settles.
check('the sell box states the rates that apply rather than inventing a '
      'total for a swap that has not happened',
      'what the sale returns' in JS and 'when the sale settles' in JS)
check('...and the platform rate comes from the server, so the box cannot '
      'quote a rate the fee code does not charge',
      'PT_FEE_RATE_TXN' in JS and 'fee_rate_txn=FEE_RATE_TXN' in src
      and 'var PT_FEE_RATE_TXN' in HTML)
check('...which is the same constant the sell leg is actually charged at',
      re.search(r'_charge_evm_txn_fee\(', src) is not None
      and 'FEE_RATE_TXN' in src.split('def _charge_evm_txn_fee')[1][:2000])

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
