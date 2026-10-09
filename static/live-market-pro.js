/* OrcAgent Live Market — "Pro terminal" desktop page controller.
   Talks to /api/market/scanner (server-side sort/filter), /api/market/tape
   (global buy/sell activity), and the existing token/wallet/trade/watchlist/
   copy-trade/leaderboard endpoints already used elsewhere in the app. */
(function(){
'use strict';
var _routeScope=OrcPageLifecycle.routeScope('live-market','.pt-shell');
window.__oaLiveMarketScope=_routeScope;

/* ── helpers ── */
function esc(s){
  return String(s==null?'':s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}
function safeMediaUrl(value){
  var raw=String(value==null?'':value).trim();
  if(!raw) return '';
  if(/^data:image\/(?:png|jpe?g|webp|gif);base64,/i.test(raw)) return raw;
  if(/^blob:/i.test(raw)) return raw;
  try{
    var u=new URL(raw,location.origin);
    return (u.protocol==='http:'||u.protocol==='https:') ? u.href : '';
  }catch(_){ return ''; }
}
function fmtUsd(n){
  n = Number(n)||0;
  if(!n) return '—';
  var sign = n<0?'-':''; n=Math.abs(n);
  if(n>=1e9) return sign+'$'+(n/1e9).toFixed(2)+'B';
  if(n>=1e6) return sign+'$'+(n/1e6).toFixed(2)+'M';
  if(n>=1e3) return sign+'$'+(n/1e3).toFixed(1)+'K';
  return sign+'$'+n.toFixed(0);
}
/* Trader PnL, in USD at the live SOL price -- t.total_pnl_usd is computed
   server-side from _sol_price_usd (null there means the price feed hasn't
   populated yet, not that PnL is zero), so this falls back to the raw SOL
   figure rather than ever showing a misleading "$0.00". */
function fmtTraderPnl(t){
  var usd = t.total_pnl_usd;
  if(usd != null){
    var sign = usd >= 0 ? '+' : '-';
    return sign + '$' + Math.abs(usd).toFixed(2);
  }
  var sol = Number(t.total_pnl||0);
  return (sol >= 0 ? '+' : '') + sol.toFixed(3) + ' SOL';
}
function fmtShort(n){
  n = Number(n)||0;
  if(n>=1000) return (n/1000)+'K';
  return String(n);
}
// A token amount, not a price: meme-coin quantities run from fractions to
// billions, so this scales rather than printing 1234567890.0000.
function fmtAmount(n){
  n = Number(n);
  if(!isFinite(n) || n <= 0) return '0';
  if(n >= 1e9) return (n/1e9).toFixed(2)+'B';
  if(n >= 1e6) return (n/1e6).toFixed(2)+'M';
  if(n >= 1e3) return Math.round(n).toLocaleString('en-US');
  if(n >= 1)   return n.toFixed(2);
  return n.toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
}
function fmtPrice(n){
  if(n==null || n==='') return '—';
  n = Number(n);
  if(isNaN(n)) return '—';
  if(n===0) return '$0.00';
  if(n>=1) return '$'+n.toFixed(2);
  if(n>=0.01) return '$'+n.toFixed(4);
  if(n>=0.0001) return '$'+n.toFixed(6);
  return '$'+n.toFixed(n<0.00000001?12:8);
}
// Chart axis: three significant digits, so a $0.0000876 token reads
// "0.0000876" rather than eight padded decimals.
function fmtAxisPrice(n){
  n = Number(n);
  if(!(n>0)) return '0';
  if(n>=1000) return Math.round(n).toLocaleString('en-US');
  if(n>=1) return n.toFixed(2);
  var dec = Math.min(12, 2 - Math.floor(Math.log10(n)));
  return n.toFixed(dec);
}
function fmtPct(n){
  n = Number(n)||0;
  return (n>=0?'+':'')+n.toFixed(2)+'%';
}
function fmtAge(createdMs){
  if(!createdMs) return '?';
  var diff = Date.now()-createdMs;
  var h = diff/3600000;
  if(h<1) return Math.max(1,Math.round(diff/60000))+'m';
  if(h<24) return Math.round(h)+'h';
  if(h<24*365) return Math.round(h/24)+'d';
  return Math.floor(h/24/365)+'y';
}
function fmtAgeSeconds(s){
  s = Math.max(0, Math.round(s||0));
  if(s<60) return s+'s';
  if(s<3600) return Math.round(s/60)+'m';
  if(s<86400) return Math.round(s/3600)+'h';
  return Math.round(s/86400)+'d';
}
function ratioStr(buys, sells){
  buys = buys||0; sells = sells||0;
  var total = buys+sells;
  if(!total) return '—';
  var bp = Math.round(buys/total*100);
  return bp+'% / '+(100-bp)+'%';
}
function authHeaders(){
  var csrf   = (document.querySelector('meta[name="csrf-token"]')||{}).content||'';
  var secret = (document.querySelector('meta[name="client-secret"]')||{}).content||'';
  var h = {'Content-Type':'application/json','X-CSRF-Token':csrf,'X-CSRFToken':csrf,'X-Requested-With':'XMLHttpRequest'};
  if(secret) h['X-API-Shared-Secret'] = secret;
  return h;
}
var _toastTimer = null;
function toast(msg){
  var el = document.getElementById('pt-toast');
  if(!el) return;
  el.textContent = msg;
  el.classList.add('show');
  _routeScope.clearTimeout(_toastTimer);
  _toastTimer = _routeScope.setTimeout(function(){ el.classList.remove('show'); }, 2600);
}
function showMsg(el, text, ok){
  if(!el) return;
  el.textContent = text;
  el.className = 'pt-buy-msg ' + (ok?'ok':'err');
  el.style.display = 'block';
}

/* ── mobile drawer/menu overlays (no-ops on desktop, where the classes
   toggled here have no matching CSS) ── */
function closeMobileOverlays(){
  // The nav drawer itself is now the shared navbar's (static/navbar.js) --
  // this only owns the filters drawer that's unique to this page.
  var left = document.getElementById('pt-left');
  var scrim = document.getElementById('pt-scrim');
  if(left) left.classList.remove('mobile-open');
  if(scrim) scrim.classList.remove('show');
  // Released here rather than at each call site, so no path can close the
  // drawer and leave the page unable to scroll.
  try{ document.body.style.overflow = ''; }catch(e){}
}

/* ── state ── */
var ST = {
  // Show the full Solana discovery feed by default. Liquidity remains an
  // optional user filter instead of silently hiding DexScreener-home tokens.
  sort: 'trending', minLiquidity: 0, age: 'any',
  lpLocked: false, mintRevoked: false, hideHoneypots: false, verifiedSocials: false,
  tokens: [], counts: {}
};
var watchSet = new Set();
var _copyStatus = {copying:false, target:null};
var _wlEditMode = false;
var _feedInFlight = false;

var SORT_DEFS = [
  {key:'trending', label:'Trending'},
  {key:'gainers',  label:'Top gainers'},
  // +5% or more over 24h AND a $30K+ market cap -- server-computed in
  // api_market_scanner()'s uptrend_set, not just "gainers" re-labeled.
  {key:'uptrend',  label:'Uptrend (+5%, $30K+ MC)'},
  {key:'new',      label:'New pairs'},
  // Recently launched (any chain) but already past the riskiest early phase:
  // real 24h volume + real transaction activity -- server-computed in
  // api_market_scanner()'s graduated_set (GRADUATED_* constants).
  {key:'graduated', label:'Graduated'},
  {key:'volume',   label:'Volume leaders'},
  {key:'friends',  label:'Friends buying'}
];

/* ── chart (custom SVG: candlesticks, volume, dotted
   current-price line, price pill, timeframe pills, time axis) ── */
var _chartTimers = {}; // idx -> {destroyed, mint, pair, tf, timer}

function updateAxis(idx, candles){
  var axisEl = document.getElementById('pt-chart-axis-'+idx);
  if(!axisEl) return;
  if(!candles.length){ axisEl.innerHTML=''; return; }
  var n = candles.length;
  var picks = [0, Math.floor(n*0.25), Math.floor(n*0.5), Math.floor(n*0.75), n-1];
  var seen = {}, html = '';
  picks.forEach(function(i){
    if(seen[i]) return; seen[i]=true;
    var d = new Date(candles[i].t*1000);
    var hh = ('0'+d.getHours()).slice(-2);
    var mm = ('0'+d.getMinutes()).slice(-2);
    html += '<span>'+hh+':'+mm+'</span>';
  });
  axisEl.innerHTML = html;
}

function renderChartSvg(idx, candles, currentPrice){
  var svg  = document.getElementById('pt-chart-svg-'+idx);
  var wrap = document.getElementById('pt-chart-wrap-'+idx);
  if(!svg || !wrap) return;
  var w = wrap.clientWidth || 300;
  var h = svg.clientHeight || 200;
  svg.setAttribute('viewBox', '0 0 '+w+' '+h);

  if(!candles || !candles.length){
    var oldPill0 = wrap.querySelector('.pt-price-pill');
    if(oldPill0) oldPill0.remove();
    var oldWait=wrap.querySelector('.pt-chart-waiting');
    if(oldWait) oldWait.remove();
    svg.innerHTML = '';
    if(!wrap.querySelector('.pt-chart-empty')){
      var emptyEl = document.createElement('div');
      emptyEl.className = 'pt-chart-empty';
      emptyEl.textContent = 'Not enough data yet';
      wrap.insertBefore(emptyEl, wrap.querySelector('.pt-chart-axis'));
    }
    updateAxis(idx, []);
    return;
  }
  var stale = wrap.querySelector('.pt-chart-empty');
  if(stale) stale.remove();

  var values = candles.map(function(c){ return Number(c.c)||0; });
  var lows = candles.map(function(c){ return Number(c.l!=null?c.l:c.c)||0; });
  var highs = candles.map(function(c){ return Number(c.h!=null?c.h:c.c)||0; });
  var min = Math.min.apply(null, lows), max = Math.max.apply(null, highs);
  // On the token page of a token you hold, "You bought at" is always in view.
  var entryPx = _pfEntryPrice(idx);
  if(entryPx > 0){ min = Math.min(min, entryPx); max = Math.max(max, entryPx); }
  if(min===max){ min = min*0.98; max = (max*1.02)||1; }
  var pad = (max-min)*0.12;
  min = Math.max(0,min-pad); max += pad;

  // The right-hand price labels get as much room as the longest one needs
  // (9px monospace is ~5.4px per character). A fixed 46px cut sub-cent
  // labels like "0.000158" off at the card edge.
  var axisLabels=[], axisChars=0;
  for(var ai=0;ai<5;ai++){
    var lbl=fmtAxisPrice(max-((max-min)/4)*ai);
    axisLabels.push(lbl); axisChars=Math.max(axisChars,lbl.length);
  }
  var axisW=Math.max(46,Math.ceil(axisChars*5.4)+9);
  var n = candles.length, priceH = h*.77, volTop = h*.79, volH = h*.18;
  var pts = candles.map(function(c,i){
    var x = n===1 ? (w-axisW)/2 : (i/(n-1))*(w-axisW);
    var y = priceH - ((c.c-min)/(max-min))*priceH;
    return {x:x, y:y};
  });

  var priceVal = (currentPrice!=null && currentPrice>0) ? currentPrice : values[values.length-1];
  var priceY = priceH - ((priceVal-min)/(max-min))*priceH;
  priceY = Math.max(3, Math.min(priceH-3, priceY));

  // Scrubbing (see attachScrub()) reads these off the timer state -- kept
  // in the exact same {x,y} pixel space the SVG itself was just drawn in
  // (viewBox="0 0 w h"), and paired 1:1 with `candles` by index, so a
  // pointer position maps straight to "nearest x" -> "that candle's price
  // and time" with no unit conversion.
  var st = _chartTimers[idx];
  if(st){ st.pts = pts; st.candles = candles; st.min = min; st.max = max; st.h = h; st.w = w; st.priceH = priceH; st.plotW = w-axisW; }

  // Gold line + area (the approved "gold chart" look), not red/green
  // candles: one continuous gold price line over a soft gold gradient, a
  // dashed guide and glowing dot at the live price, faint gold volume.
  // Reads as a clean exchange-style line chart and stays honest with sparse
  // history -- a young token with few bars is still one clear line.
  var maxVol = Math.max.apply(null,candles.map(function(c){return Number(c.v)||0;}))||1;
  var plotW=w-axisW, step=plotW/Math.max(n,1), barW=Math.max(1.5,Math.min(6,step*.55)), chartHtml='';
  var gid='ptGoldGrad'+String(idx).replace(/[^a-zA-Z0-9_-]/g,'_');
  chartHtml+='<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1">'
    +'<stop offset="0%" stop-color="#f7b955" stop-opacity=".30"></stop>'
    +'<stop offset="100%" stop-color="#f7b955" stop-opacity="0"></stop></linearGradient></defs>';
  for(var gy=0;gy<5;gy++){
    var yy=(priceH/4)*gy, label=axisLabels[gy];
    chartHtml+='<line x1="0" y1="'+yy.toFixed(2)+'" x2="'+plotW.toFixed(2)+'" y2="'+yy.toFixed(2)+'" stroke="#1a2530" stroke-width="1" vector-effect="non-scaling-stroke"></line>';
    chartHtml+='<text x="'+(plotW+5).toFixed(2)+'" y="'+Math.max(10,yy+4).toFixed(2)+'" fill="#657180" font-size="9" font-family="monospace">'+label+'</text>';
  }
  candles.forEach(function(c,i){
    var vh=((Number(c.v)||0)/maxVol)*volH;
    if(vh>0.5) chartHtml+='<rect x="'+(pts[i].x-barW/2).toFixed(2)+'" y="'+(volTop+volH-vh).toFixed(2)+'" width="'+barW.toFixed(2)+'" height="'+vh.toFixed(2)+'" fill="#f7b955" opacity=".16"></rect>';
  });
  // The line ends exactly at the live price, like the pill beside it.
  pts[pts.length-1] = {x:pts[pts.length-1].x, y:priceY};
  var head='';
  for(var pi=0;pi<pts.length-1;pi++) head+=(pi?' L':'M')+pts[pi].x.toFixed(2)+' '+pts[pi].y.toFixed(2);
  var lastPt=pts[pts.length-1], firstX=pts[0].x;
  var lineD=head+(head?' L':'M')+lastPt.x.toFixed(2)+' '+lastPt.y.toFixed(2);
  var areaD=lineD+' L'+lastPt.x.toFixed(2)+' '+priceH.toFixed(2)+' L'+firstX.toFixed(2)+' '+priceH.toFixed(2)+' Z';
  if(st){ st.lineHead=head; st.lastX=lastPt.x; st.firstX=firstX; }
  if(n>1){
    chartHtml+='<path id="pt-live-area-'+idx+'" d="'+areaD+'" fill="url(#'+gid+')"></path>';
    chartHtml+='<path id="pt-live-line-'+idx+'" d="'+lineD+'" fill="none" stroke="#f7b955" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>';
  }
  if(entryPx > 0){
    var entryY = Math.max(12, Math.min(priceH-2, priceH - ((entryPx-min)/(max-min))*priceH));
    chartHtml+='<line class="pt-pf-entry" x1="0" y1="'+entryY.toFixed(2)+'" x2="'+plotW.toFixed(2)+'" y2="'+entryY.toFixed(2)+'" stroke="#8e97a3" stroke-width="1" stroke-dasharray="4,5" opacity=".7" vector-effect="non-scaling-stroke"></line>';
    chartHtml+='<text class="pt-pf-entry-t" x="4" y="'+(entryY-6).toFixed(2)+'" fill="#b8c0ca" font-size="10" font-family="JetBrains Mono, monospace">'+esc('You bought at '+fmtPrice(entryPx))+'</text>';
  }
  chartHtml+='<line id="pt-live-guide-'+idx+'" x1="0" y1="'+priceY.toFixed(2)+'" x2="'+plotW.toFixed(2)+'" y2="'+priceY.toFixed(2)+'" stroke="#f7b955" stroke-width="1" stroke-dasharray="4,4" opacity=".6" vector-effect="non-scaling-stroke"></line>';
  chartHtml+='<circle id="pt-live-halo-'+idx+'" cx="'+lastPt.x.toFixed(2)+'" cy="'+priceY.toFixed(2)+'" r="7" fill="#f7b955" opacity=".18"></circle>';
  chartHtml+='<circle id="pt-live-dot-'+idx+'" cx="'+lastPt.x.toFixed(2)+'" cy="'+priceY.toFixed(2)+'" r="3.2" fill="#f7b955"></circle>';
  svg.innerHTML=chartHtml;
  var waiting=wrap.querySelector('.pt-chart-waiting');
  if(n<2){
    if(!waiting){waiting=document.createElement('div');waiting.className='pt-chart-waiting';wrap.appendChild(waiting);}
    waiting.textContent='First price is in · the chart draws itself as this token trades';
  }else if(waiting) waiting.remove();

  // Reused across renders (not removed+recreated) so the CSS `top`
  // transition on .pt-price-pill actually animates between positions
  // instead of jumping -- a fresh element each render has no "previous
  // value" for the browser to transition from.
  var pill = wrap.querySelector('.pt-price-pill');
  if(!pill){
    pill = document.createElement('div');
    pill.className = 'pt-price-pill';
    wrap.insertBefore(pill, wrap.querySelector('.pt-chart-axis'));
  }
  pill.style.top = priceY+'px';
  pill.textContent = fmtPrice(priceVal);
  if(st) st.renderedPrice = priceVal;

  updateAxis(idx, candles);
}

// Move only the still-forming candle. Rebuilding the complete SVG every two
// seconds caused visible flashing/jank on mobile, especially while swiping.
//
// Two things made this look like a series of little flicks-and-holds instead
// of one continuously moving line, the way a real exchange ticker reads:
//
// 1. The ease ran for only 220ms out of every ~2000ms between price ticks
//    (tickLivePrices' _pricePollBaseMs) -- 90% of the time the line was
//    sitting dead still, waiting for the next tick to give it something to
//    do. Duration now tracks the poll cadence instead of a fixed 220ms, so
//    the line is still easing toward the last known price when the next one
//    lands, rather than resting between moves.
// 2. `previous` was read from st.renderedPrice, which this function itself
//    only ever set once an animation finished -- so a tick that arrived
//    before the prior one's ease completed (normal: network jitter routinely
//    makes two ticks land closer than the nominal 2s apart) restarted the
//    ease from wherever the LAST completed animation ended, not from the
//    line's actual current on-screen position -- a visible snap backwards
//    before it eased forward again. st.animPrice is now updated on every
//    single frame, completed or not, so a new tick always continues from
//    the line's true current position.
function updateLiveChartPrice(idx, nextPrice){
  var st=_chartTimers[idx], wrap=document.getElementById('pt-chart-wrap-'+idx);
  if(!st || !wrap || !st.candles || !st.candles.length || !(nextPrice>0)) return;
  var last=st.candles[st.candles.length-1];
  var previous=Number((st.liveRaf&&st.animPrice!=null)?st.animPrice:(st.renderedPrice||last.c||nextPrice));
  last.c=nextPrice; last.h=Math.max(Number(last.h||nextPrice),nextPrice); last.l=Math.min(Number(last.l||nextPrice),nextPrice);
  // A move outside the current scale needs fresh axes; ordinary ticks stay
  // GPU-smooth. "Outside" includes the top 16px: a rising price drawn up
  // there puts the live price tag under the 1M/5M/1H/4H/1D buttons, so it
  // rescales first and keeps its headroom.
  var nextY=st.priceH-((nextPrice-st.min)/(st.max-st.min))*st.priceH;
  if(nextPrice<=st.min || nextPrice>=st.max || nextY<16){ renderChartSvg(idx,st.candles,nextPrice); return; }
  var line=document.getElementById('pt-live-line-'+idx), area=document.getElementById('pt-live-area-'+idx);
  var dot=document.getElementById('pt-live-dot-'+idx), halo=document.getElementById('pt-live-halo-'+idx), guide=document.getElementById('pt-live-guide-'+idx);
  var pill=wrap.querySelector('.pt-price-pill');
  if(!dot || !guide || st.lastX==null){ renderChartSvg(idx,st.candles,nextPrice); return; }
  if(st.liveRaf) _routeScope.cancelAnimationFrame(st.liveRaf);
  var started=performance.now(), duration=Math.max(900,(typeof _pricePollBaseMs==='number'?_pricePollBaseMs:2000)-150);
  var head=st.lineHead||'', lx=Number(st.lastX).toFixed(2), fx=Number(st.firstX).toFixed(2), base=Number(st.priceH).toFixed(2);
  function frame(now){
    var q=Math.min(1,(now-started)/duration), eased=1-Math.pow(1-q,3), p=previous+(nextPrice-previous)*eased;
    st.animPrice=p;
    var yc=(st.priceH-((p-st.min)/(st.max-st.min))*st.priceH).toFixed(2);
    // Only the line's live end moves; every settled point stays put.
    var d=head+(head?' L':'M')+lx+' '+yc;
    if(line) line.setAttribute('d', d);
    if(area) area.setAttribute('d', d+' L'+lx+' '+base+' L'+fx+' '+base+' Z');
    dot.setAttribute('cy', yc); if(halo) halo.setAttribute('cy', yc);
    guide.setAttribute('y1',yc); guide.setAttribute('y2',yc);
    if(st.pts && st.pts.length) st.pts[st.pts.length-1].y=Number(yc);
    if(pill){pill.style.top=yc+'px'; pill.textContent=fmtPrice(p);}
    if(q<1) st.liveRaf=_routeScope.requestAnimationFrame(frame); else {st.liveRaf=null; st.animPrice=null; st.renderedPrice=nextPrice;}
  }
  st.liveRaf=_routeScope.requestAnimationFrame(frame);
}

// Touch/mouse "chart-scrub" for the hand-rolled SVG chart above (the
// LightweightCharts-based charts elsewhere in the app already get this via
// chart-scrub.js's attachChartScrub() -- this one is a plain SVG polyline,
// not a LightweightCharts instance, so that helper doesn't apply here; this
// is the same drag/hover -> nearest-point -> crosshair+tooltip idea, done
// in plain pixel math against the {x,y} points renderChartSvg() already
// computed (stored on the timer state each render).
// While a finger is on the chart the card's big price shows the price at
// that point, with the move since the start of the chart and its time --
// like Robinhood/Coinbase. Letting go puts the live price back.
function _scrubTimeLabel(ts){
  var d=new Date(ts*1000), now=new Date();
  var hm=('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2);
  if(d.toDateString()===now.toDateString()) return hm;
  var mon=['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'][d.getMonth()];
  return d.getDate()+' '+mon+' '+hm;
}
function _showScrubHeader(idx, st, i){
  var t=ST.tokens && ST.tokens[idx], c=st.candles && st.candles[i], first=st.candles && st.candles[0];
  if(!t || t.mint!==st.mint || !c) return;
  st.scrubbing=true;
  var px=Number(c.c)||0, base=Number(first.o||first.c)||0;
  var pct=base>0 ? (px/base-1)*100 : 0, down=pct<0;
  var el=document.getElementById('pt-price-'+idx);
  if(el){ el.textContent=fmtPrice(px); el.classList.add('pt-scrubbing'); el.classList.remove('pt-tick-up','pt-tick-down'); }
  if((el=document.getElementById('pt-chg-'+idx))){
    el.textContent=fmtPct(pct)+' · '+_scrubTimeLabel(c.t);
    el.classList.toggle('down',down); el.classList.toggle('up',!down);
  }
}
function _restoreLiveHeader(idx, st){
  if(!st || !st.scrubbing) return;
  st.scrubbing=false;
  var t=ST.tokens && ST.tokens[idx];
  if(!t || t.mint!==st.mint) return;
  var el=document.getElementById('pt-price-'+idx);
  if(el){ el.textContent=fmtPrice(t.price_usd); el.classList.remove('pt-scrubbing'); }
  if((el=document.getElementById('pt-chg-'+idx))){
    var down=(t.price_change_24h||0)<0;
    el.textContent=t.price_change_24h==null?'—':fmtPct(t.price_change_24h)+' · 24h';
    el.classList.toggle('down',down); el.classList.toggle('up',!down);
  }
}

function attachChartSvgScrub(idx){
  var wrap = document.getElementById('pt-chart-wrap-'+idx);
  var st   = _chartTimers[idx];
  if(!wrap || !st) return;

  var line = document.createElement('div'); line.className = 'pt-chart-scrub-line';
  var dot  = document.createElement('div'); dot.className  = 'pt-chart-scrub-dot';
  var tip  = document.createElement('div'); tip.className  = 'pt-chart-scrub-tip';
  wrap.appendChild(line); wrap.appendChild(dot); wrap.appendChild(tip);

  // touchmove can fire well over 60 times/second -- doing a full
  // getBoundingClientRect() + DOM update on every single one of those
  // (rather than once per actual screen refresh) is what made this feel
  // laggy/sluggish under a fast real-world swipe. Coalesce into "at most
  // one update per animation frame": a burst of events between two frames
  // now overwrites `pendingX` instead of queuing more work, and only the
  // latest position by the time the frame is due to paint gets applied.
  var rafId = null, pendingX = null, lastBest = -1, holdTimer = null;
  var touchIntent = null, touchStartX = 0, touchStartY = 0;
  wrap.style.touchAction = 'pan-y pinch-zoom';
  function scheduleScrub(clientX){
    pendingX = clientX;
    if(rafId != null) return;
    rafId = _routeScope.requestAnimationFrame(function(){
      rafId = null;
      doScrub(pendingX);
    });
  }
  function doScrub(clientX){
    var s = _chartTimers[idx];
    var svg = document.getElementById('pt-chart-svg-'+idx);
    if(!s || !svg || !s.pts || !s.pts.length) return;
    var svgRect  = svg.getBoundingClientRect();
    var wrapRect = wrap.getBoundingClientRect();
    if(!svgRect.width) return;
    var localX = Math.max(0, Math.min(svgRect.width, clientX - svgRect.left));
    // localX is real CSS pixels on the rendered <svg>; s.pts are in the
    // viewBox's own unit space (0..s.w) -- convert before nearest-point search
    // since preserveAspectRatio="none" means those two scales only match
    // when the box happens to render at exactly s.w px wide.
    var vbX = (localX / svgRect.width) * (s.w || svgRect.width);
    var pts = s.pts, best = 0, bestDiff = Math.abs(pts[0].x - vbX);
    for(var i=1;i<pts.length;i++){
      var diff = Math.abs(pts[i].x - vbX);
      if(diff < bestDiff){ best = i; bestDiff = diff; }
    }
    var c = s.candles && s.candles[best], pt = pts[best];
    if(!c || !pt) return;
    if(best !== lastBest){
      // A light tick under the finger per point, like an exchange app.
      if(lastBest >= 0 && touchIntent === 'scrub'){ try{ navigator.vibrate && navigator.vibrate(3); }catch(_){} }
      lastBest = best;
      _showScrubHeader(idx, s, best);
    }
    wrap.classList.add('pt-scrubbing');
    var svgTop = svgRect.top - wrapRect.top;
    var pxX = (pt.x / (s.w||1)) * svgRect.width  + (svgRect.left - wrapRect.left);
    var pxY = (pt.y / (s.h||1)) * svgRect.height + (svgRect.top  - wrapRect.top);
    // `transform: translate(...)`, never left/top -- keeps every per-frame
    // update on the compositor (GPU) instead of forcing a full layout+paint
    // each time, which is the other half of what made this feel sluggish.
    // The chart sits below the LIVE/timeframe row, so the line starts at
    // the chart's own top, not the card's.
    line.style.height    = svgRect.height+'px';
    line.style.display   = 'block';
    line.style.transform = 'translate('+pxX.toFixed(1)+'px,'+svgTop.toFixed(1)+'px)';
    dot.style.display    = 'block';
    var dw = (dot.offsetWidth || 8) / 2, dh = (dot.offsetHeight || 8) / 2;
    dot.style.transform  = 'translate('+(pxX-dw).toFixed(1)+'px,'+(pxY-dh).toFixed(1)+'px)';
    tip.textContent    = fmtPrice(c.c)+'  ·  '+_scrubTimeLabel(c.t);
    tip.style.display  = 'block';
    // Manually centered + clamped here (both axes) via the transform's own
    // offset -- there is no separate CSS transform layered on top (that
    // double-applied the centering and pushed the tooltip off-screen near
    // either edge; see the earlier fix for this same tooltip).
    var tipX = Math.max(4, Math.min(wrapRect.width - tip.offsetWidth - 4, pxX - tip.offsetWidth/2));
    // Follows the dragged point vertically (just above the dot) instead of
    // sitting fixed at the top of the chart, so it actually feels attached
    // to wherever the finger/cursor is -- clamped to the chart's own band
    // (4px..svgRect.height) so it never overlaps the LIVE/timeframe pills
    // above the chart or spills past the bottom into the axis labels.
    var tipH = tip.offsetHeight || 20;
    var tipY = Math.max(svgTop + 4, Math.min(svgTop + svgRect.height - tipH - 4, pxY - tipH - 10));
    tip.style.transform = 'translate('+tipX.toFixed(1)+'px,'+tipY.toFixed(1)+'px)';
  }
  function clearScrub(){
    if(rafId != null){ _routeScope.cancelAnimationFrame(rafId); rafId = null; }
    if(holdTimer){ _routeScope.clearTimeout(holdTimer); holdTimer = null; }
    line.style.display = 'none'; dot.style.display = 'none'; tip.style.display = 'none';
    wrap.classList.remove('pt-scrubbing');
    lastBest = -1;
    _restoreLiveHeader(idx, _chartTimers[idx]);
  }
  function onTouchStart(e){
    if(!e.touches[0]) return;
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    touchIntent = null;
    // Holding a finger still on the chart also starts scrubbing (then any
    // direction scrubs); a quick vertical swipe still scrolls the page.
    if(holdTimer) _routeScope.clearTimeout(holdTimer);
    holdTimer = _routeScope.setTimeout(function(){
      holdTimer = null;
      if(touchIntent != null) return;
      touchIntent = 'scrub';
      try{ navigator.vibrate && navigator.vibrate(8); }catch(_){}
      scheduleScrub(touchStartX);
    }, 260);
  }
  function onTouchMove(e){
    if(!e.touches[0]) return;
    var dx = e.touches[0].clientX - touchStartX;
    var dy = e.touches[0].clientY - touchStartY;
    if(touchIntent == null){
      if(Math.max(Math.abs(dx), Math.abs(dy)) < 7) return;
      if(holdTimer){ _routeScope.clearTimeout(holdTimer); holdTimer = null; }
      touchIntent = Math.abs(dx) > Math.abs(dy) * 1.15 ? 'scrub' : 'scroll';
    }
    if(touchIntent !== 'scrub'){ clearScrub(); return; }
    if(e.cancelable) e.preventDefault();
    scheduleScrub(e.touches[0].clientX);
  }
  function onMouseMove(e){ scheduleScrub(e.clientX); }
  _routeScope.addEventListener(wrap,'touchstart', onTouchStart, {passive:true});
  _routeScope.addEventListener(wrap,'touchmove', onTouchMove, {passive:false});
  _routeScope.addEventListener(wrap,'touchend', clearScrub, {passive:true});
  _routeScope.addEventListener(wrap,'touchcancel', clearScrub, {passive:true});
  _routeScope.addEventListener(wrap,'mousemove', onMouseMove);
  _routeScope.addEventListener(wrap,'mouseleave', clearScrub);

  st.scrubTeardown = function(){
    if(rafId != null){ _routeScope.cancelAnimationFrame(rafId); rafId = null; }
    wrap.removeEventListener('touchstart', onTouchStart);
    wrap.removeEventListener('touchmove', onTouchMove);
    wrap.removeEventListener('touchend', clearScrub);
    wrap.removeEventListener('touchcancel', clearScrub);
    wrap.removeEventListener('mousemove', onMouseMove);
    wrap.removeEventListener('mouseleave', clearScrub);
    [line, dot, tip].forEach(function(el){ if(el.parentNode) el.parentNode.removeChild(el); });
  };
}

// Chart history loads like an exchange app: whatever is already known
// paints immediately, the network only fills in behind it.
//  * Requests run in parallel (a few at a time). They used to go through a
//    strict one-at-a-time queue spaced 2.1s apart to spare GeckoTerminal's
//    rate limit, so the tenth card waited ~20s even when the server already
//    had its candles cached. The server now owns that limit (shared budget,
//    stale-while-revalidate, pre-warming from the scanner), so the browser
//    no longer has to wait on it.
//  * Every answer is kept per token+pair+timeframe, in memory and in
//    sessionStorage. Scrolling a card back into view, switching back to a
//    timeframe or reopening Live Market in the same session repaints at
//    once instead of starting from a single seed candle.
var _CHART_FETCH_CONCURRENCY = 4;
var _chartFetchQueue = [], _chartFetchActive = 0;
function drainChartFetchQueue(){
  while(_chartFetchActive < _CHART_FETCH_CONCURRENCY && _chartFetchQueue.length){
    var job=_chartFetchQueue.shift();
    if(!job) continue;
    if(job.state && job.state.destroyed){ job.resolve(null); continue; }
    _chartFetchActive++;
    _routeScope.fetch(job.url).then(function(r){return r.json();}).then(job.resolve,function(){job.resolve(null);})
      .then(function(){ _chartFetchActive--; drainChartFetchQueue(); });
  }
}
function fetchChart(mint, tf, pairAddr, chain, state){
  var url = '/api/chart/'+encodeURIComponent(mint)+'?tf='+encodeURIComponent(tf);
  if(pairAddr) url += '&pair='+encodeURIComponent(pairAddr);
  if(chain) url += '&chain='+encodeURIComponent(chain);
  return new Promise(function(resolve){
    // Newest request first: the card the user just scrolled to or the
    // timeframe they just tapped matters more than one already off screen.
    _chartFetchQueue.unshift({url:url,resolve:resolve,state:state});
    drainChartFetchQueue();
  });
}

var _CANDLE_CACHE_KEY = 'oa-lm-candles-v1', _CANDLE_CACHE_MAX = 60;
var _candleCache = (function(){
  try{ return JSON.parse(sessionStorage.getItem(_CANDLE_CACHE_KEY) || '{}') || {}; }catch(_){ return {}; }
})();
var _candleSaveTimer = null;
function candleCacheKey(mint, pair, tf){ return mint+'|'+(pair||'')+'|'+tf; }
function candleCacheGet(mint, pair, tf){
  var e=_candleCache[candleCacheKey(mint,pair,tf)];
  return (e && e.c && e.c.length) ? e : null;
}
function candleCachePut(mint, pair, tf, candles, price){
  if(!candles || !candles.length) return;
  _candleCache[candleCacheKey(mint,pair,tf)] = {c:candles, p:price, at:Date.now()};
  var keys=Object.keys(_candleCache);
  if(keys.length > _CANDLE_CACHE_MAX){
    keys.sort(function(a,b){ return (_candleCache[a].at||0)-(_candleCache[b].at||0); });
    keys.slice(0, keys.length-_CANDLE_CACHE_MAX).forEach(function(k){ delete _candleCache[k]; });
  }
  if(_candleSaveTimer) return;
  _candleSaveTimer=_routeScope.setTimeout(function(){
    _candleSaveTimer=null;
    try{ sessionStorage.setItem(_CANDLE_CACHE_KEY, JSON.stringify(_candleCache)); }catch(_){}
  }, 800);
}

function chartBucketSeconds(tf){
  return ({'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'D':86400})[tf] || 300;
}

function startObservedCandle(st, price){
  var seconds=chartBucketSeconds(st.tf), now=Math.floor(Date.now()/1000);
  return {t:Math.floor(now/seconds)*seconds,o:price,h:price,l:price,c:price,v:0};
}

// The card's own price (the scanner's, or the live tick once one arrived).
function _cardRefPrice(st, idx){
  var t=ST.tokens && ST.tokens[idx];
  if(t && t.mint===st.mint) return Number(t._livePx||t.price_usd)||0;
  return Number(st.seedPrice)||0;
}
// Candles that sit 10x or more away from the token's real price are another
// token's chart -- the other side of the pool -- not a price move. Never
// draw a $773 line beside a $0.001979 token; start from the real price.
function _candlesMatchPrice(candles, ref){
  if(!(ref>0) || !candles || !candles.length) return true;
  var c=Number(candles[candles.length-1].c)||0;
  if(!(c>0)) return true;
  var ratio=c/ref;
  return ratio<10 && ratio>0.1;
}

function chartTick(idx){
  var st = _chartTimers[idx];
  if(!st || st.destroyed) return;
  var requestedTf=st.tf;
  fetchChart(st.mint, requestedTf, st.pair, st.chain, st).then(function(r){
    if(!st || st.destroyed || st.tf!==requestedTf) return;
    var ref=_cardRefPrice(st, idx);
    if(r && r.candles && r.candles.length && !_candlesMatchPrice(r.candles, ref)){
      if(st.candles && st.candles.length && _candlesMatchPrice(st.candles, ref)) return;
      st.price=ref;
      st.candles=[startObservedCandle(st,ref)];
      renderChartSvg(idx,st.candles,ref);
      return;
    }
    if(r && r.candles && r.candles.length){
      // Kept so a live price can redraw this chart without fetching the
      // candles again -- the candles are the shape, the price is the movement.
      st.candles = r.candles;
      st.price   = r.current_price;
      candleCachePut(st.mint, st.pair, requestedTf, r.candles, r.current_price);
      renderChartSvg(idx, st.candles, st.price);
    } else if(!st.candles || !st.candles.length){
      // Some new/EVM pools expose a current price but no OHLC history.
      // Start one honest observed candle; subsequent real ticks form it.
      var px=Number((r&&r.current_price)||st.seedPrice||0);
      if(px>0){
        st.price=px;
        st.candles=[startObservedCandle(st,px)];
        renderChartSvg(idx,st.candles,px);
      }
    }
  });
}

/* ── LIVE PRICE ────────────────────────────────────────────────────────────
   The chart is drawn from 5-minute candles. Between two candles there is
   genuinely nothing new to draw, so it sat perfectly still and looked frozen
   -- polling the candles harder would not have changed that, because the data
   itself only changes every few minutes.

   What moves is the price right now. One request covers every chart on
   screen (the server batches up to 30 pools into a single upstream call), so
   this is cheaper than the chart polling it lets us slow down, not dearer. */
var _priceTimer = null;
var _priceInFlight = false;
var _priceFailures = 0;
var _priceNextAt = 0;
var _pricePollBaseMs = 1000;   // the chart price ticks every second

// The big price, the 24h change and the market cap on the card follow the
// same live tick as the chart. They used to change only with the 15s feed
// poll, whose scanner price can be minutes old -- so the header could read
// $0.000161 while the chart beside it was already at $0.000186.
function _flashTick(el, up){
  if(!el) return;
  el.classList.remove('pt-tick-up','pt-tick-down');
  void el.offsetWidth;   // restart the flash on back-to-back ticks
  el.classList.add(up?'pt-tick-up':'pt-tick-down');
  _routeScope.clearTimeout(el._tickTimer);
  el._tickTimer=_routeScope.setTimeout(function(){el.classList.remove('pt-tick-up','pt-tick-down');},700);
}
// Re-bases a token's 24h change and market cap from `from` to price `to`:
// both scale with price over the same 24h window / the same supply.
function _rebaseTokenPrice(t, from, to){
  if(from>0){
    var open=from/(1+(Number(t.price_change_24h)||0)/100);
    if(open>0 && isFinite(open)) t.price_change_24h=(to/open-1)*100;
    if(Number(t.market_cap)>0) t.market_cap=Number(t.market_cap)*to/from;
  }
  t.price_usd=to;
}
function _syncCardPrice(st, idx, px){
  var t=ST.tokens && ST.tokens[idx];
  if(!t || t.mint!==st.mint) return;
  var old=Number(t.price_usd)||0;
  t._livePx=px; t._liveAt=Date.now();
  if(old===px) return;
  _rebaseTokenPrice(t, old, px);
  if(st.scrubbing) return;   // the finger is on the chart; restored on release
  var el=document.getElementById('pt-price-'+idx);
  if(el){ el.textContent=fmtPrice(px); if(old>0) _flashTick(el, px>old); }
  if((el=document.getElementById('pt-chg-'+idx))){
    var down=(t.price_change_24h||0)<0;
    el.textContent=t.price_change_24h==null?'—':fmtPct(t.price_change_24h)+' · 24h';
    el.classList.toggle('down',down); el.classList.toggle('up',!down);
  }
  if((el=document.getElementById('pt-mcap-'+idx))) el.textContent=fmtUsd(t.market_cap);
}

function _applyLivePrice(st, idx, px){
  if(!st || st.destroyed) return;
  px=Number(px);
  if(!(px>0)) return;
  _syncCardPrice(st, idx, px);
  if(!st.candles || !st.candles.length || px===st.price) return;
  st.price=px;
  var last=st.candles[st.candles.length-1];
  var seconds=chartBucketSeconds(st.tf), now=Math.floor(Date.now()/1000);
  var bucket=Math.floor(now/seconds)*seconds;
  if(bucket>last.t){
    last=startObservedCandle(st,px);
    st.candles.push(last);
    if(st.candles.length>60)st.candles.shift();
    renderChartSvg(idx,st.candles,px);
    return;
  }
  last.c=px;
  if(px>last.h)last.h=px;
  if(px<last.l)last.l=px;
  updateLiveChartPrice(idx,px);
}

function tickLivePrices(){
  if(document.visibilityState!=='visible' || _priceInFlight || Date.now()<_priceNextAt)return;
  var groups={}, refs={};
  Object.keys(_chartTimers).forEach(function(idx){
    var st=_chartTimers[idx];
    if(!st||st.destroyed||!st.pair||!st.candles)return;
    var c=st.chain||'solana', key=(st.pair||'').toLowerCase();
    (groups[c]=groups[c]||[]).push(st.pair);
    (refs[c]=refs[c]||{})[key]=(refs[c][key]||[]).concat([idx]);
  });
  if(!Object.keys(groups).length)return;

  // Deduplicate pair addresses per chain before serializing the request.
  Object.keys(groups).forEach(function(c){
    var seen={};groups[c]=groups[c].filter(function(p){var k=String(p).toLowerCase();if(seen[k])return false;seen[k]=1;return true;});
  });
  _priceInFlight=true;
  // The next tick is due one interval after THIS one started, not after its
  // answer arrived: otherwise every tick drifts by the request time and the
  // scheduler granularity (it ran every ~1.5 s instead of every second).
  var tickStarted=Date.now();
  var qs=new URLSearchParams();
  qs.set('groups',JSON.stringify(groups));
  _routeScope.fetch('/api/market/prices-batch?'+qs.toString(),{credentials:'include',cache:'no-store'})
    .then(function(r){
      if(r.status===429||r.status===503){var e=new Error('backoff');e.retryable=true;throw e;}
      if(!r.ok)throw new Error('price batch failed');
      return r.json();
    })
    .then(function(d){
      if(!d||!d.chains)return;
      Object.keys(d.chains).forEach(function(chain){
        var prices=d.chains[chain]||{};
        Object.keys(prices).forEach(function(pair){
          var ids=(refs[chain]&&refs[chain][pair.toLowerCase()])||[];
          ids.forEach(function(i){_applyLivePrice(_chartTimers[i],i,prices[pair]);});
        });
      });
      _priceFailures=0;
      _priceNextAt=tickStarted+_pricePollBaseMs;
    })
    .catch(function(){
      _priceFailures=Math.min(_priceFailures+1,3);
      _priceNextAt=Date.now()+Math.min(8000,_pricePollBaseMs*Math.pow(2,_priceFailures));
    })
    .finally(function(){_priceInFlight=false;});
}

function startLivePrices(){
  if(_priceTimer)return;
  tickLivePrices();
  // Small scheduler tick, actual network cadence is controlled by
  // _priceNextAt. This avoids overlapping requests and gives 429/503 an
  // exponential backoff instead of immediately hammering the same endpoint.
  _priceTimer=_routeScope.setInterval(tickLivePrices,250);
  _routeScope.addEventListener(document,'visibilitychange',function(){
    if(document.visibilityState==='visible'){
      _priceNextAt=0;
      tickLivePrices();
    }
  });
}

// `chain` defaults to 'solana' -- the API's own default -- so a caller that
// doesn't know/care about chain (there weren't any before this) still gets
// the exact prior behavior.
function primeChart(idx, mint, pairAddr, chain, seedPrice){
  if(_chartTimers[idx]) return _chartTimers[idx];
  var st = {destroyed:false, mint:mint, pair:pairAddr, chain:(chain||'solana'), seedPrice:Number(seedPrice)||0, tf:'5m', timer:null};
  _chartTimers[idx] = st;
  // Already seen this session: paint the real history immediately.
  var cached=candleCacheGet(mint,pairAddr,st.tf);
  if(cached && !_candlesMatchPrice(cached.c, st.seedPrice)) cached=null;
  if(cached){
    st.candles=cached.c.slice();
    st.price=st.seedPrice>0?st.seedPrice:(Number(cached.p)||cached.c[cached.c.length-1].c);
    renderChartSvg(idx,st.candles,st.price);
    return st;
  }
  // Otherwise paint one still-forming candle from the scanner's observed
  // real price. Provider history replaces it as soon as it arrives.
  if(st.seedPrice>0){
    st.price=st.seedPrice;
    st.candles=[startObservedCandle(st,st.seedPrice)];
    renderChartSvg(idx,st.candles,st.seedPrice);
  }
  return st;
}
function mountChart(idx, mint, pairAddr, chain, seedPrice){
  var st=primeChart(idx,mint,pairAddr,chain,seedPrice);
  if(st.timer) return;
  chartTick(idx);
  // A one-point chart needs provider history as soon as the cache refreshes;
  // established charts can wait. Server caches chart responses for 30s.
  st.timer = _routeScope.setInterval(function(){
    if(!document.hidden && (st.candles||[]).length<2) chartTick(idx);
  }, 30000);
  st.slowTimer=_routeScope.setInterval(function(){
    if(!document.hidden && (st.candles||[]).length>=2) chartTick(idx);
  }, 300000);
  attachChartSvgScrub(idx);
}
function unmountChart(idx){
  var st = _chartTimers[idx];
  if(!st) return;
  st.destroyed = true;
  if(st.timer) _routeScope.clearInterval(st.timer);
  if(st.slowTimer) _routeScope.clearInterval(st.slowTimer);
  if(st.liveRaf) _routeScope.cancelAnimationFrame(st.liveRaf);
  if(st.scrubTeardown) st.scrubTeardown();
  delete _chartTimers[idx];
}
function setChartTf(idx, tf){
  var st = _chartTimers[idx];
  if(!st) return;
  st.tf = tf;
  var cached=candleCacheGet(st.mint,st.pair,tf);
  if(cached && !_candlesMatchPrice(cached.c, st.price||st.seedPrice)) cached=null;
  if(cached){
    st.candles=cached.c.slice();
    renderChartSvg(idx,st.candles,st.price>0?st.price:cached.p);
  } else if(st.price>0){
    st.candles=[startObservedCandle(st,st.price)];
    renderChartSvg(idx,st.candles,st.price);
  }
  chartTick(idx);
}

/* ── per-card lazy loading (safety badges, friends/holders footer) ── */
var _lazyDone = {};
var _cardObserver = null;

function fetchSafety(idx, mint){
  var el = document.getElementById('pt-safety-'+idx);
  _routeScope.fetch('/api/token/'+encodeURIComponent(mint)+'/safety', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d && d.ok){ _pfSafety[mint] = d; _pfRefresh(mint); }
      if(!el) return;
      if(!d || !d.ok){ el.innerHTML=''; return; }
      var lpOk = (d.lp_locked_pct||0) >= 50;
      var mintOk = !d.mint_authority_active && !d.freeze_authority_active;
      el.innerHTML = '<span class="pt-badge '+(lpOk?'ok':'bad')+'"><span class="ico">'+(lpOk?'✓':'✕')+'</span>LP</span>'
        + '<span class="pt-badge '+(mintOk?'ok':'bad')+'"><span class="ico">'+(mintOk?'✓':'✕')+'</span>Mint</span>';
    }).catch(function(){ if(el) el.innerHTML=''; });
}

function fetchFriends(idx, mint){
  var friendsEl = document.getElementById('pt-friends-'+idx);
  // Shown only when someone you follow holds it: a zero chip on every card
  // was noise (and the footer hides itself when it has nothing to show).
  _routeScope.fetch('/api/token/'+encodeURIComponent(mint)+'/co-traders', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      var users = (d && d.ok && d.users) || [];
      (_pfCommunity[mint] = _pfCommunity[mint] || {}).users = users; _pfRefresh(mint);
      if(!friendsEl) return;
      if(!users.length){ friendsEl.innerHTML = ''; return; }
      var avs = users.slice(0,3).map(function(u){
        return u.avatar_url
          ? '<img src="'+esc(u.avatar_url)+'">'
          : '<div class="ph">'+esc((u.username||'?').slice(0,1).toUpperCase())+'</div>';
      }).join('');
      friendsEl.innerHTML = '<div class="pt-friend-avs">'+avs+'</div><span>'+users.length+' friend'+(users.length===1?'':'s')+'</span>';
    }).catch(function(){
      if(friendsEl) friendsEl.innerHTML = '';
    });

  _routeScope.fetch('/api/token/'+encodeURIComponent(mint)+'/holders', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d && d.ok){ (_pfCommunity[mint] = _pfCommunity[mint] || {}).holders = Number(d.platform_holders)||0; _pfRefresh(mint); }
      var ftEl = document.getElementById('pt-ft-stats-'+idx);
      if(!ftEl || !d || !d.ok) return;
      var t = ST.tokens[Number(idx)];
      var txns = t ? ((Number(t.buys_24h)||0)+(Number(t.sells_24h)||0)) : 0;
      var txnsStr = txns >= 1000 ? (txns/1000).toFixed(1)+'K' : String(txns);
      // 'holders' here is a count of OrcAgent users with a position in this
      // token, NOT the real on-chain holder count (DexScreener's API, which
      // powers every other stat on this card, doesn't expose that) -- kept
      // as its own small chip, clearly scoped to "on OrcAgent" rather than
      // implying it's the token's total holder count. Shown only when
      // someone holds it; the buy/sell split is already in the stats above.
      var holders = Number(d.platform_holders)||0;
      ftEl.innerHTML = (holders ? '<span class="pt-ft-chip">👤 '+holders+' on OrcAgent</span>' : '')
        + (txns ? '<span class="pt-ft-chip">'+txnsStr+' txns</span>' : '');
    }).catch(function(){});
}

function activateCard(card){
  var idx = card.dataset.idx, mint = card.dataset.mint, pair = card.dataset.pair;
  var t = ST.tokens[Number(idx)];
  mountChart(idx, mint, pair, t ? t.chain : 'solana', t ? t.price_usd : 0);
  var done = _lazyDone[idx] || (_lazyDone[idx] = {});
  if(!done.safety){ done.safety = true; fetchSafety(idx, mint); }
  if(!done.friends){ done.friends = true; fetchFriends(idx, mint); }
}

function observeCards(){
  var cards = document.querySelectorAll('.pt-card');
  if(_cardObserver) _cardObserver.disconnect();
  // Give all cards a synchronous real-price chart. Only cards near the
  // viewport continue into history/live polling, so this removes blank cards
  // during a fast scroll without firing thirty chart API calls at once.
  cards.forEach(function(card){
    var idx=card.dataset.idx,t=ST.tokens[Number(idx)];
    primeChart(idx,card.dataset.mint,card.dataset.pair,t?t.chain:'solana',t?t.price_usd:0);
  });
  if(!('IntersectionObserver' in window)){
    cards.forEach(activateCard);
    return;
  }
  _cardObserver = _routeScope.intersectionObserver(function(entries){
    entries.forEach(function(entry){
      var idx = entry.target.dataset.idx;
      if(entry.isIntersecting) activateCard(entry.target);
      else unmountChart(idx);
    });
  }, {rootMargin:'250px 0px', threshold:0.01});
  cards.forEach(function(c){ _cardObserver.observe(c); });
}

function resetCardState(){
  Object.keys(_chartTimers).forEach(unmountChart);
  _lazyDone = {};
}

/* ── markup builders ── */
function logoTile(imgUrl, symbol, cls, phCls){
  var initials = esc((symbol||'?').slice(0,2).toUpperCase());
  var safeUrl = safeMediaUrl(imgUrl);
  if(!safeUrl) return '<div class="'+phCls+'">'+initials+'</div>';
  return '<img class="'+cls+'" src="'+esc(safeUrl)+'" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">'
    + '<div class="'+phCls+'" style="display:none">'+initials+'</div>';
}
function statRow(lbl, val, id){
  return '<div class="pt-stat-row"><span class="pt-stat-lbl">'+lbl+'</span><span class="pt-stat-val mono"'+(id?' id="'+id+'"':'')+'>'+val+'</span></div>';
}
function starsHtml(score){
  var n = Math.max(0, Math.min(5, score||0));
  var cls = n>=4 ? 's-hi' : (n===3 ? 's-mid' : 's-lo');
  var str = '';
  for(var i=0;i<5;i++) str += i<n ? '★' : '☆';
  return '<span class="pt-stars '+cls+'">'+str+'</span>';
}
function tfPill(tf, label, active){
  return '<button class="pt-tf-pill'+(active?' active':'')+'" data-tf="'+tf+'">'+label+'</button>';
}
/* OrcAgent is Solana-only. Older cached scanner responses that omit a chain
   are treated as Solana so they never render blank. */
var CHAIN_LABELS = {solana:'SOL'};
// All active trades spend and receive native SOL.
function evmCurrencyLabel(chain){ return 'SOL'; }
function chainLabel(chain){ return CHAIN_LABELS[chain] || 'SOL'; }
function shortAddr(addr){
  addr = addr || '';
  return addr.length > 10 ? addr.slice(0, 4) + '…' + addr.slice(-4) : addr;
}
// Falls back to the legacy execCommand path when navigator.clipboard isn't
// available (older in-app webviews, non-HTTPS) rather than silently doing
// nothing -- copying the contract address is the entire point of this button.
function copyToClipboard(text){
  if(navigator.clipboard && navigator.clipboard.writeText){
    return navigator.clipboard.writeText(text);
  }
  return new Promise(function(resolve, reject){
    try{
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus(); ta.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error('execCommand copy failed'));
    }catch(e){ reject(e); }
  });
}
function copyCA(mint, el){
  copyToClipboard(mint).then(function(){
    toast('Contract address copied');
    if(el){
      var textEl = el.querySelector('.pt-tok-ca-text');
      if(textEl){
        var orig = textEl.textContent;
        textEl.textContent = 'Copied!';
        _routeScope.setTimeout(function(){ textEl.textContent = orig; }, 1200);
      }
    }
  }).catch(function(){ toast('Could not copy — long-press the address instead'); });
}
function chainBadgeHtml(chain){
  var c = CHAIN_LABELS[chain] ? chain : 'solana';
  return '<span class="pt-chain-badge chain-'+c+'"><span class="pt-chain-dot"></span>'+chainLabel(c)+'</span>';
}
// http(s)-only -- these URLs come from DexScreener's token metadata, which
// anyone launching a token controls, so a javascript:/data: URI slipped in
// as a "website" link must never make it into an href.
function isSafeUrl(u){
  return typeof u === 'string' && /^https?:\/\//i.test(u);
}
// Only rendered when a token actually has at least one link -- no empty
// placeholder row for tokens without socials.
function socialsHtml(t){
  var links = [];
  if(isSafeUrl(t.twitter_url))  links.push({url:t.twitter_url,  cls:'x',   label:'𝕏', title:'X (Twitter)'});
  if(isSafeUrl(t.telegram_url)) links.push({url:t.telegram_url, cls:'tg',  label:'✈', title:'Telegram'});
  if(isSafeUrl(t.website_url))  links.push({url:t.website_url,  cls:'web', label:'🌐', title:'Website'});
  if(!links.length) return '';
  return '<div class="pt-tok-socials">' + links.map(function(l){
    return '<a class="pt-tok-social pt-tok-social-'+l.cls+'" href="'+esc(l.url)+'" target="_blank" rel="noopener noreferrer" title="'+esc(l.title)+'">'+l.label+'</a>';
  }).join('') + '</div>';
}

