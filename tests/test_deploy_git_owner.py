"""The deploy must not leave the repository unpullable.

WHAT WENT WRONG
deploy/update.sh needs sudo -- it writes /opt, /data and calls systemctl.
It also pulls. So the pull ran as root, and root's pull creates directories
under .git/objects owned by root. From the next deploy onwards the person who
owns the clone could not pull at all:

    error: insufficient permission for adding an object to repository
    database .git/objects
    fatal: failed to write object
    fatal: unpack-objects failed

A deploy script that breaks the repository it deploys from, one deploy later.

TWO THINGS ARE REQUIRED
Stop causing it: anything git runs as the clone's owner, never as root.
And undo it: a clone already poisoned cannot pull the fix that repairs it, so
the repair has to happen without the owner's help -- which means the deployed
script must heal the damage an older version of itself did.

The reproduction below is real: a clone is poisoned exactly the way a root
pull poisons one, the failure is confirmed to happen, and then the block from
update.sh is run against it.
"""
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
UPDATE = open(REPO + '/deploy/update.sh').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# Comments explain the bug at length, and every phrase below appears in them.
# Matching against those would be matching against my own prose, so the script
# is stripped to executable lines first.
CODE = '\n'.join(l for l in UPDATE.split('\n')
                 if not l.lstrip().startswith('#'))

# ── 1. the script never runs git as root ──────────────────────────────────
check('git is routed through one helper rather than called directly, so there '
      'is a single place that decides who runs it',
      'git_repo()' in CODE)
check('...which drops from root to the account that owns the clone',
      re.search(r'git_repo\(\)\s*\{[^}]*runuser -u "\$REPO_OWNER"', CODE, re.S))
check('...and the owner is read off the clone, not assumed',
      "REPO_OWNER=" in CODE and "stat -c '%U'" in CODE)

stray = [l.strip() for l in CODE.split('\n')
         if re.search(r'(^|[;&|(]\s*)git\s+(-C\s+\S+\s+)?(pull|fetch|checkout|reset|merge)\b', l)
         and 'git_repo' not in l and 'printf' not in l and 'echo' not in l]
if stray:
    print('   still calling git directly: ' + ' | '.join(stray))
check('no git command that writes to the repository is left calling git '
      'directly — those would run as root and cause it all over again',
      not stray)

check('the instructions it prints do not tell anyone to run git under sudo '
      'either, which is how a clone gets poisoned by hand',
      not re.search(r'sudo\s+git\b', UPDATE))

# ── 2. it repairs a clone an older version already broke ──────────────────
check('a clone poisoned by an earlier deploy is repaired rather than merely '
      'not re-poisoned — its owner cannot pull the fix that would repair it',
      'chown -R "$REPO_OWNER:$REPO_GROUP"' in CODE and '-user root' in CODE)
check('...and the repair is checked for before it is done, so a healthy clone '
      'pays nothing and stays silent',
      re.search(r'if .*-user root -print -quit.*then', CODE))
check('...and it runs before the pull, which is the thing it unblocks',
      CODE.index('-user root') < CODE.index('git_repo pull'))

# ── 3. run it. ────────────────────────────────────────────────────────────
# Everything above reads the script. This part poisons a real clone, confirms
# the real failure, and then runs the real block against it.
def _have_user(name):
    try:
        pwd.getpwnam(name); return True
    except KeyError:
        return False

OWNER = next((u for u in ('tstuser', 'nobody') if _have_user(u)), None)

if os.geteuid() != 0 or OWNER is None or not shutil.which('runuser'):
    print('SKIP  the live reproduction needs root and an unprivileged account')
