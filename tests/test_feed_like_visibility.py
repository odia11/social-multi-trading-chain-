"""Post/reply like visibility and client-side state regression checks."""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[1]
js=(root/'static/dashboard.js').read_text()
html=(root/'dashboard.html').read_text()
css=(root/'static/feed-action-icons.css').read_text()
server=(root/'dashboard.py').read_text()
assert "<span class=\"fc-ri-lc\">'+likeCnt+'</span>" in js, 'Reply zero count must render'
assert "(likeCnt>0?" not in js, 'Do not hide reply zero count'
assert "aria-pressed=\"'+(r.liked_by_me?'true':'false')" in js
assert "aria-pressed=\"'+(e.liked_by_me?'true':'false')" in js
assert "if(heart)heart.textContent=liked?'❤️':'♡';" in js
assert "btn.disabled=true;" in js and "btn.disabled=false" in js
assert 'min-height:38px' in html and '.fc-ri-lc{display:inline-block' in html
assert '.fc-action.oa-action-like .fc-like-count{font:750 16px' in css
assert "'liked': not existing, 'like_count': count" in server
assert 'feed-action-icons.css?v=3' in (root/'app_performance.py').read_text()
assert 'feed-action-icons.css?v=3' in (root/'static/navbar.js').read_text()
# Execute the actual reply toggle with a fake DOM node and mocked API to catch
# rendering regressions, including unlike-to-zero and the failed-request rollback.
fn=js[js.index('function _feedLikeReply(replyId, btn){'):js.index('\nfunction _feedDeleteReply(',js.index('function _feedLikeReply(replyId, btn){'))]
test="""
const assert=require('assert');
let response=null, calls=0;
global.fetch=(url,init)=>{calls++;assert.strictEqual(url,'/api/feed/reply/like/7');assert.strictEqual(init.method,'POST');return Promise.resolve({json:()=>Promise.resolve(response)})};
const heart={textContent:'♡'},count={textContent:'0'};
const attrs={};const names=new Set();
const btn={disabled:false,querySelector:s=>s==='.fc-ri-heart'?heart:count,
 setAttribute:(k,v)=>attrs[k]=v,
 classList:{contains:k=>names.has(k),toggle:(k,v)=>v?names.add(k):names.delete(k)}};
async function flush(){for(let i=0;i<8;i++)await Promise.resolve()}
(async()=>{
 response={ok:true,liked:true,like_count:1};_feedLikeReply(7,btn);
 assert.strictEqual(count.textContent,'1');assert.strictEqual(attrs['aria-pressed'],'true');assert.strictEqual(heart.textContent,'❤️');
 _feedLikeReply(7,btn);assert.strictEqual(calls,1,'block double taps while waiting');
 await flush();assert.strictEqual(btn.disabled,false);
 response={ok:true,liked:false,like_count:0};_feedLikeReply(7,btn);await flush();
 assert.strictEqual(count.textContent,'0');assert.strictEqual(heart.textContent,'♡');assert.strictEqual(attrs['aria-pressed'],'false');
 response={ok:false};_feedLikeReply(7,btn);await flush();
 assert.strictEqual(count.textContent,'0');assert.strictEqual(attrs['aria-label'],'Like reply');
 console.log('PASS reply heart/count update in sync, zero stays visible, failed action rolls back, double tap guarded');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
r=subprocess.run(['node','-e',fn+'\n'+test],capture_output=True,text=True,timeout=20)
assert r.returncode==0,r.stderr
print('PASS visible post/reply like count CSS + API contract + cache bust')
print(r.stdout.strip())