function cardHtml(t, idx){
  var down = (t.price_change_24h||0) < 0;
  var isWatched = watchSet.has(t.mint);
  return '<div class="pt-card'+(t.score>=4?' hi':'')+'" id="pt-card-'+idx+'" data-mint="'+esc(t.mint)+'" data-idx="'+idx+'" data-pair="'+esc(t.pair_address||'')+'">'
    + '<div class="pt-card-hd">'
    +   logoTile(t.image_url, t.symbol, 'pt-tok-logo', 'pt-tok-logo-ph')
    +   '<div class="pt-tok-id"><div class="pt-tok-sym">$'+esc(t.symbol)+' '+starsHtml(t.score)+chainBadgeHtml(t.chain)+'</div>'
    +   '<div class="pt-tok-meta">'+esc(t.name||t.symbol)+' · '+fmtAge(t.pair_created_at)+' old'+(t.source==='solana_bonding_curve'?' · onchain':'')+'</div>'
    +   '<div class="pt-tok-ca-row">'
    +     '<div class="pt-tok-ca" data-action="copy-ca" data-mint="'+esc(t.mint)+'" title="'+esc(t.mint)+'">'
    +       '<span class="pt-tok-ca-text mono">'+esc(shortAddr(t.mint))+'</span>'
    +       '<span class="pt-tok-ca-icon">⧉</span>'
    +     '</div>'
    +     socialsHtml(t)
    +   '</div></div>'
    +   '<div class="pt-card-hd-right">'
    +     '<span id="pt-safety-'+idx+'"></span>'
    +     '<button class="pt-profile-btn" type="button" data-action="token-profile" data-mint="'+esc(t.mint)+'" aria-label="Open token profile" title="Open token profile">Profile</button>'
    +     '<button class="pt-watch-btn'+(isWatched?' active':'')+'" data-action="watch" data-mint="'+esc(t.mint)+'" data-sym="'+esc(t.symbol)+'">'+(isWatched?'★':'☆')+'</button>'
    +   '</div>'
    + '</div>'
    + '<div class="pt-card-body">'
    +   '<div class="pt-card-stats">'
    +     '<div class="pt-price mono" id="pt-price-'+idx+'">'+fmtPrice(t.price_usd)+'</div>'
    +     '<div class="pt-chg mono '+(down?'down':'up')+'" id="pt-chg-'+idx+'">'+(t.price_change_24h==null?'—':fmtPct(t.price_change_24h)+' · 24h')+'</div>'
    +     statRow('Liquidity', fmtUsd(t.liquidity_usd), 'pt-liq-'+idx)
    +     statRow('Market cap', fmtUsd(t.market_cap), 'pt-mcap-'+idx)
    +     statRow('Volume 24h', fmtUsd(t.volume_24h), 'pt-vol-'+idx)
    +     statRow('Buy / Sell', ratioStr(t.buys_24h, t.sells_24h), 'pt-ratio-'+idx)
    +     '<div class="pt-trade-btns">'
    +       '<button class="pt-buy-btn" data-action="buy-open" data-idx="'+idx+'">Buy</button>'
    +       '<button class="pt-sell-btn" data-action="sell" data-idx="'+idx+'">Sell</button>'
    +     '</div>'
    +     '<div class="pt-buy-panel" id="pt-buy-panel-'+idx+'" style="display:none"></div>'
    +   '</div>'
    +   '<div class="pt-chart-wrap" id="pt-chart-wrap-'+idx+'">'
    +     '<svg class="pt-chart-svg" id="pt-chart-svg-'+idx+'" preserveAspectRatio="none"></svg>'
    +     '<div class="pt-chart-live"><span class="pt-chart-live-dot"></span>LIVE</div>'
    +     '<div class="pt-chart-tfs" id="pt-chart-tfs-'+idx+'">'
    +       tfPill('1m','1M') + tfPill('5m','5M', true) + tfPill('1h','1H') + tfPill('4h','4H') + tfPill('D','1D')
    +     '</div>'
    +     '<div class="pt-chart-axis" id="pt-chart-axis-'+idx+'"></div>'
    +   '</div>'
    + '</div>'
    + '<div class="pt-card-ft">'
    +   '<div class="pt-friends" id="pt-friends-'+idx+'"></div>'
    +   '<div class="pt-card-ft-right mono" id="pt-ft-stats-'+idx+'"></div>'
    + '</div>'
    + '<section class="pt-profile-about" aria-label="Token profile details"></section>'
    + '</div>';
}

