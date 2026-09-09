"""Moving off Railway silently turned three security settings off.

They were gated on RAILWAY_ENVIRONMENT -- a variable that only exists on
Railway. The day the app moved to another host that variable went away, and
with it:

  the Secure flag on the session cookie, so a browser would send it over
  plain http;
  the cookie domain, so www.orcagent.fun and orcagent.fun stopped sharing a
  login and a user was logged out simply by moving between them;
  the HSTS header.

Nothing errored. It just quietly got less safe, which is the failure mode
worth having a test for.

So the question is "is this production", not "is this Railway" -- and the
default is yes, because getting THAT wrong means Secure cookies on a local
http server, while getting it wrong the other way is a hole nobody notices.
"""
import ast
import os
import subprocess
import sys
import tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# ── no host's name decides a security setting any more ──
tree = ast.parse(SRC)
railway_reads = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and n.value == 'RAILWAY_ENVIRONMENT']
check('nothing is gated on RAILWAY_ENVIRONMENT any more — a setting that turns '
      'itself off when you change hosting provider is not a setting, it is a '
      'trap', not railway_reads)
check('the environment is decided once, by name', 'IS_PRODUCTION' in SRC)
check('...and the domain is configurable rather than baked in beside it',
      "os.getenv('PUBLIC_HOST'" in SRC)
check('the data directory follows DATA_DIR first, so it is not tied to one '
      "host's /data convention", "os.getenv('DATA_DIR'" in SRC)


# ── what the settings actually come out as ──
PROBE = r'''
import json, sys
import dashboard as d
print('__RESULT__' + json.dumps({
    'production':  bool(d.IS_PRODUCTION),
    'secure':      bool(d.app.config['SESSION_COOKIE_SECURE']),
    'name':        d.app.config.get('SESSION_COOKIE_NAME'),
    'domain':      d.app.config.get('SESSION_COOKIE_DOMAIN'),
    'httponly':    bool(d.app.config['SESSION_COOKIE_HTTPONLY']),
    'samesite':    d.app.config.get('SESSION_COOKIE_SAMESITE'),
    'data_dir':    d._DATA_DIR,
    'db':          d.DB_FILE,
}))
'''

from cryptography.fernet import Fernet


def run(extra_env):
    env = dict(os.environ)
    env.update({'ENCRYPTION_KEY': Fernet.generate_key().decode(),
                'SECRET_KEY': 'test-only'})
    env.pop('RAILWAY_ENVIRONMENT', None)
    env.pop('DEV', None)
    env.pop('PUBLIC_HOST', None)
    env.pop('DATA_DIR', None)
    env.update(extra_env)
    res = subprocess.run([sys.executable, '-c', PROBE], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=300)
    line = next((l for l in res.stdout.split('\n') if l.startswith('__RESULT__')), None)
    if not line:
        print(res.stdout[-2500:]); print(res.stderr[-2500:])
        return None
    import json
    return json.loads(line[len('__RESULT__'):])


# The exact situation after the move: no Railway variable anywhere.
off_railway = run({})
check('the probe ran with no Railway variable set at all', off_railway is not None)
if off_railway:
    check('OFF RAILWAY, the session cookie is still marked Secure. This is the '
          'regression: with the old gate it silently became False the moment '
          'the app left Railway', off_railway['secure'] is True)
    check('...the cookie is still named orca_s, so it does not collide with the '
          "old 'session' cookie", off_railway['name'] == 'orca_s')
    check('...and is still scoped to .orcagent.fun, so www and the bare domain '
          'share one login instead of logging the user out between them',
          off_railway['domain'] == '.orcagent.fun')
    check('HttpOnly and SameSite were never host-dependent and are unchanged',
          off_railway['httponly'] is True and off_railway['samesite'] == 'Lax')

# Local development, which is the one case that should NOT get Secure cookies.
dev = run({'DEV': '1'})
check('DEV=1 turns it off, so a local http server can still log in',
      dev and dev['secure'] is False)
