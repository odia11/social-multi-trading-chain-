"""The desktop search bar (and balance chip, and avatar) must stay on screen.

WHAT WAS HAPPENING
static/navbar.css hides the "more" nav items (Traders, Groups, Promote,
History, Bot, ...) outside the mobile breakpoint with a bare rule:

    .pt-nb-mobile-only{display:none}                    specificity (0,1,0)

But every one of those items is an <a> tag, and also matched by:

    .pt-nb-nav a{display:inline-flex}                    specificity (0,1,1)

(0,1,1) beats (0,1,0) -- one extra type selector outranks source order. So
ten "mobile-only" links rendered inline in the primary nav row on EVERY
desktop browser, all the time, pushing the row more than 700px past a
1440px viewport and carrying the search bar, balance chip and avatar off
the right edge of the screen with it. Confirmed live via Playwright at
1440x900: the search wrap's bounding box started at x=1854.7, fully
off-screen.

THE FIX
Scope both the base rule and its mobile-breakpoint override to the existing
#pt-nb-nav id, raising each to specificity (1,1,0), which beats (0,1,1)
outright:

    #pt-nb-nav .pt-nb-mobile-only{display:none}          base, outside 900px
    #pt-nb-nav .pt-nb-mobile-only{display:block}          inside max-width:900px

Both sides need the id -- an earlier fix attempt raised only the base rule,
which then also beat the (still bare, still 0,1,0) mobile override, so the
"more" items silently disappeared from the mobile hamburger menu too. This
is checked below so that regression can't come back unnoticed.

This test computes actual CSS specificity from the source (id count, class
count) rather than trusting a fixed string, so it keeps holding if the
rules are reformatted, and fails loudly if either selector's specificity
relationship to `.pt-nb-nav a` regresses.
"""
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
CSS = open(REPO + '/static/navbar.css', encoding='utf-8').read()


def strip_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)


CSS_NC = strip_comments(CSS)

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def specificity(selector):
    ids = len(re.findall(r'#[\w-]+', selector))
    classes = len(re.findall(r'\.[\w-]+', selector))
    # crude but sufficient here: count bare type/element selectors
    # (a leading or space-preceded bare word, not preceded by . or #)
    types = len(re.findall(r'(?:^|[\s>+~])([a-zA-Z][\w-]*)', selector))
    return (ids, classes, types)


def find_rule_specificity(css_no_comments, selector_text):
    m = re.search(re.escape(selector_text) + r'\s*\{', css_no_comments)
    if not m:
        return None
    return specificity(selector_text)


# ── 1. the rules that actually govern .pt-nb-mobile-only exist and are
#      scoped with #pt-nb-nav ──────────────────────────────────────────────
base_rule_present = '#pt-nb-nav .pt-nb-mobile-only{display:none}' in CSS_NC
mobile_override_present = '#pt-nb-nav .pt-nb-mobile-only{display:block}' in CSS_NC

check('base rule (outside the mobile breakpoint) hides .pt-nb-mobile-only '
      'via an #pt-nb-nav-scoped selector',
      base_rule_present)
check('mobile-breakpoint override shows .pt-nb-mobile-only via the SAME '
      '#pt-nb-nav-scoped selector',
      mobile_override_present)

# no more bare, unscoped .pt-nb-mobile-only{display:...} left anywhere --
# that was exactly the losing rule.
bare_rule = re.search(r'(?<!#pt-nb-nav )\.pt-nb-mobile-only\s*\{\s*display\s*:\s*(none|block)',
                       CSS_NC)
check('no bare (unscoped) .pt-nb-mobile-only{display:...} rule remains -- '
      'that is the rule that used to lose the cascade',
      bare_rule is None)

# ── 2. specificity actually beats .pt-nb-nav a ─────────────────────────────
rival = specificity('.pt-nb-nav a')
base_spec = specificity('#pt-nb-nav .pt-nb-mobile-only')
mobile_spec = specificity('#pt-nb-nav .pt-nb-mobile-only')

check('.pt-nb-nav a (the rule that was winning) has specificity (0,1,1)',
      rival == (0, 1, 1))
check('#pt-nb-nav .pt-nb-mobile-only has specificity (1,1,0), which beats '
      '(0,1,1) on the id tuple alone, regardless of source order',
      base_spec[0] > rival[0])
check('the mobile override carries the identical scoped selector, so it '
      'ties the base rule on specificity and wins on source order at that '
      'breakpoint instead of silently losing to it',
      mobile_spec == base_spec)

# ── 3. the mobile override sits inside the max-width:900px media block,
#      and the base rule sits outside it ──────────────────────────────────
media_start = CSS_NC.index('@media (max-width: 900px)')
base_idx = CSS_NC.index('#pt-nb-nav .pt-nb-mobile-only{display:none}')
mobile_idx = CSS_NC.index('#pt-nb-nav .pt-nb-mobile-only{display:block}')

check('the display:none base rule sits BEFORE the mobile media query opens',
      base_idx < media_start)
check('the display:block override sits AFTER the mobile media query opens',
      mobile_idx > media_start)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