/* ── left rail: sort / toggles / liquidity / age ── */
function renderSortList(){
  var el = document.getElementById('pt-sort-list');
  el.innerHTML = SORT_DEFS.map(function(s){
    var c = ST.counts[s.key]!=null ? ST.counts[s.key] : 0;
    return '<div class="pt-sort-row'+(ST.sort===s.key?' active':'')+'" data-sort="'+s.key+'">'
      + '<span>'+s.label+'</span><span class="pt-sort-count">'+c+'</span></div>';
  }).join('');
}
function setSort(s){ ST.sort = s; renderSortList(); loadFeed(); closeMobileOverlays(); }
function setAge(a){
  ST.age = a;
  document.querySelectorAll('.pt-age-chip').forEach(function(c){ c.classList.toggle('active', c.dataset.age===a); });
  updateAdvCount();
  loadFeed();
}
var _FILTER_KEYS = {lp_locked:'lpLocked', mint_revoked:'mintRevoked', hide_honeypots:'hideHoneypots', verified_socials:'verifiedSocials'};
function toggleFilter(row){
  var stateKey = _FILTER_KEYS[row.dataset.filter];
  ST[stateKey] = !ST[stateKey];
  // The row is the button now; the switch inside it is the picture of the
  // state. Both are updated here so neither can be read as the truth alone.
  var sw = row.querySelector('.pt-switch');
  if(sw) sw.classList.toggle('on', ST[stateKey]);
  row.setAttribute('aria-pressed', ST[stateKey] ? 'true' : 'false');
  updateAdvCount();
  loadFeed();
}

// How many filters are actually doing something, shown on the collapsed row.
// Without it, folding the block hides whether anything is on — which is worse
// than the clutter it replaced, because a feed narrowed by a forgotten filter
// looks like a feed with nothing in it.
var _LIQ_DEFAULT = 0;
function updateAdvCount(){
  var n = 0;
  for(var k in _FILTER_KEYS){ if(ST[_FILTER_KEYS[k]]) n++; }
  if(ST.age && ST.age !== 'any') n++;
  if(Number(ST.minLiquidity) !== _LIQ_DEFAULT) n++;
  var el = document.getElementById('pt-adv-count');
  if(el) el.textContent = n ? (n + ' on') : '';
}

/* ── feed loading ── */
var _FEED_CACHE_KEY='orcaLiveMarketFeedV2';
function _defaultFeedState(){
  return ST.sort==='trending' && Number(ST.minLiquidity)===0 && ST.age==='any'
    && !ST.lpLocked && !ST.mintRevoked && !ST.hideHoneypots && !ST.verifiedSocials;
}
function cacheDefaultFeed(){
  if(!_defaultFeedState() || !ST.tokens.length) return;
  try{
    sessionStorage.setItem(_FEED_CACHE_KEY,JSON.stringify({
      ts:Date.now(),tokens:ST.tokens.slice(0,30),counts:ST.counts||{}
    }));
  }catch(_){}
}
function hydrateInitialFeed(){
  if(ST.tokens.length) return true;
  var payload=null,el=document.getElementById('pt-initial-feed');
  try{ if(el&&el.textContent) payload=JSON.parse(el.textContent); }catch(_){}
  if(!payload || !Array.isArray(payload.tokens) || !payload.tokens.length){
    try{
      var cached=JSON.parse(sessionStorage.getItem(_FEED_CACHE_KEY)||'null');
      if(cached && Date.now()-Number(cached.ts||0)<300000) payload=cached;
    }catch(_){}
  }
  if(!payload || !Array.isArray(payload.tokens) || !payload.tokens.length) return false;
  ST.tokens=payload.tokens.slice(0,30);
  ST.counts=payload.counts||{};
  renderSortList();
  renderFeedList();
  updateHeaderCounts();
  return true;
}
function patchWatchButtons(){
  document.querySelectorAll('.pt-watch-btn[data-mint]').forEach(function(btn){
    var active=watchSet.has(btn.dataset.mint);
    btn.classList.toggle('active',active);
    btn.textContent=active?'★':'☆';
  });
}
function updateHeaderCounts(){
  var n = ST.tokens.length;
  var el;
  if((el=document.getElementById('pt-pulse-tokens'))) el.textContent = n;
}