check('...and leaves the cookie name and domain at Flask defaults, so a local '
      'session cannot be confused with a production one',
      dev and dev['domain'] is None)

# A different domain, without touching the code.
other = run({'PUBLIC_HOST': 'example.test'})
check('a different domain is a variable, not an edit',
      other and other['domain'] == '.example.test')
leading_dot = run({'PUBLIC_HOST': '.Example.Test'})
check('...and a leading dot or capitals in that variable are tolerated rather '
      'than producing an unusable "..example.test"',
      leading_dot and leading_dot['domain'] == '.example.test')

# Railway itself must keep working -- the old host is not broken by this.
still_railway = run({'RAILWAY_ENVIRONMENT': 'production'})
check('a deploy still on Railway behaves exactly as before',
      still_railway and still_railway['secure'] is True
      and still_railway['domain'] == '.orcagent.fun')


# ── the data directory ──
tmp = tempfile.mkdtemp()
moved = run({'DATA_DIR': tmp})
check('DATA_DIR decides where the database lives, so it can sit outside the '
      'checkout where a git pull cannot land on top of it',
      moved and moved['data_dir'] == tmp and moved['db'].startswith(tmp))

bad = run({'DATA_DIR': '/proc/nope/cannot/create'})
check('a DATA_DIR that cannot be created falls back to the app directory and '
      'says so, rather than failing to start — the app coming up somewhere is '
      'better than not coming up at all',
      bad and bad['data_dir'] != '/proc/nope/cannot/create')


# ── HSTS ──
hsts = [n for n in ast.walk(tree) if isinstance(n, ast.Constant)
        and isinstance(n.value, str) and 'Strict-Transport-Security' in n.value]
check('HSTS is still sent, now on the production flag rather than the host name',
      hsts and 'if IS_PRODUCTION:' in SRC)

# ── the worker assumption the trade locks depend on ──
start_sh = open(REPO + '/start.sh').read()
check('the app still runs as a SINGLE worker. The sell lock and the repeat-buy '
      'window added with the trade engine are in-process, so more than one '
      'worker would let a double-click through again — worth knowing before '
      'anyone tunes gunicorn on the new host',
      '--workers 1' in start_sh)


# ── the installer must survive being run twice ─────────────────────────────
# It says so at the top: "safe to run again". That was true of every step
# except the nginx one, which copied a plain-HTTP template over the file
# certbot had already rewritten with the certificate, then reloaded. On a site
# whose session cookie is Secure, dropping to HTTP means nobody can log in --
# so a re-run to pick up a code change would have taken the site down.
INSTALL = open(REPO + '/deploy/install.sh').read()

check('the installer protects the environment file, which holds the key every '
      'stored wallet depends on',
      'left untouched so your secrets are not overwritten' in INSTALL)
check("...and now protects certbot's nginx config the same way, instead of "
      'copying a plain-HTTP template over a certificate',
      "grep -q 'ssl_certificate'" in INSTALL
      and 'left untouched so certbot' in INSTALL)
check('...while still installing the template on a server that has no '
      'certificate yet, so a first run works',
      'nginx-orcagent.conf' in INSTALL and 'else' in INSTALL)
check('the template it installs is plain HTTP, which is why overwriting a '
      'certificate with it was destructive',
      'ssl_certificate' not in open(REPO + '/deploy/nginx-orcagent.conf').read())
check('rsync never reaches the data directory, so a deploy cannot touch the '
      'database', "--exclude '*.db'" in INSTALL and 'DATA_DIR=/data' in INSTALL)

README = open(REPO + '/deploy/README.md').read()
check('the deploy instructions do not point at a path that only existed in an '
      'example -- the clone lives wherever it was cloned, and /opt/orcagent is '
      'a copy install.sh overwrites',
      '/root/orcagent-src' not in README)
check('...and tell you to back the database up before deploying',
      '.backup /data/backups/pre-deploy-' in README)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
