"""What that trade would be worth if you had held it.

The closed-trade card in the feed shows what happened. This adds the other
half, the one people actually talk about: those same tokens, at today's
price.

WHAT IT IS ALLOWED TO SAY
It is a hypothetical and is written as one. The figure is the notional value
of the tokens that were really sold -- the amount the app recorded, not an
estimate -- before whatever a sale today would cost. It is never called
profit, because none of it was made, and a card missing any of the three
numbers the sum needs (which token, how many, at what price) shows no line at
all. A card with no line says nothing; a card with a guessed line says
something false.

AND IT CUTS BOTH WAYS
Showing only the ones that ran up would be a machine for making people feel
stupid. When the price fell after the sale, selling was the right call, and
the card says so.

NOTHING NEW IS EXPOSED
The card already knows the token, the amount and the exit price -- they are
on it. The only thing fetched is today's price, which is a public fact about
a token and says nothing about whose trade it was.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
JS = open(REPO + '/static/dashboard.js', encoding='utf-8').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''

def jsfn(name):
    i = JS.index('function ' + name)
    depth, j, started = 0, i, False
    while j < len(JS):
        if JS[j] == '{':
            depth += 1; started = True
        elif JS[j] == '}':
            depth -= 1
            if started and depth == 0:
                return JS[i:j + 1]
        j += 1
    return JS[i:]

# ── 1. the price lookup ───────────────────────────────────────────────────
ep = fn('api_market_token_prices')
check('one request answers for many tokens, so a feed of closed trades does '
      'not cost a request per card', "','.join(stale)" in ep)
check('...capped at the 30 DexScreener accepts', 'len(wanted) >= 30' in ep)
check('...deduplicated, since the same token appears in several posts',
      # `in seen: continue` rather than `not in seen` -- the first version of
      # this looked for the wrong shape of the same, correct, logic.
      re.search(r'in seen:\s*\n\s*continue', ep) and 'seen.add(' in ep)
check('addresses are validated before any of them reaches a URL — this builds '
      'an outbound request from something a caller controls',
      '_SOLANA_ADDR_RE.match(a) or is_valid_evm_address(a)' in ep)
check('the DEEPEST pool sets the price, not whichever was listed first — a '
      'dead pool would quote a price the token does not really have',
      'liq > best[addr][0]' in ep)
ttl = re.search(r'_TOKEN_PRICE_TTL\s*=\s*(\d+)', SRC)
check('prices are cached per token, so overlapping feeds share what they have '
      'in common', '_token_price_cache' in ep and ttl and int(ttl.group(1)) <= 60)
check('...under a lock, since gunicorn serves this from several threads',
      '_token_price_lock' in ep)
check('a token whose price could not be fetched is simply absent from the '
      'answer, and its card leaves the line out',
      'except Exception' in ep and 'Better a missing line' in fn('api_market_token_prices'))

# ── 2. when the line appears at all ───────────────────────────────────────
card = jsfn('_renderTradeTerminalCard')
check('the line is only on a SELL — there is nothing counterfactual about a '
      'position still open', '!isBuy' in card and 'fumbleSlot' in card)
check('...and only when all three numbers are really recorded: which token, '
      'how many, and what they went for',
      re.search(r'_fbMint && _fbTokens > 0 && _fbExit > 0', card))

# ── 3. what it is allowed to say ──────────────────────────────────────────
line = jsfn('_fumbleLine')
check('a run-up is labelled as money NOT earned, so it cannot be read as '
      'profit', 'left on the table, not earned' in line)
check('...and the word profit is never used for it',
      'profit' not in line.lower())
check('a fall since the sale is shown as the sale having been right, rather '
      'than only ever rubbing in the ones that ran',
      'Selling saved' in line)
check('...and a move too small to mean anything says so instead of dressing '
      'up noise', 'about the same' in line.lower() and 'Math.abs(pct) < 2' in line)
check('the figure is the tokens actually sold, priced at today rate — not a '
      'guess, and not derived from the percentage',
      'tokens * now.price' in line and 'tokens * exitPrice' in line)

# ── 4. it costs the page little ───────────────────────────────────────────
hyd = jsfn('_hydrateFumbles')
check('every visible card is batched into as few requests as possible rather '
      'than one per card', 'i += 30' in hyd and 'batch.join' in hyd)
check('...and a token already fetched is not asked for again',
      '_fumbleCache[m]' in hyd)
check('...and each card is only hydrated once, however often the feed '
      'rerenders', 'fbDone' in hyd)

# ── 5. nothing new is exposed ─────────────────────────────────────────────
# The sum runs in the page, from numbers the card already shows. The server
# is only ever asked for a token price, which is a public fact and says
# nothing about whose trade it was -- so there is no endpoint that takes a
# trade id, and none that needs a permission check.
check('no endpoint computes this from a trade id, so the feature adds no way '
      'to ask the server about somebody else\u2019s trade',
      not re.search(r"/api/trade[^'\"]*fumble", SRC))
check('...and the price endpoint takes only mints — nothing that identifies a '
      'person or a position',
      "request.args.get('mints'" in ep
      and not re.search(r"request\.args\.get\('(?!mints)", ep))

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
