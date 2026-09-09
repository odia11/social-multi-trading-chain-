"""Every deploy logged everyone out.

WHAT WAS HAPPENING
The key that signs login sessions was written next to dashboard.py, inside
$APP_DIR. install.sh syncs that directory with `rsync --delete` from the git
clone, and .secret_key is gitignored — so it is absent from the source, and
rsync deleted it on every deploy. The next start generated a fresh key, which
invalidated every signed session in every browser at once. Every user was
logged out and had to reconnect their wallet, every single deploy, and
nothing anywhere said why.

TWO CHANGES, BOTH NEEDED
The key now lives in DATA_DIR, the one directory a redeploy does not touch.
And install.sh excludes it, which protects installs that still have one in
the old place — and is what makes the migration possible at all: without the
exclusion the old key is deleted before the app ever runs, so moving to the
new location would itself log everyone out one final time.

These checks RUN the loader rather than reading it, because "the same key
comes back" is the entire claim and a string match cannot show it.
"""
import ast
import os
import stat
import sys
import tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


LOADER = ast.get_source_segment(
    SRC, next(n for n in ast.walk(TREE)
              if isinstance(n, ast.FunctionDef) and n.name == '_load_secret_key'))


def load(data_dir, app_dir, env=None):
    """Run the real loader with a fabricated app directory."""
    old = os.environ.get('SECRET_KEY')
    if env is None:
        os.environ.pop('SECRET_KEY', None)
    else:
        os.environ['SECRET_KEY'] = env
    try:
        ns = {'os': os, '__file__': os.path.join(app_dir, 'dashboard.py')}
        exec(LOADER, ns)
        return ns['_load_secret_key'](data_dir)
    finally:
        os.environ.pop('SECRET_KEY', None)
        if old is not None:
            os.environ['SECRET_KEY'] = old


with tempfile.TemporaryDirectory() as tmp:
    data, app = os.path.join(tmp, 'data'), os.path.join(tmp, 'app')
    os.makedirs(data); os.makedirs(app)

    # ── the environment always wins ──
    check('SECRET_KEY in the environment beats any file, so an operator can '
          'pin it somewhere that survives losing the disk too',
          load(data, app, env='from-the-env') == b'from-the-env')
    check('...and setting it writes nothing, leaving no second copy to go stale',
          not os.path.exists(os.path.join(data, '.secret_key')))

    # ── first run generates one, in DATA_DIR ──
    k1 = load(data, app)
    check('with nothing configured a key is generated', len(k1) == 32)
    check('...in DATA_DIR, which a redeploy does not touch — this is the fix',
          os.path.exists(os.path.join(data, '.secret_key')))
    check('...and not in the app directory, which is what rsync --delete wipes',
          not os.path.exists(os.path.join(app, '.secret_key')))
    check('...readable only by the user that owns it, since it signs every '
          'session there is',
          stat.S_IMODE(os.stat(os.path.join(data, '.secret_key')).st_mode) == 0o600)

    # ── the point of the whole exercise ──
    check('a second start returns the SAME key, which is what keeps everyone '
          'logged in across a deploy', load(data, app) == k1)

with tempfile.TemporaryDirectory() as tmp:
    data, app = os.path.join(tmp, 'data'), os.path.join(tmp, 'app')
    os.makedirs(data); os.makedirs(app)
    legacy = os.path.join(app, '.secret_key')
    with open(legacy, 'wb') as f:
        f.write(b'the-key-everyone-is-signed-with')

    migrated = load(data, app)
    check('an existing key in the OLD place is moved, byte for byte — its whole '
          'value is being the same key as yesterday',
          migrated == b'the-key-everyone-is-signed-with')
    check('...so nobody is logged out by the fix itself',
          open(os.path.join(data, '.secret_key'), 'rb').read()
          == b'the-key-everyone-is-signed-with')
    check('...and the old copy is removed rather than left to be found again',
          not os.path.exists(legacy))
    check('...with the same tight permissions as a freshly generated one',
          stat.S_IMODE(os.stat(os.path.join(data, '.secret_key')).st_mode) == 0o600)

with tempfile.TemporaryDirectory() as tmp:
    app = os.path.join(tmp, 'app'); os.makedirs(app)
    unwritable = os.path.join(tmp, 'nope', 'deeper')   # parent does not exist
    k = load(unwritable, app)
    check('a key that cannot be stored still lets the app start, rather than '
          'taking the site down over it', len(k) == 32)

check('...and says so loudly, because silently regenerating it every restart '
      'is exactly the bug this file is about',
      'COULD NOT SAVE the session key' in LOADER and 'SECRET_KEY' in LOADER)
check('the migration announces itself too, so the one-off move is visible in '
      'the journal rather than mysterious',
      'moved the session key out of the app directory' in LOADER)

# ── the deploy must stop deleting it ──────────────────────────────────────
INSTALL = open(REPO + '/deploy/install.sh').read()
check('install.sh excludes the key from the delete-sync — without this the '
      'old one is gone before the migration can ever run',
      "--exclude '.secret_key'" in INSTALL)
check('...on the rsync path, which is the one that has --delete',
      "--delete" in INSTALL
      and INSTALL.index('--delete') < INSTALL.index("--exclude '.secret_key'"))

# ── and the assignment has to see DATA_DIR ────────────────────────────────
check('the key is loaded where DATA_DIR is already known, so there is one '
      'answer to where persistent state lives',
      'app.secret_key = _load_secret_key(_DATA_DIR)' in SRC
      and SRC.index('_DATA_DIR    = (os.getenv')
          < SRC.index('app.secret_key = _load_secret_key(_DATA_DIR)'))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