// Horizontal rails (surge strip, trader rail) only ever got
// native overflow-x:auto. That works fine for a touch swipe on its own --
// what made it feel broken was two separate things layered on top:
//
// 1. Nothing on desktop could scroll them at all. There's no drag gesture
//    without a touchscreen, and no visible scrollbar (deliberately hidden
//    for the mobile look), so a mouse user just saw a dead strip cut off
//    mid-card with no way to reach the rest.
// 2. On mobile, loadSurges() rebuilds pt-surge-rail's innerHTML wholesale
//    every 12s. A full innerHTML replace mid-swipe kills the browser's
//    momentum/inertia scrolling outright and snaps scrollLeft back to 0 --
//    exactly what "swiping isn't smooth" looks like from the user's thumb,
//    especially since the strip is small enough that a 12s cadence has a
//    real chance of landing mid-gesture.
//
// This adds plain click-and-drag panning for a mouse (part 1), used below
// on all three rails. Part 2 is fixed at the loadSurges() call site by
// preserving scrollLeft across the rebuild and skipping it entirely while
// the user's mouse or finger is still down on the rail.
var _railsBeingTouched = {};
function enableDragScroll(el){
  if(!el || el._dragScrollBound) return;
  el._dragScrollBound = true;
  var down = false, moved = false, startX = 0, startScroll = 0;
  // Set on release after a real drag, consumed by the click that follows.
  // A plain flag rather than a listener added on the fly: a drag that ends
  // with the cursor off the rail fires no click at all, and a one-shot
  // listener waiting for one it never gets would sit there and eat the
  // NEXT genuine tap instead. mousedown clears it, so it can never outlive
  // the gesture that set it.
  var swallowClick = false;
  _routeScope.addEventListener(el,'click', function(e){
    if(!swallowClick) return;
    swallowClick = false;
    e.stopPropagation();
    e.preventDefault();
  }, true);
  _routeScope.addEventListener(el,'mousedown', function(e){
    down = true; moved = false; swallowClick = false;
    startX = e.pageX; startScroll = el.scrollLeft;
    el.classList.add('pt-rail-dragging');
  });
  _routeScope.addEventListener(window,'mousemove', function(e){
    if(!down) return;
    var dx = e.pageX - startX;
    if(Math.abs(dx) > 3) moved = true;
    el.scrollLeft = startScroll - dx;
  });
  _routeScope.addEventListener(window,'mouseup', function(){
    if(!down) return;
    down = false;
    el.classList.remove('pt-rail-dragging');
    // A deliberate pan must never also open whatever card the cursor
    // happens to be over on release. A tap that never moved must.
    swallowClick = moved;
  });
  _routeScope.addEventListener(el,'touchstart', function(){ _railsBeingTouched[el.id] = true; }, {passive:true});
  _routeScope.addEventListener(el,'touchend', function(){ _railsBeingTouched[el.id] = false; }, {passive:true});
  _routeScope.addEventListener(el,'touchcancel', function(){ _railsBeingTouched[el.id] = false; }, {passive:true});
}

function renderFeedList(){
  resetCardState();
  var el = document.getElementById('pt-feed-list');
  if(!ST.tokens.length){
    el.innerHTML = '<div class="pt-empty">No tokens match these filters</div>';
    return;
  }
  el.innerHTML = ST.tokens.map(function(t,i){ return cardHtml(t,i); }).join('');
  observeCards();
  syncTokenProfile();
}

// Applies fresh per-token numbers (by mint) onto the SAME token objects
// already in ST.tokens, in place -- never adds, removes, or reorders
// anything. Used only by a background poll (see loadFeed()) so whichever
// cards are already on screen keep their exact position/identity; only the
// numbers on them can change.
function mergeTokenUpdates(freshTokens){
  var byMint = {};
  (freshTokens||[]).forEach(function(t){ byMint[t.mint] = t; });
  ST.tokens.forEach(function(t){
    var fresh = byMint[t.mint];
    if(!fresh) return;
    Object.assign(t, fresh);
    // The poll's scanner price can be older than the live tick already on
    // screen; keep the live one so the header never jumps back in time.
    if(t._livePx>0 && Date.now()-(t._liveAt||0)<30000)
      _rebaseTokenPrice(t, Number(fresh.price_usd)||0, t._livePx);
  });
}

// Updates just the numbers on already-rendered cards (price, 24h change,
// liquidity/mcap/volume/buy-sell) in place, via their ids -- deliberately
// NOT touching the buy panel, watch button, chart, or the card node itself,
// so nothing a user is mid-interaction with (typing a buy amount, reading
// the chart) is disturbed. Companion to mergeTokenUpdates().
function patchFeedList(){
  ST.tokens.forEach(function(t, idx){
    var el, scrubbing = !!(_chartTimers[idx] && _chartTimers[idx].scrubbing);
    if(!scrubbing && (el = document.getElementById('pt-price-'+idx))) el.textContent = fmtPrice(t.price_usd);
    if(!scrubbing && (el = document.getElementById('pt-chg-'+idx))){
      var down = (t.price_change_24h||0) < 0;
      el.textContent = t.price_change_24h==null?'—':fmtPct(t.price_change_24h)+' · 24h';
      el.classList.toggle('down', down);
      el.classList.toggle('up', !down);
    }
    if((el = document.getElementById('pt-liq-'+idx)))  el.textContent = fmtUsd(t.liquidity_usd);
    if((el = document.getElementById('pt-mcap-'+idx))) el.textContent = fmtUsd(t.market_cap);
    if((el = document.getElementById('pt-vol-'+idx)))  el.textContent = fmtUsd(t.volume_24h);
    if((el = document.getElementById('pt-ratio-'+idx))) el.textContent = ratioStr(t.buys_24h, t.sells_24h);
  });
}

// isPoll=true only from the 15s auto-refresh interval below. A background
// poll used to fully replace ST.tokens and rebuild the whole card list
// (renderFeedList()'s el.innerHTML = ...) every 15 seconds -- since every
// sort mode re-ranks as prices/volume move, that could drop the exact card
// someone was reading (or buying on) out of the new top-30, or just
// reshuffle it to a different position/idx, making it look like it
// "vanished" mid-view. renderFeedList() also tears down every mounted
// chart (resetCardState()), so even a card that DIDN'T disappear still had
// its live chart reset on every poll. Now a poll only patches numbers on
// the cards already on screen (mergeTokenUpdates + patchFeedList) --
// nothing is added, removed, or reordered, and no DOM node is recreated.
// An explicit user action (sort/filter/liquidity change) still does the
// full, freshly-ordered rebuild, since that's exactly what was asked for.
// Set from ?mint= at startup; consumed by the first loadFeed() that finishes.
var _pendingDeepLinkMint = null;
var _focusedMint = null;
var _profileMint = null;
function syncTokenProfile(){
  var idx=ST.tokens.findIndex(function(t){return t.mint===_profileMint;});
  var active=!!(_profileMint && idx>=0);
  document.body.classList.toggle('pt-profile-mode',active);
  document.querySelectorAll('.pt-card').forEach(function(card){
    var chosen=active && card.dataset.mint===_profileMint;
    card.classList.toggle('pt-profile-open',chosen);
    var button=card.querySelector('.pt-profile-btn');
    if(button){button.textContent=chosen?'Close':'Profile';button.setAttribute('aria-label',chosen?'Close token profile':'Open token profile');}
    if(!chosen) _pfUnmount(card);
  });
  if(active){
    var card=document.getElementById('pt-card-'+idx);
    if(card){window.scrollTo(0,0);loadTokenProfileDetails(card,_profileMint);_pfMount(card,ST.tokens[idx]);}
    if(_chartTimers[idx] && _chartTimers[idx].candles)
      _routeScope.requestAnimationFrame(function(){renderChartSvg(idx,_chartTimers[idx].candles,_cardRefPrice(_chartTimers[idx],idx));});
  }
}
function loadTokenProfileDetails(card,mint){
  var box=card.querySelector('.pt-profile-about');
  if(!box || box.dataset.loading) return;
  box.dataset.loading='1';
  box.textContent='Loading token details…';
  _routeScope.fetch('/api/token/info/'+encodeURIComponent(mint)).then(function(r){return r.json();}).then(function(info){
    if(!card.isConnected || card.dataset.mint!==mint) return;
    if(!info || !info.ok){box.textContent='Token details are temporarily unavailable.';return;}
    box.replaceChildren();
    var _sym=info.symbol||(ST.tokens[Number(card.dataset.idx)]||{}).symbol||'';
    var title=document.createElement('h2');title.textContent=_sym?'About $'+_sym:'About '+(info.name||'this token');box.appendChild(title);
    var desc=document.createElement('p');desc.textContent=info.description||'The creator has not added a description yet.';box.appendChild(desc);
    // Links the creator chose: plain web links only (isSafeUrl), as chips.
    var links=document.createElement('div');links.className='pt-profile-links';
    function link(url,label){
      if(!isSafeUrl(url)) return;
      var a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=label;links.appendChild(a);
    }
    link(info.website_url,'Website');link(info.twitter_url,'X');link(info.telegram_url,'Telegram');
    if(links.childNodes.length) box.appendChild(links);
    // Contract: short address, Copy, and the explorer.
    var lbl=document.createElement('div');lbl.className='pt-pf-lbl';lbl.textContent='Contract';box.appendChild(lbl);
    var row=document.createElement('div');row.className='pt-pf-contract';
    var addr=document.createElement('span');addr.className='pt-profile-address mono';addr.textContent=shortAddr(mint);addr.title=mint;row.appendChild(addr);
    var copy=document.createElement('button');copy.type='button';copy.className='pt-pf-copy';copy.textContent='Copy';
    _routeScope.addEventListener(copy,'click',function(){
      var done=function(){copy.textContent='Copied';_routeScope.setTimeout(function(){copy.textContent='Copy';},1500);};
      if(navigator.clipboard) navigator.clipboard.writeText(mint).then(done,function(){toast('Copy failed');}); else toast(mint);
    });
    row.appendChild(copy);
    if((info.chain||'solana')==='solana'){
      var sc=document.createElement('a');sc.className='pt-pf-explorer';sc.href='https://solscan.io/token/'+encodeURIComponent(mint);
      sc.target='_blank';sc.rel='noopener noreferrer';sc.textContent='Solscan ↗';row.appendChild(sc);
    }
    box.appendChild(row);
  }).catch(function(){ if(card.isConnected) box.textContent='Token details are temporarily unavailable.'; });
}
/* ── Token page (profile mode) ──
   The open card becomes a token page: a back/share/watch bar, the price
   with "New" instead of a bare dash, empty market data in words, the
   member's own position, safety checks, who holds it on OrcAgent, and a
   Buy/Sell bar pinned under the thumb (mobile). The feed card itself is
   untouched: everything here is added to, or restyled on, .pt-profile-open
   only, and removed again when the page closes. */
var _pfSafety = {};      // mint -> /api/token/<mint>/safety answer
var _pfCommunity = {};   // mint -> {users: [...], holders: n}
var _pfHold = {};        // mint -> /api/trade/holding answer
var _pfActivity = {};    // mint -> [/api/token/<mint>/activity events]
var _pfObserver = null;
var _PF_EMPTY = {liq: 'Not reported yet', vol: 'No trades yet', ratio: 'No trades yet', mcap: 'Not reported yet'};

