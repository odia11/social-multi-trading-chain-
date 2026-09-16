"""Desktop's home feed label used to be plain text -- "For You" in a <span>,
"Following" as a bare word next to it, no click handler on either. Mobile's
own re-skin of the same native .feed-tabs bar (home-mobile.js's feedTabs())
already forwarded clicks to the real .feed-tab[data-tab] buttons that
_feedTab() in dashboard.js actually switches on; desktop's addFeedLabel()
never did, so a desktop user could not reach the Following feed from here.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = open(REPO + '/static/home-desktop.js', encoding='utf-8').read()
CSS = open(REPO + '/static/home-desktop.css', encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

check('the label is built from real buttons, not plain text',
      "class=\"oa-home-feed-tab active\" data-feed=\"foryou\"" in JS
      and "class=\"oa-home-feed-tab\" data-feed=\"following\"" in JS)
check('a click on either button forwards to the native .feed-tab this app '
      'already switches on, the same forwarding trick home-mobile.js uses',
      "document.querySelector('.feed-tab[data-tab=\"'+b.dataset.feed+'\"]')" in JS
      and 'native.click()' in JS)
check('...and moves the active style to whichever was actually clicked',
      "x.classList.toggle('active',x===b)" in JS)
check('the native .feed-tabs bar is hidden on desktop, same as it already is '
      'on mobile -- otherwise this label just duplicates a second, working '
      'tab bar sitting right below it',
      'body.oa-home-desktop .feed-tabs{display:none!important}' in CSS)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
import sys
sys.exit(0 if all(c for _, c in checks) else 1)
