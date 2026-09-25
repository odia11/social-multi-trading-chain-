/* Portfolio History: in "Tip sent / To @MJ" and "Tip received / From @OJ",
   the @name opens that member's profile. Only our own /profile/<wallet>
   paths are linked; anything else stays plain text. In the day list the row
   is a <button> that expands details, so the name must stop its click from
   reaching the row (and a nested <a> inside a <button> is invalid HTML). */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const js=fs.readFileSync('static/portfolio-history-redesign.js','utf8');
function grab(name){const a=js.indexOf('function '+name+'(');assert(a>=0,name+' missing');return js.slice(a,js.indexOf('\n}',a)+2);}

// Tip events carry the counterparty's name and profile.
const ctx={String,Number,Date,Math,parsedDate:()=>new Date(),console};
vm.createContext(ctx);
vm.runInContext(grab('safeProfile')+'\n'+grab('normalizeTips'),ctx);
const W='Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9';
const [sent,recv]=ctx.normalizeTips([
  {id:1,direction:'sent',recipient_username:'@MJ',sender_username:'me',recipient_profile:'/profile/'+W,sender_profile:'/profile/x',amount:0.25,created_at:'2026-09-25 10:00:00'},
  {id:2,direction:'received',recipient_username:'me',sender_username:'OJ',recipient_profile:'/profile/x',sender_profile:'/profile/'+W,amount:15,created_at:'2026-09-25 10:00:00'}]);
assert.equal(sent.peer,'MJ'); assert.equal(sent.peerPrefix,'To '); assert.equal(sent.profile,'/profile/'+W);
assert.equal(recv.peer,'OJ'); assert.equal(recv.peerPrefix,'From ');

// Only our own profile paths are ever linked.
assert.equal(ctx.safeProfile('/profile/'+W),true);
for(const bad of ['javascript:alert(1)','https://evil.example/profile/'+W,'/profile/','/profile/../admin','//evil.example/x'])
  assert.equal(ctx.safeProfile(bad),false,bad);

// Both lists render the sub line through subLine(); the name is a
// keyboard-reachable role=link that stops propagation to the row button.
assert.equal((js.match(/main\.appendChild\(subLine\(e\)\)/g)||[]).length,2);
assert(!/main\.appendChild\(node\('small','',e\.sub\)\)/.test(js));
const sub=grab('subLine');
assert(/setAttribute\('role','link'\)/.test(sub)&&/tabIndex=0/.test(sub));
assert(/openProfile\(ev,e\.profile\)/.test(sub));
assert(/stopPropagation\(\)/.test(grab('openProfile'))&&/safeProfile\(url\)/.test(grab('openProfile')));
// The expanded details also offer the profile.
assert(/oa-h-profile-link/.test(grab('details')));
assert(/\.oa-h-user\{color:#f7b955/.test(fs.readFileSync('static/portfolio-history-redesign.css','utf8')));
console.log('PASS History: tip @names open the member profile');
