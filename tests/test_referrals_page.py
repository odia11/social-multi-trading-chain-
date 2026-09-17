"""The referrals page names the people, not just the count.

"REFERRED USERS: 2" tells somebody that two people signed up and nothing
else: not who they are, not whether either of them ever traded, not which one
is actually worth the fee share. This drives the real page through Flask and
checks it answers all three.

The check that matters most is the last one. Earnings are joined on BOTH the
referred wallet and the referrer, so one referrer can never be shown what
another earned from the same person.
"""
import json
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


PROBE = r'''
import sqlite3, time
import dashboard as d

ME    = 'RefMe1111111111111111111111111111111111'
OTHER = 'RefOther22222222222222222222222222222222'
ALICE = 'ReferredAlice333333333333333333333333333'
BOB   = 'ReferredBob44444444444444444444444444444'
CAROL = 'ReferredCarol555555555555555555555555555'
THEIRS= 'ReferredByOther66666666666666666666666666'

conn = sqlite3.connect(d.DB_FILE)
conn.execute("INSERT OR IGNORE INTO users (wallet_address, referral_code, referral_balance) "
             "VALUES (?,?,?)", (ME, 'MYCODE12', 0.5))
conn.execute("INSERT OR IGNORE INTO users (wallet_address) VALUES (?)", (OTHER,))
for w, name in ((ALICE, 'alice'), (BOB, None), (CAROL, 'carol')):
    conn.execute("INSERT OR IGNORE INTO users (wallet_address, username, referred_by) "
                 "VALUES (?,?,?)", (w, name, ME))
# Referred by somebody else entirely -- must never appear on my page.
conn.execute("INSERT OR IGNORE INTO users (wallet_address, referred_by) VALUES (?,?)",
             (THEIRS, OTHER))

def earn(referrer, referred, amount):
    conn.execute("INSERT INTO referral_earnings (referrer_wallet, referred_wallet, "
                 "trade_fee_sol, earned_sol) VALUES (?,?,?,?)",
                 (referrer, referred, amount * 5, amount))

earn(ME, ALICE, 0.030)
earn(ME, ALICE, 0.010)      # two fees from one person
earn(ME, BOB,   0.010)
# The same referred wallet earning for a DIFFERENT referrer. Mine must not
# grow because of it.
earn(OTHER, ALICE, 5.0)
conn.commit(); conn.close()

d._authenticated_wallet = lambda: ME
c = d.app.test_client()
r = c.get('/referrals')
html = r.get_data(as_text=True)
import json as _json
print('@@@' + _json.dumps({'status': r.status_code, 'html': html}))
'''

from cryptography.fernet import Fernet                        # noqa: E402
env = dict(os.environ)
env.update({'ENCRYPTION_KEY': Fernet.generate_key().decode(),
            'SECRET_KEY': 'x' * 32, 'DATA_DIR': tempfile.mkdtemp(), 'DEV': '1'})
p = subprocess.run([sys.executable, '-c', PROBE], cwd=REPO, env=env,
                   capture_output=True, text=True, timeout=300)
if '@@@' not in p.stdout:
    print(p.stdout[-3000:]); print(p.stderr[-3000:])
    sys.exit('probe did not report')
R = json.loads(p.stdout.split('@@@', 1)[1].splitlines()[0])
HTML = R['html']

ALICE = 'ReferredAlice333333333333333333333333333'
BOB   = 'ReferredBob44444444444444444444444444444'
CAROL = 'ReferredCarol555555555555555555555555555'
THEIRS= 'ReferredByOther66666666666666666666666666'

check('the page renders', R['status'] == 200 and 'Your referrals' in HTML)

# ── who ──────────────────────────────────────────────────────────────────
check('each referred person is listed by the name they chose',
      'alice' in HTML and 'carol' in HTML)
check('...and one who chose no name is listed by a short wallet rather than '
      'a blank row', BOB[:4] in HTML)
check('every one of them has a button straight to their profile',
      all(f'/profile/{w}' in HTML for w in (ALICE, BOB, CAROL))
      and HTML.count('View profile') >= 3)

# ── how much, per person ─────────────────────────────────────────────────
check('what each person earned you is shown next to them — alice\'s two fees '
      'add up to 0.040, bob\'s single one is 0.010',
      '0.040000 SOL' in HTML and '0.010000 SOL' in HTML)
check('...and the total across them is shown once, at the top',
      'Earned from these users' in HTML and '0.050000 SOL' in HTML)
check('a referred user who has never traded still appears, at zero — those '
      'are the ones worth knowing about',
      'no trades yet' in HTML and '0.000000 SOL' in HTML)
check('...and a person who HAS traded says how many fees they generated',
      re.search(r'2 fees', HTML) is not None
      and re.search(r'1 fee\b', HTML) is not None)

# ── the bar ──────────────────────────────────────────────────────────────
widths = sorted(float(w) for w in re.findall(r'ppl-bar-fill" style="width:([\d.]+)%', HTML))
check('each person gets a bar proportional to their share of the total — '
      '0.040 and 0.010 of 0.050 is 80% and 20%',
      widths == [20.0, 80.0])
check('...and nobody at zero gets a bar at all, rather than an empty one',
      len(widths) == 2)

# ── the one that must never leak ─────────────────────────────────────────
check('somebody ELSE\'s referral does not appear on this page',
      THEIRS not in HTML)
check('...and the 5 SOL another referrer earned from MY referral is not '
      'counted as mine. The join is pinned to both wallets precisely so one '
      'referrer can never be shown another\'s earnings',
      '5.000000' not in HTML and '5.010000' not in HTML)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
