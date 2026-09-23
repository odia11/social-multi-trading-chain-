/* Home once rendered as an empty screen with only an avatar in the corner.
   dashboard.html had an HTML comment that named the navbar placeholder token
   literally, and _get_index_base_html() replaces EVERY occurrence of it -- so
   a full navbar also got spliced into that comment. That stayed harmless
   only until the navbar markup itself gained an HTML comment: its "-->"
   closed dashboard.html's comment early, dumping the rest of that hidden
   navbar copy into the DOM, including a stray </div> that closed #app
   early. The real header and the whole feed ended up below a
   full-screen-height empty #app. Either half alone is enough to break it
   again, so both are guarded. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const html=fs.readFileSync('dashboard.html','utf8');
const py=fs.readFileSync('dashboard.py','utf8');

const TOKEN='__NAV'+'BAR__';
assert.equal(html.split(TOKEN).length-1,1,
  'dashboard.html must contain the navbar placeholder exactly once (the real splice point) -- ' +
  'every occurrence is replaced, including one written inside a comment');
for(const m of html.matchAll(/<!--[\s\S]*?-->/g)){
  assert(!m[0].includes(TOKEN),'the navbar placeholder must never appear inside an HTML comment in dashboard.html');
}

const start=py.indexOf("def _navbar_html(");
assert(start>0,'_navbar_html not found');
const bodyStart=py.indexOf("return Markup('''",start);
const bodyEnd=py.indexOf("'''",bodyStart+"return Markup('''".length);
assert(bodyStart>0&&bodyEnd>bodyStart,'_navbar_html markup literal not found');
const markup=py.slice(bodyStart,bodyEnd);
assert(!markup.includes('-->')&&!markup.includes('<!--'),
  '_navbar_html() markup must not contain HTML comments -- it is spliced into pages at spots that ' +
  'can sit inside a comment, and its "-->" would close that comment early');

console.log('PASS navbar splice: single placeholder, never inside a comment, navbar markup has no HTML comments');
