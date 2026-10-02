"""Groups follow OrcAgent's active-chain contract: Solana only."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update({
    'DATA_DIR': tempfile.mkdtemp(),
    'SECRET_KEY': 'x'*32,
    'ENCRYPTION_KEY': 'KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=',
    'DEV':'1','ORCAGENT_POSITION_GUARDIAN':'0'
})
import dashboard as m  # noqa:E402

checks=[]
def check(name,cond): checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+name)

check('server exposes only Solana for token groups', tuple(m.TOKEN_CHAINS)==('solana',))
check('active EVM registry is empty', m.ACTIVE_EVM_CHAINS=={})

wallet='Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9'
sol='DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263'
csrf='tok'*10
c=m.app.test_client()
with c.session_transaction() as s:
    s['wallet']=wallet; s['user_id']=m.get_or_create_user(wallet); s['csrf_token']=csrf

def create(chain,address):
    r=c.post('/api/groups',json={'name':'group-'+chain,'token_symbol':'TKN',
        'token_address':address,'chain':chain},headers={'X-CSRF-Token':csrf})
    return r.status_code,r.get_json()

status,body=create('solana',sol)
check('Solana group can be created',status==200 and body.get('ok'))
for chain in ('bsc','base','arbitrum','polygon','robinhood','ethereum'):
    st,b=create(chain,'0x2170Ed0880ac9A755fd29B2688956BD959F933F8')
    check(chain+' group is refused',st==400 and not b.get('ok'))

page=c.get('/groups').get_data(as_text=True)
check('group form offers Solana', 'value="solana"' in page)
check('group form does not offer EVM chains',
      all(('value="'+x+'"') not in page for x in ('bsc','base','arbitrum','polygon','robinhood')))
raise SystemExit(0 if all(checks) else 1)