function _pfNode(tag, cls, text){
  var n = document.createElement(tag);
  if(cls) n.className = cls;
  if(text != null) n.textContent = text;
  return n;
}
function _pfCard(mint){
  var c = document.querySelector('.pt-card.pt-profile-open');
  return c && c.dataset.mint === mint ? c : null;
}
function _pfSection(card, cls){
  var s = card.querySelector('.' + cls);
  if(!s){ s = _pfNode('section', 'pt-pf-section ' + cls); card.insertBefore(s, card.querySelector('.pt-profile-about')); }
  return s;
}
function _pfMount(card, t){
  if(!card || !t) return;
  var mint = t.mint;
  if(!card.querySelector('.pt-pf-bar')){
    var bar = _pfNode('div', 'pt-pf-bar');
    var back = _pfNode('button', 'pt-pf-back', 'Live Market');
    back.type = 'button'; back.dataset.action = 'token-profile'; back.dataset.mint = mint;
    back.setAttribute('aria-label', 'Back to Live Market');
    var share = _pfNode('button', 'pt-pf-icon pt-pf-share', '');
    share.type = 'button'; share.setAttribute('aria-label', 'Share token');
    _routeScope.addEventListener(share,'click', function(){
      var url = location.origin + '/token/' + encodeURIComponent(mint);
      if(navigator.share) navigator.share({title: '$' + (t.symbol || ''), url: url}).catch(function(){});
      else if(navigator.clipboard) navigator.clipboard.writeText(url).then(function(){ toast('Link copied'); });
    });
    var star = _pfNode('button', 'pt-pf-icon pt-pf-star', '');
    star.type = 'button'; star.setAttribute('aria-label', 'Watchlist');
    _routeScope.addEventListener(star,'click', function(){
      var w = card.querySelector('.pt-watch-btn');
      if(w) w.click();
      _routeScope.setTimeout(function(){ _pfDecorate(card); }, 400);
    });
    bar.appendChild(back); bar.appendChild(share); bar.appendChild(star);
    card.insertBefore(bar, card.firstChild);
  }
  _pfSection(card, 'pt-pf-position').hidden = true;
  _pfSection(card, 'pt-pf-community');
  _pfSection(card, 'pt-pf-safety').hidden = true;
  var buy = card.querySelector('.pt-buy-btn');
  if(buy) buy.textContent = 'Buy $' + (t.symbol || '');
  // Market cap first, as on the design; moved back on close. Every update
  // finds these cells by id, so where they sit does not matter to it.
  var liq = _pfStatRow(card, 'liq'), mcap = _pfStatRow(card, 'mcap');
  if(liq && mcap && liq.nextElementSibling === mcap) liq.parentNode.insertBefore(mcap, liq);
  _pfDecorate(card);
  _pfRefresh(mint);
  // Price, change and market data are patched in place every tick and poll;
  // re-apply the empty-state wording and the position value after each.
  if(_pfObserver) _pfObserver.disconnect();
  if('MutationObserver' in window){
    _pfObserver = _routeScope.mutationObserver(function(){ _pfDecorate(card); });
    var stats = card.querySelector('.pt-card-stats');
    if(stats) _pfObserver.observe(stats, {subtree: true, childList: true, characterData: true});
  }
  _pfLoadHolding(card, t);
  _pfLoadActivity(card, mint);
}
function _pfStatRow(card, key){
  var el = document.getElementById('pt-' + key + '-' + card.dataset.idx);
  return el && card.contains(el) ? el.parentNode : null;
}
function _pfUnmount(card){
  var bar = card.querySelector('.pt-pf-bar');
  if(!bar) return;
  bar.remove();
  card.querySelectorAll('.pt-pf-section').forEach(function(s){ s.remove(); });
  var liq = _pfStatRow(card, 'liq'), mcap = _pfStatRow(card, 'mcap');
  if(liq && mcap && mcap.nextElementSibling === liq) liq.parentNode.insertBefore(liq, mcap);
  var ratio = _pfStatRow(card, 'ratio');
  if(ratio){
    var deco = ratio.querySelector('.pt-pf-ratio');
    if(deco) deco.remove();
    ratio.classList.remove('pt-pf-has-ratio');
    var lbl = ratio.querySelector('.pt-stat-lbl');
    if(lbl) lbl.textContent = 'Buy / Sell';
  }
  var buy = card.querySelector('.pt-buy-btn');
  if(buy) buy.textContent = 'Buy';
  var sell = card.querySelector('.pt-sell-btn');
  if(sell){ sell.disabled = false; sell.removeAttribute('title'); }
  card.querySelectorAll('.pt-pf-empty').forEach(function(el){ el.classList.remove('pt-pf-empty'); });
  var chg = card.querySelector('.pt-chg');
  if(chg) chg.classList.remove('pt-pf-new');
  if(_pfObserver){ _pfObserver.disconnect(); _pfObserver = null; }
}
function _pfDecorate(card){
  if(!card || !card.classList.contains('pt-profile-open')) return;
  var idx = card.dataset.idx;
  Object.keys(_PF_EMPTY).forEach(function(k){
    var el = document.getElementById('pt-' + k + '-' + idx);
    if(!el) return;
    var empty = el.textContent.trim() === '—';
    if(el.classList.contains('pt-pf-empty') !== empty) el.classList.toggle('pt-pf-empty', empty);
    if(el.dataset.empty !== _PF_EMPTY[k]) el.dataset.empty = _PF_EMPTY[k];
  });
  var chg = document.getElementById('pt-chg-' + idx);
  if(chg){
    var isNew = chg.textContent.trim() === '—';
    if(chg.classList.contains('pt-pf-new') !== isNew) chg.classList.toggle('pt-pf-new', isNew);
  }
  var star = card.querySelector('.pt-pf-star');
  if(star){
    var on = watchSet.has(card.dataset.mint);
    if(star.classList.contains('on') !== on) star.classList.toggle('on', on);
    star.setAttribute('aria-pressed', on ? 'true' : 'false');
  }
  _pfRenderRatio(card);
  _pfRenderPosition(card);
}
// "Buys / sells 24h": a green/red bar with the two counts, as on the design,
// instead of "58% / 42%". No trades yet keeps the words.
function _pfRenderRatio(card){
  var row = _pfStatRow(card, 'ratio');
  if(!row) return;
  var lbl = row.querySelector('.pt-stat-lbl');
  if(lbl && lbl.textContent !== 'Buys / sells 24h') lbl.textContent = 'Buys / sells 24h';
  var t = ST.tokens[Number(card.dataset.idx)] || {};
  var b = Math.max(0, Number(t.buys_24h) || 0), s = Math.max(0, Number(t.sells_24h) || 0);
  var deco = row.querySelector('.pt-pf-ratio');
  if(!(b + s)){
    if(deco) deco.remove();
    if(row.classList.contains('pt-pf-has-ratio')) row.classList.remove('pt-pf-has-ratio');
    return;
  }
  var key = b + '|' + s;
  if(deco && deco.dataset.key === key) return;
  if(!deco){ deco = _pfNode('div', 'pt-pf-ratio'); row.appendChild(deco); }
  deco.dataset.key = key;
  deco.replaceChildren();
  var bar = _pfNode('div', 'pt-pf-ratio-bar'), fill = _pfNode('i');
  fill.style.width = Math.round(b / (b + s) * 100) + '%';
  bar.appendChild(fill);
  var n = _pfNode('div', 'pt-pf-ratio-n mono');
  n.appendChild(_pfNode('span', 'up', b.toLocaleString('en-US')));
  n.appendChild(_pfNode('span', 'down', s.toLocaleString('en-US')));
  deco.appendChild(bar); deco.appendChild(n);
  if(!row.classList.contains('pt-pf-has-ratio')) row.classList.add('pt-pf-has-ratio');
}
function _pfRefresh(mint){
  var card = _pfCard(mint);
  if(!card) return;
  _pfRenderSafety(card, _pfSafety[mint]);
  _pfRenderCommunity(card, _pfCommunity[mint] || {});
}
function _pfLoadHolding(card, t){
  var mint = t.mint, sell = card.querySelector('.pt-sell-btn');
  if(sell){ sell.disabled = true; sell.title = "You don't hold this token"; }
  _routeScope.fetch('/api/trade/holding?chain=' + encodeURIComponent(t.chain || 'solana')
        + '&token_address=' + encodeURIComponent(mint), {credentials: 'include', headers: authHeaders()})
    .then(function(r){ return r.ok ? r.json() : null; })
    .then(function(d){
      if(!card.isConnected || !card.classList.contains('pt-profile-open') || card.dataset.mint !== mint) return;
      _pfHold[mint] = d && d.ok ? d : null;
      var held = !!(d && d.ok && Number(d.amount) > 0);
      if(sell){ sell.disabled = !held; if(held) sell.removeAttribute('title'); }
      var buy = card.querySelector('.pt-buy-btn');
      if(buy) buy.textContent = held ? 'Buy more' : 'Buy $' + (t.symbol || '');
      _pfRenderPosition(card);
      var idx = Number(card.dataset.idx), st = _chartTimers[idx];
      if(held && st && st.candles) renderChartSvg(idx, st.candles, _cardRefPrice(st, idx));
    })
    .catch(function(){});
}
function _pfLoadActivity(card, mint){
  _routeScope.fetch('/api/token/' + encodeURIComponent(mint) + '/activity', {credentials: 'include'})
    .then(function(r){ return r.ok ? r.json() : null; })
    .then(function(d){
      if(!d || !d.ok) return;
      _pfActivity[mint] = d.events || [];
      _pfRefresh(mint);
    })
    .catch(function(){});
}
// What the member paid per token, for the chart's "You bought at" line --
// only on the open token page, only for a position they still hold.
function _pfEntryPrice(idx){
  var t = ST.tokens[Number(idx)];
  if(!t || t.mint !== _profileMint) return 0;
  var h = _pfHold[t.mint];
  return h && Number(h.amount) > 0 && Number(h.entry_price_usd) > 0 ? Number(h.entry_price_usd) : 0;
}
function _pfUsd(n){
  n = Number(n) || 0;
  var a = Math.abs(n);
  return (n < 0 ? '-' : '') + '$' + (a >= 1000 ? a.toLocaleString('en-US', {maximumFractionDigits: 0}) : a.toFixed(2));
}
function _pfAmount(n){
  n = Number(n) || 0;
  if(n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if(n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if(n >= 1e3) return n.toLocaleString('en-US', {maximumFractionDigits: 0});
  return n.toLocaleString('en-US', {maximumFractionDigits: 4});
}
function _pfRenderPosition(card){
  var box = card.querySelector('.pt-pf-position');
  if(!box) return;
  var h = _pfHold[card.dataset.mint];
  var t = ST.tokens[Number(card.dataset.idx)];
  if(!h || !(Number(h.amount) > 0)){ box.hidden = true; return; }
  var price = Number(t && t.price_usd) || Number(h.price_usd) || 0;
  var value = price > 0 ? Number(h.amount) * price : Number(h.value_usd) || 0;
  var cost = h.cost_usd != null ? Number(h.cost_usd) : null;
  var entry = h.entry_price_usd != null ? Number(h.entry_price_usd) : null;
  var pnl = cost != null && cost > 0 ? value - cost : null;
  var key = [value.toFixed(4), pnl == null ? '' : pnl.toFixed(4), h.amount, Math.floor((Date.now() / 1000 - (Number(h.opened_at) || 0)) / 60)].join('|');
  if(box.dataset.key === key && !box.hidden) return;
  box.dataset.key = key;
  box.replaceChildren();
  var hd = _pfNode('div', 'pt-pf-pos-hd');
  hd.appendChild(_pfNode('h3', 'pt-pf-h', 'Your position'));
  if(Number(h.opened_at) > 0) hd.appendChild(_pfNode('span', 'pt-pf-pos-ago', 'You bought ' + fmtAge(Number(h.opened_at) * 1000) + ' ago'));
  box.appendChild(hd);
  var top = _pfNode('div', 'pt-pf-pos-top');
  var left = _pfNode('div');
  left.appendChild(_pfNode('div', 'pt-pf-lbl', 'Value now'));
  left.appendChild(_pfNode('div', 'pt-pf-pos-value mono', _pfUsd(value)));
  top.appendChild(left);
  if(pnl != null){
    var up = pnl >= 0, right = _pfNode('div', 'pt-pf-pos-pnl ' + (up ? 'up' : 'down'));
    right.appendChild(_pfNode('div', 'mono', (up ? '+' : '') + _pfUsd(pnl)));
    right.appendChild(_pfNode('div', 'mono pt-pf-pos-pct', (up ? '+' : '') + (pnl / cost * 100).toFixed(1) + '%'));
    top.appendChild(right);
  }
  box.appendChild(top);
  var grid = _pfNode('div', 'pt-pf-pos-grid');
  function cell(label, val){ var c = _pfNode('div'); c.appendChild(_pfNode('div', 'pt-pf-lbl', label)); c.appendChild(_pfNode('div', 'mono pt-pf-pos-v', val)); grid.appendChild(c); }
  cell('You hold', _pfAmount(h.amount));
  cell('Avg buy price', entry ? fmtPrice(entry) : '—');
  cell('You paid', cost != null ? _pfUsd(cost) : '—');
  box.appendChild(grid);
  box.hidden = false;
}
function _pfRenderSafety(card, d){
  var box = card.querySelector('.pt-pf-safety');
  if(!box) return;
  if(!d){ box.hidden = true; return; }
  var lp = Number(d.lp_locked_pct) || 0;
  var rows = [
    lp >= 50 ? [true, 'Liquidity locked', Math.round(lp) + '%'] : [false, 'Liquidity not locked', 'Can be pulled'],
    d.mint_authority_active ? [false, 'Mint authority active', 'Supply can grow'] : [true, 'Mint authority revoked', 'No new supply']
  ];
  if(d.freeze_authority_active) rows.push([false, 'Freeze authority active', 'Wallets can be frozen']);
  box.replaceChildren();
  box.appendChild(_pfNode('h3', 'pt-pf-lbl pt-pf-safety-h', 'Safety checks'));
  rows.forEach(function(r){
    var row = _pfNode('div', 'pt-pf-check ' + (r[0] ? 'ok' : 'bad'));
    row.appendChild(_pfNode('span', 'pt-pf-check-ico', r[0] ? '✓' : '✕'));
    row.appendChild(_pfNode('span', 'pt-pf-check-t', r[1]));
    row.appendChild(_pfNode('span', 'pt-pf-check-s', r[2]));
    box.appendChild(row);
  });
  box.hidden = false;
}
function _pfProfileLink(user, cls){
  var wallet = String(user.wallet_address || '');
  var link = _pfNode(wallet ? 'a' : 'span', cls);
  if(wallet){
    link.href = '/profile/' + encodeURIComponent(wallet);
    link.setAttribute('aria-label', 'View profile of ' + (user.username || 'trader'));
  }
  return link;
}
function _pfUserAvatar(user, cls){
  var avatar = _pfProfileLink(user, cls);
  avatar.appendChild(_pfNode('span', 'pt-pf-avatar-initials', (user.username || '?').replace(/^@/, '').slice(0, 2).toUpperCase()));
  var src = safeMediaUrl(user.avatar_url);
  if(src){
    var img = document.createElement('img');
    img.src = src;
    img.alt = '';
    img.decoding = 'async';
    img.addEventListener('error', function(){ img.remove(); }, {once: true});
    avatar.appendChild(img);
  }
  return avatar;
}
function _pfRenderCommunity(card, c){
  var box = card.querySelector('.pt-pf-community');
  if(!box) return;
  var users = c.users || [], holders = Number(c.holders) || 0;
  var events = _pfActivity[card.dataset.mint] || [];
  var token = ST.tokens[Number(card.dataset.idx)];
  var symbol = token && token.symbol || 'this token';
  box.replaceChildren();
  var hd = _pfNode('div', 'pt-pf-comm-hd');
  hd.appendChild(_pfNode('h3', 'pt-pf-h', 'On OrcAgent'));
  hd.appendChild(_pfNode('span', 'pt-pf-comm-label', 'Activity'));
  box.appendChild(hd);
  var who = _pfNode('div', 'pt-pf-comm-who');
  if(users.length){
    var avs = _pfNode('div', 'pt-pf-friend-avatars');
    users.slice(0, 3).forEach(function(u){ avs.appendChild(_pfUserAvatar(u, 'pt-pf-avatar pt-pf-friend-avatar')); });
    who.appendChild(avs);
    who.appendChild(_pfNode('span', null, users.length + (users.length === 1 ? ' friend holds ' : ' friends hold ') + symbol));
  } else {
    who.appendChild(_pfNode('span', null, holders ? holders + ' trader' + (holders === 1 ? '' : 's') + ' hold it' : 'No friends hold it yet'));
  }
  box.appendChild(who);
  if(events.length){
    var list = _pfNode('div', 'pt-pf-act-list');
    events.slice(0, 5).forEach(function(e){
      var buy = e.side === 'buy', row = _pfNode('div', 'pt-pf-act');
      row.appendChild(_pfUserAvatar(e, 'pt-pf-avatar pt-pf-act-avatar'));
      var identity = _pfNode('div', 'pt-pf-act-identity');
      var name = _pfProfileLink(e, 'pt-pf-act-who');
      name.appendChild(_pfNode('span', 'pt-pf-act-name', e.you ? 'You' : '@' + (e.username || 'trader').replace(/^@/, '')));
      if(e.wallet_address){
        var arrow = _pfNode('span', 'pt-pf-act-arrow', '›');
        arrow.setAttribute('aria-hidden', 'true');
        name.appendChild(arrow);
      }
      identity.appendChild(name);
      identity.appendChild(_pfNode('div', 'pt-pf-act-ago', (buy ? 'Bought ' : 'Sold ') + symbol + ' · ' + fmtAge(Number(e.ts) * 1000) + ' ago'));
      row.appendChild(identity);
      var amount = _pfNode('div', 'pt-pf-act-amount');
      amount.appendChild(_pfNode('span', 'pt-pf-act-usd mono', _pfUsd(e.usd)));
      amount.appendChild(_pfNode('span', 'pt-pf-act-side ' + (buy ? 'buy' : 'sell'), buy ? 'BUY' : 'SELL'));
      row.appendChild(amount);
      list.appendChild(row);
    });
    box.appendChild(list);
  } else {
    box.appendChild(_pfNode('div', 'pt-pf-comm-empty', 'Buys and sells by you and the people you follow show up here'));
  }
}

function setTokenProfile(mint){
  _profileMint=_profileMint===mint?null:mint;
  _focusedMint=_profileMint||_focusedMint;
  var url=new URL(location.href);
  if(_profileMint){url.searchParams.set('mint',_profileMint);url.searchParams.set('profile','1');}
  else url.searchParams.delete('profile');
  history.pushState(null,'',url.pathname+url.search);
  syncTokenProfile();
}

function loadFeed(isPoll){
  if(_feedInFlight) return;
  _feedInFlight = true;
  var qs = new URLSearchParams({
    sort: ST.sort,
    min_liquidity: ST.minLiquidity,
    age: ST.age,
    lp_locked: ST.lpLocked?1:0,
    mint_revoked: ST.mintRevoked?1:0,
    hide_honeypots: ST.hideHoneypots?1:0,
    verified_socials: ST.verifiedSocials?1:0
  });
  _routeScope.fetch('/api/market/scanner?'+qs.toString(), {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(!d || !d.ok) return;
      ST.counts = d.counts || {};
      if(isPoll && ST.tokens.length){
        mergeTokenUpdates(d.tokens);
        patchFeedList();
        renderSortList();
      } else {
        ST.tokens = d.tokens || [];
        renderSortList();
        renderFeedList();
      }
      updateHeaderCounts();
      cacheDefaultFeed();
    })
    .catch(function(){})
    .finally(function(){
      _feedInFlight = false;
      // Runs whether that load succeeded or failed: a deep-linked token is
      // still worth showing when the scanner itself is having a bad minute.
      if(_pendingDeepLinkMint){
        var _m = _pendingDeepLinkMint;
        _pendingDeepLinkMint = null;
        prependSearchedToken(_m, '', '');
      }
    });
}

/* ── trade actions ── */
// Shared close path so every way a buy panel can close (manual toggle, or
// auto-hide after a completed buy below) keeps _openBuyPanelCount accurate.
// The card still renders an empty #pt-buy-panel-<idx> of its own, left over
// from the in-card buy screen, and the sheet's footer BORROWS that same id
// while it is open. Two elements, one id: getElementById answers with
// whichever comes first in the document, which is the card's. So this asked
// the card whether it was in the sheet, got "no", and hid an already-hidden
// empty div -- leaving the sheet open forever after a successful buy. The
// sheet is asked first now, by where it actually is rather than by an id it
// shares.
function closeBuyPanel(idx){
  if(_sheetIdx !== null && String(_sheetIdx) === String(idx) && _sheetFooter()){
    closeBuySheet();
    return;
  }
  var p = document.getElementById('pt-buy-panel-'+idx);
  if(p && p.closest('#pt-sheet')){ closeBuySheet(); return; }
  if(p){ p.style.display = 'none'; p.innerHTML = ''; }
}

// The sheet's footer, found by where it is rather than by the id it borrows
// -- see closeBuyPanel() above for why the id alone is not enough.
function _sheetFooter(){
  return document.querySelector('#pt-sheet .pt-sheet-ft');
}

/* ── THE BUY SHEET ─────────────────────────────────────────────────────────
   A full screen: the token at the top, the amount enormous in the middle, a
   keypad underneath. It exists because the old buy box was a number input
   inside the card, so on a phone the OS keyboard slid up and covered the
   price, the move and the balance -- every figure the person was deciding
   on -- at the exact moment they were deciding.

   What it deliberately does NOT do is touch the trade. On open it renames
   its own footer's ids to the ones confirmBuy() already looks for
   (pt-buy-panel-N / pt-buy-amt-N / pt-buy-msg-N) and puts the index on the
   button, so the existing buy path -- quotes, the EVM routes, the auto-
   bridge polling -- runs byte for byte as it did before. This is a change
   of what somebody looks at, not of what happens when they press Buy. */
var _sheetIdx = null;       // index of the token being traded, null when closed
var _sheetMode = 'buy';     // 'buy' or 'sell'
var _sheetAmt = '';         // what the keypad has typed, as a string
var _sheetSolPrice = 0;
var _sheetAvail = null;     // spendable USDC on THIS token's chain
var _availCache = {t: 0, data: null};

function _sheetEl(id){ return document.getElementById(id); }

// The ids confirmBuy() reaches for are handed to the footer on open and
// taken back on close, so the sheet can be reused by the next token.
// Borrowed ids are looked up INSIDE the sheet, never document-wide. The card
// still renders an empty #pt-buy-panel-<idx> of its own, so a document-wide
// getElementById can answer with the card's element instead of the sheet's --
// and then the swap hands the borrowed id to the wrong element and every
// later lookup drifts. Scoping to #pt-sheet makes the match unambiguous.
var _SHEET_IDS = ['pt-buy-panel', 'pt-buy-amt', 'pt-buy-msg', 'pt-quote'];
function _sheetOwn(id){ return document.querySelector('#pt-sheet [id="' + id + '"]'); }
function _sheetBindIds(idx){
  _SHEET_IDS.forEach(function(base){
    var el = _sheetOwn(base + '-sheet');
    if(el) el.id = base + '-' + idx;
  });
}
function _sheetUnbindIds(idx){
  _SHEET_IDS.forEach(function(base){
    var el = _sheetOwn(base + '-' + idx);
    if(el) el.id = base + '-sheet';
  });
  var q = _sheetOwn('pt-quote-sheet');
  if(q){ q.style.display = 'none'; q.innerHTML = ''; }
}

// The same four buttons, relabelled. Buying they are shares of the balance
// to spend; selling, shares of the position to close -- and the sell set
// starts at a quarter rather than a tenth, because a tenth of a position is
// rarely what anyone means and the row only has four slots.
function _paintPcts(mode){
  var sell = mode === 'sell';
  document.querySelectorAll('#pt-sheet .pt-pct').forEach(function(b){
    var pct = sell ? b.dataset.spct : b.dataset.pct;
    var last = pct === '100';
    b.textContent = last ? (sell ? 'All' : 'Max') : (pct + '%');
    b.setAttribute('aria-label', sell
      ? (last ? 'Sell your whole position' : 'Sell ' + pct + '% of your position')
      : (last ? 'Spend your whole balance' : 'Spend ' + pct + '% of your balance'));
    b.classList.toggle('on', sell && Number(pct) === _sellPct);
  });
}

// What the trade costs. Solana buys are priced by the instant-trade route;
// selling states the rates that apply until the transaction settles.
function _paintFees(t, mode){
  var box = document.getElementById('pt-fees');
  var amtEl = document.getElementById('pt-fees-amt');
  var sellEl = document.getElementById('pt-fees-sell');
  if(box) box.open = false;      // folded away again for the next token
  if(mode !== 'sell'){ if(amtEl) amtEl.textContent = ''; return; }
  var pct = (PT_FEE_RATE_TXN * 100).toFixed(2).replace(/\.?0+$/, '');
  var gas = (CHAIN_LABELS[t.chain] || (t.chain || '').toUpperCase());
  if(amtEl) amtEl.textContent = pct + '% + network fee';
  if(sellEl){
    sellEl.innerHTML =
        '<div class="pt-quote-row"><span>OrcAgent fee</span><span>'
      +   esc(pct) + '% of the sale</span></div>'
      + '<div class="pt-quote-row"><span>Network fee</span><span>'
      +   esc(gas) + ' gas</span></div>'
      + '<div class="pt-quote-note">Both are taken when the sale settles, so '
      + 'the amounts follow whatever it actually returns.</div>';
  }
}

// Spendable balance is native SOL after the network reserve. Cached briefly so reopening the sheet
// does not repeat the same wallet lookup.
// Fetched once when the page loads, not when the sheet opens. Opening used
// to start the request, so the first buy of a session sat on "Checking
// balance…" for ~290ms with the 10/25/50/Max buttons inert -- measured on a
// throttled phone. By the time anyone taps Buy this has long since landed.
function _prefetchBalances(){
  _routeScope.fetch('/api/wallet/trading-balance', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){ if(d && d.ok){ _availCache = {t: Date.now(), data: d}; _sheetSolPrice=Number(d.sol_price_usd||0); } })
    .catch(function(){});
}

// What there is to sell. The amount and the price both come from the
// server, because the server is what decides how many tokens a dollar
// figure turns into when the sell actually runs -- a price of the page's
// own would put a different number on the screen than the one that trades.
function _loadSheetHolding(t){
  var idx = _sheetIdx;
  var failed = function(){
    if(_sheetIdx !== idx || _sheetMode !== 'sell') return;
    _holdErr = true;
    _paintSheet();
  };
  _routeScope.fetch('/api/trade/holding?chain=' + encodeURIComponent(t.chain)
        + '&token_address=' + encodeURIComponent(t.mint),
        {credentials:'include', headers: authHeaders()})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(_sheetIdx !== idx || _sheetMode !== 'sell') return;
      if(!d || !d.ok || d.value_sol == null){ failed(); return; }
      _sheetHold = {amount: Number(d.amount || 0), price: Number(d.sol_price_usd)>0?Number(d.price_usd||0)/Number(d.sol_price_usd):0,
                    value: Number(d.value_sol || 0)};
      _sheetAvail = _sheetHold.value;
      // Open on the whole position, which is what the button used to do and
      // is still the common case -- now with the figure filled in, so it can
      // be edited down instead of retyped from nothing.
      if(_sellPct >= 100 && _sheetAmt === '' && _sheetHold.value > 0){
        _sheetAmt = String(Math.floor(_sheetHold.value * 1e9) / 1e9);
        var hidden = document.getElementById('pt-buy-amt-'+idx);
        if(hidden) hidden.value = _sheetAmt;
      }
      _paintSheet();
    })
    .catch(failed);
}

function _loadSheetBalance(chain){
  var now = Date.now();
  var use = function(d){
    var v = d.available_sol;
    _sheetSolPrice=Number(d.sol_price_usd||0);
    _sheetAvail = Number(v || 0);
    _paintSheet();
  };
  if(_availCache.data && now - _availCache.t < 12000){ use(_availCache.data); return; }
  _routeScope.fetch('/api/wallet/trading-balance', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(!d || !d.ok) return;
      _availCache = {t: Date.now(), data: d};
      use(d);
    })
    .catch(function(){});
}

function openBuySheet(idx){ _openSheet(idx, 'buy'); }
function openSellSheet(idx){ _openSheet(idx, 'sell'); }

// How much of the position a sell is for, as a percentage. Buying has an
// amount; selling used to have nothing to say -- the routes closed the whole
// position and the client could not ask for anything else. It can now, and
// 100 stays the default, so opening the sheet and sliding does exactly what
// it always did.
var _sellPct = 100;
// What the sell screen is measuring against: how many tokens are held, what
// they are worth each, and what that comes to. Null until it is known --
// the screen says "Checking…" rather than showing a figure it has not got.
var _sheetHold = null;
// Set when the lookup itself failed, as opposed to answering "you hold
// nothing". Closing a position is how somebody cuts a loss, so a lookup
// that cannot be reached must never be what stops them.
var _holdErr = false;

function _openSheet(idx, mode){
  var t = ST.tokens[Number(idx)];
  if(!t) return;
  _sheetIdx = idx;
  _sheetMode = mode;
  _sheetAmt = '';
  _sheetAvail = null;
  _sheetHold = null;
  _holdErr = false;
  _sellPct = 100;
  _paintPcts(mode);
  _paintFees(t, mode);
  _sheetBindIds(idx);
  _sheetEl('pt-sheet').classList.toggle('sell-mode', mode === 'sell');
  _sheetEl('pt-sheet').setAttribute('aria-label', (mode === 'sell' ? 'Sell ' : 'Buy ') + (t.symbol || 'token'));
  _slideReset();
  // The previous trade's receipt belongs to the previous trade. Leaving it
  // up would show one token's transaction under another token's name.
  var stale = document.getElementById('pt-txline');
  if(stale) stale.remove();
  _tradeStartedAt = 0;

  // Logo, or the token's initials when it has none / the image 404s --
  // an invisible image left a 44px hole in the header.
  var img = _sheetEl('pt-sheet-img'), ph = _sheetEl('pt-sheet-img-ph');
  ph.textContent = (t.symbol || '?').slice(0, 2).toUpperCase();
  if(t.image_url){
    img.src = t.image_url; img.style.display = ''; ph.style.display = 'none';
    img.onerror = function(){ img.style.display = 'none'; ph.style.display = 'flex'; };
  } else {
    img.removeAttribute('src'); img.style.display = 'none'; ph.style.display = 'flex';
  }
  _sheetEl('pt-sheet-sym').textContent = '$' + (t.symbol || '?');
  _sheetEl('pt-sheet-chain').textContent = 'SOL';
  _sheetEl('pt-sheet-mc').textContent = t.market_cap ? fmtUsd(t.market_cap) + ' MC' : '';
  _sheetEl('pt-sheet-price').textContent = fmtPrice(t.price_usd);
  var chg = Number(t.price_change_24h || 0);
  var chgEl = _sheetEl('pt-sheet-chg');
  chgEl.textContent = (chg >= 0 ? '▲ ' : '▼ ') + Math.abs(chg).toFixed(2) + '%';
  chgEl.className = 'pt-sheet-chg ' + (chg < 0 ? 'down' : 'up');

  if(mode === 'sell'){
    _sheetEl('pt-sheet-cap-txt').textContent = 'You sell';
    _sheetEl('pt-sheet-cur').textContent = 'SOL';
  } else {
    _sheetEl('pt-sheet-cap-txt').textContent = 'You spend';
    _sheetEl('pt-sheet-cur').textContent = 'SOL';
  }
  _sheetEl('pt-slide').classList.toggle('sell', mode === 'sell');

  var msg = document.getElementById('pt-buy-msg-'+idx);
  if(msg){ msg.style.display = 'none'; msg.textContent = ''; }
  _sheetEl('pt-sheet-go').dataset.idx = idx;
  _sheetEl('pt-sheet-quote').textContent = '';

  _sheetEl('pt-sheet').classList.add('open');
  _sheetEl('pt-sheet-scrim').classList.add('open');
  try{ document.body.style.overflow = 'hidden'; }catch(e){}
  _paintSheet();
  // A sell closes the whole tracked position server-side, so there is no
  // balance to divide up and nothing to price -- only a confirmation.
  if(mode === 'buy'){ _loadSheetBalance(t.chain); }
  else _loadSheetHolding(t);
}

