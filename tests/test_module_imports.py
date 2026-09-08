"""dashboard.py must actually import.

This exists because it did not. A startup helper was added that called
_free_bytes() a hundred lines before its def, so the module raised NameError
on import and the whole site went down -- while every other test passed,
because they all exec individual functions in isolation and cannot see the
order things are defined in.

So: import the real module, in a subprocess, with the environment it needs.
Nothing else catches this class of error."""
import os, subprocess, sys, tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

from cryptography.fernet import Fernet
env = dict(os.environ)
env.update({
    'ENCRYPTION_KEY': Fernet.generate_key().decode(),
    'SECRET_KEY': 'test-only-not-a-real-secret',
    # A throwaway data dir, so importing never touches a real database.
    'DATA_DIR': tempfile.mkdtemp(),
})

probe = (
    'import sys, traceback\n'
    'try:\n'
    '    import dashboard\n'
    '    print("__IMPORT_OK__")\n'
    'except BaseException as e:\n'
    '    print("__IMPORT_FAILED__", type(e).__name__, e)\n'
    '    for f in traceback.extract_tb(sys.exc_info()[2])[-4:]:\n'
    '        print("   ", f.filename.split("/")[-1] + ":" + str(f.lineno), (f.line or "").strip())\n'
)
res = subprocess.run([sys.executable, '-c', probe], cwd=REPO, env=env,
                     capture_output=True, text=True, timeout=300)
out = res.stdout + res.stderr
ok = '__IMPORT_OK__' in out

if not ok:
    print('\n'.join(l for l in out.split('\n') if '__IMPORT_FAILED__' in l or l.startswith('    ')))
check('dashboard.py imports without raising — if this fails the site is down, '
      'whatever every other test says', ok)

# The specific ordering that broke it, asserted directly so the fix cannot be
# quietly undone by moving the helpers back down the file.
SRC = open(REPO + '/dashboard.py').read()
def defpos(name):
    return SRC.index('\ndef %s(' % name)
for helper in ('_free_bytes', '_backup_files', '_prune_backups'):
    check('%s is defined before the startup check that calls it' % helper,
          defpos(helper) < SRC.index('\n_db_write_selftest()'))
check('...and before backup_database, which also uses them',
      defpos('_prune_backups') < defpos('backup_database'))

check('the startup self-test is still actually called', '\n_db_write_selftest()' in SRC)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
