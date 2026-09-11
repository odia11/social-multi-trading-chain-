"""A swap that lands in a second still has to be checkable.

WHAT WAS HAPPENING
A buy went: slide, one frozen moment, "Bought". On a fast chain that whole
sequence fits in under two seconds, and it read as nothing having happened
-- no sign the money moved, nothing to look up afterwards.

WHAT THIS IS NOT
It is not a delay. Slowing a finished trade down to make it feel weightier
would be theatre: the trade is already confirmed by then, and inventing a
wait would mean the screen was lying about what the chain was doing. The
confirmation itself is real and is not touched here -- EVM waits on
wait_for_transaction_receipt(), Solana polls getSignatureStatuses() until
the signature is confirmed or finalized -- so there is nothing to slow down
that would not be a fiction.

WHAT IT IS
Two honest things instead. While the server is holding for the chain, the
control says what is being waited on and keeps moving, so the wait reads as
work rather than as a hang. When it lands, the transaction the chain
accepted is printed with how long it took and a link into that chain's own
explorer -- which is the thing that actually makes a fast trade believable,
because it can be checked by someone who does not believe it.

The explorer addresses come from the same EVM_CHAINS entries the rest of
the app uses. A second list of explorers would be a way to send somebody
hunting for their transaction on the wrong network.

WHAT THIS MUST NOT BREAK
A bought trade may not leave the slider armed. The sheet lingers after a
purchase so the receipt can be read, and an armed "Slide to buy" sitting
under "Bought $X" for those seconds is an invitation to buy the same token
twice.
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


JS = open(REPO + '/static/live-market-pro.js', encoding='utf-8').read()
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
SOL = open(REPO + '/orcagent_solana.py', encoding='utf-8').read()

client = m.app.test_client()
html = client.get('/live-market').get_data(as_text=True)

# ── 1. the confirmation itself is real, and stays real ───────────────────
check('an EVM buy waits for the chain to accept it, rather than reporting '
      'success on submission', 'wait_for_transaction_receipt' in SRC)
check('a Solana trade waits for the signature to confirm, same reason',
      'def _confirm_transaction' in SOL and 'getSignatureStatuses' in SOL)
check('...and every Solana swap actually goes through that wait, rather '
      'than reporting the signature it just submitted',
      SOL.count('conf = _confirm_transaction(sig)') >= 2)
check('nothing was added that holds a finished trade back to make it feel '
      'slower -- the screen reports the chain, it does not pace it',
      'setTimeout' not in JS.split('function _slideRelease(')[1].split('\n}')[0])

# ── 2. the wait says what it is waiting on ───────────────────────────────
rel = JS.split('function _slideRelease(')[1].split('\nfunction ')[0]
check('sliding to confirm puts the control into an in-flight state instead '
      'of freezing on the last frame of the gesture',
      '_slideWorking(' in rel)
check('...which names the chain as what is being waited on',
      'Confirming on chain' in JS)
check('...and keeps moving, so the wait reads as work rather than a hang',
      '.pt-slide.working' in html and 'ptSweep' in html)
check('the in-flight state ends by itself when the answer arrives, rather '
      'than on a timer of its own',
      "e.wrap.classList.remove('working')" in JS
      and 'function _slideReset' in JS)

# A live sheet must not be overwritten with a vaguer word than it already
# shows: confirmBuy() writes "Buying…" into the same element, and did.
buy = JS.split('function confirmBuy(')[1]
check('the sheet keeps its own wording while a buy is in flight',
      re.search(r"if\(_sheetIdx === null\) btn\.textContent = 'Buying…';", buy)
      is not None)

# ── 3. the receipt ───────────────────────────────────────────────────────
check('a finished trade prints the transaction the chain accepted',
      'function _showTxReceipt' in JS)
check('...with how long the chain actually took, measured rather than '
      'asserted', '_tradeStartedAt' in JS and 'confirmed in ' in JS)
check('...as a link into that chain\'s own explorer, so it can be checked '
      'by someone who does not believe it',
      'PT_TX_EXPLORERS[t.chain]' in JS)
check('a trade that returned no transaction prints no receipt rather than '
      'an empty one', 'if(!hash) return;' in JS)

# every shape the four trade routes answer with
for field in ['tx_hash', 'tx', 'sig', 'signature']:
    check(f'the receipt reads a transaction sent back as {field}',
          'd.' + field in JS.split('function _showTxReceipt(')[1].split('\n}')[0])

# ── 4. the explorers come from the chains themselves ─────────────────────
check('the page is handed an explorer per chain by the server',
      'var PT_TX_EXPLORERS' in html)
found = re.search(r'var PT_TX_EXPLORERS = (\{.*?\});', html)
table = {}
if found:
    import json
    try:
        table = json.loads(found.group(1))
    except ValueError:
        table = {}
for chain in m.TOKEN_CHAINS:
    check(f'{m.chain_display_name(chain)} has an explorer to link to',
          bool(table.get(chain)))
check('the explorer addresses are derived from EVM_CHAINS rather than typed '
      'out a second time, so a link cannot send somebody to the wrong '
      'network', "EVM_CHAINS[c]['explorer']" in SRC)
for chain in m.EVM_CHAINS:
    check(f'...{m.chain_display_name(chain)} points at its own explorer',
          table.get(chain, '').startswith(m.EVM_CHAINS[chain]['explorer']))
check('a chain with no explorer configured is simply absent, rather than '
      'taking the whole page down with a KeyError',
      ".get('explorer')" in SRC)

# ── 5. what the receipt must not do ──────────────────────────────────────
check('a bought trade leaves the slider disarmed, so "Bought" never sits '
      'above a live "Slide to buy" while the sheet lingers',
      "_slideSetLabel('Bought')" in JS and 'var bought = false;' in JS)
check('a refused or failed buy still re-arms, so it can be retried without '
      'closing the sheet', '_restoreSlide();' in JS)
check('the previous trade\'s receipt is cleared when the sheet opens, so one '
      "token's transaction is never shown under another token's name",
      "var stale = document.getElementById('pt-txline');" in JS)
check('a sold position shows its transaction too',
      '_showTxReceipt(idx, t, d);' in JS.split('function handleSell(')[1])

# ── 6. the id the sheet borrows is looked up inside the sheet ────────────
# The card renders an empty #pt-buy-panel-<idx> of its own and the sheet's
# footer borrows that same id while open. A document-wide getElementById
# answers with whichever comes first -- the card's -- so the receipt was
# appended to a hidden leftover, the sheet never closed after a buy, and
# the ids drifted onto the wrong elements on the way out.
check('the borrowed ids are resolved within the sheet, not document-wide',
      "document.querySelector('#pt-sheet [id=\"' + id + '\"]')" in JS)
check('...including the footer the receipt is printed into',
      'function _sheetFooter' in JS
      and '_sheetFooter() || document.getElementById' in JS)
check('...and closing the buy screen closes the sheet the person is looking '
      'at, rather than hiding the card\'s already-hidden leftover',
      'String(_sheetIdx) === String(idx) && _sheetFooter()' in JS)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
