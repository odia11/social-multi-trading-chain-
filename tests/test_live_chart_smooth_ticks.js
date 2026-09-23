/* Live Market's price line must read as one continuously moving line
   between ticks, like a real exchange ticker -- not a quick flick every
   ~2s followed by a long still hold, and never a visible snap backwards
   when two ticks land close together (routine under network jitter). */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const js=fs.readFileSync('static/live-market-pro.js','utf8');

const fmtStart=js.indexOf('function fmtPrice('), fmtEnd=js.indexOf('\n}',fmtStart)+2;
const fnStart=js.indexOf('function updateLiveChartPrice(');
const fnEnd=js.indexOf('\nfunction ',fnStart+1);
assert(fmtStart>=0&&fnStart>fmtStart&&fnEnd>fnStart,'expected functions not found at their usual offsets');

// One in-flight rAF callback at a time, invoked manually by the test so it
// can inspect state mid-animation instead of racing a real animation loop.
let rafCb=null, rafId=0;
const ctx={
  requestAnimationFrame:(fn)=>{rafCb=fn; return ++rafId;},
  cancelAnimationFrame:()=>{rafCb=null;},
  performance:{now:()=>ctx._now},
  _now:0,
  document:{getElementById:(id)=>ctx._els[id]},
  _els:{},
  _pricePollBaseMs:2000,
  Number, Math, isNaN,
};
vm.createContext(ctx);
vm.runInContext(js.slice(fmtStart,fmtEnd)+'\n'+js.slice(fnStart,fnEnd), ctx);

function makeEl(){ return {attrs:{}, setAttribute(k,v){this.attrs[k]=v;}}; }
const idx=0;
const body=makeEl(), wick=makeEl(), guide=makeEl();
const pill={style:{}, textContent:''};
ctx._els['pt-live-body-'+idx]=body;
ctx._els['pt-live-wick-'+idx]=wick;
ctx._els['pt-live-guide-'+idx]=guide;
ctx._els['pt-chart-wrap-'+idx]={querySelector:()=>pill};

const last={t:0,o:1.00,h:1.00,l:1.00,c:1.00,v:0};
const st={candles:[last], min:0.5, max:1.5, priceH:200, liveRaf:null, animPrice:null, renderedPrice:1.00};
// updateLiveChartPrice() reads _chartTimers[idx] as a plain global lookup
// (the real file declares it with module-level `var`) -- a context property
// of the same name is what a vm script sees as that global.
ctx._chartTimers={0:st};
ctx._now=0;

// ---- Duration now tracks the poll cadence, not a fixed 220ms ----
ctx.updateLiveChartPrice(idx, 1.10);
assert(rafCb,'first tick must schedule an animation frame');
ctx._now=210; rafCb(ctx._now); // 220ms used to be the ENTIRE old duration
assert(st.liveRaf!==null, 'with a ~2s poll cadence, a 220ms-long ease must not already be finished at t=210ms');
const priceAt210=st.animPrice;
assert(priceAt210>1.00 && priceAt210<1.10, 'price should be partway through the ease, not at either end');

// ---- A second tick arriving mid-animation must continue from the line's
//      actual current position, not snap back to the stale renderedPrice ----
const beforeSecondTick=st.animPrice;
ctx.updateLiveChartPrice(idx, 1.20); // st.renderedPrice is still 1.00 here -- the bug used that
assert(rafCb,'second tick must schedule its own frame');
ctx._now+=1; rafCb(ctx._now); // one frame in: should start essentially where it left off
const justAfter=st.animPrice;
assert(
  Math.abs(justAfter-beforeSecondTick) < 0.01,
  `a tick arriving mid-animation must not jump backwards: was ${beforeSecondTick}, now ${justAfter}`
);
assert(justAfter>=beforeSecondTick-1e-9, 'price must keep moving forward, never regress, across back-to-back ticks');

// ---- Finishing an animation still records renderedPrice for the next tick ----
ctx._now+=5000; rafCb(ctx._now); // run past duration
assert.equal(st.liveRaf,null,'animation must end once its duration has elapsed');
assert.equal(st.renderedPrice,1.20,'a completed animation must land exactly on the target price');
assert.equal(st.animPrice,null,'animPrice must clear once nothing is in flight, so the next tick reads renderedPrice');

console.log('PASS live market chart: ticks ease across the full poll interval, and a tick arriving mid-animation continues forward instead of snapping backwards');
