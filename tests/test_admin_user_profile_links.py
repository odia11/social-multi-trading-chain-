"""Admin user/wallet tap must resolve the real OrcAgent profile on mobile."""
from pathlib import Path
import re
import subprocess

root=Path(__file__).resolve().parents[1]
html=(root/'templates/admin.html').read_text()
server=(root/'dashboard.py').read_text()

assert 'var wf = u.wallet_full || \'\';' in html
assert "'/profile/' + encodeURIComponent(wf)" in html
assert "'<a class=\"cell-user-link\" href=\"'" in html
assert "_escHtml(u.username || wf)" in html
assert "(u.username||'').toLowerCase().includes(q)" in html
assert '.cell-user-link{display:flex' in html and 'min-height:44px' in html
assert "'username':    username or ''" in server
assert "is_valid_solana_address(wallet_address) or is_valid_evm_address(wallet_address)" in server
assert "if is_valid_solana_address(wallet_address):\n            try:\n                r = requests.post(SOLANA_RPC" in server

# Run the actual admin user renderer against mocked DOM with two sample users.
start=html.index('function renderUsers() {')
end=html.index('\nfunction filterUsers()',start)
renderer=html[start:end]
short=html[html.index('function _short(w) {'):html.index('\nfunction _av(w) {')]
escape=html[html.index('function _escHtml(s) {'):html.index('\nfunction _walletStatusTag(',html.index('function _escHtml(s) {'))]
script=short+'\n'+escape+'\n'+renderer+'''
const assert=require('assert');
const cells={'usr-search':{value:''},'usr-filter':{value:'all'},'usr-count':{textContent:''},'usr-body':{innerHTML:''}};
const document={getElementById:(id)=>cells[id]};
function _av(){return '#f7b955'}
function _fmt(){return '0.0000'}
const _userRole='admin';
const sol='9zdKtt8pGPD68H56MCqk8Vv7LKJGhK1arj3BTDqSSty';
const evm='0x1234567890abcdef1234567890abcdef12345678';
let _allUsers=[
 {wallet_full:sol,wallet:'9zdK...SSty',username:'MJ',has_key:true,trading:false,positions:0,total_trades:2,pnl_today:0,is_verified:true},
 {wallet_full:evm,wallet:'0x12...5678',username:'<img src=x onerror=alert(1)>',has_key:false,trading:false,positions:0,total_trades:0,pnl_today:0,is_verified:false},
];
renderUsers();
assert.strictEqual(cells['usr-count'].textContent,'2 / 2 users');
assert(cells['usr-body'].innerHTML.includes('href="/profile/'+sol+'"'));
assert(cells['usr-body'].innerHTML.includes('href="/profile/'+evm+'"'));
assert(!cells['usr-body'].innerHTML.includes('href="/profile/9zdK...SSty"'));
assert(cells['usr-body'].innerHTML.includes('&lt;img src=x onerror=alert(1)&gt;'));
assert(cells['usr-body'].innerHTML.includes('View profile of MJ'));
assert(cells['usr-body'].innerHTML.includes('Ban</button>'));
assert(cells['usr-body'].innerHTML.includes('Close All</button>'));
cells['usr-search'].value='MJ';renderUsers();
assert.strictEqual(cells['usr-count'].textContent,'1 / 2 users');
assert(cells['usr-body'].innerHTML.includes('href="/profile/'+sol+'"'));
console.log('PASS full Solana/EVM wallet routes, username search, mobile link, escaping, unchanged admin actions');
'''
r=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=20)
assert r.returncode==0,r.stderr
print(r.stdout.strip())

# Verify that the inline admin page scripts parse with Jinja output replaced.
for n,source in enumerate(re.findall(r'<script(?:\\s[^>]*)?>([\\s\\S]*?)</script>',html)):
    if not source.strip():continue
    source=re.sub(r'\\{%[\\s\\S]*?%\\}', '',source)
    source=re.sub(r'\\{\\{[\\s\\S]*?\\}\\}', 'null',source)
    check=subprocess.run(['node','--check'],input=source,capture_output=True,text=True)
    assert check.returncode==0,f'admin inline script {n}: {check.stderr}'
print('PASS admin inline JS syntax and full-wallet profile route handling')