function closeBuySheet(){
  if(_sheetIdx === null) return;
  var idx = _sheetIdx;
  _sheetIdx = null;
  _sheetAmt = '';
  _sheetEl('pt-sheet').classList.remove('open');
  _sheetEl('pt-sheet-scrim').classList.remove('open');
  try{ document.body.style.overflow = ''; }catch(e){}
  _sheetUnbindIds(idx);
}

// `settled` means the amount is final rather than mid-typing -- a tap on
// 25% or Max. There is nothing to debounce there: the number will not
// change in 450ms, and waiting is 450ms of "Pricing…" for no reason.
function _sheetSetAmount(next, settled){
  _sheetAmt = next;
  var hidden = document.getElementById('pt-buy-amt-'+_sheetIdx);
  if(hidden) hidden.value = next;
  _paintSheet();
  // Solana buys use the shared instant-trade route; no separate EVM quote
  // scheduler is needed.
}

// Typing a figure means it is no longer "a share of the position" -- it is
// that figure. The request then carries the dollars rather than the
// percentage, so what is sold is what the screen says.
function _sheetTypeAmount(next){
  if(_sheetMode === 'sell'){ _sellPct = null; _paintPcts('sell'); }
  _sheetSetAmount(next);
}

function _paintSheet(){
  if(_sheetIdx === null) return;
  var t = ST.tokens[Number(_sheetIdx)];
  if(_sheetMode === 'sell'){
    // Selling is the same question as buying, asked in the same unit: a
    // figure in dollars, converted to tokens. It used to be a percentage
    // and nothing else -- "Sell all" with no way to say how much -- which
    // meant the one screen in the app that spends money had two completely
    // different ways of naming an amount depending on which direction you
    // were going.
    //
    // The three readings a sell decision actually turns on, from the same
    // token object the card reads -- not a second lookup that could
    // disagree with what the person just tapped.
    var sc = Number(t && t.price_change_24h || 0);
    _sheetEl('pt-sheet-stats').innerHTML = [
      ['24h move', (sc >= 0 ? '+' : '') + sc.toFixed(2) + '%', sc < 0 ? 'down' : 'up'],
      ['Liquidity', fmtUsd(t && t.liquidity_usd || 0), ''],
      ['Volume 24h', fmtUsd(t && t.volume_24h || 0), '']
    ].map(function(r){
      return '<div><div class="pt-tstat-k">' + esc(r[0]) + '</div>'
           + '<div class="pt-tstat-v ' + r[2] + '">' + esc(r[1]) + '</div></div>';
    }).join('');

    var sAmt = parseFloat(_sheetAmt);
    var sEl  = _sheetEl('pt-sheet-amt');
    sEl.textContent = (_sheetAmt === '' ? '0' : _sheetAmt);
    sEl.classList.toggle('dim', !(sAmt > 0));

    // What that sells, in tokens -- the same conversion the buy screen
    // does, run the other way, at the price the server quoted.
    var px = _sheetHold ? _sheetHold.price : 0;
    _sheetEl('pt-sheet-get').textContent = (sAmt > 0 && px > 0)
      ? ('≈ ' + fmtAmount(sAmt / px) + ' ' + (t && t.symbol || ''))
      : '';

    _sheetEl('pt-sheet-avail').innerHTML = _holdErr
      ? 'Could not read your position — you can still sell all of it'
      : ((_sheetAvail === null)
          ? 'Checking your position…'
          : ('<b>' + _sheetAvail.toFixed(6) + ' SOL</b> held'));

    // Selling is how a loss gets cut. A lookup that could not be reached is
    // not a reason to leave somebody holding a position they are trying to
    // get out of -- the whole-position sell needs no figure and no price, so
    // that one stays available whatever the lookup did.
    if(_holdErr){
      _sellPct = 100;
      sEl.textContent = 'Sell all';
      sEl.classList.remove('dim');
      _sheetEl('pt-sheet-get').textContent = 'Your whole $' + (t && t.symbol || '') + ' position';
      _slideSetLabel('Slide to sell all $' + (t && t.symbol || ''));
      _slideEnable(true);
      return;
    }

    if(_sheetAvail !== null && !(_sheetAvail > 0)){
      _slideSetLabel('Nothing to sell'); _slideEnable(false);
    } else if(!(sAmt > 0)){
      _slideSetLabel('Enter an amount'); _slideEnable(false);
    } else if(_sheetAvail !== null && sAmt > _sheetAvail + 1e-9){
      // A cent of slack: "Max" floors to the cent, and a price that ticks
      // between the fill and the tap must not disarm the control someone
      // just used.
      _slideSetLabel('More than you hold'); _slideEnable(false);
    } else {
      // Saying "all" out loud when it IS all: the difference between
      // trimming a position and closing it is the whole decision.
      _slideSetLabel(_sellPct >= 100
        ? ('Slide to sell all $' + (t && t.symbol || ''))
        : ('Slide to sell ' + _sheetAmt + ' SOL'));
      _slideEnable(true);
    }
    return;
  }
  var amt = parseFloat(_sheetAmt);
  var el = _sheetEl('pt-sheet-amt');
  el.textContent = (_sheetAmt === '' ? '0' : _sheetAmt);
  el.classList.toggle('dim', !(amt > 0));

  // What that money buys, at the price on screen. An estimate, and labelled
  // as one -- the executed price is whatever the swap returns.
  var get = _sheetEl('pt-sheet-get');
  var px = Number(t && t.price_usd || 0);
  get.textContent = (amt > 0 && px > 0)
    ? '≈ ' + fmtAmount(Math.max(0, amt - 0.003) * (1 - PT_FEE_RATE_TXN) * _sheetSolPrice / px) + ' ' + (t.symbol || '')
    : '';

  // Cents, not fmtUsd's compact form: a balance of 12.40 shown as "$12"
  // contradicts the 12.40 that Max then fills in, and a person reading a
  // number about their own money should see the actual number.
  var feeBase = Math.max(0, amt - 0.003);
  var feeSummary = _sheetEl('pt-fees-amt'), feeDetails = _sheetEl('pt-fees-sell');
  if(feeSummary) feeSummary.textContent = 'Included in SOL budget';
  if(feeDetails) feeDetails.innerHTML =
    '<div class="pt-quote-row"><span>Maximum spend</span><span>'+Math.max(0,amt||0).toFixed(9)+' SOL</span></div>'
    + '<div class="pt-quote-row"><span>Network and account-rent allowance</span><span>0.003 SOL</span></div>'
    + '<div class="pt-quote-row"><span>OrcAgent fee · '+(PT_FEE_RATE_TXN*100).toFixed(2)+'%</span><span>'+(feeBase*PT_FEE_RATE_TXN).toFixed(9)+' SOL</span></div>'
    + '<div class="pt-quote-note">Costs come out of your budget. Unused allowance stays in your wallet. Slippage changes the tokens received. The transaction is checked before sending.</div>';

  var availEl = _sheetEl('pt-sheet-avail');
  availEl.innerHTML = (_sheetAvail === null)
    ? 'Checking balance…'
    : '<b>' + _sheetAvail.toFixed(6) + ' SOL</b> available';

  // The button says why it cannot be pressed, rather than sitting greyed out
  // with no reason -- "nothing happens" is the worst state a Buy can be in.
  var min = PT_MIN_BUY_SOL;
  if(!(amt > 0)){
    _slideSetLabel('Enter an amount'); _slideEnable(false);
  } else if(amt < min){
    _slideSetLabel(min + ' SOL minimum'); _slideEnable(false);
  } else if(_sheetAvail !== null && amt > _sheetAvail + 1e-9){
    _slideSetLabel('More than you have'); _slideEnable(false);
  } else {
    _slideSetLabel('Slide to buy $' + (t && t.symbol || '')); _slideEnable(true);
  }
}

/* ── slide to confirm ───────────────────────────────────────────────────────
   Both Buy and Sell are irreversible and both used to be one tap away: Buy a
   single press, Sell a press-then-press-again with a 3-second window. A tap
   is what a pocket, a mis-scroll or a fat thumb produces by accident, and
   the 3-second arm made a Sell either too easy (inside the window) or
   confusing (outside it, where the second tap silently re-armed instead of
   selling). Dragging the knob the width of the track cannot happen by
   accident, and letting go early simply snaps back.

   The label is a separate element from the control on purpose: confirmBuy()
   writes "Buying…" into .pt-buy-confirm, and if that were the whole slider
   its textContent write would delete the knob and the fill. */
var _slideAt = 0, _slideOn = false, _sliding = false;

function _slideEls(){
  return {wrap: _sheetEl('pt-slide'), knob: _sheetEl('pt-slide-knob'),
          fill: _sheetEl('pt-slide-fill'), label: _sheetEl('pt-sheet-go')};
}
function _slideSetLabel(txt){
  var e = _slideEls(); if(e.label) e.label.textContent = txt;
}
function _slideEnable(on){
  _slideOn = on;
  var e = _slideEls(); if(e.wrap) e.wrap.classList.toggle('ready', !!on);
  if(!on) _slideReset();
}
// What makes a fast trade believable is not a longer wait -- it is being
// able to check it. This prints the transaction the chain accepted, how long
// it took, and a link straight to that chain's explorer.
function _showTxReceipt(idx, t, d){
  // The sheet's footer, not the card's empty panel of the same id -- the
  // receipt was being appended to a hidden leftover and never seen.
  var ft = _sheetFooter() || document.getElementById('pt-buy-panel-'+idx);
  if(!ft) return;
  var hash = d && (d.tx_hash || d.tx || d.sig || d.signature);
  var old = document.getElementById('pt-txline');
  if(old) old.remove();
  if(!hash) return;
  var base = (typeof PT_TX_EXPLORERS !== 'undefined' && PT_TX_EXPLORERS[t.chain]) || '';
  var secs = _tradeStartedAt ? ((Date.now() - _tradeStartedAt) / 1000).toFixed(1) : '';
  var short = String(hash).slice(0, 6) + '…' + String(hash).slice(-4);
  var el = document.createElement('div');
  el.className = 'pt-txline';
  el.id = 'pt-txline';
  el.innerHTML = (secs ? '<span class="pt-txms">confirmed in ' + secs + 's</span>' : '')
    + (base ? '<a href="' + esc(base + hash) + '" target="_blank" rel="noopener">' + esc(short) + '</a>'
            : '<span>' + esc(short) + '</span>');
  ft.appendChild(el);
}

// After a buy attempt ends WITHOUT a purchase -- refused, repriced, or the
// network died -- the slider has to become usable again. It used to be reset
// with btn.textContent='Confirm Buy', which wrote the OLD button's wording
// into the slider's label and left it disarmed: the sheet showed "Confirm
// Buy" over a dead grey knob, and a refused buy could not be retried at all
// without closing the sheet and finding the token again. A buy that DID go
// through does not come here -- it stays disarmed and says "Bought".
function _restoreSlide(){
  if(_sheetIdx === null) return;
  _slideReset();
  _paintSheet();
}
// The in-flight state. The wait is the chain confirming -- the server has
// already submitted by this point and is holding for a receipt -- so this
// says so and keeps moving. It is not a delay: nothing is held back, and it
// ends the moment the server answers.
var _tradeStartedAt = 0;
function _slideWorking(text){
  _tradeStartedAt = Date.now();
  var e = _slideEls();
  if(e.wrap){ e.wrap.classList.add('working'); e.wrap.classList.remove('ready'); }
  if(e.fill){ e.fill.style.width = ''; }
  if(e.label) e.label.textContent = text;
}
function _slideReset(){
  _slideAt = 0;
  var e = _slideEls();
  if(e.wrap) e.wrap.classList.remove('working');
  if(e.knob){ e.knob.style.transform = ''; }
  if(e.fill){ e.fill.style.width = '0'; }
  if(e.wrap){ e.wrap.classList.remove('dragging'); }
}
function _slideTravel(){
  var e = _slideEls();
  if(!e.wrap || !e.knob) return 1;
  return Math.max(1, e.wrap.clientWidth - e.knob.offsetWidth - 10);
}
function _slideMove(px){
  var max = _slideTravel();
  _slideAt = Math.max(0, Math.min(max, px));
  var e = _slideEls();
  if(e.knob) e.knob.style.transform = 'translateX(' + _slideAt + 'px)';
  if(e.fill) e.fill.style.width = (_slideAt + 46) + 'px';
}
function _slideRelease(){
  var e = _slideEls();
  if(e.wrap) e.wrap.classList.remove('dragging');
  // Most of the way is enough: asking for the last few pixels turns a
  // deliberate gesture into a dexterity test.
  if(_slideAt >= _slideTravel() * 0.85){
    _slideMove(_slideTravel());
    var idx = _sheetIdx;
    if(idx === null) return;
    _slideEnable(false);
    _slideWorking(_sheetMode === 'sell' ? 'Selling…' : 'Confirming on chain…');
    if(_sheetMode === 'sell') handleSell(idx);
    else confirmBuy(idx);
  } else {
    _slideReset();
  }
}

(function bindSlide(){
  // Touch listeners are PASSIVE. They used to be {passive:false} on the
  // whole document, only so a drag on the knob wouldn't also scroll the
  // page -- but a non-passive document touchstart/touchmove makes Android
  // Chrome wait for this JS before it may start ANY scroll anywhere on Live
  // Market. The knob now declares touch-action:none in CSS, which stops the
  // browser scrolling for touches that start on it without blocking the
  // rest of the page. Mouse events keep preventDefault (no text selection
  // while dragging); they never delay scrolling.
  function down(e){
    if(!_slideOn || _sheetIdx === null) return;
    var els = _slideEls();
    if(!els.knob || !els.knob.contains(e.target)) return;
    _sliding = true;
    els.wrap.classList.add('dragging');
    els.wrap._x0 = (e.touches ? e.touches[0].clientX : e.clientX) - _slideAt;
    if(!e.touches) e.preventDefault();
  }
  function move(e){
    if(!_sliding) return;
    var els = _slideEls();
    var x = (e.touches ? e.touches[0].clientX : e.clientX) - els.wrap._x0;
    _slideMove(x);
    if(!e.touches) e.preventDefault();
  }
  function up(){ if(!_sliding) return; _sliding = false; _slideRelease(); }
  _routeScope.addEventListener(document,'touchstart', down, {passive:true});
  _routeScope.addEventListener(document,'touchmove',  move, {passive:true});
  _routeScope.addEventListener(document,'touchend',   up);
  _routeScope.addEventListener(document,'touchcancel',up);
  _routeScope.addEventListener(document,'mousedown',  down);
  _routeScope.addEventListener(document,'mousemove',  move);
  _routeScope.addEventListener(document,'mouseup',    up);
  // A keyboard has no gesture to make, and Enter used to confirm in one
  // press -- which is the single accidental keystroke this whole control
  // exists to prevent, just moved off the touchscreen. The arrow keys walk
  // the knob the same distance a thumb would: eight presses to the end,
  // where it confirms, and Escape or Home puts it back. Deliberate by the
  // same measure, reachable without a touchscreen.
  var KEY_STEPS = 8;
  _routeScope.addEventListener(document,'keydown', function(e){
    if(_sheetIdx === null || !_slideOn) return;
    if(document.activeElement !== _sheetEl('pt-slide-knob')) return;
    var max = _slideTravel();
    if(e.key === 'ArrowRight'){
      e.preventDefault();
      _slideMove(_slideAt + max / KEY_STEPS);
      if(_slideAt >= max - 0.5) _slideRelease();
    } else if(e.key === 'ArrowLeft'){
      e.preventDefault();
      _slideMove(_slideAt - max / KEY_STEPS);
    } else if(e.key === 'Home' || e.key === 'Escape'){
      e.preventDefault();
      _slideReset();
    }
  });
})();

/* ── swipe the sheet down to dismiss ──
   Replaces the ✕ that sat in the top-right corner: on a phone that corner is
   the hardest place on the screen to reach, and a downward flick is what
   every other sheet on the device already answers to. Closing returns to
   Live Market, which is simply the page underneath -- nothing is navigated. */
(function bindSheetDrag(){
  var y0 = null, dy = 0, dragging = false;
  function start(e){
    if(_sheetIdx === null || _sliding) return;
    var sheet = _sheetEl('pt-sheet');
    // Not from the keypad or the slider: a drag that starts there is aimed
    // at those, not at the sheet.
    if(e.target.closest('#pt-keys, .pt-slide, .pt-sheet-pcts')) return;
    // A sheet scrolled down (a small phone, Protection or Fees open) is
    // scrolled back up by the same downward drag -- that must scroll, not
    // close the sheet under the finger.
    if(!sheet || sheet.scrollTop > 0) return;
    y0 = e.touches[0].clientY; dy = 0; dragging = true;
    sheet.classList.add('dragging');
  }
  function move(e){
    if(!dragging) return;
    var sh = _sheetEl('pt-sheet');
    if(sh.scrollTop > 0){                    // it became a scroll after all
      dragging = false; dy = 0;
      sh.classList.remove('dragging'); sh.style.transform = '';
      return;
    }
    dy = e.touches[0].clientY - y0;
    if(dy < 0) dy = 0;                       // upward does nothing
    _sheetEl('pt-sheet').style.transform = 'translateY(' + dy + 'px)';
  }
  function end(){
    if(!dragging) return;
    dragging = false;
    var sheet = _sheetEl('pt-sheet');
    sheet.classList.remove('dragging');
    sheet.style.transform = '';
    // A quarter of the screen, or 140px, whichever is smaller -- far enough
    // to be deliberate, near enough not to be a workout.
    if(dy > Math.min(140, window.innerHeight * 0.25)) closeBuySheet();
  }
  _routeScope.addEventListener(document,'touchstart', start, {passive:true});
  _routeScope.addEventListener(document,'touchmove',  move,  {passive:true});
  _routeScope.addEventListener(document,'touchend',   end);
  _routeScope.addEventListener(document,'touchcancel',end);
})();

// Keypad and the percentage row. Delegated, so the buttons themselves carry
// no handlers and the markup stays in the template.
_routeScope.addEventListener(document,'click', function(e){
  // The close button and the scrim are wired here rather than with an inline
  // onclick in the template: everything in this file lives inside an IIFE,
  // so closeBuySheet() is not a global and `onclick="closeBuySheet()"` threw
  // ReferenceError -- the sheet simply would not close.
  if(e.target.closest('[data-action="close-sheet"]')){ closeBuySheet(); return; }
  var modeButton=e.target.closest('#pt-sheet [data-mode]');
  if(modeButton && _sheetIdx !== null){
    var nextMode=modeButton.dataset.mode;
    if((nextMode==='buy'||nextMode==='sell') && nextMode!==_sheetMode){var currentIdx=_sheetIdx;closeBuySheet();_openSheet(currentIdx,nextMode);}
    return;
  }
  var k = e.target.closest('#pt-keys .pt-key');
  if(k && _sheetIdx !== null){
    var v = k.dataset.k;
    if(v === 'del'){
      _sheetTypeAmount(_sheetAmt.slice(0, -1));
    } else if(v === '.'){
      if(_sheetAmt.indexOf('.') === -1) _sheetTypeAmount((_sheetAmt || '0') + '.');
    } else {
      // No leading zeros ("05"), and SOL supports nine decimal places.
      var next = (_sheetAmt === '0') ? v : _sheetAmt + v;
      var dot = next.indexOf('.');
      if(dot !== -1 && next.length - dot > 10) return;
      if(next.replace('.', '').length > 12) return;
      _sheetTypeAmount(next);
    }
    return;
  }
  var p = e.target.closest('.pt-sheet-pcts .pt-pct');
  if(p && _sheetIdx !== null){
    if(_sheetAvail === null) return;
    var sell = _sheetMode === 'sell';
    var pct = Number(sell ? p.dataset.spct : p.dataset.pct);
    // Selling, the share is remembered as WELL as being filled in: a tap on
    // "All" must close the position exactly, and a dollar figure rounded to
    // the cent at a price that moves would leave a sliver behind. The
    // request carries the share; the figure is there so the screen can say
    // what that share comes to.
    if(sell){ _sellPct = pct || 100; _paintPcts('sell'); }
    var part = _sheetAvail * (pct / 100);
    // Floored to the cent: rounding up on Max would ask to spend more than
    // the wallet holds, and the server would refuse it.
    _sheetSetAmount(String(Math.floor(part * 1e9) / 1e9), true);
  }
});

