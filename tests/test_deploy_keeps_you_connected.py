"""A deploy must never sign anyone out of Phantom.

THE REQUIREMENT, IN THE OWNER'S WORDS
"als ik updates uitvoer en nieuwe updates deployd mag die niet disconnecten
met Phantom ter alle tijden" -- running updates and deploying new ones must
not disconnect Phantom, ever.

This has broken twice, in two completely different ways, and both were
invisible until a user complained:

  1. The signing key was generated next to dashboard.py, inside APP_DIR.
     install.sh syncs that directory with `rsync --delete` from a clone
     where .secret_key is gitignored and therefore absent, so every deploy
     deleted it. The next start generated a new one, and every signed
     session cookie in every browser became invalid at once.

  2. The remembered login (the device token that restores a session after
     the cookie is gone) was deleted by the browser on ANY failed resume --
     and a failure included "the request never reached the server", which is
     exactly what the few seconds of a service restart look like.

So this checks the thing itself rather than the parts: sign in, restart the
app the way a deploy does -- a brand new process, loading its key from disk
the way a fresh boot must -- and see whether the same browser is still
signed in.

WHAT IS DELIBERATELY NOT SET HERE
SECRET_KEY. Setting it in the environment would make this pass no matter
what, since every process would be handed the same key -- and hide the exact
regression that caused (1). The key has to come from DATA_DIR, which is the
one directory a redeploy does not touch.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
DATA = tempfile.mkdtemp()

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


WALLET = 'Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9'

# Each "boot" is a separate process: a fresh interpreter, a fresh import of
# dashboard, a fresh read of whatever is on disk. That is what a restart is.
BOOT = r'''
import json, os, sys
sys.path.insert(0, %(repo)r)
os.environ.update({'DATA_DIR': %(data)r,
                   'ENCRYPTION_KEY': 'K'*43 + '=', 'DEV': '1'})
os.environ.pop('SECRET_KEY', None)          # must come from DATA_DIR
import dashboard as d
out = {'key': d.app.secret_key.hex() if isinstance(d.app.secret_key, bytes)
                else str(d.app.secret_key)}
c = d.app.test_client()
%(body)s
print('@@' + json.dumps(out))
'''


def boot(body):
    src = BOOT % {'repo': REPO, 'data': DATA, 'body': body}
    r = subprocess.run([sys.executable, '-c', src], capture_output=True,
                       text=True, timeout=180)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    line = [l for l in r.stdout.splitlines() if l.startswith('@@')][-1]
    return json.loads(line[2:])


# ── boot 1: somebody connects their wallet ───────────────────────────────
first = boot('''
with c.session_transaction() as s:
    s['wallet'] = %(w)r
    s['user_id'] = d.get_or_create_user(%(w)r)
    s.permanent = True
out['cookie'] = next(ck.value for ck in c._cookie_jar
                     if ck.name == d.app.config.get('SESSION_COOKIE_NAME', 'session')) \
    if hasattr(c, '_cookie_jar') else ''
# The remembered login, issued exactly as a real sign-in issues it.
out['device_token'] = d._issue_device_token(d.get_or_create_user(%(w)r), %(w)r)
out['who'] = c.get('/api/session').get_json()
''' % {'w': WALLET})

check('a fresh install signs somebody in',
      first['who'].get('authenticated') and first['who'].get('wallet') == WALLET)
check('...and hands the browser a remembered login to come back with',
      len(first.get('device_token') or '') > 20)

# ── the deploy: a new process, exactly as systemctl restart gives you ────
second = boot('''
out['resume'] = None
''')

check('THE KEY SURVIVES THE RESTART — if it did not, every signed session '
      'cookie in every browser would be void at once, which is precisely '
      'what used to happen on every single deploy',
      second['key'] == first['key'])

# ── boot 3: the same browser comes back after the deploy ────────────────
third = boot('''
tok = %(tok)r
w, new = d._redeem_device_token(tok)
out['resumed_wallet'] = w
out['got_fresh_token'] = bool(new) and new != tok
''' % {'tok': first['device_token']})

check('the remembered login still works after the deploy, so a browser whose '
      'cookie did expire is signed straight back in rather than shown the '
      'connect screen',
      third['resumed_wallet'] == WALLET)
check('...and it is rotated on use, so the deploy does not leave a stale '
      'credential lying about',
      third['got_fresh_token'])

# ── the two mechanisms that make it true, guarded at their source ───────
INSTALL = open(REPO + '/deploy/install.sh', encoding='utf-8').read()
check('install.sh still excludes the signing key from the rsync --delete '
      'that overwrites the app directory',
      "--exclude '.secret_key'" in INSTALL)

SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
check('the key is loaded from DATA_DIR, the one directory a redeploy does '
      'not touch — not from beside dashboard.py, where a deploy erased it',
      '_load_secret_key(_DATA_DIR)' in SRC)

JS = open(REPO + '/static/dashboard.js', encoding='utf-8').read()
i = JS.index('async function _resumeFromDeviceToken()')
resume = JS[i:JS.index('\n}', i) + 2]
check('a resume that never reached the server does NOT throw the remembered '
      'login away — the seconds a deploy is restarting look exactly like that',
      'res.status === 401' in resume)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
