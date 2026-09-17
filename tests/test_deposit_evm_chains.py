"""The deposit card has to say which chain it means.

WHAT WENT WRONG
The EVM deposit tab was labelled "BSC" and its explorer link was hardwired to
BscScan -- while the address behind it is one shared EVM wallet that also
receives on Base, Arbitrum, Polygon and Robinhood Chain. So somebody funding
Base looked for a Base wallet, did not find one, and then checked the only
link offered and saw an empty page on the wrong chain.

That is not cosmetic. The address is identical on all five networks and the
NETWORK is what decides where the money lands, so a deposit card that names
one chain while meaning five is a card that can lose somebody their deposit.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


HTML = open(os.path.join(REPO, 'templates', 'wallet.html')).read()

# ── the tab ──────────────────────────────────────────────────────────────
check('the shared-EVM tab is labelled EVM, not after one of the five chains '
      'it covers',
      re.search(r'data-chain="bsc"[^>]*>EVM<', HTML) is not None
      and re.search(r'data-chain="bsc"[^>]*>BSC<', HTML) is None)

# ── the explorer ─────────────────────────────────────────────────────────
check('the explorer link is no longer hardwired to one chain',
      'id="dep-evm-scan"' in HTML
      and HTML.count('href="https://bscscan.com/address/') == 0)
check('...and a picker offers every chain this address really receives on',
      all(host in HTML for host in ('basescan.org', 'bscscan.com',
                                    'arbiscan.io', 'polygonscan.com',
                                    'robinhoodchain.blockscout.com')))
check('...with Base selected by default, because that is the chain a '
      'cross-chain trade is funded from',
      re.search(r'value="https://basescan\.org\|BaseScan" selected', HTML)
      is not None)
check('...and switching it rewrites both the link and its label, so the '
      'button never says one explorer and open another',
      "link.href = parts[0] + '/address/' + _bscAddr" in HTML
      and "link.textContent = 'View on ' + parts[1]" in HTML)
check('...reusing the address already on the page rather than a second copy '
      'of it that could drift', '_bscAddr' in HTML)

# ── the words around it ──────────────────────────────────────────────────
check('the note names all five chains, and says plainly that the network is '
      'what decides where the money lands',
      'Base, BNB Chain, Arbitrum, Polygon and Robinhood Chain' in HTML
      and 'the network decides where the money lands' in HTML)
check('the balances underneath say which chain they are from, instead of '
      'reading as the whole EVM side',
      'wlt-bsc-bal-scope' in HTML and '>On BNB Chain<' in HTML)

# ── and the Solana side is untouched ─────────────────────────────────────
check('the Solana tab still points at Solscan and still says SOL',
      'solscan.io/account/' in HTML
      and re.search(r'data-chain="sol"[^>]*>SOL<', HTML) is not None)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
