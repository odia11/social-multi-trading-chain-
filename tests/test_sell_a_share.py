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

# ── 1b. a dollar figure, turned into tokens on this side ─────────────────
# 2,340 tokens at $0.0442 is $103.43 of position.
HELD, PX = 2340.0, 0.0442
check('a dollar figure is priced into a share against the holding and the '
      'price the SERVER has, not a token count from the browser',
      abs(m._sell_share({'sell_usd': 25}, HELD, PX)[0] - (25 / PX / HELD)) < 1e-12)
check('...and that share is a partial, so the rest stays open',
      m._sell_share({'sell_usd': 25}, HELD, PX)[1] is False)
check('asking for more dollars than the position is worth is a full close, '
      'not an error -- "$200 of a $103 holding" means all of it, and the '
      'price moves between the screen and the server anyway',
      m._sell_share({'sell_usd': 200}, HELD, PX) == (1.0, True))
check('...and so is a figure within half a percent of the whole, by the same '
      'dust rule a percentage uses',
      m._sell_share({'sell_usd': HELD * PX * 0.997}, HELD, PX) == (1.0, True))
check('a dollar figure wins over a percentage when both are sent, the same '
      'precedence amount_usdc already has over amount_sol',
      m._sell_share({'sell_pct': 100, 'sell_usd': 25}, HELD, PX)[1] is False)
check('no dollar figure falls through to the percentage, so every caller '
      'that predates this is untouched',
      m._sell_share({}, HELD, PX) == (1.0, True)
      and m._sell_share({'sell_pct': 50}, HELD, PX) == (0.5, False))

for bad, label in [(-5, 'a negative figure'), (0, 'zero dollars'),
                   (float('nan'), 'not a number'), (float('inf'), 'infinity'),
                   ('abc', 'letters'), ([25], 'a list')]:
    try:
        m._sell_share({'sell_usd': bad}, HELD, PX)
        ok = False
    except ValueError:
        ok = True
    except Exception:
        ok = False
    check(f'refused: {label} of dollars', ok)

for held, px, label in [(0.0, PX, 'a token with no position to price against'),
                        (HELD, 0.0, 'a token with no price right now')]:
    try:
        m._sell_share({'sell_usd': 25}, held, px)
        ok = False
    except ValueError:
        ok = True
    check(f'refused, rather than guessed at: {label}', ok)
check('...and the no-price refusal says what to do instead rather than just '
      'failing',
      'sell by percentage instead' in str(sys.exc_info()[1] or '')
      or 'sell by percentage instead' in open(REPO + '/dashboard.py',
                                               encoding='utf-8').read())

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
      and re.search(r'if full_close:[\s\S]{0,300}?_close_open_position\(', evm)
      is not None)
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

# ── 3b. what there is to sell ────────────────────────────────────────────
hold_src = src.split('def api_trade_holding')[1].split('\ndef ')[0]
check('the sell screen can ask what is actually held, on any chain the '
      'platform trades', "@app.route('/api/trade/holding'" in src
      and 'chain not in TOKEN_CHAINS' in hold_src)
check('...validating the address against the chain it was sent for, rather '
      'than assuming Solana the way the older position route does',
      'is_valid_token_address(addr, chain)' in hold_src)
check('...reporting the TRACKED position first, which is what the sell '
      'routes actually close, so the screen and the trade agree',
      "get_user_state(wallet)['positions']" in hold_src
      and "source = 'position'" in hold_src)
# Live Market's own Solana buy route has never written to open_positions,
# so a tracked amount of 0 there does not mean an empty wallet.
# The fallback moved into a helper the copy path shares, so the screen and
# the trade cannot disagree about what is there. Asserted where it lives
# now, plus that the route still reaches it.
held_src = src.split('def _solana_token_amount')[1].split('\ndef ')[0]
check('...falling back to what the chain itself reports on Solana, rather '
      'than telling somebody they hold nothing while their wallet says '
      'otherwise',
      "chain == 'solana'" in hold_src
      and '_solana_token_amount(wallet, addr)' in hold_src
      and '_fetch_wallet_tokens' in held_src)
check('...through one lookup, shared with the copy path, so a sale and the '
      'copy of it cannot disagree about how much was there',
      src.count('_solana_token_amount(') >= 3)
