"""Live Market shows each thing once, and says what is true.

- A row of token circles above the feed repeated the first 14 tokens of the
  feed right below it (tap = scroll to the same card). Gone.
- Each card showed the buy/sell split twice: in its stats ("Buy / Sell 58% /
  42%") and again as a chip in its footer. The footer keeps what is not
  elsewhere: OrcAgent holders (only when there are any) and the txn count;
  "👥 0 friends" and "👤 0 on OrcAgent" are no longer shown.
- The header said "refreshes every 15s" while prices update every second.
- The bot card read "Bot is scanning · auto-buys on ≥5% breakout with these
  filters" for everyone: wrong with the bot off, and the bot buys on its own
  settings, not this feed's filters. It now shows the user's real bot state.
- Desktop navbar: with Calls (and Admin Console) the search box was squeezed
  to a sliver at 1280px. Icons return from 1400px, the search keeps 170px
  from 1280px, and narrower desktops get compact pills with a search that
  opens out while typing.
- Desktop Home showed a second logo, bell and two more search boxes under the
  navbar that already has them.
"""
import os, re, sys
ROOT = os.path.join(os.path.dirname(__file__), '..')
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

js, html = read('static', 'live-market-pro.js'), read('templates', 'live_market_pro.html')
check('no token circle row repeating the feed', 'pt-story-rail' not in js and 'pt-story-rail' not in html
      and 'renderStoryRail' not in js and 'data-action="story"' not in js)
card = js[js.index("'<div class=\"pt-card-ft\">'"):js.index("'<section class=\"pt-profile-about\"")]
check('the buy/sell split is shown once per card (stats), not again in the footer',
      'ratioStr' not in card and js.count("statRow('Buy / Sell'") == 1)
holders = js[js.index("/holders'"):js.index('function activateCard(')]
check('...the footer chips: holders only when there are any, txns only when there are any',
      'ratio' not in holders and "holders ? '<span class=\"pt-ft-chip\">" in holders and "txns ? '<span" in holders)
check('no "0 friends" chip', '0 friends' not in js)
check('an empty footer is hidden', '.pt-card-ft:not(:has(' in html)
check('the header no longer claims "refreshes every 15s"', 'refreshes every 15s' not in html
      and 'Live prices · update every second' in html)
check('the bot card is not hard-coded "Bot is scanning" / "≥5% breakout with these filters"',
      'Bot is scanning' not in html and 'breakout with these filters' not in html)
bot = js[js.index('function loadBotCard('):]
bot = bot[:bot.index('\n}\n')]
check('...it shows the user\'s real bot state', "fetch('/api/bot/status'" in bot and "'Your bot is on'" in bot
      and "'Your bot is off'" in bot and "classList.toggle('off', !running)" in bot and 'loadBotCard();' in js)

nav = read('static', 'navbar.css')
check('navbar icons come back only from 1400px', '@media (min-width:1400px){ .pt-nb-nav a .pt-nb-ic{display:block} }' in nav
      and '(min-width:1100px)' not in nav)
check('...the search keeps a readable width from 1280px', '@media (min-width:1280px){ .pt-nb-search-wrap{min-width:170px} }' in nav)
check('...and on narrower desktops opens out while typing',
      '.pt-nb-search-wrap:focus-within .pt-nb-search{position:absolute' in nav)
check('the stylesheet still has balanced braces', nav.count('{') == nav.count('}'))

hd = read('static', 'home-desktop.js')
check('desktop Home: no second logo, bell or search under the navbar',
      'oa-desk-brand' not in hd and 'oa-home-head-btn' not in hd and "icon('search')" not in hd
      and '#right-rail .rr-search{display:none}' in read('dashboard.html'))
raise SystemExit(0 if all(checks) else 1)