else:
    def run(*a, **kw):
        return subprocess.run(a, capture_output=True, text=True, **kw)
    def asuser(*a):
        return run('runuser', '-u', OWNER, '--', *a)

    # Under the owner's home: a temp dir may sit under a /tmp that the
    # unprivileged account cannot even traverse, which fails for the wrong
    # reason and looks like the bug being fixed.
    home = pwd.getpwnam(OWNER).pw_dir
    W = os.path.join(home if os.path.isdir(home) else '/home', 'orcagent-deploy-test')
    shutil.rmtree(W, ignore_errors=True)
    os.makedirs(W)
    shutil.chown(W, OWNER, OWNER)
    os.chmod(W, 0o755)
    origin, clone = os.path.join(W, 'origin.git'), os.path.join(W, 'clone')

    # EVERY setup step runs as the owner. git refuses to operate on a
    # repository owned by someone else ("dubious ownership"), so a single
    # root-run git in here fails for a reason that has nothing to do with
    # what is being tested.
    def commit(where, text, message):
        asuser('sh', '-c', f'printf %s {text!r} > {os.path.join(where, "f")}')
        asuser('git', '-C', where, 'add', 'f')
        return asuser('git', '-C', where, '-c', 'user.email=a@b',
                      '-c', 'user.name=a', 'commit', '-qm', message)

    asuser('git', 'init', '-q', '-b', 'main', '--bare', origin)
    asuser('git', 'clone', '-q', origin, clone)
    commit(clone, 'one', 'one')
    asuser('git', '-C', clone, 'push', '-q', 'origin', 'main')
    asuser('git', '-C', clone, 'branch', '-q', '--set-upstream-to=origin/main', 'main')

    # A newer commit for it to pull.
    sender = os.path.join(W, 'sender')
    asuser('git', 'clone', '-q', origin, sender)
    commit(sender, 'two', 'two')
    asuser('git', '-C', sender, 'push', '-q', 'origin', 'main')

    started = open(os.path.join(clone, 'f')).read().strip()
    check('the reproduction starts from a working clone, or nothing below '
          'means anything', started == 'one')

    # Poison it the way a root pull does. It is not the object FILES that lock
    # the owner out -- it is the DIRECTORIES git has to create new objects in.
    objects = os.path.join(clone, '.git', 'objects')
    shutil.chown(objects, 'root', 'root')
    shutil.chown(os.path.join(objects, 'pack'), 'root', 'root')

    before = asuser('git', '-C', clone, 'pull', '--ff-only')
    check('a clone poisoned this way really does lock its owner out — the bug '
          'this repairs is reproduced, not assumed',
          'insufficient permission for adding an object' in before.stderr)

    # ── the block from update.sh, run for real ──
    script = f'''
      set -eu
      REPO_DIR={clone}
      REPO_OWNER="$(stat -c '%U' "$REPO_DIR/.git")"
      REPO_GROUP="$(stat -c '%G' "$REPO_DIR/.git")"
      git_repo(){{ if [ "$REPO_OWNER" != root ] && id -u "$REPO_OWNER" >/dev/null 2>&1; then
          runuser -u "$REPO_OWNER" -- git -C "$REPO_DIR" "$@"
        else git -C "$REPO_DIR" "$@"; fi; }}
      if [ "$REPO_OWNER" != root ] && [ -n "$(find "$REPO_DIR/.git" -user root -print -quit 2>/dev/null)" ]; then
        chown -R "$REPO_OWNER:$REPO_GROUP" "$REPO_DIR/.git"
      fi
      git_repo pull --ff-only
    '''
    done = run('bash', '-c', script)
    check('...and the deploy pulls through it successfully',
          done.returncode == 0 and open(os.path.join(clone, 'f')).read().strip() == 'two')

    left = run('find', os.path.join(clone, '.git'), '-user', 'root')
    check('...leaving nothing under .git owned by root',
          left.stdout.strip() == '')

    # The point of the whole exercise: a normal `git pull` works again.
    commit(sender, 'three', 'three')
    asuser('git', '-C', sender, 'push', '-q', 'origin', 'main')
    after = asuser('git', '-C', clone, 'pull', '--ff-only')
    check('...so the owner can pull by hand again, without sudo — which is the '
          'whole point, and what was broken on the server',
          after.returncode == 0
          and open(os.path.join(clone, 'f')).read().strip() == 'three')

    shutil.rmtree(W, ignore_errors=True)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
