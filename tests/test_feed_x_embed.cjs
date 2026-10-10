// Safe X status parsing, lazy loading and no feed redraw regressions.
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const src=fs.readFileSync(path.resolve(__dirname,'../static/feed-x-embed.js'),'utf8');
const feed=fs.readFileSync(path.resolve(__dirname,'../static/dashboard.js'),'utf8');
const html=fs.readFileSync(path.resolve(__dirname,'../dashboard.html'),'utf8');
const csp=fs.readFileSync(path.resolve(__dirname,'../security_hardening.py'),'utf8');

class FakeObserver{
  constructor(callback,opts){this.callback=callback;this.options=opts;this.targets=new Set();FakeObserver.current=this;}
  observe(target){this.targets.add(target)}
  unobserve(target){this.targets.delete(target)}
}
let renderCount=0;
const context={
  window:{OrcPageLifecycle:{createScope(){return {
    isActive(){return true;},
    intersectionObserver(callback,opts){return new FakeObserver(callback,opts);},
    onCleanup(){},
  }}},twttr:{widgets:{createTweet(id,target,opts){
    renderCount++;
    assert.equal(id,'1234567890123456789');
    assert.equal(opts.dnt,true);
    assert.equal(opts.theme,'dark');
    target.rendered=true;
    return Promise.resolve({tagName:'IFRAME'});
  }}}},
  IntersectionObserver:FakeObserver,
  URL, Promise, setTimeout, clearTimeout,
};
vm.createContext(context);
vm.runInContext(src,context);
const x=context.window.OrcFeedXEmbed;
assert.ok(x);
for(const [raw,id] of [
  ['Check https://x.com/Orcagent/status/1234567890123456789?s=20', '1234567890123456789'],
  ['https://twitter.com/Orcagent/status/1234567890123456789', '1234567890123456789'],
  ['https://www.x.com/Orcagent/status/1234567890123456789.', '1234567890123456789'],
  ['https://mobile.twitter.com/Orcagent/status/1234567890123456789', '1234567890123456789'],
  ['https://x.com/i/web/status/1234567890123456789', '1234567890123456789'],
  ['x.com/Orcagent/status/1234567890123456789', '1234567890123456789'],
]){
  assert.equal(x.statusFromText(raw).id,id,raw);
  assert.ok(x.card(raw).includes('data-x-post-id="'+id+'"'),raw);
}
for(const raw of [
  'See https://evilx.com/Orcagent/status/1234567890123456789',
  'https://x.com.evil.example/Orcagent/status/1234567890123456789',
  'https://x.com/Orcagent/status/foo',
  'https://x.com/Orcagent',
  'https://x.com/intent/tweet?text=hello',
  'https://x.com/Orcagent/status/12345/extra',
  'https://x.com/Orcagent/status/1234567890123456789@evil.test',
  '<script>alert(1)</script>',
]){
  assert.equal(x.statusFromText(raw),null,raw);
  assert.equal(x.card(raw),'',raw);
}
// A pasted tweet URL is only shown once: the embedded card already has
// its own Open on X link. Ordinary post text and unrelated links survive.
const tweet='https://x.com/pbi_trade/status/210896351890948915';
assert.equal(x.stripEmbeddedStatusUrl(tweet),'');
assert.equal(x.stripEmbeddedStatusUrl('x.com/pbi_trade/status/210896351890948915?s=20'),'');
assert.equal(x.stripEmbeddedStatusUrl('https://twitter.com/pbi_trade/status/210896351890948915'),'');
assert.equal(x.stripEmbeddedStatusUrl('See this: '+tweet),'See this:');
assert.equal(x.stripEmbeddedStatusUrl('This is interesting '+tweet+' from today'),
             'This is interesting from today');
assert.equal(x.stripEmbeddedStatusUrl('Check it out\n'+tweet+'\nThoughts?'),
             'Check it out\nThoughts?');
assert.equal(x.stripEmbeddedStatusUrl('Look '+tweet+' and https://example.org/info'),
             'Look and https://example.org/info');
assert.equal(x.stripEmbeddedStatusUrl('https://example.org/info'),
             'https://example.org/info');
assert.equal(x.stripEmbeddedStatusUrl('https://evilx.com/name/status/210896351890948915'),
             'https://evilx.com/name/status/210896351890948915');
assert.equal(x.stripEmbeddedStatusUrl('Nothing to embed'),'Nothing to embed');
assert.ok(x.card(tweet).includes('Open on X'),'visible fallback is still needed');
assert.ok(feed.includes('window.OrcFeedXEmbed.stripEmbeddedStatusUrl(_rawContent)'));
assert.ok(feed.includes('window.OrcFeedXEmbed.card(e.content)'),
          'Original content must still be used to build the embed');

const card=x.card('Shared https://x.com/Orcagent/status/1234567890123456789');
assert.ok(card.includes('href="https://x.com/Orcagent/status/1234567890123456789"'));
assert.ok(card.includes('target="_blank" rel="noopener noreferrer nofollow"'));
assert.ok(!card.includes('<iframe') && !card.includes('<script'));
assert.equal(x.card('hello there'),'');
assert.ok(html.indexOf('/static/feed-x-embed.js') < html.indexOf('/static/dashboard.js'));
assert.ok(html.includes('/static/feed-x-embed.css'));
assert.ok(feed.includes('window.OrcFeedXEmbed.card(e.content)'));
assert.ok(feed.includes('window.OrcFeedXEmbed.observe(root)'));
assert.ok(feed.includes('window.OrcFeedXEmbed.reuse(oldRoot,fresh)'));
assert.ok(feed.includes('window.OrcFeedXEmbed.dispose(root)'));
assert.ok(csp.includes('https://platform.twitter.com') && csp.includes('https://syndication.twitter.com'));

function root(){
  const slot={textContent:'',rendered:false,replaceChildren(){this.textContent='';}};
  return {dataset:{xPostId:'1234567890123456789'},isConnected:true,
    querySelector(q){return q==='.oa-x-post-slot'?slot:null},slot};
}
const first=root();
const parent={querySelectorAll(){return [first]}};
x.observe(parent);
assert.equal(renderCount,0,'X must not load before approaching the viewport');
assert.equal(FakeObserver.current.targets.has(first),true);
FakeObserver.current.callback([{isIntersecting:true,target:first}]);
(async function(){
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(renderCount,1);
  assert.equal(first.dataset.xState,'ready');
  assert.equal(first.slot.rendered,true);
  x.observe(parent);
  assert.equal(renderCount,1,'refresh must not reload same tweet');
  const second=root();
  second.dataset.xPostId='9999999999999999999';
  x.observe({querySelectorAll(){return [second]}});
  assert.equal(FakeObserver.current.targets.has(second),true);
  x.dispose({querySelectorAll(){return [second]}});
  assert.equal(FakeObserver.current.targets.has(second),false);
  console.log('X FEED EMBED TESTS PASSED');
})().catch(e=>{console.error(e);process.exitCode=1});
