/* A post containing a contract address or a long link (one unbroken
   "word") must wrap inside the card instead of running off the right edge,
   where the rest of it could not be seen. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const html=fs.readFileSync('dashboard.html','utf8');
const js=fs.readFileSync('static/dashboard.js','utf8');
// The post text container every feed card renders its body into.
assert(/'<div id="fc-text-'\+safePostId\+'">'/.test(js),'feed card text container');
const rule=html.match(/\[id\^="fc-text-"\]\{([^}]*)\}/);
assert(rule,'wrap rule for the post text container');
assert(/overflow-wrap:anywhere/.test(rule[1]));
assert(/min-width:0/.test(rule[1]));
// Nothing may switch wrapping back off for the post text.
for(const f of fs.readdirSync('static').filter(n=>n.endsWith('.css')))
  assert(!/fc-text[^{]*\{[^}]*white-space:nowrap/.test(fs.readFileSync('static/'+f,'utf8')),f);
console.log('PASS feed posts: long addresses/links wrap inside the card');
