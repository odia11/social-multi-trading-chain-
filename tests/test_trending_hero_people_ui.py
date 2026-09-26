"""The reaction total opens profiles; pressing an action still casts votes."""
from pathlib import Path
import re
import subprocess

root=Path(__file__).resolve().parents[1]
js=(root/'static/home-trending-hero.js').read_text()
css=(root/'static/home-trending-hero.css').read_text()
assert "data-people=\\\"bull\\\"" not in js or 'data-people="bull"' in js
for kind in ('bull','bear','like'):
    assert 'data-people="'+kind+'"' in js
assert 'if(b.dataset.people){openPeople(b.dataset.people);return;}' in js
assert js.index('if(b.dataset.people){openPeople(b.dataset.people);return;}') < js.index("if(typeof checkGuest==='function'&&checkGuest())return")
assert 'oa-th-reaction-group' in js and 'oa-th-people-overlay' in js
assert "kind='+encodeURIComponent(context.kind)" in js
assert "peopleNext=d.next_offset;" in js
assert "modal.querySelector('.oa-th-people-more').hidden=peopleNext===null;" in js
assert 'if(seq!==peopleSeq||modal.hidden||!d.ok)return;' in js
assert "'<a class=\"oa-th-person\" href=\"/profile/'+encodeURIComponent(wallet)+'\">'" in js
assert '.oa-th-people-overlay[hidden]{display:none!important}' in css
assert 'text-decoration-style:dotted' in css
assert 'max-height:min(75dvh,680px)' in css
assert subprocess.run(['node','--check',str(root/'static/home-trending-hero.js')],capture_output=True).returncode==0

# Execute the real profile renderer in JS, including an untrusted username.
start=js.index('function peopleRow(u){')
end=js.index('\nfunction openPeople(',start)
fn=js[start:end]
esc=js[js.index('function esc(s){'):js.index('\nfunction fmtPrice(')]
program=esc+'\n'+fn+'''
const assert=require('assert');
const result=peopleRow({wallet:'Wallet123ABC',username:'<img src=x onerror=alert(1)>',avatar_url:'javascript:alert(1)',verified:true});
assert(!result.includes('href="javascript:'));
assert(!result.includes('src="javascript:'));
assert(result.includes('&lt;img src=x onerror=alert(1)&gt;'));
assert(result.includes('/profile/Wallet123ABC'));
assert(result.includes('oa-th-people-verified'));
console.log('PASS user profile rows escape names and reject malicious avatar schemes');
'''
r=subprocess.run(['node','-e',program],capture_output=True,text=True)
assert r.returncode==0,r.stderr
print('PASS separate Bullish/Bearish/Like counts open paginated public profiles')
print('PASS guests can view user lists without casting a vote')
print('PASS close/loading/switch guard, responsive overlay and JS syntax')
print(r.stdout.strip())
