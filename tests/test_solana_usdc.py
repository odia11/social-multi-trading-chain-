"""One funding currency, on every chain.

Solana used to be the exception, and the two halves of the app disagreed
about it. There was a per-user setting, pref_solana_base_currency, defaulting
to USDC — and the autonomous bot honoured it while every manual buy ignored
it and spent SOL. The same user, on the same token, spent a different
currency depending on which button they pressed.

USDC is what the setting already defaulted to and what every EVM chain uses,
so that is what stays. SOL is still needed on Solana for network fees; that
is unavoidable and separate from what a trade is funded with, and the two
must not be confused in a balance check or in an error message.

The one thing that must NOT change: a position opened in SOL is still sold
back into SOL. Its base is recorded on the position, and forcing those sells
into USDC would misstate the profit on every trade opened before today.
"""
import ast
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''


# ── one value, in one place ──
check('there is a single constant naming the funding currency',
      "SOLANA_BASE_CURRENCY = 'USDC'" in SRC)
check('...and a minimum spend, so a trade cannot be so small that the network '
      'fee is most of it', 'SOLANA_MIN_SPEND_USDC' in SRC)

# ── nothing reads the old preference any more ──
check('the per-user preference is no longer read to decide a currency — that '
      'split is what let one user spend two different currencies',
      "_solana_base = SOLANA_BASE_CURRENCY" in SRC
      and "str(row[14]).upper() == 'USDC'" not in SRC)
check('...and the settings endpoint no longer writes it, rather than storing a '
      'preference the app then ignores',
      "updates.append('pref_solana_base_currency=?')" not in SRC)
check('...while still ANSWERING with the real currency, so an older page that '
      'shows the field shows something true',
      "'pref_solana_base_currency': SOLANA_BASE_CURRENCY," in SRC)

# ── the manual buy ──
buy = fn('_solana_buy_flow')
check('the manual buy funds the trade in the one currency',
      'base=SOLANA_BASE_CURRENCY' in buy)
check('...spending the configured size directly, with no conversion through a '
      'SOL price that may not have loaded yet',
      'spend = round(min(min_trade_usdc, us_usdc), 2)' in buy)
check('...checking the USDC balance for the trade', '_get_solana_usdc_balance' in buy)
check('...and the SOL balance SEPARATELY, for the network fee. One check '
      'covering both is how a user gets told the wrong currency is short',
      '_get_user_sol' in buy and 'SOL_NETWORK_RESERVE' in buy)
check('the two shortfalls read differently, so the message names what to send',
      'Not enough SOL for network fees' in buy
      and 'Send {SOLANA_BASE_CURRENCY} to your trading wallet' in buy)
check('the position records the currency it was bought with, so its SELL routes '
      'back into the same one', "pos['base']            = SOLANA_BASE_CURRENCY" in buy)

# ── the one-click route ──
inst = fn('api_instant_trade')
check('the one-click buy funds in the same currency', 'base=SOLANA_BASE_CURRENCY' in inst)
check('...reads amount_usdc, while still accepting the old amount_sol name so a '
      'cached page keeps working',
      "data.get('amount_usdc', data.get('amount_sol', 0))" in inst)
check('...checks USDC for the trade and SOL for the fee, separately',
      '_get_solana_usdc_balance' in inst and 'SOL_NETWORK_RESERVE' in inst)
check('...on the TRADING wallet, not the session wallet — different keypairs, '
      'and the funds are on the first', '_get_trading_wallet_address(wallet)' in inst)
check('...and states the currency in its answer', "'currency':       SOLANA_BASE_CURRENCY" in inst)

# ── what must not change ──
check('a SELL still routes back into whatever the position was opened with. '
      'Forcing old SOL positions into USDC would misstate the profit on every '
      'trade made before today',
      SRC.count("base=pos.get('base', 'SOL')") >= 4)

# ── the screens ──
LM = open(REPO + '/static/live-market-pro.js').read()
TC = open(REPO + '/static/token-card.js').read()
check('Live Market labels a Solana buy in USDC, not SOL',
      "isEvm?evmCurrencyLabel(t.chain):'USDC'" in LM)
check('...and sends amount_usdc, with amount_sol alongside for an older deploy',
      'amount_usdc:amt, amount_sol:amt' in LM)
check('...and reports back in the currency the server names',
      "(d.currency || 'USDC')" in LM)
check('the token card says USDC for every chain it trades',
      "function _tcUnit(chain){ return 'USDC'; }" in TC)
check('...and sends both names too', 'amount_usdc:amount, amount_sol:amount' in TC)

ST = open(REPO + '/templates/settings.html').read()
check('the setting is stated rather than offered, since there is nothing to '
      'choose', 'st-row-value">USDC<' in ST and 'id="s-solbase"' not in ST)
check('...and the page no longer sends a field the server ignores',
      'pref_solana_base_currency:' not in ST)
check('...with the styling for a stated value actually defined, not a class '
      'name that renders as nothing', '.st-row-value{' in ST)
check('...and it says plainly that SOL is still needed for fees, because a '
      'wallet holding only USDC cannot trade',
      'network fees' in ST and 'SOL is still needed' in ST)

# ── the wallet page ────────────────────────────────────────────────────────
# It led with SOL as "Available balance" and put USDC in a card below. After
# the currency change that is backwards: a wallet holding $4.64 of tradeable
# balance and no SOL read as completely empty.
W = open(REPO + '/templates/wallet.html').read()

check('the headline balance is what a trade is funded from',
      'Available to trade' in W and 'USDC across all chains' in W)
check('...and is filled from the USDC summary, not the SOL balance',
      "_availEl.textContent=_tot" in W)
check('SOL is shown as the network fee it now is, not as a balance',
      'SOL for network fees' in W and 'id="fee-sol"' in W)
check('...and is flagged when there is too little to send a trade. Running out '
      'of SOL and having nothing to trade with are different problems needing '
      'different deposits', 'SOL_FEE_RESERVE' in W and '_low ? ' in W)
check('...against the same figure the server keeps back, not a second number '
      'invented on the page', 'var SOL_FEE_RESERVE = 0.005' in W)
check('the total is not printed twice — two headline numbers compete to be the '
      'important one', W.count('id="usdc-total"') == 1
      and 'Total USDC' not in W)
check('a first load that fails blanks the headline rather than leaving a stale '
      'or wrong figure', "_a.textContent='—'" in W)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
