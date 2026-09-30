"""The Terms of Service state the fees the app actually charges.

- A Fees section quotes FEE_RATE_TXN itself (0.75% per buy and per sell,
  1.5% for a round trip), so the Terms can never drift from the code.
- It lists what has no OrcAgent fee and what the network/providers charge.
- The version is bumped, so everyone who accepted the old Terms is asked
  to accept the new ones; the PDF copy includes the Fees section.
- The Fees page shows the same, including the 0% items.
"""
import os, re, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

tos = d._TOS_CONTENT_HTML
flat = ' '.join(tos.split())
pct = ('%.2f' % (d.FEE_RATE_TXN * 100)).rstrip('0').rstrip('.')
check('the Terms quote the live platform fee per buy and sell',
      '<h2>Fees</h2>' in tos and pct + '% of the amount of every buy' in flat and d.FEE_RATE_TXN == 0.0075)
check('...and the round-trip total', '1.5% in platform fees' in flat)
check('...and what is free', all(w in flat for w in ('deposits', 'withdrawals', 'tips', 'launching a token',
                                                     'creator rewards', 'token calls')))
check('...and that network / provider fees are not OrcAgent’s and gas fronting is repaid, not subsidised',
      'set by the blockchain or the provider' in flat and 'recovered from' in flat and 'it is not a subsidy' in flat)
check('the Terms use only headings and paragraphs (the PDF copy reads exactly those)',
      set(re.findall(r'<(\w+)', tos)) == {'h2', 'p'})
blocks = d._parse_tos_html_blocks(tos)
check('...so the PDF includes the Fees section', ('h2', 'Fees') in blocks)
check('the version is bumped from 1.0', d.TOS_VERSION != '1.0')

w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,?)', (uid, '1.0', '2026-09-01 10:00:00'))
c.commit(); c.close()
client = app.test_client()
BASE = 'https://orcagent.fun'
with client.session_transaction(base_url=BASE) as s:
    s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = 'x' * 40
st = client.get('/api/tos/status', base_url=BASE).get_json()
check('someone who accepted 1.0 is asked to accept the new Terms, with the Fees section shown',
      st['needs_acceptance'] and '<h2>Fees</h2>' in st['html'])

page = client.get('/info', base_url=BASE).get_data(as_text=True)
check('the Fees page shows the live rate and the 0% items',
      pct + '%' in page and 'What has no OrcAgent fee' in page and 'Token launch' in page)
check('...and its Terms section is the same text', '<h2>Fees</h2>' in page)
raise SystemExit(0 if all(checks) else 1)
