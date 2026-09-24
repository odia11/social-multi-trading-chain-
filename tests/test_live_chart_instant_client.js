/* Live Market chart history in the browser: parallel requests (no more
   2.1s-per-request queue), newest request first, and a per-token candle
   cache so a card scrolled back into view or a timeframe switched back to
   repaints real history immediately. */
const assert=require('node:assert/strict');
(async()=>{
const fs=require('node:fs');
const vm=require('node:vm');
const src=fs.readFileSync('static/live-market-pro.js','utf8');
const qStart=src.indexOf('var _CHART_FETCH_CONCURRENCY');
const qEnd=src.indexOf('function chartBucketSeconds(tf){');
const primeStart=src.indexOf('function startObservedCandle(');
const primeEnd=src.indexOf('function mountChart(');
const tfStart=src.indexOf('function setChartTf(');
const tfEnd=src.indexOf('/* ── per-card lazy loading');
assert(qStart>0&&qEnd>qStart&&primeStart>0&&primeEnd>primeStart&&tfStart>0&&tfEnd>tfStart);
assert(!/2100-\(Date\.now\(\)-_lastChartFetchAt\)/.test(src),'the fixed 2.1s spacing must be gone');

function makeCtx(stored){
  const pending=[], renders=[], store={};
  if(stored) store['oa-lm-candles-v1']=JSON.stringify(stored);
  const ctx={
    fetch:(url)=>new Promise(res=>pending.push({url,res})),
    sessionStorage:{getItem:k=>store[k]||null,setItem:(k,v)=>{store[k]=v}},
    setTimeout:(fn)=>{fn();return 1}, Date, JSON, Object, Math, Number, Promise,
    renderChartSvg:(idx,c,p)=>renders.push({idx,n:c.length,p}),
    chartTick:()=>{}, _chartTimers:{}, _priceNextAt:0, tickLivePrices(){},
    chartBucketSeconds:()=>300,
  };
  vm.createContext(ctx);
  vm.runInContext(src.slice(qStart,qEnd)+src.slice(primeStart,primeEnd)+src.slice(tfStart,tfEnd),ctx);
  return {ctx,pending,renders,store};
}

// Parallel, newest first.
let {ctx,pending}=makeCtx();
for(let i=0;i<6;i++) ctx.fetchChart('M'+i,'5m','P'+i,'solana',{});
assert.equal(pending.length,4,'four chart requests start at once (was: one every 2.1s)');
// When a slot frees up, the most recent waiting request (the card just
// scrolled to) goes next, not the oldest.
pending[0].res({json:()=>({candles:[]})});

await new Promise(r=>setImmediate(r));
assert.equal(pending.length,5);
assert.match(pending[4].url,/M5/,'newest waiting request is started first');

// Cache: stored history paints immediately on prime and on a timeframe switch.
const candles=[{t:1,o:1,h:1,l:1,c:1},{t:2,o:1,h:2,l:1,c:2},{t:3,o:2,h:3,l:2,c:3}];
let r=makeCtx({'MINT|PAIR|5m':{c:candles,p:3,at:1},'MINT|PAIR|1h':{c:candles.slice(0,2),p:2,at:1}});
let st=r.ctx.primeChart(0,'MINT','PAIR','solana',3.1);
assert.equal(st.candles.length,3,'cached candles are used instead of a single seed candle');
assert.equal(r.renders[0].n,3,'and painted immediately');
r.ctx.setChartTf(0,'1h');
assert.equal(r.renders[1].n,2,'switching to a cached timeframe repaints its history immediately');

// Nothing cached: falls back to the single observed seed candle, as before.
r=makeCtx();
st=r.ctx.primeChart(1,'OTHER','P','solana',2);
assert.equal(r.renders[0].n,1,'no cache: one seed candle from the live price');

// Put persists to sessionStorage and is bounded.
r=makeCtx();
for(let i=0;i<70;i++) r.ctx.candleCachePut('M'+i,'P','5m',candles,1);
const saved=JSON.parse(r.store['oa-lm-candles-v1']);
assert(Object.keys(saved).length<=60,'the candle cache is bounded');
assert(r.ctx.candleCacheGet('M69','P','5m'),'newest entries survive');
console.log('PASS live chart client: parallel newest-first loading, instant repaint from the candle cache');
})().catch(e=>{console.error(e);process.exit(1);});
