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
check('...and what is free', all(w in flat for w in ('deposits', 'withdrawals', 'tips', 'token calls'))
      and 'OrcAgent charges no launch fee ($0)' in flat)
share = ('%g' % (d.ORCAGENT_CREATOR_FEE_BPS / 100))
check("...and OrcAgent's share of new tokens' creator fees: 20% of creator fees, not of volume, creator keeps 80%",
      d.ORCAGENT_CREATOR_FEE_BPS == 2000 and share == '20'
      and 'the creator earns 80% of the token\'s creator fees, and OrcAgent\'s platform fee is the other 20%' in flat
      and 'The platform fee is 20% of the creator fees, not 20% of trading volume' in flat
      and 'Tokens launched before 30 September 2026 have no platform fee' in flat
      and 'neither does a Holder Rewards token' in flat)
check('the Terms state OrcAgent is independent and name third-party protocols and infrastructure',
      '<h2>Third-party protocols and infrastructure</h2>' in tos and 'OrcAgent is an independent platform' in flat)
check('no launch-protocol branding in the public Terms', 'pump' not in flat.lower())
check('...and that network / provider fees are not OrcAgent’s and gas fronting is repaid, not subsidised',
      'set by the blockchain or the provider' in flat and 'recovered from' in flat and 'it is not a subsidy' in flat)
check('the Terms use only headings and paragraphs (the PDF copy reads exactly those)',
      set(re.findall(r'<(\w+)', tos)) == {'h2', 'p'})
blocks = d._parse_tos_html_blocks(tos)
check('...so the PDF includes the fee summary, Fees and Token launch fees sections',
      {('h2', 'Fees at a glance'), ('h2', 'Fees'), ('h2', 'Token launch fees')} <= set(blocks))
check('the version is bumped past 1.2 (the fee summary is new)', d.TOS_VERSION not in ('1.0', '1.1', '1.2'))
glance = ' '.join(tos.split('<h2>Access</h2>')[0].split())
check('the Terms OPEN with the fees: trading, $0 launch, the 80/20 creator-fee split with a worked example',
      tos.strip().startswith('<h2>Fees at a glance</h2>')
      and pct + '% of every buy and every sell' in glance and 'Launching a token: $0' in glance
      and 'the creator earns 80% of them, paid to the creator\'s wallet, and OrcAgent\'s platform fee is the other 20%, instead of an upfront launch fee' in glance
      and 'This is 20% of the creator fees, not 20% of trading volume' in glance
      and 'if a token earns $100 in creator fees, the creator receives $80 and OrcAgent receives $20' in glance)
check('token launches have their own section, with the community example',
      '<h2>Token launch fees</h2>' in tos and 'creator 65%, community 15% and OrcAgent 20%' in flat
      and 'it cannot be changed afterwards' in flat)

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
check('the Fees page shows the live rate, the $0 launch fee, what the creator earns, the platform fee and the 0% items',
      pct + '%' in page and 'What has no OrcAgent fee' in page and '<div class="fee-stat-label">Launch fee</div>' in page
      and 'Creator earnings' in page and 'OrcAgent platform fee' in page
      and '80% of the token\'s creator fees' in page and 'never of trading volume' in page
      and '$800 for the creator' in page and '$200 for OrcAgent' in page)
check('...and its Terms section is the same text', '<h2>Fees</h2>' in page)
raise SystemExit(0 if all(checks) else 1)
