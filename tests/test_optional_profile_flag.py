"""Optional country/flag with explicit opt-in and hidden-by-default public state.

Runs against a temporary test database. No production users or wallets touched.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='orca_flag_test_')
os.environ['ENCRYPTION_KEY']='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck='
os.environ['ORCAGENT_TRENDING_ALERTS']='0'
os.environ['ORCAGENT_FRONTS_GAS']='0'
from solders.keypair import Keypair
import app_entry
import sqlite3

d=app_entry._dashboard
app=app_entry.app
wallet=str(Keypair().pubkey())
uid=d.get_or_create_user(wallet)
BASE='https://orcagent.fun'
client=app.test_client()
csrf='country-test-csrf-token'
with client.session_transaction(base_url=BASE) as ses:
    ses['wallet']=wallet
    ses['user_id']=uid
    ses['csrf_token']=csrf
headers={'X-CSRF-Token':csrf}
def get():return client.get('/api/profile/country',base_url=BASE)
def save(code,visible,custom_headers=headers):
    return client.post('/api/profile/country',json={'country_code':code,'show_country':visible},headers=custom_headers,base_url=BASE)

countries=json.loads((root/'static/profile-countries.json').read_text())
assert len(countries)>=240
assert len({c['code'] for c in countries})==len(countries)
assert {c['code']:c['flag'] for c in countries}['NL']=='🇳🇱'
assert {c['code']:c['flag'] for c in countries}['LR']=='🇱🇷'
print('PASS ISO country list: optional country/territory choices with native flags')

unauth=app.test_client().get('/api/profile/country',base_url=BASE)
assert unauth.status_code==401
initial=get()
assert initial.status_code==200,initial.get_data(as_text=True)[:160]
prefs=initial.get_json()
assert prefs['country_code']=='' and prefs['show_country'] is False
assert len(prefs['countries'])>=240
with sqlite3.connect(d.DB_FILE) as conn:
    cols={r[1] for r in conn.execute('PRAGMA table_info(users)')}
    assert 'profile_country_code' in cols and 'profile_country_visible' in cols
print('PASS database migrated; new and existing accounts start with hidden flag')

assert save('NL',True,custom_headers={}).status_code==403
assert save('ZZ',True).status_code==400
assert save('',True).status_code==400
assert save('nl',True).status_code==400
assert save('NL','yes').status_code==400
assert save('NL',True).get_json()=={'ok':True,'country_code':'NL','show_country':True}
assert get().get_json()['show_country'] is True
print('PASS authenticated CSRF, validated country and explicit visible opt-in')

# Public profile uses the selected emoji, without inferring geolocation.
d.SOLANA_RPC='http://127.0.0.1:1'
d._PROXY_RPCS=[]
html=app.test_client().get('/profile/'+wallet,base_url=BASE)
assert html.status_code==200,html.get_data(as_text=True)[:200]
assert 'class="pf-country-flag"' in html.get_data(as_text=True)
assert '🇳🇱' in html.get_data(as_text=True)
api=app.test_client().get('/api/profile/'+str(uid),base_url=BASE)
assert api.status_code==200,api.get_data(as_text=True)[:130]
assert api.get_json()['country_flag']=='🇳🇱'
print('PASS opted-in country flag visible on real public profile and profile card API')

assert save('LR',False).status_code==200
prefs=get().get_json()
assert prefs['country_code']=='LR' and prefs['show_country'] is False
html=app.test_client().get('/profile/'+wallet,base_url=BASE).get_data(as_text=True)
assert 'class="pf-country-flag"' not in html
api=app.test_client().get('/api/profile/'+str(uid),base_url=BASE).get_json()
assert api['country_name']=='' and api['country_flag']==''
assert save('',False).status_code==200
prefs=get().get_json()
assert prefs['country_code']=='' and prefs['show_country'] is False
print('PASS selecting a country privately, hiding and clearing never reveal origin')