_routeScope.addEventListener(document,'keydown', function(e){
  if(_sheetIdx === null) return;
  if(e.key === 'Escape'){ closeBuySheet(); return; }
  if(e.key === 'Backspace'){ _sheetTypeAmount(_sheetAmt.slice(0, -1)); e.preventDefault(); return; }
  if(e.key === '.' && _sheetAmt.indexOf('.') === -1){ _sheetTypeAmount((_sheetAmt || '0') + '.'); return; }
  if(e.key >= '0' && e.key <= '9'){
    var next = (_sheetAmt === '0') ? e.key : _sheetAmt + e.key;
    var dot = next.indexOf('.');
    if(dot !== -1 && next.length - dot > 10) return;
    _sheetTypeAmount(next);
  }
});

function openBuyPanel(idx){
  // Kept as the name every card's Buy button already calls. The in-card
  // panel it used to build is gone: on a phone the OS keyboard covered the
  // price, the move and the balance -- the figures being decided on -- the
  // moment the field was focused. See openBuySheet().
  openBuySheet(idx);
}

// Solana-only: pricing/execution uses /api/instant-trade; no EVM quote cache.

function confirmBuy(idx){
  var t = ST.tokens[Number(idx)];
  if(!t) return;
  var input = document.getElementById('pt-buy-amt-'+idx);
  var amt = parseFloat(input ? input.value : '');
  var msgEl = document.getElementById('pt-buy-msg-'+idx);
  if(!amt || amt<=0){ showMsg(msgEl, 'Enter a valid amount', false); return; }
  var btn = document.querySelector('#pt-buy-panel-'+idx+' .pt-buy-confirm');
  // When the sheet is driving, it has already said what is being waited on
  // ("Confirming on chain…"), which is more than "Buying…" says. Writing
  // over it would replace the specific with the vague.
  if(btn){
    btn.disabled = true;
    if(_sheetIdx === null) btn.textContent = 'Buying…';
  }
  var url = '/api/instant-trade';
  var body = {symbol:t.symbol, token_address:t.mint, pair_address:t.pair_address,
              side:'buy', currency:'SOL', amount_sol:amt,
              max_platform_fee_bps:Math.round(PT_FEE_RATE_TXN*10000)};
  var creatorContext = new URLSearchParams(location.search).get('creator_context');
  if(creatorContext) body.creator_context = creatorContext;
  body.protect = false;

  // Whether this attempt ended in a purchase. A bought trade must NOT leave
  // the slider armed again: the sheet would then read "Bought ..." above a
  // live "Slide to buy" for the seconds before it closes, which is an
  // invitation to buy the same token twice by accident.
  var bought = false;
  _routeScope.fetch(url, {
    method:'POST', credentials:'include', headers: authHeaders(),
    body: JSON.stringify(body)
  }).then(function(r){ return r.json(); }).then(function(d){
    // /api/instant-trade returns the accepted Solana transaction in one of
    // the compatibility fields below; accept only an explicit success shape.
    if(d && (d.success || d.tx || d.ok || d.sig || d.tx_hash)){
      // Show the realized USDC amount returned by the Solana trade when known.
      var got = (d.sol_amount != null) ? d.sol_amount : amt;
      var cur = d.currency || 'SOL';
      var line = 'Bought ' + got + ' ' + cur + ' of $' + t.symbol;
      if(d.max_spend_usd != null && Number(d.max_spend_usd) > Number(got)){
        line += ' (spent ' + d.max_spend_usd + ' ' + cur + ')';
      }
      bought = true;
      showMsg(msgEl, line, true);
      if(input) input.value = '';
      // The receipt is the whole point of the wait: it names the transaction
      // the chain accepted and links to it. A sheet that closes in 2.6s takes
      // that away before it can be read, so a buy that produced a hash holds
      // the sheet open longer -- long enough to read it and tap through.
      _showTxReceipt(idx, t, d);
      _routeScope.setTimeout(function(){ closeBuyPanel(idx); },
                 document.getElementById('pt-txline') ? 7000 : 2600);
    } else {
      showMsg(msgEl, (d && (d.error||d.msg)) || 'Buy failed', false);
    }
    if(bought){
      _slideEnable(false);          // also clears the in-flight sweep
      _slideSetLabel('Bought');
    } else {
      if(btn){ btn.disabled=false; }
      _restoreSlide();
    }
  }).catch(function(){
    showMsg(msgEl, 'Network error — buy not sent', false);
    if(btn){ btn.disabled=false; }
    _restoreSlide();
  });
}

function handleSell(idx, btn){
  var t = ST.tokens[Number(idx)];
  if(!t) return;
  // The confirmation is the slide in the sheet now, not a second tap here.
  // The old arm was a 3-second window: inside it a stray tap sold, outside
  // it the second tap silently re-armed instead of selling. `btn` is only
  // passed by the card's own button, which now just opens the sheet.
  if(btn){ openSellSheet(idx); return; }
  var msgEl = document.getElementById('pt-buy-msg-'+idx);
  _slideSetLabel('Selling…');
  var url = '/api/instant-trade';
  // A SHARE, never a quantity. The server works out how many tokens that is
  // from what it can see is held -- so a tampered number can only ever ask
  // for a different slice of your own position, never for more of it than
  // exists, and never for somebody else's.
  // Which of the two the screen was last driven by. A tapped share travels
  // as a share, so "All" closes the position exactly rather than to the
  // nearest cent; a typed figure travels as dollars, so what is sold is
  // what was typed. Either way the server does the converting.
  var how;
  if(_sellPct != null){
    how = {sell_pct: Math.min(100, Math.max(1, Number(_sellPct) || 100))};
  } else {
    var usd = parseFloat(_sheetAmt);
    if(!(usd > 0)){ toast('Enter an amount to sell'); _slideEnable(true); _slideReset(); return; }
    how = {sell_sol: usd};
  }
  var body = Object.assign({symbol:t.symbol, token_address:t.mint,
                            pair_address:t.pair_address, side:'sell', amount_sol:0,
                            max_platform_fee_bps:Math.round(PT_FEE_RATE_TXN*10000)}, how);
  _routeScope.fetch(url, {
    method:'POST', credentials:'include', headers: authHeaders(),
    body: JSON.stringify(body)
  }).then(function(r){ return r.json(); }).then(function(d){
    // Both EVM sell routes used to answer HTTP 200 with ok:true even for a
    // swap that failed -- ok meant only "the position was found and a sell
    // was attempted" -- so sell_executed was the one trustworthy signal.
    // They now answer ok:false with an error status when the sell does not
    // go through, and the two agree; both are checked so this keeps working
    // whichever version of the backend is deployed.
    var sold = !!(d && (d.success||d.tx||d.ok||d.sig));
    // proceeds_usdc is what the swap actually returned, measured from the
    // wallet across the trade -- shown only when it was measured, since the
    // fallback is a market quote rather than the realised amount.
    var got = (sold && d && d.sol_amount != null)
      ? (' for ' + Number(d.sol_amount).toFixed(6) + ' SOL') : '';
    var partial = sold && (d && d.position_closed === false);
    toast(sold ? ((partial ? 'Sold ' + (d.sold_pct != null ? d.sold_pct + '% of $' : 'part of $')
                           : 'Sold $') + t.symbol + got)
               : ((d && (d.error||d.msg)) || 'Sell failed'));
    // A sold position is gone, so there is nothing left for this sheet to
    // act on -- it closes rather than offering to sell it again. A failure
    // keeps it open with the slider armed, so the person can retry without
    // finding the card again.
    if(sold){
      // Same as a buy: show what the chain accepted before the sheet goes.
      _showTxReceipt(idx, t, d);
      if(document.getElementById('pt-txline')){
        _slideEnable(false);        // also clears the in-flight sweep
        _slideSetLabel('Sold');
        // Only if this is still the same sheet: opening another token inside
        // those seconds must not have its screen closed out from under it.
        _routeScope.setTimeout(function(){
          if(String(_sheetIdx) === String(idx)) closeBuySheet();
        }, 7000);
      } else {
        closeBuySheet();
      }
    } else { _slideEnable(true); _slideReset(); }
  }).catch(function(){
    toast('Network error — sell not sent');
    _slideEnable(true); _slideReset();
  });
}

/* ── watchlist ── */
function loadWatchlistSet(){
  return _routeScope.fetch('/api/watchlist', {credentials:'include'}).then(function(r){ return r.json(); }).then(function(d){
    watchSet = new Set((d && d.ok ? d.tokens : []).map(function(t){ return t.token_address; }));
  }).catch(function(){});
}
function toggleWatch(mint, sym, btn){
  var active = watchSet.has(mint);
  _routeScope.fetch('/api/watchlist/'+encodeURIComponent(mint), {
    method: active?'DELETE':'POST', credentials:'include', headers: authHeaders(),
    body: active ? undefined : JSON.stringify({symbol:sym})
  }).then(function(r){ return r.json(); }).then(function(d){
    if(d && d.ok){
      if(active) watchSet.delete(mint); else watchSet.add(mint);
      if(btn){ btn.classList.toggle('active', !active); btn.textContent = !active?'★':'☆'; }
      loadWatchlist();
    } else {
      toast((d && d.msg) || 'Connect your wallet to use the watchlist');
    }
  }).catch(function(){ toast('Network error'); });
}
function toggleWlEdit(){
  _wlEditMode = !_wlEditMode;
  var btn = document.getElementById('pt-wl-edit-btn');
  if(btn) btn.textContent = _wlEditMode ? 'Done' : 'Edit';
  document.querySelectorAll('.pt-wl-remove').forEach(function(b){ b.classList.toggle('show', _wlEditMode); });
}
function removeWatchFromList(mint){
  _routeScope.fetch('/api/watchlist/'+encodeURIComponent(mint), {method:'DELETE', credentials:'include', headers:authHeaders()})
    .then(function(r){ return r.json(); }).then(function(d){
      if(d && d.ok){ watchSet.delete(mint); loadWatchlist(); renderFeedList(); }
    }).catch(function(){});
}
function loadWatchlist(){
  _routeScope.fetch('/api/watchlist', {credentials:'include'}).then(function(r){ return r.json(); }).then(function(d){
    var addrs = (d && d.ok ? d.tokens : []) || [];
    var el = document.getElementById('pt-wl-list');
    if(!addrs.length){ el.innerHTML = '<div class="pt-tape-empty">No tokens watched</div>'; return; }
    var joined = addrs.map(function(t){ return t.token_address; }).join(',');
    _routeScope.fetch('/api/dexscreener/tokens/'+joined).then(function(r){ return r.json(); }).then(function(pd){
      var byAddr = {};
      (pd.pairs||[]).forEach(function(p){
        var a = p.baseToken && p.baseToken.address;
        if(!a) return;
        var liq = (p.liquidity && p.liquidity.usd) || 0;
        var cur = byAddr[a];
        if(!cur || liq > ((cur.liquidity&&cur.liquidity.usd)||0)) byAddr[a] = p;
      });
      el.innerHTML = addrs.map(function(t){
        var p = byAddr[t.token_address];
        var price = p ? fmtPrice(p.priceUsd) : '—';
        var chg = p && p.priceChange ? p.priceChange.h24 : null;
        var img = p && p.info && p.info.imageUrl;
        return '<div class="pt-wl-row">'
          + logoTile(img, t.symbol, 'pt-trader-av', 'pt-trader-av-ph')
          + '<div class="pt-trader-mid"><div class="pt-trader-name">$'+esc(t.symbol||'?')+'</div></div>'
          + '<div class="pt-trader-right"><div class="mono" style="font-size:11.5px;font-weight:700">'+price+'</div>'
          + '<div class="mono '+((chg||0)>=0?'up':'down')+'" style="font-size:10px">'+(chg!=null?fmtPct(chg):'—')+'</div></div>'
          + '<button class="pt-wl-remove'+(_wlEditMode?' show':'')+'" data-mint="'+esc(t.token_address)+'">✕</button>'
          + '</div>';
      }).join('');
    }).catch(function(){ el.innerHTML = '<div class="pt-tape-empty">No tokens watched</div>'; });
  }).catch(function(){});
}

/* ── live trades tape ── */
/* ── SURGE STRIP ──
   Tokens whose 5-minute activity just jumped far above their own recent
   normal (see surge_radar.py). Pinned above the sorted feed because this is
   the one thing on the page that stops being useful within minutes. */
function surgeCardHtml(s){
  var buys = s.buys_5m || 0, sells = s.sells_5m || 0, tot = buys + sells;
  var buyPct = tot ? (buys / tot * 100) : 50;
  var img = s.image_url
    ? '<img class="pt-surge-img" src="'+esc(s.image_url)+'" alt="" onerror="this.style.visibility=\'hidden\'">'
    : '<span class="pt-surge-img"></span>';
  var age = s.age_seconds < 60 ? (s.age_seconds+'s')
          : (Math.floor(s.age_seconds/60)+'m');
  // The price move is what people come to this strip for, so it takes the
  // card's most prominent slot and the volume multiplier drops to the meta
  // line. Prefer DexScreener's 5m figure so the card agrees with the rest of
  // the site; fall back to the move the radar measured across its own
  // samples, labelled with the period it actually covers rather than
  // borrowed as "5m".
  var chg = Number(s.price_change_5m)||0, chgWin = '5m';
  if(Math.abs(chg) < 0.05){
    chg = Number(s.price_change_obs)||0;
    chgWin = Math.max(1, Math.round((Number(s.obs_seconds)||0)/60))+'m';
  }
  // On its own line, not squeezed into the header row: five items sharing
  // 172px was clipping tickers to "$A..." and left no room to make the
  // percentage the largest thing on the card, which is the whole point.
  var chgHtml = Math.abs(chg) >= 0.05
    ? '<div class="pt-surge-chg '+(chg>=0?'up':'down')+'" title="Price move over '+chgWin+'">'
        + (chg>=0?'+':'')+chg.toFixed(1)+'%<i>'+chgWin+'</i></div>'
    : '<div class="pt-surge-chg none" title="No price move measured yet">—</div>';
  return '<div class="pt-surge-card'+(s.cooling?' cooling':'')+'" data-action="open-surge" data-mint="'+esc(s.mint)+'"'
       + ' data-pair="'+esc(s.pair_address||'')+'" data-chain="'+esc(s.chain||'')+'" data-symbol="'+esc(s.symbol||'')+'">'
    + '<div class="pt-surge-top">'+img
      + '<span class="pt-surge-sym">$'+esc(s.symbol||'?')+'</span>'
      // Being talked about on X is a bonus signal, never why a token is
      // here -- the badge only appears on something that already surged.
      + (s.x_buzz ? '<span class="pt-surge-x" title="Also being talked about on X">𝕏</span>' : '')
      // The short badge the rest of the page uses -- "ROBINHOOD" spelled out
      // here ate the ticker's width and left cards reading "$A...".
      + '<span class="pt-surge-chain">'+esc(CHAIN_LABELS[s.chain] || (s.chain||'').toUpperCase())+'</span>'
    + '</div>'
    + chgHtml
    + '<div class="pt-surge-meta">'
      + '<span class="pt-surge-mult" title="Volume versus this token\'s own recent average">'+(s.vol_ratio||0)+'x</span><span>·</span>'
      + '<span>'+fmtUsd(s.volume_5m||0)+'/5m</span><span>·</span>'
      + '<span>'+tot+' tx</span><span>·</span>'
      + '<span>'+age+'</span>'
    + '</div>'
    + '<div class="pt-surge-bar"><i style="width:'+buyPct.toFixed(0)+'%"></i><i class="s" style="width:'+(100-buyPct).toFixed(0)+'%"></i></div>'
  + '</div>';
}

var _surgeMarkup=null, _tapeIdentity=null, _traderIdentity=null;
// Tokens launched on OrcAgent, newest first. Tapping one opens its card here
// (the same in-page path a surge uses), so the buy runs through OrcAgent.
var _launchMarkup=null;
function _launchAge(ts){
  var s=Math.max(0,Date.now()/1000-(Number(ts)||0));
  if(!ts) return '';
  if(s<3600) return Math.max(1,Math.floor(s/60))+'m';
  if(s<86400) return Math.floor(s/3600)+'h';
  return Math.floor(s/86400)+'d';
}
function launchCardHtml(l){
  return '<div class="pt-launch-card" data-action="open-surge" data-mint="'+esc(l.mint)+'" data-symbol="'+esc(l.symbol)+'">'
    +'<img class="pt-launch-img" src="'+esc(l.logo_url)+'" alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">'
    +'<div class="pt-launch-body"><div class="pt-launch-sym">$'+esc(l.symbol)+'</div>'
    +'<div class="pt-launch-meta">'+esc(l.quote_asset)+' · '+_launchAge(l.finalized_at||l.created_at)+'</div></div>'
    +'<span class="pt-launch-buy">Buy</span></div>';
}
/* The strip appeared once its fetch answered and pushed the token list down.
   The cards seen last this session are shown straight away instead; the
   fresh list replaces them in place. */
var _LAUNCH_CACHE_KEY='oa_lm_launches_v1';
function restoreLaunches(){
  try{
    var markup=sessionStorage.getItem(_LAUNCH_CACHE_KEY);
    var wrap=document.getElementById('pt-launch-wrap'), rail=document.getElementById('pt-launch-rail');
    if(!markup || !wrap || !rail) return;
    rail.innerHTML=markup; _launchMarkup=markup; wrap.style.display='';
  }catch(e){}
}
function loadLaunches(){
  _routeScope.fetch('/api/token-launches?page=1', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      var wrap=document.getElementById('pt-launch-wrap'), rail=document.getElementById('pt-launch-rail');
      if(!wrap || !rail || _railsBeingTouched['pt-launch-rail']) return;
      var list=((d && d.launches) || []).slice(0, 12);
      // No launches yet: no empty strip.
      if(!list.length){ wrap.style.display='none'; _launchMarkup=null; try{ sessionStorage.setItem(_LAUNCH_CACHE_KEY,''); }catch(e){} return; }
      wrap.style.display='';
      var markup=list.map(launchCardHtml).join('');
      try{ sessionStorage.setItem(_LAUNCH_CACHE_KEY, markup); }catch(e){}
      if(markup!==_launchMarkup){
        var keep=rail.scrollLeft; rail.innerHTML=markup; _launchMarkup=markup; rail.scrollLeft=keep;
      }
    })
    .catch(function(){});
}
function loadSurges(){
  _routeScope.fetch('/api/market/surges', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      var wrap = document.getElementById('pt-surge-wrap');
      var rail = document.getElementById('pt-surge-rail');
      if(!wrap || !rail) return;
      // A full rebuild mid-swipe cancels the browser's own momentum
      // scrolling and snaps the strip back to its start -- defer this
      // tick rather than yank the rail out from under an active gesture.
      // The next poll (12s later) picks it up once the finger lifts.
      if(_railsBeingTouched['pt-surge-rail']) return;
      var list = (d && d.surges) || [];
      // Hidden entirely when nothing is surging -- an empty "SURGING NOW"
      // strip would read as a broken feature rather than a quiet market.
      if(!list.length){ wrap.style.display = 'none'; _surgeMarkup=null; return; }
      wrap.style.display = '';
      var newMarkup=list.map(surgeCardHtml).join('');
      if(newMarkup!==_surgeMarkup){
        var keepScroll=rail.scrollLeft;
        rail.innerHTML=newMarkup;
        _surgeMarkup=newMarkup;
        rail.scrollLeft=keepScroll;
      }
      var sub = document.getElementById('pt-surge-sub');
      if(sub) sub.textContent = list.length + (list.length === 1 ? ' token' : ' tokens')
        + ' · vs their own 5m average';
    })
    .catch(function(){});
}

function loadTape(){
  _routeScope.fetch('/api/market/tape').then(function(r){ return r.json(); }).then(function(d){
    var el = document.getElementById('pt-tape-list');
    var rows = (d && d.ok && d.trades) || [];
    var identity=JSON.stringify(rows.slice(0,14).map(function(t){return [t.id,t.tx_hash,t.timestamp,t.side,t.symbol,t.sol_amount,t.usd_amount];}));
    if(identity===_tapeIdentity) return;
    _tapeIdentity=identity;
    if(!rows.length){ el.innerHTML = '<div class="pt-tape-empty">Waiting for trades…</div>'; return; }
    el.innerHTML = rows.slice(0,14).map(function(r){
      var side = String(r.side||'').toLowerCase()==='sell' ? 'sell' : 'buy';
      return '<div class="pt-tape-row">'
        + '<span class="pt-tape-pill '+side+'">'+side.toUpperCase()+'</span>'
        + '<span class="pt-tape-sym">$'+esc(r.symbol)+'</span>'
        + '<span class="pt-tape-amt">'+(r.usd_amount!=null?'$'+Number(r.usd_amount).toFixed(2):Number(r.sol_amount||0).toFixed(3)+' SOL')+'</span>'
        + '<span class="pt-tape-age">'+fmtAgeSeconds(r.age_seconds)+'</span>'
        + '</div>';
    }).join('');
  }).catch(function(){});
}

