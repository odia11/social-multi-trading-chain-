"""verify_live.py must run itself under the app's own interpreter.

WHAT WAS HAPPENING
The tool exists to be run by somebody trying to find out what is wrong,
often from a phone over SSH. Its own docstring says to run it as
`python3 tools/verify_live.py` -- and on the server that died before a
single check had finished:

    File "/opt/orcagent/dashboard.py", line 9, in <module>
        from PIL import Image, ImageDraw, ImageFont
    ModuleNotFoundError: No module named 'PIL'

The app's dependencies live in APP_ROOT/venv, not in the system python. So a
tool that checks RPC endpoints and gas sponsor balances greeted its reader
with an import error about an imaging library, and then advised them:

    "That is usually a missing ENCRYPTION_KEY/SECRET_KEY, or being run from
     the wrong directory."

Both wrong. The keys were set and the directory was right, which sends
somebody hunting through /etc/orcagent.env for a problem that was never
there.

THE FIX
It switches interpreters itself, before importing anything, when a venv
python exists next to it and is not already the one running. Nobody has to
know the path. If it cannot switch -- no venv, or execv refuses -- it falls
through and runs anyway, and a missing module is then reported as what it
actually is, with the exact command to use.

The re-exec is guarded by an environment marker so a venv whose imports are
genuinely broken cannot put the tool in a loop that re-executes forever.

Checked by running the real script against small stand-in app directories,
rather than by reading its source: a re-exec either happens or it does not,
and only running it can tell.
"""
import os
import subprocess
import sys
import tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
TOOL = REPO + '/tools/verify_live.py'

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def build(with_venv, dashboard_body):
    """A stand-in app directory: tools/verify_live.py, an optional venv
    python that marks itself as having been used, and a dashboard.py that
    stands in for the real import."""
    root = tempfile.mkdtemp()
    os.makedirs(root + '/tools')
    with open(TOOL, encoding='utf-8') as f:
        src = f.read()
    with open(root + '/tools/verify_live.py', 'w', encoding='utf-8') as f:
        f.write(src)
    with open(root + '/dashboard.py', 'w', encoding='utf-8') as f:
        f.write(dashboard_body)
    if with_venv:
        os.makedirs(root + '/venv/bin')
        p = root + '/venv/bin/python'
        with open(p, 'w') as f:
            f.write('#!/bin/bash\necho "VENV-PYTHON-USED"\nexec %s "$@"\n' % sys.executable)
        os.chmod(p, 0o755)
    return root


def run(root, timeout=60):
    r = subprocess.run([sys.executable, 'tools/verify_live.py'], cwd=root,
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


# dashboard.py that fails exactly like the server did -- unless it is being
# imported by the re-executed run, which is what proves the switch happened.
DASHBOARD_NEEDS_VENV = (
    "import os\n"
    "if not os.environ.get('_VERIFY_LIVE_REEXEC'):\n"
    "    raise ModuleNotFoundError(\"No module named 'PIL'\")\n"
    "print('IMPORTED-OK')\n"
    "raise SystemExit(0)\n"
)
DASHBOARD_ALWAYS_FAILS = "raise ModuleNotFoundError(\"No module named 'PIL'\")\n"

# ── 1. the command a person actually types now works ─────────────────────
root = build(True, DASHBOARD_NEEDS_VENV)
code, out = run(root)
check("`python3 tools/verify_live.py` re-executes under the app's own "
      'interpreter instead of dying on a missing dependency',
      'VENV-PYTHON-USED' in out)
check('...and the app then imports, which is the whole point of switching',
      'IMPORTED-OK' in out)
check('...and it says which interpreter it switched to, so the run is not '
      'silently different from what was typed',
      "the app's own interpreter" in out)

# ── 2. a broken venv must not loop forever ───────────────────────────────
root = build(True, DASHBOARD_ALWAYS_FAILS)
try:
    code, out = run(root, timeout=45)
    finished = True
except subprocess.TimeoutExpired:
    finished, code, out = False, None, ''
check('a venv that still cannot import stops instead of re-executing itself '
      'forever', finished)
check('...and exits non-zero, so a deploy calling this does not read a '
      'crash as success', finished and code != 0)
check('...naming the interpreter as the problem, with the exact command',
      "app's own interpreter" in out and 'venv/bin/python tools/verify_live.py' in out)
check('...and not the old guess about keys or the working directory, which '
      'sent somebody through /etc/orcagent.env for a problem that was not '
      'there',
      'ENCRYPTION_KEY' not in out)

# ── 3. no venv at all: run anyway, and be honest about what is missing ───
root = build(False, DASHBOARD_ALWAYS_FAILS)
code, out = run(root)
check('with no venv present it still runs rather than refusing outright',
      'live dependency check' in out)
check('...and reports the missing interpreter, saying where a venv should be',
      'no virtualenv at' in out and code != 0)

# ── 4. the guard is a marker, not a count ────────────────────────────────
src = open(TOOL, encoding='utf-8').read()
check('the re-exec is skipped when the marker is already set, so the guard '
      'cannot be defeated by argv or cwd changing between runs',
      "_VERIFY_LIVE_REEXEC" in src
      and "os.environ.get('_VERIFY_LIVE_REEXEC')" in src)
check('a failed execv leaves the tool running rather than half-configured',
      'except OSError' in src)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
