/* "$Attention+" in an @orcagent post linked only "$Attention": a ticker could
   hold letters, digits and _ only, so the plus fell off and the link searched
   for a different token by name. And the post did not say which call it was
   about at all -- its picture had replaced the call card, marker and all.

   Now a post that is about one call or token links "$" + that exact symbol
   to exactly that call or token, whatever characters the ticker has, and a
   trailing "+" is part of any ticker. */
const assert=require('node:assert/strict');
const fs=require('fs');
const vm=require('vm');
const js=fs.readFileSync('static/dashboard.js','utf8');
const start=js.indexOf('function _fcTagText(');
const end=js.indexOf('\nfunction _fcLinkHtml(',start);
assert(start>0&&end>start,'cashtag linker exists');
const ctx={esc:s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'),
           safeMint:m=>/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(String(m||''))?String(m):''};
vm.createContext(ctx);
vm.runInContext(js.slice(start,end),ctx);
const MINT='9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin';
const tags=html=>[...html.matchAll(/<span class="token-tag"[^>]*>([^<]*)<\/span>/g)].map(m=>m[1]);

// The reported post: the whole ticker, to the call it is about.
let out=ctx._fcTagText('$Attention+ just hit 10x since @degentrader1990 called it.',{symbol:'Attention+',mint:MINT,callId:7,callPostId:41});
assert.deepEqual(tags(out),['$Attention+'],'the plus is part of the link');
assert.match(out,/onclick="event\.stopPropagation\(\);_feedCallOpenPost\(41\)"/,'the ticker opens the call itself');
assert.match(out,new RegExp('data-mint="'+MINT+'"'));
assert.ok(out.includes('just hit 10x'),'the rest of the text stays');

// Other characters a ticker can have, matched exactly from the post's token.
out=ctx._fcTagText('$WIF.X is trending. $wif.x again',{symbol:'WIF.X',mint:MINT});
assert.deepEqual(tags(out),['$WIF.X','$wif'],'exact symbol links whole; other case falls back to the generic rule');
assert.match(out,/showTokenCard\(this\.dataset\.sym,this\.dataset\.mint\)/);
out=ctx._fcTagText('$<b>x</b> is up',{symbol:'<b>x</b>',mint:MINT});
assert.ok(!out.includes('<b>'),'a symbol is always escaped');

// Without a known token: a trailing + still belongs to the ticker,
// sentence punctuation does not, and prices are never tickers.
assert.deepEqual(tags(ctx._fcTagText('Bought $Attention+ and $SOL. Paid $500.',null)),['$Attention+','$SOL']);
// A call with no separate post of its own opens the call page.
assert.match(ctx._fcTagText('$BONK',{symbol:'BONK',mint:MINT,callId:9}),/location\.href=\\?'\/call\/9\\?'/);

// The feed takes the post's token from its call / chart, and @orcagent's
// picture stands in for the card instead of dropping what the post is about.
assert.match(js,/_postToken = \{symbol: e\.call\.symbol, mint: e\.call\.mint, callId: e\.call\.id,/);
assert.match(js,/var _pictureIsCard = _isAgentPost && e\.image_url && e\.call\.featured;/);
assert.match(js,/_fcRichText\(_rawContent,_postToken\)/);
assert.match(js,/_fcRichText\(_textPart,_postToken\)/);
console.log('PASS cashtags: exact token of the post whatever its characters, trailing +, call route, escaping');
