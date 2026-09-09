"""Signing in FROM the app on the home screen.

THE DEAD END
An app added to the home screen cannot finish a wallet connection. It opens
Phantom's deeplink, Phantom hands back to Safari, and the session is created
over there -- inside a storage container this app cannot see. It starts the
login and never learns how it ended. So it used to give up and say "open the
site in Safari to connect your wallet", which is not a fix, it is the bug
written out as an instruction.

Carrying the login in at install time (the manifest's start_url) helps only
the person who installs it AFTER connecting. Anyone whose app is already on
their home screen is still stuck.

THE WAY ACROSS
The app starts the login carrying a pairing token of its own, and afterwards
asks the server who signed. The signature is still verified in exactly the
place it always was -- this only carries the ANSWER back to the side that
asked, which is the one thing the boundary was blocking.

WHAT THAT OBLIGES
The wallet written into a pairing comes from the branch that checked a
signature, never from anything a caller sends. Claiming is single-use.
"Not finished yet", "expired" and "never existed" are one answer, because
the app polls and must not be able to tell them apart.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
JS = open(REPO + '/static/dashboard.js').read()
CB = open(REPO + '/templates/phantom_callback.html').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''

# ── 1. the app no longer sends people away ────────────────────────────────
check('the home-screen app does not refuse to connect any more — telling '
      'someone to go and do it in Safari was the bug stated as an '
      'instruction, not a fix',
      'Open orcagent.fun in Safari' not in JS)
check('...it starts a pairing instead', 'api/pair/start' in JS)
# "'pair=' not in JS" was the first shape of this check, and it matched
# `const pair=` in the trading-pair code -- unrelated, and it would have gone
# on failing for a reason that had nothing to do with sign-in. What matters is
# narrower: the pairing token must never be built into a URL.
_urlish = [l.strip() for l in JS.split('\n')
           if '_pair' in l and re.search(r'location\.href|URLSearchParams|_cbUrl|encodeURIComponent', l)]
check('...and the pairing rides along inside the deeplink round trip rather '
      'than in a URL, so the token never reaches an address bar or a history '
      'entry',
      'JSON.stringify({pair:_pair})' in JS and not _urlish)

# ── 2. who signed is decided where signatures are checked ─────────────────
setter = fn('set_wallet')
check('a pairing is completed inside the wallet login',
      '_complete_pair(' in setter)
check('...AFTER the signature has been verified, so the wallet recorded is '
      'the one that was proved',
      setter.index('Signature verification failed') < setter.index('_complete_pair'))

completers = sorted(
    n.name for n in ast.walk(TREE)
    if isinstance(n, ast.FunctionDef)
    and n.name != '_complete_pair'
    and '_complete_pair(' in (ast.get_source_segment(SRC, n) or ''))
check('...and NOTHING else may complete a pairing. Every other caller would '
      'be a way to hand somebody a session for a wallet they never proved',
      completers == ['set_wallet'])

claim = fn('api_pair_claim')
check('claiming reads the wallet from the row the server wrote, never from '
      'the request — the token says which sign-in is being asked about, not '
      'who the asker is',
      '_claim_pair(' in claim
      and not re.search(r"\.get\(\s*['\"](wallet|address)['\"]", claim))
check('...and the session it opens is a real one, permanent, with any '
      'read-only flag cleared',
      'session.permanent = True' in claim and "session.pop('readonly'" in claim)
check('...which is immediately remembered, or the app is back here the next '
      'time iOS clears its storage', '_issue_device_token(' in claim)

# ── 3. the shape of the token itself ──────────────────────────────────────
claim_fn = fn('_claim_pair')
check('a pairing is single use', "SET claimed_at" in claim_fn
      and 'claimed_at IS NULL' in fn('_complete_pair'))
check('...expires', 'expires_at' in claim_fn and 'expires_at > ?' in fn('_complete_pair'))
check('...and answers "not yet", "expired" and "never existed" identically, '
      "since the app polls and must not be able to tell them apart",
      claim_fn.count("return ''") >= 2 and 'pending' in claim)
ttl = re.search(r'PAIR_TTL_SECONDS\s*=\s*(\d+)', SRC)
check('...and lives for minutes, not months — it carries one sign-in, it is '
      'not a login', ttl and int(ttl.group(1)) <= 3600)
check('only its hash is stored', '_hash_device_token(' in fn('_start_pair')
      and 'token_hash' in fn('_start_pair'))
check('starting and claiming are both rate limited, being unauthenticated '
      'endpoints on the way to a session',
      SRC.count('@rate_limit') and '@rate_limit' in
      SRC[SRC.index('def api_pair_start') - 220:SRC.index('def api_pair_start')]
      and '@rate_limit' in SRC[SRC.index('def api_pair_claim') - 220:SRC.index('def api_pair_claim')])

# ── 4. the answer actually gets picked up ─────────────────────────────────
check('the callback sends back which sign-in round this was, so the server '
      'can finish the pairing', 'token:token' in CB)
check('the app asks again when it becomes visible — coming back from Phantom '
      'does not reload the page, so nothing else would ever ask',
      "addEventListener('visibilitychange'" in JS
      and '_claimPairing()' in JS[JS.index("addEventListener('visibilitychange'"):][:700])
check('...and on a cold start too, before concluding nobody is signed in',
      JS.index('var _w = await _claimPairing();')
      < JS.index("orca_manual_disconnect') && !phantomKey"))
check('a claimed pairing is dropped rather than asked about forever',
      '_clearPairToken()' in JS[JS.index('async function _claimPairing'):][:1200])
check('every storage read and write is wrapped — private browsing throws',
      all('try{' in JS[JS.index('function ' + f):][:200]
          for f in ('_pairToken(', '_storePairToken(', '_clearPairToken(')))

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
