"""When somebody is signed out, the server has to be able to say why.

Four rounds of "I was logged out again" produced four different real causes:
an inactivity timer, a wallet-mismatch guard, a CSRF hole in the login chain,
and storage that does not cross into the installed app. Each was found by
reading code and guessing, because the server recorded nothing about any of
them.

The remembered-login path was the worst of it. It answers a caller with one
uniform silence for expired, revoked, unknown and malformed -- correct, so a
guesser cannot tell them apart -- and it gave the OPERATOR exactly the same
silence. The one fact worth having was thrown away at the same moment it was
produced.

So the answer is now written down, on the server, where it cannot leak: which
of the four it was, whether a token was even offered, when one is issued, and
-- loudest of all -- when something revokes them, since that is the only
thing that ends a session on devices other than the one asking.

And which code is running. The deployed copy has no .git, so _app_version()
always fell through to the time the process started: a fine cache-buster and
a useless answer to the first question of every support round.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
INSTALL = open(REPO + '/deploy/install.sh', encoding='utf-8').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''


def code(name):
    """The function with its comments gone and its split strings joined.

    Two traps this suite has fallen into repeatedly, and they meet here. A
    comment saying "one answer for expired, revoked, unknown" reads as the
    code distinguishing them; and a message written across two source lines
    ('...with no remembered ' 'login stored') is in the file but matches
    neither half. ast.unparse solves both at once: it drops comments and
    renders implicit concatenation as one literal.
    """
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.unparse(f)


# ── 1. the four refusals are distinguishable in the log ───────────────────
redeem = fn('_redeem_device_token')
for label, needle in (('no such token', 'no such token'),
                      ('revoked', 'was revoked'),
                      ('expired', 'expired')):
    check(f'a refused remembered login says "{label}" in the log',
          needle in redeem)
check('...and a successful resume is recorded too, so a quiet log means '
      'nothing tried rather than everything failing',
      'resumed' in redeem)

# The response must stay uniform. Distinguishing them to the CALLER is the
# thing this deliberately does not do.
resume = code('api_session_resume')
check('the ANSWER to the caller stays one message for every refusal — the '
      'log is for the operator, not a hint for whoever is guessing',
      resume.count('jsonify') == 2
      and 'no longer remembered' in resume
      and not any(w in resume for w in ('expired', 'revoked', 'no such')))

check('a browser that offers no token at all is a separate line, since '
      '"nothing stored" and "what it had was refused" are different problems '
      'with the same symptom',
      'no remembered login stored' in resume)

# ── 2. issuing and revoking ───────────────────────────────────────────────
check('issuing a remembered login is recorded', 'issued a remembered login' in fn('_issue_device_token'))
revoke = fn('_revoke_device_tokens')
check('revoking is the loudest line, being the only thing that signs a wallet '
      'out on devices other than the one asking',
      'REVOKED' in revoke and 'every' in revoke)
check('...and says HOW MANY were revoked, which is the difference between '
      '"this browser" and "everything, everywhere"',
      'rowcount' in revoke)
check('...counting only the ones it actually changed, not every row it has '
      'ever written for this wallet', 'revoked=0' in revoke)

# ── 3. no wallet is printed in full ───────────────────────────────────────
prints = re.findall(r"print\(f?'\[device-session\][^']*'", redeem + revoke
                    + fn('_issue_device_token') + resume)
bad = [p for p in prints if re.search(r'\{wallet\}|\{token\}|\{h\}', p)]
check('nothing in these lines prints a whole wallet or a token — a log is '
      'read by more people than a database', not bad)

# ── 4. which code is running ──────────────────────────────────────────────
ver = fn('_app_version')
check('the version comes from a stamped file first, because the deployed copy '
      'has no .git to ask', "'VERSION'" in ver and ver.index('VERSION') < ver.index('rev-parse'))
check('...git second, so running out of a clone still reports the commit',
      'rev-parse' in ver)
check('...and a timestamp only as a last resort, so a missing stamp still '
      'gives a fresh value per restart rather than pinning every browser to '
      'one cached copy', ver.rstrip().endswith('return str(int(_time.time()))'))
check('the deploy writes that stamp, from the clone, which is the only place '
      'that knows the commit',
      'rev-parse --short HEAD > "$APP_DIR/VERSION"' in INSTALL)
check('...and cannot fail the install if git is unavailable',
      re.search(r'VERSION"[^\n]*\|\| true', INSTALL))

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
