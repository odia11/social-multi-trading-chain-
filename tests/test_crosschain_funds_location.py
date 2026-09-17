"""Where the user's money is, read back off the real status endpoint.

A cross-chain trade can fail in two ways that share a word and share nothing
else:

    nothing left the source chain        -> the USDC is where it always was
    the bridge delivered, the buy did not -> the USDC is on the OTHER chain

Both of those print "Trade failed". A user reading that will go looking for
their dollars on the chain they started from, and in the second case they are
not there -- they are sitting as USDC on the destination chain, perfectly
safe and completely invisible.

So the status endpoint says which, in a sentence, and this drives the real
route through Flask to read it back rather than asserting on a helper.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


PROBE = r'''
import json, sqlite3, time
import dashboard as d

c = d.app.test_client()
d._authenticated_wallet = lambda: 'W1'
d._get_uid = lambda conn, w: 1

def seed(trade_id, state, cc_extra, failure=''):
    conn = sqlite3.connect(d.DB_FILE)
    now = time.time()
    conn.execute("INSERT OR IGNORE INTO users (wallet_address) VALUES ('W1')")
    conn.execute(
        "INSERT OR REPLACE INTO trade_quotes (quote_id,user_id,wallet,mode,"
        "source_chain,destination_chain,token_address,max_spend_usd,"
        "token_purchase_usd,total_cost_usd,subsidy_usd,route,same_chain,"
        "can_execute,breakdown_json,created_at,expires_at) VALUES "
        "(?,1,'W1','manual','base','solana','TOK','30','28.44','30','0',"
        "'base->bridge->solana',0,1,'{}',?,?)",
        ('q-' + trade_id, now, now + 3600))
    conn.execute(
        "INSERT OR REPLACE INTO trade_executions (trade_id,idempotency_key,"
        "quote_id,user_id,wallet,mode,state,same_chain,max_spend_usd,created_at,"
        "updated_at,failure_reason) VALUES (?,?,?,1,'W1','manual',?,0,'30',?,?,?)",
        (trade_id, 'k-' + trade_id, 'q-' + trade_id, state, now, now, failure))
    cols = {'trade_id': trade_id, 'quote_id': 'q-' + trade_id, 'user_id': 1,
            'provider': '0x', 'source_chain': 'base',
            'destination_chain': 'solana', 'source_token': '0xU',
            'destination_token': 'SolU', 'source_amount_raw': '30000000',
            'created_at': now, 'updated_at': now}
    cols.update(cc_extra)
    conn.execute('INSERT OR REPLACE INTO trade_crosschain (%s) VALUES (%s)'
                 % (','.join(cols), ','.join('?' * len(cols))),
                 tuple(cols.values()))
    conn.commit(); conn.close()

out = {}

# the bridge delivered and the purchase did not
seed('t-after', 'FAILED',
     {'provider_status': 'bridge_filled', 'destination_tx_hash': '0xDEST',
      'actual_out_raw': '29700000'},
     failure='the destination swap was not sent')
out['after'] = (c.get('/api/trade/status/t-after').get_json() or {})

# nothing ever left
seed('t-before', 'FAILED', {'provider_status': 'origin_tx_pending'},
     failure='the origin transaction was not sent')
out['before'] = (c.get('/api/trade/status/t-before').get_json() or {})

# still moving
seed('t-flight', 'BRIDGING', {'provider_status': 'bridge_pending',
                              'source_tx_hash': '0xSRC'})
out['flight'] = (c.get('/api/trade/status/t-flight').get_json() or {})

# a person is looking
seed('t-review', 'MANUAL_REVIEW', {'provider_status': 'unknown',
                                   'source_tx_hash': '0xSRC'},
     failure='the origin transaction may have been sent')
out['review'] = (c.get('/api/trade/status/t-review').get_json() or {})

# it worked
seed('t-done', 'COMPLETED',
     {'provider_status': 'bridge_filled', 'destination_tx_hash': '0xDEST',
      'actual_out_raw': '29700000', 'swap_tx_hash': '0xSWAP'})
out['done'] = (c.get('/api/trade/status/t-done').get_json() or {})

print('@@@' + json.dumps(out, default=str))
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

after, before = R['after'], R['before']

check('the status endpoint answers a cross-chain trade at all',
      after.get('ok') is True and after.get('state') == 'FAILED')

check('a trade that failed AFTER the bridge delivered says the money is on '
      'the destination chain', after.get('funds_location') == 'destination')
check('...and names Solana, in a sentence a person can act on, rather than '
      'leaving them to work it out from a state name',
      'Solana' in (after.get('funds_note') or '')
      and 'USDC' in after.get('funds_note'))
check('...without contradicting the failure itself, which is still reported '
      'as it was', after.get('failure_reason') == 'the destination swap was not sent'
      and after.get('completed') is False)

check('a trade that failed BEFORE anything left says the money never moved',
      before.get('funds_location') == 'source'
      and 'Nothing left' in (before.get('funds_note') or ''))
check('...so the two failures, which share a state and a headline, do not '
      'share an answer about where somebody\'s dollars are',
      after.get('funds_location') != before.get('funds_location'))

check('a bridge still in flight claims nothing about where the money landed, '
      'because it has not landed', R['flight'].get('funds_location') == 'in_flight'
      and not R['flight'].get('funds_note'))

check('MANUAL_REVIEW refuses to guess — that state exists because what '
      'happened could not be established, and it says a person is looking '
      'rather than inventing a location',
      R['review'].get('funds_location') == 'unknown'
      and 'has not been lost' in (R['review'].get('funds_note') or ''))

check('a completed trade adds no note, because the money is in the token and '
      'there is nothing to go looking for',
      R['done'].get('funds_location') == 'spent'
      and not R['done'].get('funds_note')
      and R['done'].get('completed') is True)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
