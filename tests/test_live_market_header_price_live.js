/* The big price on a Live Market card must follow the same live tick as the
   chart beside it. It used to change only with the 15s feed poll (the
   scanner's price, often minutes old), so the header read $0.000161 while
   the chart was already at $0.000186. The 24h change and market cap move
   with it, a later poll never drags the header back to the older price,
   and the chart's price axis leaves room for sub-cent labels. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const js=fs.readFileSync('static/live-market-pro.js','utf8');

function grab(name){
  const a=js.indexOf('function '+name+'(');
  assert(a>=0, name+' not found');
  const b=js.indexOf('\n}',a)+2;
  return js.slice(a,b);
}

function el(){return {textContent:'',_cls:new Set(),offsetWidth:1,
  classList:{add(...c){c.forEach(x=>this._o._cls.add(x))},remove(...c){c.forEach(x=>this._o._cls.delete(x))},
             toggle(c,on){on?this._o._cls.add(c):this._o._cls.delete(c)},contains(c){return this._o._cls.has(c)}}};}
const els={};
for(const id of ['pt-price-0','pt-chg-0','pt-mcap-0','pt-liq-0','pt-vol-0','pt-ratio-0']){const e=el();e.classList._o=e;els[id]=e;}

const token={mint:'MINT',price_usd:0.000161,price_change_24h:212,market_cap:160700,liquidity_usd:37800,
  volume_24h:747200,buys_24h:57,sells_24h:43};
const ctx={ST:{tokens:[token]}, document:{getElementById:id=>els[id]}, setTimeout:()=>0, clearTimeout:()=>{},
  Date, Math, Number, isFinite, isNaN, _chartTimers:{}, renderChartSvg:()=>{}, updateLiveChartPrice:()=>{},
  chartBucketSeconds:()=>300, startObservedCandle:()=>({})};
vm.createContext(ctx);
vm.runInContext(['fmtPrice','fmtUsd','fmtPct','fmtAxisPrice','ratioStr','_flashTick','_rebaseTokenPrice',
  '_syncCardPrice','_applyLivePrice','mergeTokenUpdates','patchFeedList'].filter(n=>js.includes('function '+n+'(')).map(grab).join('\n'),ctx);

const st={mint:'MINT',candles:null,price:0};
// A live tick arrives before the chart history has loaded: the header still updates.
ctx._applyLivePrice(st,0,0.000186);
assert.equal(els['pt-price-0'].textContent,'$0.000186','header price follows the live tick');
assert(els['pt-price-0']._cls.has('pt-tick-up'),'an up-tick flashes green');
// Opened at 0.000161/3.12 24h ago -> now +260.5%.
assert.match(els['pt-chg-0'].textContent,/^\+260\.\d\d% · 24h$/,'24h change re-based on the live price: '+els['pt-chg-0'].textContent);
assert(Math.abs(token.market_cap-160700*186/161)<1,'market cap scales with price');

ctx._applyLivePrice(st,0,0.000180);
assert(els['pt-price-0']._cls.has('pt-tick-down')&&!els['pt-price-0']._cls.has('pt-tick-up'),'a down-tick flashes red');

// The next 15s poll brings the old scanner price; the header keeps the live one.
ctx.mergeTokenUpdates([{mint:'MINT',price_usd:0.000161,price_change_24h:212,market_cap:160700}]);
if(ctx.patchFeedList) ctx.patchFeedList();
assert.equal(token.price_usd,0.000180,'a poll must not drag the price back to the stale scanner value');
assert.equal(els['pt-price-0'].textContent,'$0.000180');

// A tick for a different token at the same index (list re-rendered) is ignored.
ctx._applyLivePrice({mint:'OTHER',candles:null,price:0},0,5);
assert.equal(els['pt-price-0'].textContent,'$0.000180');

// Price axis: 3 significant digits, and the reserved width fits the label.
assert.equal(ctx.fmtAxisPrice(0.000158),'0.000158');
assert.equal(ctx.fmtAxisPrice(0.0000876),'0.0000876');
assert.equal(ctx.fmtAxisPrice(1.234),'1.23');
assert(!/w-46\b/.test(js),'plot width must come from the measured axis labels, not a fixed 46px');
assert(/axisW=Math\.max\(46,Math\.ceil\(axisChars\*5\.4\)\+9\)/.test(js));

// A live price climbing into the top 16px rescales the chart instead of
// sliding its price tag under the timeframe buttons.
assert(/nextY<16\)\{ renderChartSvg\(idx,st\.candles,nextPrice\); return; \}/.test(js));

// Flash styles ship, with a bumped stylesheet version everywhere it's loaded.
const css=fs.readFileSync('static/live-market-final.css','utf8');
assert(/\.pt-price\.pt-tick-up\{color:#3ddc97!important/.test(css));
assert(/\.pt-price\.pt-tick-down\{color:#ff6b6b!important/.test(css));
for(const f of ['app_performance.py','static/app-ux.js','static/live-market-redesign.js'])
  assert(fs.readFileSync(f,'utf8').includes('live-market-final.css?v=5'),f+' loads live-market-final.css?v=5');
console.log('PASS Live Market header price, 24h change and market cap follow the live tick');
