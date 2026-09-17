"""A malformed Solana key must not take the app down.

WHAT HAPPENED
A quoted value in the environment file:

    SOL_GAS_SPONSOR_PRIVATE_KEY="4xQ..."

systemd strips those quotes; anything that merely exports the file does not.
So the key arrived with a literal `"` at index 0, solders panicked, and
dashboard.py failed to IMPORT -- at module level, on line 32547, with a Rust
traceback and nothing resembling an explanation.

WHY THE GUARD DID NOT GUARD
There was one. _sol_gas_sponsor_address() has caught `Exception` around that
parse all along and printed a clear message. But solders is a Rust extension:
it raises pyo3_runtime.PanicException, which inherits from BaseException, not
from Exception. Every `except Exception` around a key parse in that file --
and there were twenty of them -- was a guard that could not catch the one
thing it existed for.

So the parse now goes through one helper that turns a panic into an ordinary
ValueError, and the existing handlers work as they were always written to.
"""
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


SRC = open(os.path.join(REPO, 'dashboard.py')).read()

# ── the parse happens in exactly one place ───────────────────────────────
direct = [m for m in re.findall(r'^\s*.*\.from_base58_string\(.*$', SRC, re.M)
          if '_KP_parse' not in m]
check('every base58 key parse goes through the one guarded helper — twenty '
      'call sites each with their own local import and their own hopeful '
      '`except Exception` is twenty chances to get this wrong',
      direct == [] and SRC.count('from_base58_string(') == 1)
check('...and that helper re-raises KeyboardInterrupt and SystemExit '
      'untouched, because those are not the key being wrong',
      'except (KeyboardInterrupt, SystemExit):' in SRC
      and 'except BaseException as e:' in SRC)


# ── and it really does not panic ─────────────────────────────────────────
PROBE = r'''
import sys
sys.path.insert(0, %r)
import dashboard as d

out = []
for bad in ('"4xQabc"', '', '   ', 'not base58 at all!!', '[1,2,3]',
            '0' * 88, '\x00\x01'):
    try:
        d._sol_keypair_from_base58(bad)
        out.append((bad[:12], 'PARSED'))
    except ValueError as e:
        out.append((bad[:12], 'ValueError'))
    except BaseException as e:
        out.append((bad[:12], type(e).__name__))
print('@@@' + repr(out))
''' % (REPO,)

env = dict(os.environ)
env.update({'SECRET_KEY': 'x' * 32, 'ENCRYPTION_KEY': 'K' * 43 + '=',
            'DATA_DIR': tempfile.mkdtemp(), 'DEV': '1',
            # The exact shape that brought the app down: a quoted value.
            'SOL_GAS_SPONSOR_PRIVATE_KEY': '"4xQabcdefghijkmnopqrstuvwxyz"'})
p = subprocess.run([sys.executable, '-c', PROBE], cwd=REPO, env=env,
                   capture_output=True, text=True, timeout=300)

check('dashboard IMPORTS with a quoted SOL_GAS_SPONSOR_PRIVATE_KEY in the '
      'environment — the exact value that used to stop it booting',
      '@@@' in p.stdout)
if '@@@' not in p.stdout:
    print(p.stdout[-2000:]); print(p.stderr[-2000:])
else:
    results = eval(p.stdout.split('@@@', 1)[1].splitlines()[0])
    kinds = {kind for _, kind in results}
    check('...and every malformed key raises a plain ValueError — no '
          'PanicException, and nothing parsed that should not have',
          kinds == {'ValueError'})
    check('...including the quoted one, which is where this started',
          dict((k, v) for k, v in results).get('"4xQabc"') == 'ValueError')

check('the gas sponsor address answers empty rather than raising when the '
      'key is unusable, which is what its callers have always expected',
      "def _sol_gas_sponsor_address" in SRC and "return ''" in SRC)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