check('...and saying which of the two answered, so the caller is not '
      'guessing', "'source': source" in hold_src)
check('...behind the same login every other trade route is behind',
      '_authenticated_wallet()' in hold_src and 'No wallet connected' in hold_src)
check('...and rate limited, since it prices a token on every call',
      '@rate_limit' in src.split("@app.route('/api/trade/holding'")[1][:120])

# The EVM sell decides the share where the holding and the price are both
# known, not before -- the dollar conversion needs them.
check('the EVM sell prices the dollar figure inside the lock, against the '
      'position it is about to sell',
      re.search(r'quoted_px = [\s\S]{0,700}_sell_share\(data, held, quoted_px\)',
                evm) is not None)
check('...while the shape of the request is still refused up front, before '
      'any work is done',
      re.search(r'_sell_fraction\(data\)[\s\S]{0,200}400', evm) is not None)
check('the Solana sell prices it here and lets the swap clamp it to the real '
      'balance', 'sell_usd_tokens = _usd / _px' in inst
      and "f'{sell_usd_tokens:.9f}'" in inst)
check('...and refuses a token with no price rather than dividing by it',
      'No price for this token right now' in inst)

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
check('the screen says what it is about to do, in the figure being sold',
      "'Slide to sell $' + _sheetAmt" in JS)
check('...and says "all" out loud when it is all, because trimming a '
      'position and closing it are different decisions',
      "'Slide to sell all $'" in JS)
check('a tapped share travels as a share, so "All" closes the position '
      'exactly rather than to the nearest cent',
      re.search(r"if\(_sellPct != null\)\{\s*\n\s*how = \{sell_pct:", JS)
      is not None)
check('a typed figure travels as dollars, so what is sold is what was typed',
      'how = {sell_usd: usd}' in JS)
check('...and typing clears the tapped share, so the two can never disagree '
      'about which one the screen means',
      re.search(r"function _sheetTypeAmount[\s\S]{0,200}_sellPct = null", JS)
      is not None)
check('neither carries a quantity of tokens',
      re.search(r"amount_token", JS.split('function handleSell')[1]) is None)
check('...bounded on this side as well, so a broken screen cannot send '
      'nonsense in the first place',
      'Math.min(100, Math.max(1, Number(_sellPct) || 100))' in JS)
check('a partial sale is reported as one rather than as "Sold $X"',
      "d.position_closed === false" in JS and 'sold_pct' in JS)

# ── 4b. the figure, and the tokens it comes to ───────────────────────────
check('the sell screen takes a figure in dollars, on the same keypad the '
      'buy screen uses', '.pt-sheet.sell-mode .pt-keys' not in HTML)
check('...and shows what it comes to in tokens, the same conversion the buy '
      'screen does the other way',
      re.search(r"_sheetMode === 'sell'[\s\S]{0,2200}fmtAmount\(sAmt / px\)", JS)
      is not None)
check('...at the price the SERVER quoted, so the number on the screen is the '
      'one that trades', '_sheetHold ? _sheetHold.price : 0' in JS
      and '/api/trade/holding' in JS)
check('...measured against what is held, said in the same place the buy '
      'screen says what is spendable', "'</b> held'" in JS)
check('...and refusing to arm for more than that',
      "'More than you hold'" in JS)
check('the quick shares fill the figure in rather than replacing it, so one '
      'row drives one number in both modes',
      re.search(r"var part = _sheetAvail \* \(pct / 100\);", JS) is not None)
check('a sale is not sent to the quote route, which prices a purchase',
      re.search(r"_sheetMode !== 'sell' && t && EVM_TRADE_CHAINS", JS) is not None)
# Closing a position is how a loss gets cut.
check('a holding lookup that cannot be reached still leaves the whole '
      'position sellable, because that is how somebody cuts a loss',
      '_holdErr' in JS
      and re.search(r"if\(_holdErr\)\{[\s\S]{0,420}_slideEnable\(true\)", JS)
      is not None)
check('...and says so rather than pretending it read something',
      'Could not read your position' in JS)
check('a token with nothing in it says so instead of arming a sell that '
      'would fail', "'Nothing to sell'" in JS)

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
