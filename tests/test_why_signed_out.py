"""The sign-out diagnostic must not answer a question it cannot answer.

The first run of this cost a round trip: the log was searched for lines that
the deployed code does not yet write, came back empty, and empty read as "no
remembered login was refused". It was not a finding. It was the logging not
being there.

So the script leads with which commit is deployed, compares it against the
clone, and refuses to report "nothing revoked" when nothing is recording
revocations in the first place. "No" and "I cannot see" are different
answers, and a diagnostic that confuses them is worse than none: it produces
confident wrong conclusions.
"""
import os
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SH = open(REPO + '/tools/why_signed_out.sh', encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

# Comments quote the wording they explain, so match executable lines only.
CODE = '\n'.join(l for l in SH.split('\n') if not l.lstrip().startswith('#'))

# And the printed text wraps across source lines, so a sentence in the output
# matches neither half of it in the file. Collapse whitespace before looking
# for anything the person running this will actually read.
FLAT = re.sub(r'\s+', ' ', SH)

check('it exists and is runnable', os.access(REPO + '/tools/why_signed_out.sh', os.X_OK))

# ── 1. it says what is deployed, first ────────────────────────────────────
check('it reads the deployed commit from the VERSION stamp',
      'VERSION' in CODE and 'DEPLOYED' in CODE)
check('...and compares it with the clone, so "I deployed that" can be checked '
      'rather than assumed', 'rev-parse --short HEAD' in CODE)
check('...and says plainly when they differ',
      'NOT running the newest code' in FLAT)
check('...before it prints any log finding, since the finding is meaningless '
      'without it',
      CODE.index('DEPLOYED=') < CODE.index('device-session'))

# ── 2. it never turns "cannot see" into "no" ──────────────────────────────
check('an empty log is not reported as "nothing was refused" when the logging '
      'is not deployed', 'proves nothing' in FLAT)
check('...and the revocation question answers "cannot tell" rather than "no" '
      'in that case',
      'cannot tell' in FLAT
      and re.search(r'if \[ -z "\$DEPLOYED" \][\s\S]{0,400}?cannot tell', CODE))
check('...while a genuinely empty log, WITH the logging deployed, is reported '
      'as the finding it actually is: nothing asked to resume',
      'no browser asked to resume' in FLAT)

# ── 3. it is safe to run and to paste back ────────────────────────────────
check('read-only — it inspects and prints, and changes nothing',
      not re.search(r'\b(rm|mv|systemctl (start|stop|restart)|chown|chmod|>\s*/opt)\b', CODE))
check('...and asks for no secrets: it never reads the environment file',
      'orcagent.env' not in SH)
check('the window is a parameter, since "it happened an hour ago" is the '
      'normal case', 'MINS="${1:-' in CODE)
check('it ends by asking WHERE it happened — Safari, the installed app, or '
      "Phantom's browser are three separate storage areas and the answer "
      'decides where to look',
      'home screen' in FLAT and 'storage areas' in FLAT)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
