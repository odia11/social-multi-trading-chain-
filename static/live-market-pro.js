/* OrcAgent Live Market — "Pro terminal" desktop page controller.
   Talks to /api/market/scanner (server-side sort/filter), /api/market/tape
   (global buy/sell activity), and the existing token/wallet/trade/watchlist/
   copy-trade/leaderboard endpoints already used elsewhere in the app. */
(function(){
'use strict';

/* ── helpers ── */
function esc(s){
  return String(s==null?'':s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
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
  n = Number(n);
  if(n==null || isNaN(n)) return '—';
  if(n===0) return '$0.00';
  if(n>=1) return '$'+n.toFixed(2);
  if(n>=0.01) return '$'+n.toFixed(4);
  if(n>=0.0001) return '$'+n.toFixed(6);
  return '$'+n.toFixed(8);
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
  return Math.round(h/24)+'d';
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
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(function(){ el.classList.remove('show'); }, 2600);
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
  sort: 'trending', minLiquidity: 25000, age: 'any',
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

/* ── chart (custom SVG: smooth cubic-bezier line, gradient fill, dotted
   current-price line, price pill, timeframe pills, time axis) ── */
var _chartTimers = {}; // idx -> {destroyed, mint, pair, tf, timer}

function buildSmoothPath(pts){
  if(pts.length<2) return '';
  var d = 'M'+pts[0].x.toFixed(2)+','+pts[0].y.toFixed(2);
  for(var i=0;i<pts.length-1;i++){
    var p0 = pts[i===0?0:i-1], p1 = pts[i], p2 = pts[i+1], p3 = pts[i+2]||p2;
    var c1x = p1.x+(p2.x-p0.x)/6, c1y = p1.y+(p2.y-p0.y)/6;
    var c2x = p2.x-(p3.x-p1.x)/6, c2y = p2.y-(p3.y-p1.y)/6;
    d += ' C'+c1x.toFixed(2)+','+c1y.toFixed(2)+' '+c2x.toFixed(2)+','+c2y.toFixed(2)+' '+p2.x.toFixed(2)+','+p2.y.toFixed(2);
  }
  return d;
}

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

  if(!candles || candles.length<2){
    var oldPill0 = wrap.querySelector('.pt-price-pill');
    if(oldPill0) oldPill0.remove();
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
  if(min===max){ min = min*0.98; max = (max*1.02)||1; }
  var pad = (max-min)*0.12;
  min -= pad; max += pad;

  var n = candles.length, priceH = h*.77, volTop = h*.79, volH = h*.18;
  var pts = candles.map(function(c,i){
    var x = n===1 ? 0 : (i/(n-1))*(w-46);
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
  if(st){ st.pts = pts; st.candles = candles; st.min = min; st.max = max; st.h = h; st.w = w; st.priceH = priceH; st.plotW = w-46; }

  var maxVol = Math.max.apply(null,candles.map(function(c){return Number(c.v)||0;}))||1;
  var plotW=w-46, step=plotW/Math.max(n,1), bodyW=Math.max(2,Math.min(7,step*.62)), chartHtml='';
  for(var gy=0;gy<5;gy++){
    var yy=(priceH/4)*gy, label=max-((max-min)/4)*gy;
    chartHtml+='<line x1="0" y1="'+yy.toFixed(2)+'" x2="'+plotW.toFixed(2)+'" y2="'+yy.toFixed(2)+'" stroke="#1a2530" stroke-width="1" vector-effect="non-scaling-stroke"></line>';
    chartHtml+='<text x="'+(plotW+5).toFixed(2)+'" y="'+Math.max(10,yy+4).toFixed(2)+'" fill="#657180" font-size="9" font-family="monospace">'+fmtPrice(label).replace('$','')+'</text>';
  }
  candles.forEach(function(c,i){
    var x=pts[i].x, open=Number(c.o!=null?c.o:c.c)||0, close=Number(c.c)||0, high=Number(c.h!=null?c.h:c.c)||0, low=Number(c.l!=null?c.l:c.c)||0;
    var yo=priceH-((open-min)/(max-min))*priceH, yc=priceH-((close-min)/(max-min))*priceH, yh=priceH-((high-min)/(max-min))*priceH, yl=priceH-((low-min)/(max-min))*priceH;
    var color=close>=open?'#3ad29b':'#f76b62', top=Math.min(yo,yc), bh=Math.max(1.5,Math.abs(yc-yo));
    var liveIds=i===candles.length-1?' id="pt-live-wick-'+idx+'"':'';
    var liveBodyId=i===candles.length-1?' id="pt-live-body-'+idx+'"':'';
    chartHtml+='<line'+liveIds+' x1="'+x.toFixed(2)+'" y1="'+yh.toFixed(2)+'" x2="'+x.toFixed(2)+'" y2="'+yl.toFixed(2)+'" stroke="'+color+'" stroke-width="1" vector-effect="non-scaling-stroke"></line>';
    chartHtml+='<rect'+liveBodyId+' x="'+(x-bodyW/2).toFixed(2)+'" y="'+top.toFixed(2)+'" width="'+bodyW.toFixed(2)+'" height="'+bh.toFixed(2)+'" rx=".6" fill="'+color+'"></rect>';
    var vh=((Number(c.v)||0)/maxVol)*volH;
    chartHtml+='<rect x="'+(x-bodyW/2).toFixed(2)+'" y="'+(volTop+volH-vh).toFixed(2)+'" width="'+bodyW.toFixed(2)+'" height="'+vh.toFixed(2)+'" fill="'+color+'" opacity=".45"></rect>';
  });
  svg.innerHTML=chartHtml+'<line id="pt-live-guide-'+idx+'" x1="0" y1="'+priceY.toFixed(2)+'" x2="'+plotW.toFixed(2)+'" y2="'+priceY.toFixed(2)+'" stroke="#f7b955" stroke-width="1" stroke-dasharray="4,4" opacity=".72" vector-effect="non-scaling-stroke"></line>';

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
function updateLiveChartPrice(idx, nextPrice){
  var st=_chartTimers[idx], wrap=document.getElementById('pt-chart-wrap-'+idx);
  if(!st || !wrap || !st.candles || !st.candles.length || !(nextPrice>0)) return;
  var last=st.candles[st.candles.length-1], previous=Number(st.renderedPrice||last.c||nextPrice);
  last.c=nextPrice; last.h=Math.max(Number(last.h||nextPrice),nextPrice); last.l=Math.min(Number(last.l||nextPrice),nextPrice);
  // A move outside the current scale needs fresh axes; ordinary ticks stay GPU-smooth.
  if(nextPrice<=st.min || nextPrice>=st.max){ renderChartSvg(idx,st.candles,nextPrice); return; }
  var body=document.getElementById('pt-live-body-'+idx), wick=document.getElementById('pt-live-wick-'+idx), guide=document.getElementById('pt-live-guide-'+idx);
  var pill=wrap.querySelector('.pt-price-pill');
  if(!body || !wick || !guide){ renderChartSvg(idx,st.candles,nextPrice); return; }
  if(st.liveRaf) cancelAnimationFrame(st.liveRaf);
  var started=performance.now(), duration=220;
  function frame(now){
    var q=Math.min(1,(now-started)/duration), eased=1-Math.pow(1-q,3), p=previous+(nextPrice-previous)*eased;
    var y=function(v){return st.priceH-((v-st.min)/(st.max-st.min))*st.priceH;};
    var yo=y(Number(last.o!=null?last.o:p)), yc=y(p), yh=y(Math.max(Number(last.h)||p,p)), yl=y(Math.min(Number(last.l)||p,p));
    var color=p>=Number(last.o!=null?last.o:p)?'#3ad29b':'#f76b62';
    body.setAttribute('y',Math.min(yo,yc).toFixed(2)); body.setAttribute('height',Math.max(1.5,Math.abs(yc-yo)).toFixed(2)); body.setAttribute('fill',color);
    wick.setAttribute('y1',yh.toFixed(2)); wick.setAttribute('y2',yl.toFixed(2)); wick.setAttribute('stroke',color);
    guide.setAttribute('y1',yc.toFixed(2)); guide.setAttribute('y2',yc.toFixed(2));
    if(pill){pill.style.top=yc+'px'; pill.textContent=fmtPrice(p);}
    if(q<1) st.liveRaf=requestAnimationFrame(frame); else {st.liveRaf=null; st.renderedPrice=nextPrice;}
  }
  st.liveRaf=requestAnimationFrame(frame);
}

// Touch/mouse "chart-scrub" for the hand-rolled SVG chart above (the
// LightweightCharts-based charts elsewhere in the app already get this via
// chart-scrub.js's attachChartScrub() -- this one is a plain SVG polyline,
// not a LightweightCharts instance, so that helper doesn't apply here; this
// is the same drag/hover -> nearest-point -> crosshair+tooltip idea, done
// in plain pixel math against the {x,y} points renderChartSvg() already
// computed (stored on the timer state each render).
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
  var rafId = null, pendingX = null;
  function scheduleScrub(clientX){
    pendingX = clientX;
    if(rafId != null) return;
    rafId = requestAnimationFrame(function(){
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
    var pxX = (pt.x / (s.w||1)) * svgRect.width  + (svgRect.left - wrapRect.left);
    var pxY = (pt.y / (s.h||1)) * svgRect.height + (svgRect.top  - wrapRect.top);
    // `transform: translate(...)`, never left/top -- keeps every per-frame
    // update on the compositor (GPU) instead of forcing a full layout+paint
    // each time, which is the other half of what made this feel sluggish.
    line.style.height    = svgRect.height+'px';
    line.style.display   = 'block';
    line.style.transform = 'translateX('+pxX.toFixed(1)+'px)';
    dot.style.display    = 'block';
    dot.style.transform  = 'translate('+(pxX-4).toFixed(1)+'px,'+(pxY-4).toFixed(1)+'px)';
    var d = new Date(c.t*1000);
    var hh = ('0'+d.getHours()).slice(-2), mm = ('0'+d.getMinutes()).slice(-2);
    tip.textContent    = fmtPrice(c.c)+'  ·  '+hh+':'+mm;
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
    var tipY = Math.max(4, Math.min(svgRect.height - tipH - 4, pxY - tipH - 10));
    tip.style.transform = 'translate('+tipX.toFixed(1)+'px,'+tipY.toFixed(1)+'px)';
  }
  function clearScrub(){
    if(rafId != null){ cancelAnimationFrame(rafId); rafId = null; }
    line.style.display = 'none'; dot.style.display = 'none'; tip.style.display = 'none';
  }
  function onTouchStart(e){ if(e.touches[0]) scheduleScrub(e.touches[0].clientX); }
  function onTouchMove(e){ if(e.touches[0]){ e.preventDefault(); scheduleScrub(e.touches[0].clientX); } }
  function onMouseMove(e){ scheduleScrub(e.clientX); }
  wrap.addEventListener('touchstart', onTouchStart, {passive:true});
  wrap.addEventListener('touchmove', onTouchMove, {passive:false});
  wrap.addEventListener('touchend', clearScrub, {passive:true});
  wrap.addEventListener('touchcancel', clearScrub, {passive:true});
  wrap.addEventListener('mousemove', onMouseMove);
  wrap.addEventListener('mouseleave', clearScrub);

  st.scrubTeardown = function(){
    if(rafId != null){ cancelAnimationFrame(rafId); rafId = null; }
    wrap.removeEventListener('touchstart', onTouchStart);
    wrap.removeEventListener('touchmove', onTouchMove);
    wrap.removeEventListener('touchend', clearScrub);
    wrap.removeEventListener('touchcancel', clearScrub);
    wrap.removeEventListener('mousemove', onMouseMove);
    wrap.removeEventListener('mouseleave', clearScrub);
    [line, dot, tip].forEach(function(el){ if(el.parentNode) el.parentNode.removeChild(el); });
  };
}

function fetchChart(mint, tf, pairAddr, chain){
  var url = '/api/chart/'+encodeURIComponent(mint)+'?tf='+encodeURIComponent(tf);
  if(pairAddr) url += '&pair='+encodeURIComponent(pairAddr);
  if(chain) url += '&chain='+encodeURIComponent(chain);
  return fetch(url).then(function(r){ return r.json(); }).catch(function(){ return null; });
}

function chartTick(idx){
  var st = _chartTimers[idx];
  if(!st || st.destroyed) return;
  fetchChart(st.mint, st.tf, st.pair, st.chain).then(function(r){
    if(!st || st.destroyed) return;
    if(r && r.candles && r.candles.length>=2){
      // Kept so a live price can redraw this chart without fetching the
      // candles again -- the candles are the shape, the price is the movement.
      st.candles = r.candles;
      st.price   = r.current_price;
      renderChartSvg(idx, st.candles, st.price);
    } else if(!st.candles || st.candles.length<2){
      // Some new/EVM pools expose a real current price but no OHLC history.
      // Start an honest flat live session immediately; subsequent real ticks
      // form the candle instead of leaving a permanently empty chart.
      var px=Number((r&&r.current_price)||st.seedPrice||0);
      if(px>0){
        var now=Math.floor(Date.now()/1000);
        st.price=px;
        st.candles=[{t:now-2,o:px,h:px,l:px,c:px,v:0},{t:now,o:px,h:px,l:px,c:px,v:0}];
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

function tickLivePrices(){
  var byChain = {};
  Object.keys(_chartTimers).forEach(function(idx){
    var st = _chartTimers[idx];
    if(!st || st.destroyed || !st.pair || !st.candles) return;
    var c = st.chain || 'solana';
    (byChain[c] = byChain[c] || []).push(idx);
  });
  Object.keys(byChain).forEach(function(chain){
    var idxs  = byChain[chain];
    var pairs = idxs.map(function(i){ return _chartTimers[i].pair; });
    fetch('/api/market/prices?chain='+encodeURIComponent(chain)
          +'&pairs='+encodeURIComponent(pairs.join(',')))
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d || !d.prices) return;
        idxs.forEach(function(i){
          var st = _chartTimers[i];
          if(!st || st.destroyed || !st.candles || !st.candles.length) return;
          var px = d.prices[(st.pair||'').toLowerCase()];
          if(!(px > 0) || px === st.price) return;
          st.price = px;
          // The newest candle is the one still forming, so its close IS the
          // current price -- move it, and stretch its high/low to match, or
          // the wick would end up outside its own candle.
          var last = st.candles[st.candles.length - 1];
          last.c = px;
          if(px > last.h) last.h = px;
          if(px < last.l) last.l = px;
          updateLiveChartPrice(i, px);
        });
      })
      .catch(function(){});   // decoration: a miss leaves the last drawing up
  });
}

function startLivePrices(){
  if(_priceTimer) return;
  tickLivePrices();
  _priceTimer = setInterval(function(){
    // Nothing to ask about when the tab is in the background, and asking
    // anyway is how a page ends up rate-limited for charts nobody is looking
    // at. It resumes on the next tick when the tab comes back.
    if(document.visibilityState === 'visible') tickLivePrices();
  }, 2000);   // must not be shorter than the server's price window, or the
              // extra ticks just re-ask for an answer that cannot have changed
}

// `chain` defaults to 'solana' -- the API's own default -- so a caller that
// doesn't know/care about chain (there weren't any before this) still gets
// the exact prior behavior.
function mountChart(idx, mint, pairAddr, chain, seedPrice){
  if(_chartTimers[idx]) return;
  var st = {destroyed:false, mint:mint, pair:pairAddr, chain:(chain||'solana'), seedPrice:Number(seedPrice)||0, tf:'5m', timer:null};
  _chartTimers[idx] = st;
  chartTick(idx);
  // 15s, not 5s: the server caches candles for 30 seconds, so polling every
  // five asked the same question six times for one answer. Movement comes
  // from the live price tick above instead, which costs one request for the
  // whole page.
  st.timer = setInterval(function(){ chartTick(idx); }, 15000);
  attachChartSvgScrub(idx);
}
function unmountChart(idx){
  var st = _chartTimers[idx];
  if(!st) return;
  st.destroyed = true;
  if(st.timer) clearInterval(st.timer);
  if(st.liveRaf) cancelAnimationFrame(st.liveRaf);
  if(st.scrubTeardown) st.scrubTeardown();
  delete _chartTimers[idx];
}
function setChartTf(idx, tf){
  var st = _chartTimers[idx];
  if(!st) return;
  st.tf = tf;
  chartTick(idx);
}

/* ── per-card lazy loading (safety badges, friends/holders footer) ── */
var _lazyDone = {};
var _cardObserver = null;

function fetchSafety(idx, mint){
  var el = document.getElementById('pt-safety-'+idx);
  fetch('/api/token/'+encodeURIComponent(mint)+'/safety', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
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
  // Always shows something -- including "0 friends hold this" -- instead of
  // going blank when nobody you follow holds it, so the Friends section
  // reads as a real, always-there stat rather than something that only
  // appears sometimes.
  fetch('/api/token/'+encodeURIComponent(mint)+'/co-traders', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(!friendsEl) return;
      var users = (d && d.ok && d.users) || [];
      if(!users.length){
        friendsEl.innerHTML = '<span class="pt-friends-empty">👥 0 friends</span>';
        return;
      }
      var avs = users.slice(0,3).map(function(u){
        return u.avatar_url
          ? '<img src="'+esc(u.avatar_url)+'">'
          : '<div class="ph">'+esc((u.username||'?').slice(0,1).toUpperCase())+'</div>';
      }).join('');
      friendsEl.innerHTML = '<div class="pt-friend-avs">'+avs+'</div><span>'+users.length+' friend'+(users.length===1?'':'s')+'</span>';
    }).catch(function(){
      if(friendsEl) friendsEl.innerHTML = '<span class="pt-friends-empty">👥 0 friends</span>';
    });

  fetch('/api/token/'+encodeURIComponent(mint)+'/holders', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){
      var ftEl = document.getElementById('pt-ft-stats-'+idx);
      if(!ftEl || !d || !d.ok) return;
      var t = ST.tokens[Number(idx)];
      var txns = t ? (t.buys_24h+t.sells_24h) : 0;
      var txnsStr = txns >= 1000 ? (txns/1000).toFixed(1)+'K' : String(txns);
      var ratio = t ? ratioStr(t.buys_24h, t.sells_24h) : '—';
      // 'holders' here is a count of OrcAgent users with a position in this
      // token, NOT the real on-chain holder count (DexScreener's API, which
      // powers every other stat on this card, doesn't expose that) -- kept
      // as its own small chip, clearly scoped to "on OrcAgent" rather than
      // implying it's the token's total holder count.
      ftEl.innerHTML = '<span class="pt-ft-chip">👤 '+(d.platform_holders||0)+' on OrcAgent</span>'
        + '<span class="pt-ft-chip">'+txnsStr+' txns</span>'
        + '<span class="pt-ft-chip">'+ratio+'</span>';
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
  if(!('IntersectionObserver' in window)){
    cards.forEach(activateCard);
    return;
  }
  _cardObserver = new IntersectionObserver(function(entries){
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
  if(!imgUrl) return '<div class="'+phCls+'">'+initials+'</div>';
  return '<img class="'+cls+'" src="'+esc(imgUrl)+'" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">'
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
/* Which chain a token/trade lives on -- feeds a token's Buy/Sell routing
   (confirmBuy/handleSell below) as well as this badge, so a Solana token
   always spends SOL via /api/instant-trade, BSC always spends USDC via
   /api/bsc/trade/*, and Base/Arbitrum/Polygon/Robinhood Chain always spend
   their own chain's USD stablecoin via the generic /api/evm/trade/* (see
   EVM_TRADE_CHAINS below). Defaults to 'solana' for any candidate that
   omits it (every pre-multi-chain scanner response), so old cached
   responses never render as blank/unlabeled. */
var EVM_TRADE_CHAINS = {bsc:1, base:1, arbitrum:1, polygon:1, robinhood:1};
var CHAIN_LABELS = {bsc:'BSC', base:'BASE', arbitrum:'ARB', polygon:'POLY', robinhood:'HOOD'};
// What the user is told they are spending: USDC, on every chain.
//
// This used to name Robinhood Chain's USDG, on the reasoning that USDC does
// not exist there and calling it USDC would be a lie. The reasoning was
// right about the chain and wrong about the question. The user never holds,
// picks, or deposits USDG -- they spend USDC, and the app bridges it there,
// where it converts to USDG on arrival. Naming that intermediate token on
// the Buy button described the plumbing instead of the payment.
//
// The on-chain symbol still exists server-side as usdc_symbol, and still
// says USDG, because a log line or an explorer lookup needs the token that
// actually moved. See user_currency_label() in dashboard.py.
function evmCurrencyLabel(chain){ return 'USDC'; }
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
        setTimeout(function(){ textEl.textContent = orig; }, 1200);
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

function storyHtml(t, idx){
  var down = (t.price_change_24h||0) < 0;
  return '<div class="pt-story" data-action="story" data-idx="'+idx+'">'
    + '<div class="pt-story-ring'+(down?' down':'')+'"><div class="pt-story-inner">'
    +   logoTile(t.image_url, t.symbol, 'pt-story-img', 'pt-story-img-ph')
    + '</div></div>'
    + '<div class="pt-story-name">$'+esc(t.symbol||'?')+'</div>'
    + '<div class="pt-story-chg mono '+(down?'down':'up')+'">'+fmtPct(t.price_change_24h)+'</div>'
    + '</div>';
}

function cardHtml(t, idx){
  var down = (t.price_change_24h||0) < 0;
  var isWatched = watchSet.has(t.mint);
  return '<div class="pt-card'+(t.score>=4?' hi':'')+'" id="pt-card-'+idx+'" data-mint="'+esc(t.mint)+'" data-idx="'+idx+'" data-pair="'+esc(t.pair_address||'')+'">'
    + '<div class="pt-card-hd">'
    +   logoTile(t.image_url, t.symbol, 'pt-tok-logo', 'pt-tok-logo-ph')
    +   '<div class="pt-tok-id"><div class="pt-tok-sym">$'+esc(t.symbol)+' '+starsHtml(t.score)+chainBadgeHtml(t.chain)+'</div>'
    +   '<div class="pt-tok-meta">'+esc(t.name||t.symbol)+' · '+fmtAge(t.pair_created_at)+' old</div>'
    +   '<div class="pt-tok-ca-row">'
    +     '<div class="pt-tok-ca" data-action="copy-ca" data-mint="'+esc(t.mint)+'" title="'+esc(t.mint)+'">'
    +       '<span class="pt-tok-ca-text mono">'+esc(shortAddr(t.mint))+'</span>'
    +       '<span class="pt-tok-ca-icon">⧉</span>'
    +     '</div>'
    +     socialsHtml(t)
    +   '</div></div>'
    +   '<div class="pt-card-hd-right">'
    +     '<span id="pt-safety-'+idx+'"></span>'
    +     '<button class="pt-watch-btn'+(isWatched?' active':'')+'" data-action="watch" data-mint="'+esc(t.mint)+'" data-sym="'+esc(t.symbol)+'">'+(isWatched?'★':'☆')+'</button>'
    +   '</div>'
    + '</div>'
    + '<div class="pt-card-body">'
    +   '<div class="pt-card-stats">'
    +     '<div class="pt-price mono" id="pt-price-'+idx+'">'+fmtPrice(t.price_usd)+'</div>'
    +     '<div class="pt-chg mono '+(down?'down':'up')+'" id="pt-chg-'+idx+'">'+fmtPct(t.price_change_24h)+' · 24h</div>'
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
    +   '<div class="pt-card-ft-right mono" id="pt-ft-stats-'+idx+'">'+(t.buys_24h+t.sells_24h)+' txns · '+ratioStr(t.buys_24h,t.sells_24h)+'</div>'
    + '</div>'
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
var _LIQ_DEFAULT = 25000;
function updateAdvCount(){
  var n = 0;
  for(var k in _FILTER_KEYS){ if(ST[_FILTER_KEYS[k]]) n++; }
  if(ST.age && ST.age !== 'any') n++;
  if(Number(ST.minLiquidity) !== _LIQ_DEFAULT) n++;
  var el = document.getElementById('pt-adv-count');
  if(el) el.textContent = n ? (n + ' on') : '';
}

/* ── feed loading ── */
function updateHeaderCounts(){
  var n = ST.tokens.length;
  var el;
  if((el=document.getElementById('pt-tok-count'))) el.textContent = n;
  if((el=document.getElementById('pt-bot-count'))) el.textContent = n;
  if((el=document.getElementById('pt-pulse-tokens'))) el.textContent = n;
}

function renderStoryRail(){
  var el = document.getElementById('pt-story-rail');
  var list = ST.tokens.slice(0, 14);
  el.innerHTML = list.map(function(t,i){ return storyHtml(t,i); }).join('');
}

// Horizontal rails (surge strip, story rail, trader rail) only ever got
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
  el.addEventListener('click', function(e){
    if(!swallowClick) return;
    swallowClick = false;
    e.stopPropagation();
    e.preventDefault();
  }, true);
  el.addEventListener('mousedown', function(e){
    down = true; moved = false; swallowClick = false;
    startX = e.pageX; startScroll = el.scrollLeft;
    el.classList.add('pt-rail-dragging');
  });
  window.addEventListener('mousemove', function(e){
    if(!down) return;
    var dx = e.pageX - startX;
    if(Math.abs(dx) > 3) moved = true;
    el.scrollLeft = startScroll - dx;
  });
  window.addEventListener('mouseup', function(){
    if(!down) return;
    down = false;
    el.classList.remove('pt-rail-dragging');
    // A deliberate pan must never also open whatever card the cursor
    // happens to be over on release. A tap that never moved must.
    swallowClick = moved;
  });
  el.addEventListener('touchstart', function(){ _railsBeingTouched[el.id] = true; }, {passive:true});
  el.addEventListener('touchend', function(){ _railsBeingTouched[el.id] = false; }, {passive:true});
  el.addEventListener('touchcancel', function(){ _railsBeingTouched[el.id] = false; }, {passive:true});
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
    if(fresh) Object.assign(t, fresh);
  });
}

// Updates just the numbers on already-rendered cards (price, 24h change,
// liquidity/mcap/volume/buy-sell) in place, via their ids -- deliberately
// NOT touching the buy panel, watch button, chart, or the card node itself,
// so nothing a user is mid-interaction with (typing a buy amount, reading
// the chart) is disturbed. Companion to mergeTokenUpdates().
function patchFeedList(){
  ST.tokens.forEach(function(t, idx){
    var el;
    if((el = document.getElementById('pt-price-'+idx))) el.textContent = fmtPrice(t.price_usd);
    if((el = document.getElementById('pt-chg-'+idx))){
      var down = (t.price_change_24h||0) < 0;
      el.textContent = fmtPct(t.price_change_24h)+' · 24h';
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
  fetch('/api/market/scanner?'+qs.toString(), {credentials:'include'})
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
        renderStoryRail();
        renderFeedList();
      }
      updateHeaderCounts();
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

// What the trade costs. Buying, the breakdown is quoted and rendered by
// renderQuote() as it always was. Selling is not quoted -- what a sale
// returns is known when it settles -- so this states the rates that apply
// rather than inventing a total for a swap that has not happened.
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
      +   esc(pct) + '% of what the sale returns</span></div>'
      + '<div class="pt-quote-row"><span>Network fee</span><span>paid in '
      +   esc(gas) + ' gas</span></div>'
      + '<div class="pt-quote-note">Both are taken when the sale settles, so '
      + 'the amounts follow whatever it actually returns.</div>';
  }
}

// Spendable balance is per chain, never a pooled total: buying on BSC spends
// the BSC balance and nothing else. Cached briefly so reopening the sheet
// does not re-read every chain.
// Fetched once when the page loads, not when the sheet opens. Opening used
// to start the request, so the first buy of a session sat on "Checking
// balance…" for ~290ms with the 10/25/50/Max buttons inert -- measured on a
// throttled phone. By the time anyone taps Buy this has long since landed.
function _prefetchBalances(){
  fetch('/api/wallet/usdc-summary', {credentials:'include'})
    .then(function(r){ return r.json(); })
    .then(function(d){ if(d && d.ok) _availCache = {t: Date.now(), data: d}; })
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
  fetch('/api/trade/holding?chain=' + encodeURIComponent(t.chain)
        + '&token_address=' + encodeURIComponent(t.mint),
        {credentials:'include', headers: authHeaders()})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(_sheetIdx !== idx || _sheetMode !== 'sell') return;
      if(!d || !d.ok){ failed(); return; }
      _sheetHold = {amount: Number(d.amount || 0), price: Number(d.price_usd || 0),
                    value: Number(d.value_usd || 0)};
      _sheetAvail = _sheetHold.value;
      // Open on the whole position, which is what the button used to do and
      // is still the common case -- now with the figure filled in, so it can
      // be edited down instead of retyped from nothing.
      if(_sellPct >= 100 && _sheetAmt === '' && _sheetHold.value > 0){
        _sheetAmt = String(Math.floor(_sheetHold.value * 100) / 100);
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
    var v = (chain === 'solana') ? d.solana_usdc : ((d.evm_chains || {})[chain]);
    _sheetAvail = Number(v || 0);
    _paintSheet();
  };
  if(_availCache.data && now - _availCache.t < 12000){ use(_availCache.data); return; }
  fetch('/api/wallet/usdc-summary', {credentials:'include'})
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
  _sheetEl('pt-sheet-chain').textContent = CHAIN_LABELS[t.chain] || (t.chain || '').toUpperCase();
  _sheetEl('pt-sheet-mc').textContent = t.market_cap ? fmtUsd(t.market_cap) + ' MC' : '';
  _sheetEl('pt-sheet-price').textContent = fmtPrice(t.price_usd);
  var chg = Number(t.price_change_24h || 0);
  var chgEl = _sheetEl('pt-sheet-chg');
  chgEl.textContent = (chg >= 0 ? '▲ ' : '▼ ') + Math.abs(chg).toFixed(2) + '%';
  chgEl.className = 'pt-sheet-chg ' + (chg < 0 ? 'down' : 'up');

  // On the EVM chains the amount is a CEILING -- the fees and the slippage
  // reserve come out of it, so what is bought is what remains, and the
  // breakdown below prices exactly that. On Solana it is simply what is
  // spent. Every chain funds a buy in USDC; the label names what actually
  // moves, which on Robinhood Chain is USDG.
  var isEvm = !!EVM_TRADE_CHAINS[t.chain];
  if(mode === 'sell'){
    // A sale is entered in dollars and settles in the chain's own dollar
    // token, so the caption names the unit being typed rather than the one
    // that arrives -- what lands is in the fee box, where it belongs.
    _sheetEl('pt-sheet-cap-txt').textContent = 'You sell';
    _sheetEl('pt-sheet-cur').textContent = 'USD';
  } else {
    _sheetEl('pt-sheet-cap-txt').textContent = isEvm ? 'You spend at most' : 'You spend';
    _sheetEl('pt-sheet-cur').textContent = isEvm ? evmCurrencyLabel(t.chain) : 'USDC';
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
  if(mode === 'buy') _loadSheetBalance(t.chain);
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
  clearTimeout(_quoteTimers[idx]);
  delete _quotes[idx];
  delete _quoteRenewals[idx];
}

// `settled` means the amount is final rather than mid-typing -- a tap on
// 25% or Max. There is nothing to debounce there: the number will not
// change in 450ms, and waiting is 450ms of "Pricing…" for no reason.
function _sheetSetAmount(next, settled){
  _sheetAmt = next;
  var hidden = document.getElementById('pt-buy-amt-'+_sheetIdx);
  if(hidden) hidden.value = next;
  _paintSheet();
  var t = ST.tokens[Number(_sheetIdx)];
  // Only a buy is quoted. A sale is priced when it settles, so asking the
  // quote route about one would be asking a buy-shaped question.
  if(_sheetMode !== 'sell' && t && EVM_TRADE_CHAINS[t.chain]) scheduleQuote(_sheetIdx, settled ? 0 : 250);
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
    sEl.textContent = '$' + (_sheetAmt === '' ? '0' : _sheetAmt);
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
          : ('<b>$' + _sheetAvail.toFixed(2) + '</b> held'));

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
    } else if(_sheetAvail !== null && sAmt > _sheetAvail + 0.01){
      // A cent of slack: "Max" floors to the cent, and a price that ticks
      // between the fill and the tap must not disarm the control someone
      // just used.
      _slideSetLabel('More than you hold'); _slideEnable(false);
    } else {
      // Saying "all" out loud when it IS all: the difference between
      // trimming a position and closing it is the whole decision.
      _slideSetLabel(_sellPct >= 100
        ? ('Slide to sell all $' + (t && t.symbol || ''))
        : ('Slide to sell $' + _sheetAmt));
      _slideEnable(true);
    }
    return;
  }
  var amt = parseFloat(_sheetAmt);
  var el = _sheetEl('pt-sheet-amt');
  el.textContent = '$' + (_sheetAmt === '' ? '0' : _sheetAmt);
  el.classList.toggle('dim', !(amt > 0));

  // What that money buys, at the price on screen. An estimate, and labelled
  // as one -- the executed price is whatever the swap returns.
  var get = _sheetEl('pt-sheet-get');
  var px = Number(t && t.price_usd || 0);
  get.textContent = (amt > 0 && px > 0)
    ? '≈ ' + fmtAmount(amt / px) + ' ' + (t.symbol || '')
    : '';

  // Cents, not fmtUsd's compact form: a balance of 12.40 shown as "$12"
  // contradicts the 12.40 that Max then fills in, and a person reading a
  // number about their own money should see the actual number.
  var availEl = _sheetEl('pt-sheet-avail');
  availEl.innerHTML = (_sheetAvail === null)
    ? 'Checking balance…'
    : '<b>$' + _sheetAvail.toFixed(2) + '</b> available';

  // The button says why it cannot be pressed, rather than sitting greyed out
  // with no reason -- "nothing happens" is the worst state a Buy can be in.
  var min = PT_MIN_BUY_USDC;
  if(!(amt > 0)){
    _slideSetLabel('Enter an amount'); _slideEnable(false);
  } else if(amt < min){
    _slideSetLabel('$' + min + ' minimum'); _slideEnable(false);
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
  function down(e){
    if(!_slideOn || _sheetIdx === null) return;
    var els = _slideEls();
    if(!els.knob || !els.knob.contains(e.target)) return;
    _sliding = true;
    els.wrap.classList.add('dragging');
    els.wrap._x0 = (e.touches ? e.touches[0].clientX : e.clientX) - _slideAt;
    e.preventDefault();
  }
  function move(e){
    if(!_sliding) return;
    var els = _slideEls();
    var x = (e.touches ? e.touches[0].clientX : e.clientX) - els.wrap._x0;
    _slideMove(x);
    e.preventDefault();
  }
  function up(){ if(!_sliding) return; _sliding = false; _slideRelease(); }
  document.addEventListener('touchstart', down, {passive:false});
  document.addEventListener('touchmove',  move, {passive:false});
  document.addEventListener('touchend',   up);
  document.addEventListener('touchcancel',up);
  document.addEventListener('mousedown',  down);
  document.addEventListener('mousemove',  move);
  document.addEventListener('mouseup',    up);
  // A keyboard has no gesture to make, and Enter used to confirm in one
  // press -- which is the single accidental keystroke this whole control
  // exists to prevent, just moved off the touchscreen. The arrow keys walk
  // the knob the same distance a thumb would: eight presses to the end,
  // where it confirms, and Escape or Home puts it back. Deliberate by the
  // same measure, reachable without a touchscreen.
  var KEY_STEPS = 8;
  document.addEventListener('keydown', function(e){
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
    y0 = e.touches[0].clientY; dy = 0; dragging = true;
    sheet.classList.add('dragging');
  }
  function move(e){
    if(!dragging) return;
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
  document.addEventListener('touchstart', start, {passive:true});
  document.addEventListener('touchmove',  move,  {passive:true});
  document.addEventListener('touchend',   end);
  document.addEventListener('touchcancel',end);
})();

// Keypad and the percentage row. Delegated, so the buttons themselves carry
// no handlers and the markup stays in the template.
document.addEventListener('click', function(e){
  // The close button and the scrim are wired here rather than with an inline
  // onclick in the template: everything in this file lives inside an IIFE,
  // so closeBuySheet() is not a global and `onclick="closeBuySheet()"` threw
  // ReferenceError -- the sheet simply would not close.
  if(e.target.closest('[data-action="close-sheet"]')){ closeBuySheet(); return; }
  var k = e.target.closest('#pt-keys .pt-key');
  if(k && _sheetIdx !== null){
    var v = k.dataset.k;
    if(v === 'del'){
      _sheetTypeAmount(_sheetAmt.slice(0, -1));
    } else if(v === '.'){
      if(_sheetAmt.indexOf('.') === -1) _sheetTypeAmount((_sheetAmt || '0') + '.');
    } else {
      // No leading zeros ("05"), and two decimals is as fine as money gets.
      var next = (_sheetAmt === '0') ? v : _sheetAmt + v;
      var dot = next.indexOf('.');
      if(dot !== -1 && next.length - dot > 3) return;
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
    _sheetSetAmount(String(Math.floor(part * 100) / 100), true);
  }
});

document.addEventListener('keydown', function(e){
  if(_sheetIdx === null) return;
  if(e.key === 'Escape'){ closeBuySheet(); return; }
  if(e.key === 'Backspace'){ _sheetTypeAmount(_sheetAmt.slice(0, -1)); e.preventDefault(); return; }
  if(e.key === '.' && _sheetAmt.indexOf('.') === -1){ _sheetTypeAmount((_sheetAmt || '0') + '.'); return; }
  if(e.key >= '0' && e.key <= '9'){
    var next = (_sheetAmt === '0') ? e.key : _sheetAmt + e.key;
    var dot = next.indexOf('.');
    if(dot !== -1 && next.length - dot > 3) return;
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

/* ── live cost breakdown ───────────────────────────────────────────────────
   Only for the EVM chains: /api/trade/quote prices a trade against a spend
   ceiling, and it is the same quote the buy then executes, so what is shown
   here is what is spent rather than an estimate drawn separately.

   Solana has no such quote -- its buy has no ceiling to price against, since
   the platform fee there already comes out of the amount inside the swap
   itself -- so no breakdown is shown for it rather than a made-up one. */
var _quoteTimers = {};
var _quotes      = {};

function _quoteCurrency(t){ return evmCurrencyLabel(t.chain); }

function scheduleQuote(idx, delayMs){
  clearTimeout(_quoteTimers[idx]);
  _quoteRenewals[idx] = 0;   // a new amount starts its own renewal budget
  delete _quotes[idx];
  var box = document.getElementById('pt-quote-'+idx);
  var input = document.getElementById('pt-buy-amt-'+idx);
  var amt = parseFloat(input ? input.value : '');
  if(!amt || amt <= 0){ if(box){ box.style.display='none'; box.innerHTML=''; } return; }
  if(box){
    box.style.display = 'block';
    box.innerHTML = '<div class="pt-quote-wait">Pricing…</div>';
  }
  // The previous amount's total is not this amount's total.
  var feeAmt = document.getElementById('pt-fees-amt');
  if(feeAmt && _sheetMode !== 'sell') feeAmt.textContent = '';
  // Debounced: a quote is a live route lookup, and firing one per keystroke
  // would spend the rate limit on numbers the user is still typing. But a
  // settled amount -- a tap on 25% or Max -- passes 0 and goes straight out,
  // because there is no further keystroke coming to wait for.
  var wait = (delayMs == null) ? 450 : delayMs;
  if(wait <= 0){ fetchQuote(idx, amt); return; }
  _quoteTimers[idx] = setTimeout(function(){ fetchQuote(idx, amt); }, wait);
}

function fetchQuote(idx, amt){
  var t = ST.tokens[Number(idx)];
  if(!t) return;
  var box = document.getElementById('pt-quote-'+idx);
  fetch('/api/trade/quote', {
    method:'POST', credentials:'include', headers: authHeaders(),
    body: JSON.stringify({chain:t.chain, token_address:t.mint, max_spend_usd:String(amt)})
  }).then(function(r){ return r.json(); }).then(function(d){
    var input = document.getElementById('pt-buy-amt-'+idx);
    // The user kept typing while this was in flight: this answer prices an
    // amount they are no longer asking about.
    if(!input || parseFloat(input.value) !== amt) return;
    if(!box) return;
    if(!d || d.ok === false || d.can_execute === false){
      _quotes[idx] = null;
      box.innerHTML = '<div class="pt-quote-bad">'
        + esc((d && (d.reject_reason || d.msg)) || 'Could not price this trade')
        + '</div>';
      return;
    }
    _quotes[idx] = {
      id: d.quote_id, amt: amt,
      expiresAt: Date.now() + (Number(d.expires_in_seconds) || 0) * 1000,
      purchase: d.token_purchase_usd
    };
    renderQuote(idx, d, t);
  }).catch(function(){
    _quotes[idx] = null;
    if(box) box.innerHTML = '<div class="pt-quote-bad">Could not reach the pricing service</div>';
  });
}

var COST_LABELS = {
  source_gas:       'Network fee',
  destination_gas:  'Network fee (destination)',
  platform_fee:     'OrcAgent fee',
  bridge_fee:       'Bridge fee',
  dex_fee:          'DEX fee',
  slippage_reserve: 'Slippage reserve'
};

function renderQuote(idx, d, t){
  var box = document.getElementById('pt-quote-'+idx);
  if(!box) return;
  var cur = _quoteCurrency(t);
  var rows = '';
  var kinds = d.costs_by_kind || {};
  for(var k in kinds){
    if(!Object.prototype.hasOwnProperty.call(kinds, k)) continue;
    rows += '<div class="pt-quote-row"><span>' + esc(COST_LABELS[k] || k) + '</span>'
          + '<span>-' + esc(Number(kinds[k]).toFixed(2)) + '</span></div>';
  }
  box.innerHTML =
      '<div class="pt-quote-row pt-quote-top"><span>You spend</span><span>'
    +   esc(Number(d.max_spend_usd).toFixed(2)) + ' ' + esc(cur) + '</span></div>'
    + rows
    + '<div class="pt-quote-row pt-quote-get"><span>You get</span><span>'
    +   esc(Number(d.token_purchase_usd).toFixed(2)) + ' ' + esc(cur)
    +   ' of $' + esc(t.symbol || '') + '</span></div>'
    // The reserve is money held back against price movement, not a charge.
    // Saying so is the difference between a cost the user resents and one
    // they understand.
    + (kinds.slippage_reserve
        ? '<div class="pt-quote-note">The slippage reserve is held back against '
          + 'price movement, not charged. Anything unused stays yours.</div>'
        : '')
    + '<div class="pt-quote-note" id="pt-quote-exp-'+idx+'"></div>';
  // The folded summary carries the total, so the box says what it costs
  // without having to be opened at all.
  var amtEl = document.getElementById('pt-fees-amt');
  if(amtEl){
    var spend = Number(d.max_spend_usd), gets = Number(d.token_purchase_usd);
    amtEl.textContent = (isFinite(spend) && isFinite(gets) && spend > gets)
      ? ('-' + (spend - gets).toFixed(2) + ' ' + cur) : '';
  }
  tickQuoteExpiry(idx);
}

// While the sheet is open, a price about to lapse is renewed rather than
// declared stale. A quote is held for ~6 seconds; sliding to confirm is a
// deliberate gesture that takes longer than that, plus however long someone
// spends reading the breakdown. So the old behaviour -- "This price has
// expired, edit the amount to get a new one" -- was what most people met
// when they finally slid, and the confirm then had to re-price on the spot,
// paying for a round trip at the one moment nobody wants to wait. Renewing
// in the background keeps the fast execute-this-exact-quote path available
// the whole time the screen is up.
var _quoteRenewals = {};
var QUOTE_MAX_RENEWALS = 20;   // ~2 minutes; a sheet left open stops asking

function tickQuoteExpiry(idx){
  var q = _quotes[idx];
  var el = document.getElementById('pt-quote-exp-'+idx);
  if(!q || !el) return;
  var left = Math.max(0, Math.round((q.expiresAt - Date.now())/1000));
  if(left <= 1 && _sheetIdx === String(idx) && _sheetMode === 'buy'
     && parseFloat(_sheetAmt) === q.amt
     && (_quoteRenewals[idx] || 0) < QUOTE_MAX_RENEWALS){
    _quoteRenewals[idx] = (_quoteRenewals[idx] || 0) + 1;
    fetchQuote(idx, q.amt);
    return;
  }
  if(left <= 0){
    el.textContent = 'This price has expired — edit the amount to get a new one.';
    el.className = 'pt-quote-note pt-quote-stale';
    _quotes[idx] = null;
    return;
  }
  el.textContent = 'Price held for ' + left + 's.';
  el.className = 'pt-quote-note';
  setTimeout(function(){ tickQuoteExpiry(idx); }, 1000);
}

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
  // Which chain this token lives on decides both the endpoint and the
  // currency the entered amount is denominated in: BSC keeps its own
  // dedicated route, Base/Arbitrum/Polygon share the generic /api/evm/*
  // route (chain passed in the body), and only a plain Solana token ever
  // spends SOL via /api/instant-trade -- the three EVM engines can never be
  // crossed with each other or with Solana here.
  var isBsc = t.chain === 'bsc';
  var isEvm = !!EVM_TRADE_CHAINS[t.chain];
  var url  = isBsc ? '/api/bsc/trade/buy' : (isEvm ? '/api/evm/trade/buy' : '/api/instant-trade');
  var body = isBsc ? {token_address:t.mint, amount_usdc:amt}
    : isEvm ? {chain:t.chain, token_address:t.mint, amount_usdc:amt}
    // amount_usdc is what the server reads; amount_sol is sent alongside it
    // only so an older deploy that has not been updated still gets the value
    // under the name it knows.
    : {symbol:t.symbol, token_address:t.mint, pair_address:t.pair_address, side:'buy',
       amount_usdc:amt, amount_sol:amt};

  // When a live quote for this exact amount is still good, execute THAT
  // quote rather than asking the buy route to price a fresh one. The
  // difference matters: the user agreed to the numbers they were shown, and
  // a second pricing a moment later is a different set of numbers wearing
  // the same intent. The buy route prices correctly either way, so this is
  // about honouring what was on screen, not about correctness of the total.
  var q = _quotes[idx];
  if(isEvm && q && q.id && q.amt === amt && q.expiresAt > Date.now()){
    url  = '/api/trade/execute';
    body = {quote_id: q.id};
  }
  // Whether this attempt ended in a purchase. A bought trade must NOT leave
  // the slider armed again: the sheet would then read "Bought ..." above a
  // live "Slide to buy" for the seconds before it closes, which is an
  // invitation to buy the same token twice by accident.
  var bought = false;
  fetch(url, {
    method:'POST', credentials:'include', headers: authHeaders(),
    body: JSON.stringify(body)
  }).then(function(r){ return r.json(); }).then(function(d){
    // If this chain's own balance couldn't cover the trade, the server
    // already started an automatic top-up from whichever chain has enough
    // and attached this buy to it -- {ok:true, pending:true, bridge_id:...}.
    // Poll silently until the purchase actually happens; the user only ever
    // sees "Buying..." then a normal Bought/failed message, never bridge
    // terminology, matching every other buy on this page.
    if(d && d.ok && d.pending && d.bridge_id){
      showMsg(msgEl, 'Buying $'+t.symbol+'…', true);
      _pollAutoBuyBridge(d.bridge_id, idx, t, amt, msgEl, input);
      return;
    }
    // /api/instant-trade's real success shape is {success:true, tx:<sig>, ...};
    // /api/bsc/trade/buy's and /api/evm/trade/buy's is {ok:true, tx_hash:<sig>, ...}
    // -- checking every one of success/tx/ok/sig/tx_hash covers all of them
    // instead of assuming any single endpoint's exact shape (a prior version
    // of this only checked the Solana shape, so every successful BSC buy
    // showed "Buy failed" anyway).
    if(d && (d.success || d.tx || d.ok || d.sig || d.tx_hash)){
      // What was BOUGHT, which on an EVM chain is less than what was spent
      // -- the costs came out of the ceiling. Saying "bought for $100" when
      // $97.43 of token was bought is the mismatch this whole change removes.
      var got = (d.amount_usdc != null) ? d.amount_usdc : amt;
      var cur = isEvm ? evmCurrencyLabel(t.chain) : (d.currency || 'USDC');
      var line = 'Bought ' + got + ' ' + cur + ' of $' + t.symbol;
      if(d.max_spend_usd != null && Number(d.max_spend_usd) > Number(got)){
        line += ' (spent ' + d.max_spend_usd + ' ' + cur + ')';
      }
      bought = true;
      showMsg(msgEl, line, true);
      if(input) input.value = '';
      delete _quotes[idx];
      // The receipt is the whole point of the wait: it names the transaction
      // the chain accepted and links to it. A sheet that closes in 2.6s takes
      // that away before it can be read, so a buy that produced a hash holds
      // the sheet open longer -- long enough to read it and tap through.
      _showTxReceipt(idx, t, d);
      setTimeout(function(){ closeBuyPanel(idx); },
                 document.getElementById('pt-txline') ? 7000 : 2600);
    } else if(d && d.requote){
      // The quote expired between being shown and being confirmed. Re-price
      // rather than executing at a number the user never saw.
      showMsg(msgEl, 'That price expired — repricing…', false);
      delete _quotes[idx];
      scheduleQuote(idx);
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

// Polls a background auto-bridge-then-buy through to completion, purely so
// confirmBuy() can show the same Bought/failed message it always would have
// -- the bridge itself (and the wait, up to a few minutes) is never
// surfaced to the user, per the "no friction from bridging" requirement.
// The button stays disabled/'…' for the whole wait, same as any other
// in-flight buy, rather than re-enabling and inviting a duplicate click.
function _pollAutoBuyBridge(bridgeId, idx, t, amt, msgEl, input){
  var attempts = 0;
  var maxAttempts = 150; // ~150 * 8s = 20 minutes outer ceiling, generous over the bridge's own 30-min timeout
  var btn = document.querySelector('#pt-buy-panel-'+idx+' .pt-buy-confirm');
  function tick(){
    attempts++;
    fetch('/api/bridge/status/'+bridgeId, {credentials:'include', headers: authHeaders()})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(!d || !d.ok){ return scheduleNext(); }
        if(d.auto_buy_status === 'done'){
          var res = d.auto_buy_result || {};
          showMsg(msgEl, 'Bought $'+(res.symbol||t.symbol)+' for '+(res.amount_usdc!=null?res.amount_usdc:amt)+' '+evmCurrencyLabel(t.chain), true);
          if(input) input.value = '';
          _slideEnable(false);
          _slideSetLabel('Bought');
          _showTxReceipt(idx, t, res);
          setTimeout(function(){ closeBuyPanel(idx); },
                     document.getElementById('pt-txline') ? 7000 : 2200);
          return;
        }
        if(d.auto_buy_status === 'failed'){
          var err = (d.auto_buy_result && d.auto_buy_result.error) || 'Buy failed after funds arrived — your balance is safe, try again';
          showMsg(msgEl, err, false);
          if(btn){ btn.disabled=false; }
    _restoreSlide();
          return;
        }
        if(d.status === 'bridge_failed' || d.status === 'origin_tx_reverted' || d.status === 'timed_out'){
          showMsg(msgEl, 'Buy failed — could not move funds to this chain', false);
          if(btn){ btn.disabled=false; }
    _restoreSlide();
          return;
        }
        scheduleNext();
      })
      .catch(scheduleNext);
  }
  function scheduleNext(){
    if(attempts >= maxAttempts){
      showMsg(msgEl, 'Still buying… check your Wallet page shortly', true);
      if(btn){ btn.disabled=false; }
    _restoreSlide();
      return;
    }
    setTimeout(tick, 8000);
  }
  tick();
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
  // Same chain-based routing as confirmBuy() -- an EVM position can only ever
  // be closed through its own chain's endpoint (it sells the exact tracked
  // position server-side, same as the Solana endpoint does for amount_sol:0).
  var isBsc = t.chain === 'bsc';
  var isEvm = !!EVM_TRADE_CHAINS[t.chain];
  var url  = isBsc ? '/api/bsc/trade/sell' : (isEvm ? '/api/evm/trade/sell' : '/api/instant-trade');
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
    how = {sell_usd: usd};
  }
  var body = isBsc ? Object.assign({token_address:t.mint}, how)
    : isEvm ? Object.assign({chain:t.chain, token_address:t.mint}, how)
    : Object.assign({symbol:t.symbol, token_address:t.mint,
                     pair_address:t.pair_address, side:'sell', amount_sol:0}, how);
  fetch(url, {
    method:'POST', credentials:'include', headers: authHeaders(),
    body: JSON.stringify(body)
  }).then(function(r){ return r.json(); }).then(function(d){
    // Both EVM sell routes used to answer HTTP 200 with ok:true even for a
    // swap that failed -- ok meant only "the position was found and a sell
    // was attempted" -- so sell_executed was the one trustworthy signal.
    // They now answer ok:false with an error status when the sell does not
    // go through, and the two agree; both are checked so this keeps working
    // whichever version of the backend is deployed.
    var sold = isEvm ? !!(d && d.ok && d.sell_executed)
                     : !!(d && (d.success||d.tx||d.ok||d.sig));
    // proceeds_usdc is what the swap actually returned, measured from the
    // wallet across the trade -- shown only when it was measured, since the
    // fallback is a market quote rather than the realised amount.
    var got = (sold && d && d.proceeds_usdc != null && d.exit_price_estimated === false)
      ? (' for $' + Number(d.proceeds_usdc).toFixed(2)) : '';
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
        setTimeout(function(){
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
  return fetch('/api/watchlist', {credentials:'include'}).then(function(r){ return r.json(); }).then(function(d){
    watchSet = new Set((d && d.ok ? d.tokens : []).map(function(t){ return t.token_address; }));
  }).catch(function(){});
}
function toggleWatch(mint, sym, btn){
  var active = watchSet.has(mint);
  fetch('/api/watchlist/'+encodeURIComponent(mint), {
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
  fetch('/api/watchlist/'+encodeURIComponent(mint), {method:'DELETE', credentials:'include', headers:authHeaders()})
    .then(function(r){ return r.json(); }).then(function(d){
      if(d && d.ok){ watchSet.delete(mint); loadWatchlist(); renderFeedList(); }
    }).catch(function(){});
}
function loadWatchlist(){
  fetch('/api/watchlist', {credentials:'include'}).then(function(r){ return r.json(); }).then(function(d){
    var addrs = (d && d.ok ? d.tokens : []) || [];
    var el = document.getElementById('pt-wl-list');
    if(!addrs.length){ el.innerHTML = '<div class="pt-tape-empty">No tokens watched</div>'; return; }
    var joined = addrs.map(function(t){ return t.token_address; }).join(',');
    fetch('/api/dexscreener/tokens/'+joined).then(function(r){ return r.json(); }).then(function(pd){
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

function loadSurges(){
  fetch('/api/market/surges', {credentials:'include'})
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
      if(!list.length){ wrap.style.display = 'none'; return; }
      wrap.style.display = '';
      var keepScroll = rail.scrollLeft;
      rail.innerHTML = list.map(surgeCardHtml).join('');
      rail.scrollLeft = keepScroll;
      var sub = document.getElementById('pt-surge-sub');
      if(sub) sub.textContent = list.length + (list.length === 1 ? ' token' : ' tokens')
        + ' · vs their own 5m average';
    })
    .catch(function(){});
}

function loadTape(){
  fetch('/api/market/tape').then(function(r){ return r.json(); }).then(function(d){
    var el = document.getElementById('pt-tape-list');
    var rows = (d && d.ok && d.trades) || [];
    if(!rows.length){ el.innerHTML = '<div class="pt-tape-empty">Waiting for trades…</div>'; return; }
    el.innerHTML = rows.slice(0,14).map(function(r){
      return '<div class="pt-tape-row">'
        + '<span class="pt-tape-pill '+r.side+'">'+r.side.toUpperCase()+'</span>'
        + '<span class="pt-tape-sym">$'+esc(r.symbol)+'</span>'
        + '<span class="pt-tape-amt">'+Number(r.sol_amount||0).toFixed(3)+' SOL</span>'
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
function loadTraders(){
  fetch('/api/leaderboard').then(function(r){ return r.json(); }).then(function(rows){
    rows = Array.isArray(rows) ? rows : [];
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

/* Compact horizontal spotlight, same visual language as the token story
   rail directly above it (ring + circle avatar + name + a stat underneath)
   but for people instead of tokens -- sits inside the always-visible center
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
  fetch('/api/copy-trade/toggle', {
    method:'POST', credentials:'include', headers: authHeaders(),
    body: JSON.stringify({wallet: wallet, sol_amount: alreadyCopying ? 0 : 0.05})
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
  fetch('/api/platform/stats').then(function(r){ return r.json(); }).then(function(d){
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
  fetch('/api/online-count').then(function(r){ return r.json(); }).then(function(d){
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
  if(!wasHi) setTimeout(function(){ card.classList.remove('hi'); }, 1600);
}

function prependSearchedToken(mint, sym, pairAddr){
  fetch('/api/token/info/'+encodeURIComponent(mint)).then(function(r){ return r.json(); }).then(function(info){
    var tok;
    if(info && info.ok){
      var pc = info.price_change || {};
      tok = {
        mint: info.address||mint, symbol: info.symbol||sym, name: info.name||sym,
        chain: info.chain||'solana', pair_address: info.pair_address||pairAddr,
        image_url: info.image_url||'', price_usd: Number(info.price_usd||info.price||0),
        market_cap: Number(info.market_cap||info.mcap||0), liquidity_usd: Number(info.liquidity_usd||info.liquidity||0),
        volume_24h: Number(info.volume_24h||0), buys_24h: Number(info.buyers_24h||0), sells_24h: Number(info.sellers_24h||0),
        price_change_24h: Number(pc.h24||0), pair_created_at: null, verified_socials:false, score:3
      };
    } else {
      tok = {mint:mint, symbol:sym, name:sym, chain:'solana', pair_address:pairAddr, image_url:'',
        price_usd:0, market_cap:0, liquidity_usd:0, volume_24h:0, buys_24h:0, sells_24h:0,
        price_change_24h:0, pair_created_at:null, verified_socials:false, score:3};
    }
    ST.tokens = [tok].concat(ST.tokens.filter(function(t){ return t.mint !== tok.mint; }));
    renderStoryRail();
    renderFeedList();
    updateHeaderCounts();
    setTimeout(function(){ scrollToCard(0); }, 60);
  }).catch(function(){});
}

/* ── event wiring ── */
document.addEventListener('click', function(e){
  var el;
  if((el = e.target.closest('[data-action="story"]'))){ scrollToCard(el.dataset.idx); return; }
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
document.addEventListener('DOMContentLoaded', function(){
  var liqSlider  = document.getElementById('pt-liq-slider');
  var liqValueEl = document.getElementById('pt-liq-value');
  var _liqDebounce = null;
  liqSlider.addEventListener('input', function(){
    ST.minLiquidity = parseInt(liqSlider.value, 10);
    liqValueEl.textContent = '$'+fmtShort(ST.minLiquidity)+' of $500K';
    updateAdvCount();
    clearTimeout(_liqDebounce);
    _liqDebounce = setTimeout(loadFeed, 350);
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
  window.addEventListener('resize', syncNavbarHeight);
  window.addEventListener('orientationchange', syncNavbarHeight);

  if(filtersBtn) filtersBtn.addEventListener('click', function(){
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
  if(scrimEl) scrimEl.addEventListener('click', closeMobileOverlays);

  /* re-measure & redraw mounted charts on resize/rotation (e.g. desktop<->mobile
     breakpoint change) -- renderChartSvg() re-reads clientWidth each call, it
     just isn't re-triggered by a resize on its own between 5s poll ticks */
  var _resizeTimer = null;
  window.addEventListener('resize', function(){
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(function(){
      Object.keys(_chartTimers).forEach(function(idx){ chartTick(idx); });
    }, 200);
  });

  enableDragScroll(document.getElementById('pt-story-rail'));
  enableDragScroll(document.getElementById('pt-surge-rail'));
  enableDragScroll(document.getElementById('pt-trader-rail'));

  _prefetchBalances();
  renderSortList();
  loadWatchlistSet().then(function(){ loadFeed(); });
  loadSurges();
  loadTape();
  loadTraders();
  loadWatchlist();
  loadPulse();
  fetch('/api/copy-trade/status', {credentials:'include'}).then(function(r){ return r.json(); }).then(function(d){
    if(d && d.ok){ _copyStatus.copying = d.copying; _copyStatus.target = d.target_wallet; loadTraders(); }
  }).catch(function(){});

  // A token arrives here as ?mint=<addr> from the shared navbar's search, the
  // wallet, the calls page and a surge push notification -- all plain
  // full-page navigations, since none of those have this feed to inject into.
  //
  // It has to be injected AFTER the first scanner load, which replaces
  // ST.tokens wholesale and would wipe it. That used to be a 900ms guess:
  // fine on a fast connection, and on a slow one the token silently vanished
  // -- worst of all on a notification tap, which is the one moment it has to
  // work. It is now queued and injected when that first load actually
  // finishes, however long it takes.
  var _qMint = new URLSearchParams(location.search).get('mint');
  if(_qMint){
    history.replaceState(null, '', location.pathname);
    _pendingDeepLinkMint = _qMint;
  }

  setInterval(function(){ loadFeed(true); }, 15000);
  // Polled faster than the feed: the whole point of a surge is that it is
  // happening right now, and the radar itself re-samples every 30s.
  setInterval(loadSurges, 12000);
  setInterval(loadTape, 8000);
  setInterval(loadTraders, 30000);
  setInterval(loadPulse, 20000);
  // The one that makes the charts move. Started once for the whole page, not
  // per card -- it batches every visible chart into a single request.
  startLivePrices();
});

})();
