"""The Buy button, once a trade outlives the request that started it.

WHAT IS DIFFERENT ABOUT A CROSS-CHAIN BUY IN THE UI
A same-chain buy is one request: press, wait a moment, done. A cross-chain buy
comes back in seconds with the bridge still in flight and finishes minutes
later in a worker that has nothing to do with the page. So the page cannot own
the outcome; it can only follow it.

Which creates the failure this file mostly exists to prevent: the user
refreshes, the page has forgotten, and pressing Buy again starts a SECOND
trade on top of one that is already running. The trade id is written to
storage before polling starts and read back on load, so a refresh reconnects.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


CC = open(os.path.join(REPO, 'static', 'crosschain-buy.js')).read()
TC = open(os.path.join(REPO, 'static', 'token-card.js')).read()
PRO = open(os.path.join(REPO, 'static', 'live-market-pro.js')).read()
CSS = open(os.path.join(REPO, 'static', 'token-card.css')).read()


# ── it is actually loaded, on the page that is actually served ───────────
# live_market_pro.html is what /live-market renders. live_market.html is
# unrouted and kept on disk; wiring only that one would have looked complete
# and shipped nothing, which is how this was caught -- by driving the real
# page in a browser rather than by reading the template that sounded right.
for tpl in ('live_market_pro.html', 'live_market.html', 'token.html'):
    page = open(os.path.join(REPO, 'templates', tpl)).read()
    check(f'{tpl} loads the cross-chain module beside the buy panel',
          'crosschain-buy.js' in page)
    check(f'{tpl} ...cache-busted with the app version, so a deploy does not '
          f'leave a stale copy following trades with old logic',
          re.search(r'crosschain-buy\.js\?v=\{\{\s*app_version\s*\}\}', page) is not None)


# ── the quote shows what the user is agreeing to ─────────────────────────
check('every BUY is priced now, on every chain — the breakdown used to appear '
      'on EVM only, which is the version a user cannot learn to trust',
      "if(_lmtdSide !== 'buy'){" in TC and "!_tcIsEvm(chain) || _lmtdSide !== 'buy'" not in TC)

for label, needle in (
        ('the amount', 'You spend at most'),
        ('the route, source to destination', 'lmtd-quote-route'),
        ('how long the bridge is expected to take', 'estimated_time_seconds'),
        ('what it actually buys', 'Buys</span>')):
    check(f'the quote shows {label}', needle in TC)

check('the cost rows cover the bridge fee, the network fees and the OrcAgent '
      'fee by name rather than as one lump',
      all(k in TC for k in ('bridge_fee', 'source_gas', 'destination_gas',
                            'platform_fee')))

check('a route needing native gas says so IN THE QUOTE, with the token, the '
      'amount and what the wallet actually holds — before the button is '
      'pressed, not after the money has moved',
      'native_gas_required' in TC and 'estimated_native_gas' in TC
      and 'to pay the network for this transfer' in TC)
check('...and calls it an estimate rather than an exact figure',
      'This is an estimate, not an exact' in TC)
check('...and says plainly that OrcAgent does not cover it',
      'OrcAgent does not pay it for you' in TC)


# ── the same, on the Live Market panel (the busiest buy surface) ────────
check('the Live Market quote box shows the route when a trade has to bridge',
      'PT_CHAIN_NAMES' in PRO and "'<div class=\"pt-quote-row\"><span>Route</span>" in PRO)
check('the Live Market quote shows what is GUARANTEED to arrive next to what '
      'is expected — the gap between them is the bridge\'s own slippage, and a '
      'user is entitled to it before agreeing rather than after',
      'bridge_minimum_out_usd' in PRO and 'Guaranteed minimum' in PRO
      and 'bridge_expected_out_usd' in PRO)
check('...and the token card shows the same two numbers',
      'bridge_minimum_out_usd' in TC and 'Guaranteed minimum' in TC)
check('...both taken as dollars from the server, never converted in the '
      'browser: the raw amount needs the destination stable\'s decimals, and '
      'those differ per chain (BSC USDC is 18, everyone else 6), so a client '
      'doing that conversion can be wrong by a factor of a trillion',
      'bridge_minimum_out_raw' not in PRO and 'bridge_minimum_out_raw' not in TC)
check('...and the native-gas requirement, with the amount and what is held',
      'native_gas_required' in PRO and 'estimated_native_gas' in PRO
      and 'OrcAgent does not pay it for you' in PRO)
check('...and the quote remembers that it bridges, because that cannot be '
      'worked out from the token\'s chain alone — it depends on where THIS '
      "user's dollars are, which only the server knows",
      'bridge: !!d.bridge_required' in PRO)
check('...so confirming a bridged buy goes to the follower rather than the '
      'one-response then()-chain, which would have to call it bought or '
      'failed while it is still neither',
      'window.OrcaCrossChain.execute(q.id' in PRO)
check('...and a same-chain buy on that panel is untouched',
      "if(isEvm && q && q.id && q.amt === amt && q.expiresAt > Date.now()){" in PRO)


# ── pressing Buy on a cross-chain quote ──────────────────────────────────
check('a cross-chain buy executes the quote the user was just shown, by its '
      'quote_id — not a fresh one at a price they never saw',
      'q.bridge_required' in TC and 'q.quote_id' in TC
      and 'OrcaCrossChain.execute(q.quote_id' in TC)
check('...and refuses to start when the quote already said native gas is '
      'missing, rather than letting the server say no a second later',
      'if(q.native_gas_required){' in TC)
check('...while a same-chain buy is left exactly as it was',
      'executeTrade(sym, pairAddr, _lmtdSide, amount, addr, btn, chain);' in TC)

check('the execute call sends only the quote id, so the server\'s own '
      'idempotency key (the quote) is what stops a double press becoming two '
      'bridges', "JSON.stringify({ quote_id: quoteId })" in CC)
check('NATIVE_GAS_REQUIRED coming back from the server is shown as its own '
      'answer rather than a generic failure', "d.code === 'NATIVE_GAS_REQUIRED'" in CC)


# ── the part that survives a refresh ─────────────────────────────────────
check('the trade id is written to storage BEFORE polling starts, so a refresh '
      'one second later still finds it',
      re.search(r'remember\(tradeId, meta\);\s*\n\s*poll\(tradeId\)', CC) is not None)
check('a page load reconnects to the trade already running instead of leaving '
      'the user to press Buy again', 'function resume()' in CC
      and "addEventListener('DOMContentLoaded', resume)" in CC)
check('...and watching a trade already being watched is a no-op, so a second '
      'render cannot start a second poll loop',
      'if (_watching === tradeId) return;' in CC)
check('storage failures do not break the trade — a private window still gets '
      'the progress panel, it just cannot reconnect after a refresh',
      'catch (e) { /* private window' in CC)
check('a trade the server no longer recognises is dropped rather than polled '
      'forever', 'stop(); forget(); return;' in CC)
check('a failed poll is retried, because a network blip says nothing about '
      'the trade', 'POLL_MS * 2' in CC)


# ── the seven steps ──────────────────────────────────────────────────────
for label in ('Preparing route', 'Waiting for signature', 'Sending from',
              'Bridging', 'Funds arrived', 'Buying token', 'Complete'):
    check(f'the progress UI has a step for "{label}"', label in CC)

check('the stepper is driven by the SAME states the engine uses, so the '
      'picture and the database cannot disagree',
      all(s in CC for s in ('AWAITING_SOURCE', 'BRIDGING', 'DEST_RECEIVED',
                            'SWAPPING', 'CONFIRMING', 'COMPLETED')))
check('an unknown state shows as "not started" rather than as nearly done — '
      'guessing forward is how a user is told a trade finished that did not',
      'An unknown state is not progress' in CC)
check('MANUAL_REVIEW and REFUNDED are terminal but are NOT successes, and the '
      'UI keeps them apart from COMPLETED',
      "BAD = ['FAILED', 'CANCELLED', 'MANUAL_REVIEW']" in CC
      and 'REFUNDED' in CC and 'are NOT successes' in CC)
check('...and a trade parked for review tells the user their money is still '
      'reserved rather than leaving them to guess',
      'still reserved while this is checked' in CC)

check('closing the panel hides it and does NOT cancel the trade, which is '
      'still running', 'is not cancelling a trade' in CC)
check('the panel is fixed to the corner, not inside the buy modal — the modal '
      'closes and the trade does not',
      '.cc-progress{position:fixed' in CSS)
check('...and it is usable on a phone', '@media (max-width:520px)' in CSS
      and '.cc-progress{left:12px' in CSS)
check('the only animation respects a reduced-motion preference',
      'prefers-reduced-motion' in CSS)


# ── it cannot leak or spend ──────────────────────────────────────────────
check('the module sends the CSRF token like every other mutating call',
      "'X-CSRF-Token'" in CC)
check('...and never touches a key, a seed or a signature',
      not any(w in CC for w in ('privateKey', 'private_key', 'mnemonic',
                                'seed', 'signTransaction')))
check('...and the only endpoints it talks to are the engine\'s own',
      sorted(set(re.findall(r"fetch\('([^']+)", CC)))
      == ['/api/trade/execute', '/api/trade/status/'])

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