/* ── top traders / copy trade ──
   /api/leaderboard is the real rolling-24h leaderboard (see its own
   docstring server-side) -- this used to call /api/leaderboard/full, the
   ALL-TIME ranking, while both the right-rail card and this rail's own
   heading say "24h". Fetched once and rendered into both the compact
   top-of-feed rail (renderTraderRail, mobile+desktop, above the fold) and
   the fuller right-rail list (desktop only, has the Copy-trade button). */
/* The Top traders rail appeared once /api/leaderboard answered and pushed
   the token list 144px down. The traders seen last this session are drawn
   straight away; the fresh list replaces them in place. */
var _TRADERS_CACHE_KEY='oa_lm_traders_v1';
function restoreTraders(){
  try{
    var rows=JSON.parse(sessionStorage.getItem(_TRADERS_CACHE_KEY)||'null');
    if(Array.isArray(rows) && rows.length) renderTraderRail(rows);
  }catch(e){}
}
function loadTraders(){
  _routeScope.fetch('/api/leaderboard').then(function(r){ return r.json(); }).then(function(rows){
    rows = Array.isArray(rows) ? rows : [];
    try{ sessionStorage.setItem(_TRADERS_CACHE_KEY, JSON.stringify(rows.slice(0, 20))); }catch(e){}
    var identity=JSON.stringify([rows,_copyStatus.copying,_copyStatus.target]);
    if(identity===_traderIdentity) return;
    _traderIdentity=identity;
    renderTraderRail(rows);
    var el = document.getElementById('pt-traders-list');
    if(!el) return;
    if(!rows.length){ el.innerHTML = '<div class="pt-tape-empty">No traders yet</div>'; return; }
    el.innerHTML = rows.slice(0,8).map(function(t){
      var isCopying = _copyStatus.copying && _copyStatus.target === t.wallet_address;
      var pnl = Number(t.total_pnl||0);
      return '<div class="pt-trader-row">'
        + '<span class="pt-trader-rank">'+t.rank+'</span>'
        + '<span class="pt-trader-click" data-action="trader-profile" data-wallet="'+esc(t.wallet_address)+'">'
        +   logoTile(t.avatar_url, t.username, 'pt-trader-av', 'pt-trader-av-ph')
        +   '<div class="pt-trader-mid"><div class="pt-trader-name">'+esc(t.username)+'</div>'
        +     '<div class="pt-trader-sub">'+(t.win_rate||0)+'% win · '+(t.trade_count||0)+' trades</div></div>'
        + '</span>'
        + '<div class="pt-trader-right"><div class="pt-trader-pnl mono '+(pnl>=0?'up':'down')+'">'+fmtTraderPnl(t)+'</div>'
        +   '<button class="pt-copy-link'+(isCopying?' active':'')+'" data-action="copy" data-wallet="'+esc(t.wallet_address)+'">'+(isCopying?'Copying':'Copy')+'</button></div>'
        + '</div>';
    }).join('');
  }).catch(function(){});
}

/* The bot card says what YOUR bot is doing. It read "Bot is scanning ·
   auto-buys on ≥5% breakout with these filters" for everyone: true for no
   one with the bot off, and the bot buys on its own settings (breakout
   trigger, market-cap floor...), not on this feed's filters. */
function loadBotCard(){
  var card = document.getElementById('pt-bot-card');
  if(!card) return;
  _routeScope.fetch('/api/bot/status', {credentials:'include'})
    .then(function(r){ return r.status === 401 ? {ok:false, guest:true} : r.json(); })
    .then(function(d){
      var state = document.getElementById('pt-bot-state'), sub = document.getElementById('pt-bot-sub');
      if(!d || !d.ok){
        if(d && d.guest){
          state.textContent = 'Auto-trading bot';
          sub.textContent = 'Connect a wallet and the bot trades for you with your own settings.';
        }
        card.classList.add('off');
        return;
      }
      var running = !!d.running, open = Number(d.open_positions)||0;
      card.classList.toggle('off', !running);
      state.textContent = running ? 'Your bot is on' : 'Your bot is off';
      sub.textContent = running
        ? (open ? open+' open position'+(open===1?'':'s')+' · ' : '')+'Buys with your bot settings, not these filters.'
        : 'Turn it on to trade automatically with your own settings.';
    }).catch(function(){});
}

/* Compact horizontal spotlight (ring + circle avatar + name + a stat
   underneath) for people -- sits inside the always-visible center
   feed so it doesn't need the desktop-only right rail to be seen, and
   answers exactly what was asked: which traders are actually up real money
   (shown in USD, see fmtTraderPnl()) today, one tap to their profile. */
function renderTraderRail(rows){
  var wrap = document.getElementById('pt-trader-rail-wrap');
  var el = document.getElementById('pt-trader-rail');
  if(!wrap || !el) return;
  var top = (rows||[]).filter(function(t){ return Number(t.total_pnl||0) > 0; }).slice(0, 10);
  if(!top.length){ wrap.style.display = 'none'; return; }
  wrap.style.display = '';
  el.innerHTML = top.map(function(t){
    var verified = t.badges && t.badges.indexOf('verified') !== -1;
    return '<div class="pt-story pt-trader-story" data-action="trader-profile" data-wallet="'+esc(t.wallet_address)+'">'
      + '<div class="pt-trader-rank-badge'+(t.rank===1?' gold':'')+'">'+esc(String(t.rank))+'</div>'
      + '<div class="pt-story-ring">'
      +   '<div class="pt-story-inner">'
      +     logoTile(t.avatar_url, t.username, 'pt-story-img', 'pt-story-img-ph')
      +   '</div>'
      + '</div>'
      + '<div class="pt-story-name">'+esc(t.username||'')+(verified?' ✓':'')+'</div>'
      + '<div class="pt-story-chg up">'+fmtTraderPnl(t)+'</div>'
      + '</div>';
  }).join('');
}
function toggleCopy(btn){
  var wallet = btn.dataset.wallet;
  var alreadyCopying = _copyStatus.copying && _copyStatus.target === wallet;
  _routeScope.fetch('/api/copy-trade/toggle', {
    method:'POST', credentials:'include', headers: authHeaders(),
    // No amount: the copy spends this user's own trade size, in USDC.
    body: JSON.stringify({wallet: wallet})
  }).then(function(r){ return r.json(); }).then(function(d){
    if(d && d.ok){
      var copying = d.copying!=null ? d.copying : d.active;
      _copyStatus.copying = !!copying;
      _copyStatus.target  = copying ? wallet : null;
      loadTraders();
      toast(copying ? 'Copy-trading enabled' : 'Copy-trading stopped');
    } else {
      toast((d && d.msg) || 'Could not update copy-trade');
    }
  }).catch(function(){ toast('Network error'); });
}

/* ── market pulse ── */
function loadPulse(){
  _routeScope.fetch('/api/platform/stats').then(function(r){ return r.json(); }).then(function(d){
    if(!d || !d.ok) return;
    var tradesEl = document.getElementById('pt-pulse-trades');
    var netEl    = document.getElementById('pt-pulse-net');
    if(tradesEl) tradesEl.textContent = d.trades_today;
    if(netEl){
      var net = Number(d.net_pnl_today||0);
      netEl.textContent = (net>=0?'+':'')+net.toFixed(2);
      netEl.classList.toggle('green', net>=0);
      netEl.style.color = net<0 ? 'var(--red)' : '';
    }
  }).catch(function(){});
  _routeScope.fetch('/api/online-count').then(function(r){ return r.json(); }).then(function(d){
    var el = document.getElementById('pt-pulse-online');
    if(d && d.ok && el) el.textContent = d.online;
  }).catch(function(){});
}

/* ── deep-linked token (shared navbar's search redirects here as ?mint=) ── */
function scrollToCard(idx){
  var card = document.getElementById('pt-card-'+idx);
  if(!card) return;
  card.scrollIntoView({behavior:'smooth', block:'center'});
  var wasHi = card.classList.contains('hi');
  card.classList.add('hi');
  if(!wasHi) _routeScope.setTimeout(function(){ card.classList.remove('hi'); }, 1600);
}

// Buy links open the existing confirmation sheet once, for the exact mint.
// Opening it never submits a trade; the member still chooses an amount and confirms.
function _openRequestedBuy(mint){
  var url = new URL(location.href);
  if(url.searchParams.get('buy') !== '1' || (url.searchParams.get('mint') || url.searchParams.get('addr')) !== mint) return;
  var idx = ST.tokens.findIndex(function(t){ return t.mint === mint; });
  if(idx < 0) return;
  url.searchParams.delete('buy');
  history.replaceState(history.state, '', url.pathname + url.search + url.hash);
  openBuyPanel(idx);
}

function prependSearchedToken(mint, sym, pairAddr){
  return _routeScope.fetch('/api/token/info/'+encodeURIComponent(mint)).then(function(r){ return r.json(); }).then(function(info){
    var tok;
    if(info && info.ok){
      var pc = info.price_change || {};
      tok = {
        mint: info.address||mint, symbol: info.symbol||sym, name: info.name||sym,
        chain: info.chain||'solana', pair_address: info.pair_address||pairAddr,
        image_url: info.image_url||'', price_usd: info.price_usd==null?null:Number(info.price_usd),
        market_cap: info.market_cap==null?null:Number(info.market_cap), liquidity_usd: info.liquidity_usd==null?null:Number(info.liquidity_usd),
        volume_24h: info.volume_24h==null?null:Number(info.volume_24h), buys_24h: info.buyers_24h==null?null:Number(info.buyers_24h), sells_24h: info.sellers_24h==null?null:Number(info.sellers_24h),
        price_change_24h: info.price_change_24h==null?(info.source?null:Number(pc.h24||0)):Number(info.price_change_24h), pair_created_at: info.pair_created_at||null, verified_socials:false, score:3, source:info.source||'', quote_asset:info.quote_asset||''
      };
    } else {
      tok = {mint:mint, symbol:sym, name:sym, chain:'solana', pair_address:pairAddr, image_url:'',
        price_usd:0, market_cap:0, liquidity_usd:0, volume_24h:0, buys_24h:0, sells_24h:0,
        price_change_24h:0, pair_created_at:null, verified_socials:false, score:3};
    }
    ST.tokens = [tok].concat(ST.tokens.filter(function(t){ return t.mint !== tok.mint; }));
    renderFeedList();
    updateHeaderCounts();
    _routeScope.setTimeout(function(){ if(_profileMint===tok.mint) syncTokenProfile(); else scrollToCard(0); _openRequestedBuy(tok.mint); }, 60);
  }).catch(function(){});
}

/* ── event wiring ── */
_routeScope.addEventListener(document,'click', function(e){
  var el;
  if((el = e.target.closest('[data-action="token-profile"]'))){ setTokenProfile(el.dataset.mint); return; }
  if((el = e.target.closest('[data-action="watch"]'))){ toggleWatch(el.dataset.mint, el.dataset.sym, el); return; }
  if((el = e.target.closest('[data-action="buy-open"]'))){ openBuyPanel(el.dataset.idx); return; }
  if((el = e.target.closest('[data-action="confirm-buy"]'))){ confirmBuy(el.dataset.idx); return; }
  if((el = e.target.closest('[data-action="sell"]'))){ handleSell(el.dataset.idx, el); return; }
  if((el = e.target.closest('[data-action="copy"]'))){ toggleCopy(el); return; }
  if((el = e.target.closest('[data-action="copy-ca"]'))){ copyCA(el.dataset.mint, el); return; }
  if((el = e.target.closest('[data-action="open-surge"]'))){
    // Reuses the same path the navbar search uses -- a surging token is
    // usually not in the current sorted feed yet, so it has to be injected
    // rather than scrolled to.
    prependSearchedToken(el.dataset.mint, el.dataset.symbol || '', el.dataset.pair || '');
    return;
  }
  if((el = e.target.closest('[data-action="trader-profile"]'))){
    if(el.dataset.wallet) location.href = '/profile/' + encodeURIComponent(el.dataset.wallet);
    return;
  }
  if((el = e.target.closest('.pt-tf-pill'))){
    var wrap = el.closest('.pt-chart-tfs');
    var idx = wrap.id.replace('pt-chart-tfs-','');
    wrap.querySelectorAll('.pt-tf-pill').forEach(function(b){ b.classList.toggle('active', b===el); });
    setChartTf(idx, el.dataset.tf);
    return;
  }
  if((el = e.target.closest('[data-sort]'))){ setSort(el.dataset.sort); return; }
  if((el = e.target.closest('.pt-age-chip'))){ setAge(el.dataset.age); return; }
  if((el = e.target.closest('.pt-toggle-row'))){ toggleFilter(el); return; }
  if((el = e.target.closest('#pt-wl-edit-btn'))){ toggleWlEdit(); return; }
  if((el = e.target.closest('.pt-wl-remove'))){ removeWatchFromList(el.dataset.mint); return; }
});

/* ── init ── */
_routeScope.addEventListener(document,'DOMContentLoaded', function(){
  var liqSlider  = document.getElementById('pt-liq-slider');
  var liqValueEl = document.getElementById('pt-liq-value');
  var _liqDebounce = null;
  _routeScope.addEventListener(liqSlider,'input', function(){
    ST.minLiquidity = parseInt(liqSlider.value, 10);
    liqValueEl.textContent = '$'+fmtShort(ST.minLiquidity)+' of $500K';
    updateAdvCount();
    _routeScope.clearTimeout(_liqDebounce);
    _liqDebounce = _routeScope.setTimeout(loadFeed, 350);
  });

  // Folded by default on a phone, open on desktop. Set from JS rather than
  // CSS because <details> is driven by an attribute, not a display property —
  // and only at startup, so reopening it is not undone on the next resize.
  var advEl = document.getElementById('pt-adv');
  if(advEl && window.matchMedia && window.matchMedia('(max-width: 900px)').matches){
    advEl.open = false;
  }
  updateAdvCount();

  /* mobile: left-rail filters drawer (the nav drawer is the shared navbar's
     own, see static/navbar.js) */
  var filtersBtn = document.getElementById('pt-mobile-filters-btn');
  var leftEl     = document.getElementById('pt-left');
  var scrimEl    = document.getElementById('pt-scrim');

  // How tall the navbar actually is, published as a CSS variable so the
  // drawer and the scrim can start underneath it.
  //
  // Measured, not assumed: at this breakpoint the search field wraps onto a
  // second line, so the bar is not one fixed height, and a notch or a font
  // that loads late moves it again. Guessing produced the bug this fixes --
  // the drawer began at the top of the screen, underneath a navbar sitting
  // 105 z-index levels above it, so its first rows were simply not visible.
  function syncNavbarHeight(){
    var nb = document.querySelector('.pt-nb-topbar');
    if(!nb) return;
    var h = Math.round(nb.getBoundingClientRect().height);
    if(h > 0) document.documentElement.style.setProperty('--pt-nb-h', h + 'px');
  }
  syncNavbarHeight();
  // Again after webfonts settle, which is the common way the bar ends up a
  // few pixels taller than it measured on first paint.
  if(document.fonts && document.fonts.ready) document.fonts.ready.then(syncNavbarHeight);
  _routeScope.addEventListener(window,'resize', syncNavbarHeight);
  _routeScope.addEventListener(window,'orientationchange', syncNavbarHeight);

  if(filtersBtn) _routeScope.addEventListener(filtersBtn,'click', function(){
    var opening = !leftEl.classList.contains('mobile-open');
    closeMobileOverlays();
    // Re-measured on open rather than only at startup: the bar can have
    // grown or shrunk since (a wrapped search field, a badge appearing).
    if(opening){
      syncNavbarHeight();
      leftEl.classList.add('mobile-open');
      scrimEl.classList.add('show');
      // The feed behind it must not scroll: scrolling it moves nothing the
      // reader can see and takes the page somewhere else once they close it.
      try{ document.body.style.overflow = 'hidden'; }catch(e){}
    }
  });
  if(scrimEl) _routeScope.addEventListener(scrimEl,'click', closeMobileOverlays);

  /* re-measure & redraw mounted charts on resize/rotation (e.g. desktop<->mobile
     breakpoint change) -- renderChartSvg() re-reads clientWidth each call, it
     just isn't re-triggered by a resize on its own between 5s poll ticks */
  var _resizeTimer = null;
  _routeScope.addEventListener(window,'resize', function(){
    _routeScope.clearTimeout(_resizeTimer);
    _resizeTimer = _routeScope.setTimeout(function(){
      Object.keys(_chartTimers).forEach(function(idx){ chartTick(idx); });
    }, 200);
  });

  enableDragScroll(document.getElementById('pt-surge-rail'));
  enableDragScroll(document.getElementById('pt-launch-rail'));
  enableDragScroll(document.getElementById('pt-trader-rail'));

  _prefetchBalances();
  renderSortList();
  var _hydratedFeed=hydrateInitialFeed();
  // Deep links must paint the requested token before the full scanner feed.
  // The feed is only a background numbers refresh once that profile exists.
  // ?addr= is the older spelling that token cards in DMs and shared trades
  // (and links already sent) use; it opens the token's profile like
  // ?mint=...&profile=1.
  var _qs = new URLSearchParams(location.search);
  var _qMint = _qs.get('mint') || _qs.get('addr');
  if(_qMint){
    _focusedMint = _qMint;
    if(_qs.get('profile')==='1' || (_qs.get('addr') && !_qs.get('mint'))) _profileMint=_qMint;
    // Warm real chart history in parallel with token details, with the server
    // resolving the active pool. A first visit does not wait for the scanner.
    fetchChart(_qMint,'5m','','solana').then(function(r){
      if(!r || !r.candles || !r.candles.length || !r.pair_address) return;
      var idx=ST.tokens.findIndex(function(t){return t.mint===_qMint;});
      var tok=ST.tokens[idx];
      if(tok && tok.pair_address && tok.pair_address!==r.pair_address) return;
      candleCachePut(_qMint,r.pair_address,'5m',r.candles,r.current_price);
      var st=_chartTimers[idx];
      if(st && !st.destroyed && _candlesMatchPrice(r.candles,_cardRefPrice(st,idx))){
        st.candles=r.candles;st.price=r.current_price;
        renderChartSvg(idx,st.candles,st.price);
      }
    });
    prependSearchedToken(_qMint,'','').finally(function(){
      if(!ST.tokens.some(function(t){return t.mint===_qMint;})) _pendingDeepLinkMint=_qMint;
      loadFeed(true);
      loadWatchlistSet().then(patchWatchButtons);
    });
  } else {
    loadFeed(_hydratedFeed);
    loadWatchlistSet().then(patchWatchButtons);
  }
  loadSurges();
  restoreLaunches();
  loadLaunches();
  loadTape();
  restoreTraders();
  loadTraders();
  loadWatchlist();
  loadPulse();
  _routeScope.fetch('/api/copy-trade/status', {credentials:'include'}).then(function(r){ return r.json(); }).then(function(d){
    if(d && d.ok){ _copyStatus.copying = d.copying; _copyStatus.target = d.target_wallet; loadTraders(); }
  }).catch(function(){});

  // A token arrives here as ?mint=<addr> from the shared navbar's search, the
  // wallet, the calls page and a surge push notification -- all plain
  // full-page navigations, since none of those have this feed to inject into.
  //
  // A deep link opens directly above. The scanner can refresh its numbers
  // later without replacing the focused card.
  _routeScope.addEventListener(window,'popstate',function(){
    var q=new URLSearchParams(location.search);
    _profileMint=q.get('profile')==='1'?q.get('mint'):(q.get('addr')&&!q.get('mint')?q.get('addr'):null);
    syncTokenProfile();
  });

  // Background tabs do zero market polling. Mobile browsers otherwise keep
  // old pages alive long enough to burn through rate limits for data nobody
  // can see, then return to the foreground already throttled.
  _routeScope.setInterval(function(){ if(!document.hidden) loadFeed(true); }, 15000);
  _routeScope.setInterval(function(){
    if(!_focusedMint || document.hidden) return;
    _routeScope.fetch('/api/token/info/'+encodeURIComponent(_focusedMint)).then(function(r){return r.json();}).then(function(info){
      if(!info || !info.ok) return;
      var idx=ST.tokens.findIndex(function(t){return t.mint===_focusedMint;});
      if(idx<0) return;
      var t=ST.tokens[idx];
      if(info.price_usd!=null) t.price_usd=Number(info.price_usd);
      if(info.market_cap!=null) t.market_cap=Number(info.market_cap);
      t.source=info.source||t.source;
      patchFeedList();
    }).catch(function(){});
  }, 15000);
  _routeScope.setInterval(function(){ if(!document.hidden) loadSurges(); }, 12000);
  _routeScope.setInterval(function(){ if(!document.hidden) loadLaunches(); }, 60000);
  _routeScope.setInterval(function(){ if(!document.hidden) loadTape(); }, 8000);
  _routeScope.setInterval(function(){ if(!document.hidden) loadTraders(); }, 30000);
  loadBotCard();
  _routeScope.setInterval(function(){ if(!document.hidden) loadBotCard(); }, 30000);
  _routeScope.setInterval(function(){ if(!document.hidden) loadPulse(); }, 20000);
  // The one that makes the charts move. Started once for the whole page, not
  // per card -- it batches every visible chart into a single request.
  startLivePrices();
});

// Pull-to-refresh (live_market_pro.html). Every loader lives inside this
// closure, so the page can only reach them through this one export. The
// feed refreshes in poll mode -- merged in place, no flash of a re-rendered
// list.
window.OrcAgentRefreshLiveMarket=function(){
  loadFeed(true); loadSurges(); loadLaunches(); loadTape(); loadTraders(); loadWatchlist(); loadPulse();
};

})();
