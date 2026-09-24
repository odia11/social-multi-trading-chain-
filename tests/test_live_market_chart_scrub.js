/* Dragging a finger over a Live Market chart shows the price at that point,
   like Robinhood/Coinbase: a crosshair + price/time tag on the chart, and the
   card's big price switches to the scrubbed price with the move since the
   start of the chart. Releasing restores the live price. On phones the
   crosshair used to be hidden by live-market-final.css (display:none
   !important), so touching the chart showed nothing. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const js=fs.readFileSync('static/live-market-pro.js','utf8');
const css=fs.readFileSync('static/live-market-final.css','utf8');

// 1. Mobile CSS no longer hides the scrub crosshair/dot/tag.
const hidden=css.match(/[^}]*\{display:none!important\}/g)||[];
for(const sel of ['.pt-chart-scrub-line','.pt-chart-scrub-dot','.pt-chart-scrub-tip'])
  assert(!hidden.some(r=>r.includes(sel)), sel+' must not be display:none on phones');
assert(/\.pt-price\.pt-scrubbing\{color:#f7b955!important/.test(css));

// 2. Header follows the finger and comes back on release.
function grab(name){const a=js.indexOf('function '+name+'(');assert(a>=0,name);return js.slice(a,js.indexOf('\n}',a)+2);}
function el(){const e={textContent:'',_c:new Set()};e.classList={add:(...c)=>c.forEach(x=>e._c.add(x)),remove:(...c)=>c.forEach(x=>e._c.delete(x)),toggle:(c,on)=>on?e._c.add(c):e._c.delete(c)};e.offsetWidth=1;return e;}
const els={'pt-price-0':el(),'pt-chg-0':el(),'pt-mcap-0':el()};
const token={mint:'M',price_usd:0.0002,price_change_24h:100,market_cap:200000};
const ctx={ST:{tokens:[token]},document:{getElementById:id=>els[id]},Date,Math,Number,isFinite,setTimeout:()=>0,clearTimeout:()=>{},
  _chartTimers:{},navigator:{}};
vm.createContext(ctx);
vm.runInContext(['fmtPrice','fmtPct','fmtUsd','_scrubTimeLabel','_showScrubHeader','_restoreLiveHeader','_flashTick','_rebaseTokenPrice','_syncCardPrice'].map(grab).join('\n'),ctx);
const now=Math.floor(Date.now()/1000);
const st={mint:'M',candles:[{t:now-600,o:0.0001,c:0.00011},{t:now-300,o:0.00011,c:0.00015},{t:now,o:0.00015,c:0.0002}]};
ctx._chartTimers[0]=st;
ctx._showScrubHeader(0,st,1);
assert.equal(els['pt-price-0'].textContent,'$0.000150','header shows the scrubbed price');
assert.match(els['pt-chg-0'].textContent,/^\+50\.00% · \d\d:\d\d$/,'move since chart start + time: '+els['pt-chg-0'].textContent);
assert(els['pt-price-0']._c.has('pt-scrubbing'));
// A live tick while the finger is down updates the data, not the header.
ctx._syncCardPrice(st,0,0.00021);
assert.equal(els['pt-price-0'].textContent,'$0.000150','a live tick must not overwrite the scrubbed price');
ctx._restoreLiveHeader(0,st);
assert.equal(els['pt-price-0'].textContent,'$0.000210','release restores the (newest) live price');
assert.match(els['pt-chg-0'].textContent,/ · 24h$/);
assert(!els['pt-price-0']._c.has('pt-scrubbing'));

// 3. Wiring: long-press starts scrubbing, release restores, polls respect it,
//    and the chart never starts a pull-to-refresh.
const scrub=grab('attachChartSvgScrub');
assert(/holdTimer = setTimeout\(/.test(scrub),'holding a finger still starts scrubbing');
assert(/_showScrubHeader\(idx, s, best\)/.test(scrub));
assert(/_restoreLiveHeader\(idx, _chartTimers\[idx\]\)/.test(scrub));
assert(/if\(st\.scrubbing\) return;/.test(grab('_syncCardPrice')));
assert(/scrubbing = !!\(_chartTimers\[idx\] && _chartTimers\[idx\]\.scrubbing\)/.test(grab('patchFeedList')));
assert(fs.readFileSync('templates/live_market_pro.html','utf8').includes("initPullToRefresh({ ignoreTarget: '.pt-chart-wrap'"));
for(const f of ['app_performance.py','static/app-ux.js','static/live-market-redesign.js'])
  assert(fs.readFileSync(f,'utf8').includes('live-market-final.css?v=6'),f+' loads live-market-final.css?v=6');
console.log('PASS Live Market chart scrub: finger on the chart shows the price at that point');
