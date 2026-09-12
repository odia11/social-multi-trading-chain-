/* Live Market production layer: guaranteed gold charts, live ticks, touch scrub + Buy/Sell switching. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/live-market')return;

/* ── Buy / Sell mode switching ───────────────────────────────────────── */
function cleanSymbol(s){return String(s||'').replace(/^\$/,'').trim().toUpperCase()}
function currentCard(){var se=document.getElementById('pt-sheet-sym'),sym=cleanSymbol(se&&se.textContent);if(!sym)return null;var cards=document.querySelectorAll('.pt-card');for(var i=0;i<cards.length;i++){var x=cards[i].querySelector('.pt-tok-sym');if(cleanSymbol(x&&x.textContent).indexOf(sym)===0)return cards[i]}return null}
function switchTradeMode(mode){var card=currentCard();if(!card)return false;var btn=card.querySelector(mode==='sell'?'[data-action="sell"]':'[data-action="buy-open"]');if(!btn)return false;btn.click();return true}
document.addEventListener('click',function(e){var b=e.target.closest('.oa-swipe-mode [data-mode]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();switchTradeMode(b.dataset.mode)},true);
function syncModeButtons(){var sheet=document.getElementById('pt-sheet');if(!sheet)return;var sell=sheet.classList.contains('sell-mode');sheet.querySelectorAll('.oa-swipe-mode [data-mode]').forEach(function(b){var on=(b.dataset.mode==='sell')===sell;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on?'true':'false')})}
function installModeObserver(){var sheet=document.getElementById('pt-sheet');if(!sheet)return;syncModeButtons();new MutationObserver(syncModeButtons).observe(sheet,{attributes:true,attributeFilter:['class']})}

/* ── chart helpers ───────────────────────────────────────────────────── */
function ensureStyles(){if(document.getElementById('oa-chart-hotfix-style'))return;var s=document.createElement('style');s.id='oa-chart-hotfix-style';s.textContent='body.oa-live-v2 .pt-chart-wrap{position:relative!important}body.oa-live-v2 .oa-chart-hotfix{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;display:block!important;z-index:4!important;pointer-events:auto!important;touch-action:pan-y!important;-webkit-user-select:none!important;user-select:none!important}body.oa-live-v2 .pt-chart-live,body.oa-live-v2 .pt-chart-tfs{z-index:8!important}.oa-chart-hotfix-status{position:absolute;left:50%;top:55%;transform:translate(-50%,-50%);z-index:5;color:#718091;font:600 11px Geist,system-ui,sans-serif;white-space:nowrap;pointer-events:none}.oa-swipe-mode button.active{color:#111820!important}.oa-live-pulse{animation:oaLivePulse 1.1s ease-in-out infinite}@keyframes oaLivePulse{0%,100%{opacity:.55}50%{opacity:1}}';document.head.appendChild(s)}
function mint(card){return card.dataset.mint||((card.querySelector('[data-action="copy-ca"][data-mint],.pt-tok-ca[data-mint]')||{}).dataset||{}).mint||''}
function pair(card){return card.dataset.pair||''}
function chain(card){var b=card.querySelector('.pt-chain-badge'),m=b&&b.className.match(/chain-([a-z0-9_-]+)/i);return(m&&m[1])||'solana'}
function domPrice(card){var e=card.querySelector('.pt-price'),v=Number(((e&&e.textContent)||'').replace(/[$,]/g,''));return isFinite(v)&&v>0?v:0}
function fmt(n){n=Number(n);if(!isFinite(n))return'—';if(n>=1)return'$'+n.toFixed(2);if(n>=.01)return'$'+n.toFixed(4);if(n>=.0001)return'$'+n.toFixed(6);return'$'+n.toFixed(8)}
function tfSeconds(tf){return({'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'D':86400})[tf]||300}
function chartUrl(st,tf){var u='/api/chart/'+encodeURIComponent(st.mint)+'?tf='+encodeURIComponent(tf)+'&chain='+encodeURIComponent(st.chain);if(st.pair)u+='&pair='+encodeURIComponent(st.pair);return u}
var charts=new Map();

function setHeadlinePrice(st,p){var el=st.card.querySelector('.pt-price');if(el&&p>0)el.textContent=fmt(p)}
function formatTime(ts){var d=new Date(Number(ts||0)*1000);return('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)}

function draw(st){
  if(!st.data||st.data.length<2||!st.svg.isConnected)return;
  var r=st.wrap.getBoundingClientRect(),w=Math.max(260,r.width||320),h=Math.max(180,r.height||286),L=10,R=54,T=48,B=27,pw=w-L-R,ph=h-T-B;
  var vals=st.data.map(function(c){return Number(c.c)||0}).filter(function(v){return v>0});if(vals.length<2)return;
  var live=Number(st.current)||vals[vals.length-1],active=st.scrubIndex!=null&&st.data[st.scrubIndex]?st.data[st.scrubIndex]:null,shown=active?(Number(active.c)||live):live;vals.push(live);if(active)vals.push(shown);
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);if(mn===mx){mn*=.99;mx=mx*1.01||1}var pad=(mx-mn)*.1;mn-=pad;mx+=pad;
  function X(i){return L+i/(st.data.length-1)*pw}function Y(v){return T+(mx-Number(v))/(mx-mn)*ph}
  var path='M'+X(0).toFixed(1)+' '+Y(st.data[0].c).toFixed(1);for(var i=1;i<st.data.length;i++)path+=' L'+X(i).toFixed(1)+' '+Y(st.data[i].c).toFixed(1);
  var gid='hf'+st.id,area=path+' L'+X(st.data.length-1).toFixed(1)+' '+(T+ph)+' L'+X(0).toFixed(1)+' '+(T+ph)+' Z';
  var html='<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#f7b955" stop-opacity=".32"/><stop offset="100%" stop-color="#f7b955" stop-opacity=".015"/></linearGradient></defs>';
  for(var g=0;g<5;g++){var gy=T+ph/4*g,lab=mx-(mx-mn)/4*g;html+='<line x1="'+L+'" y1="'+gy+'" x2="'+(L+pw)+'" y2="'+gy+'" stroke="#18232d"/><text x="'+(L+pw+6)+'" y="'+(gy+3)+'" fill="#6e7b8a" font-size="9" font-family="monospace">'+fmt(lab).replace('$','')+'</text>'}
  html+='<path d="'+area+'" fill="url(#'+gid+')"/><path d="'+path+'" fill="none" stroke="#f7b955" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"/>';
  var py=Math.max(T,Math.min(T+ph,Y(shown)));html+='<line x1="'+L+'" y1="'+py+'" x2="'+(L+pw)+'" y2="'+py+'" stroke="#f7b955" stroke-dasharray="4 4" opacity=".72"/>';
  if(active){
    var sx=X(st.scrubIndex),sy=Math.max(T,Math.min(T+ph,Y(shown))),tipW=108,tipX=Math.max(L,Math.min(L+pw-tipW,sx-tipW/2));
    html+='<line x1="'+sx+'" y1="'+T+'" x2="'+sx+'" y2="'+(T+ph)+'" stroke="#9aa8b8" stroke-width="1" stroke-dasharray="3 3" opacity=".7"/><circle cx="'+sx+'" cy="'+sy+'" r="4.2" fill="#f7b955" stroke="#111820" stroke-width="2"/><rect x="'+tipX+'" y="'+(T+7)+'" width="'+tipW+'" height="24" rx="7" fill="#eef1f5"/><text x="'+(tipX+7)+'" y="'+(T+23)+'" fill="#111820" font-size="9" font-weight="800" font-family="monospace">'+fmt(shown)+' · '+formatTime(active.t)+'</text>';
  }else{
    html+='<circle cx="'+(L+pw)+'" cy="'+py+'" r="3.5" fill="#ffd36a" class="oa-live-pulse"/>';
  }
  html+='<rect x="'+(L+pw+2)+'" y="'+(py-10)+'" rx="5" width="50" height="20" fill="#f7b955"/><text x="'+(L+pw+6)+'" y="'+(py+3)+'" fill="#111820" font-size="8" font-weight="800" font-family="monospace">'+fmt(shown).replace('$','')+'</text>';
  [0,.25,.5,.75,1].forEach(function(q,k){var j=Math.round((st.data.length-1)*q),t=formatTime(st.data[j].t);html+='<text x="'+X(j)+'" y="'+(h-7)+'" fill="#718091" font-size="9" text-anchor="'+(k===0?'start':k===4?'end':'middle')+'" font-family="monospace">'+t+'</text>'});
  st.svg.setAttribute('viewBox','0 0 '+w+' '+h);st.svg.innerHTML=html;st.geom={w:w,L:L,pw:pw};if(st.status)st.status.style.display='none';
}

function applyTick(st,p){
  p=Number(p);if(!(p>0)||!st.data||!st.data.length)return;
  var now=Math.floor(Date.now()/1000),sec=tfSeconds(st.tf),bucket=Math.floor(now/sec)*sec,last=st.data[st.data.length-1],prev=Number(last.c)||p;
  if(!last.t||bucket>=Number(last.t)+sec){st.data.push({t:bucket,o:prev,h:p,l:p,c:p,v:0});if(st.data.length>120)st.data=st.data.slice(-120)}else{last.c=p;last.h=Math.max(Number(last.h||last.c)||p,p);last.l=Math.min(Number(last.l||last.c)||p,p)}
  st.current=p;if(st.scrubIndex==null)setHeadlinePrice(st,p);draw(st);
}
function animateTick(st,next){
  next=Number(next);if(!(next>0)||!st.data)return;
  if(st.raf)cancelAnimationFrame(st.raf);
  var from=Number(st.current)||Number(st.data[st.data.length-1].c)||next,start=performance.now(),dur=650;
  function frame(now){if(!st.card.isConnected){st.raf=null;return}var t=Math.min(1,(now-start)/dur),e=1-Math.pow(1-t,3),p=from+(next-from)*e;applyTick(st,p);if(t<1)st.raf=requestAnimationFrame(frame);else{st.raf=null;applyTick(st,next)}}
  st.raf=requestAnimationFrame(frame);
}

function scrubAt(st,clientX){if(!st.data||st.data.length<2||!st.geom)return;var r=st.svg.getBoundingClientRect(),local=(clientX-r.left)/Math.max(1,r.width)*st.geom.w,rel=(local-st.geom.L)/Math.max(1,st.geom.pw);rel=Math.max(0,Math.min(1,rel));st.scrubIndex=Math.max(0,Math.min(st.data.length-1,Math.round(rel*(st.data.length-1))));var c=st.data[st.scrubIndex];setHeadlinePrice(st,Number(c.c)||st.current);draw(st)}
function clearScrub(st){if(st.scrubIndex==null)return;st.scrubIndex=null;setHeadlinePrice(st,Number(st.current)||0);draw(st)}
function bindScrub(st){var svg=st.svg,down=false,startX=0,startY=0,horizontal=false;
  svg.addEventListener('pointerdown',function(e){if(e.pointerType==='mouse'&&e.button!==0)return;down=true;horizontal=false;startX=e.clientX;startY=e.clientY;scrubAt(st,e.clientX);try{svg.setPointerCapture(e.pointerId)}catch(_){}},{passive:true});
  svg.addEventListener('pointermove',function(e){if(e.pointerType==='mouse'&&!down){scrubAt(st,e.clientX);return}if(!down)return;var dx=Math.abs(e.clientX-startX),dy=Math.abs(e.clientY-startY);if(!horizontal&&dx>5)horizontal=dx>=dy;if(horizontal){e.preventDefault();scrubAt(st,e.clientX)}},{passive:false});
  svg.addEventListener('pointerup',function(e){down=false;horizontal=false;clearScrub(st);try{svg.releasePointerCapture(e.pointerId)}catch(_){}});
  svg.addEventListener('pointercancel',function(){down=false;horizontal=false;clearScrub(st)});
  svg.addEventListener('pointerleave',function(e){if(e.pointerType==='mouse'&&!down)clearScrub(st)});
}

function derivedFallback(st){return fetch('/api/token/info/'+encodeURIComponent(st.mint),{credentials:'include',cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(d){var cur=Number((d&&d.price_usd)||domPrice(st.card));if(!(cur>0))return false;var pc=(d&&d.price_change)||{},now=Math.floor(Date.now()/1000),defs=[['h24',86400],['h6',21600],['h1',3600],['m5',300]],out=[];defs.forEach(function(x){var p=Number(pc[x[0]]);if(!isFinite(p)||p<=-99.9)return;var v=cur/(1+p/100);if(v>0)out.push({t:now-x[1],c:v,o:v,h:v,l:v,v:0})});out.sort(function(a,b){return a.t-b.t});out.push({t:now,c:cur,o:cur,h:cur,l:cur,v:0});if(out.length<2)out.unshift({t:now-3600,c:cur,o:cur,h:cur,l:cur,v:0});st.data=out;st.current=cur;draw(st);return true}).catch(function(){return false})}
function load(st){if(st.loading||!st.mint)return;st.loading=true;var tfs=[st.tf,'5m','1m','1h','4h','D'].filter(function(v,i,a){return a.indexOf(v)===i});function next(i){if(i>=tfs.length)return derivedFallback(st).then(function(ok){if(!ok){st.status.textContent='Live price only';st.status.style.display='block'}});return fetch(chartUrl(st,tfs[i]),{credentials:'include',cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(j){if(j&&j.candles&&j.candles.length>1){st.data=j.candles.slice(-120);st.current=Number(j.current_price)||domPrice(st.card)||Number(st.data[st.data.length-1].c)||0;draw(st);return true}return next(i+1)}).catch(function(){return next(i+1)})}return next(0).finally(function(){st.loading=false})}

function setup(card){
  if(card.dataset.oaChartHotfix==='4')return;
  var wrap=card.querySelector('.pt-chart-wrap'),m=mint(card);if(!wrap||!m)return;
  card.dataset.oaChartHotfix='4';wrap.querySelectorAll('.oa-chart-hotfix,.oa-chart-hotfix-status').forEach(function(x){x.remove()});
  var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('oa-chart-hotfix');svg.setAttribute('aria-label','Interactive live price chart');var status=document.createElement('div');status.className='oa-chart-hotfix-status';status.textContent='Loading chart…';wrap.insertBefore(svg,wrap.firstChild);wrap.appendChild(status);
  var st={id:Math.random().toString(36).slice(2),card:card,wrap:wrap,svg:svg,status:status,mint:m,pair:pair(card),chain:chain(card),tf:'5m',data:null,current:0,loading:false,raf:null,scrubIndex:null,geom:null};charts.set(card,st);bindScrub(st);
  var tf=wrap.querySelector('.pt-chart-tfs');if(tf)tf.addEventListener('click',function(e){var b=e.target.closest('.pt-tf-pill');if(!b)return;st.tf=b.dataset.tf||'5m';st.data=null;st.scrubIndex=null;load(st)});load(st);
}
function scan(){document.querySelectorAll('.pt-card').forEach(setup);charts.forEach(function(st,c){if(!c.isConnected){if(st.raf)cancelAnimationFrame(st.raf);charts.delete(c)}})}

/* One batched live-price request per chain. This endpoint is the authoritative
   fast price source for the card and the chart, so the line keeps ticking even
   if some other DOM updater stalls. */
function pollLivePrices(){
  if(document.hidden)return;
  var groups={};charts.forEach(function(st){if(!st.card.isConnected||!st.data||!st.pair)return;(groups[st.chain]=groups[st.chain]||[]).push(st)});
  Object.keys(groups).forEach(function(ch){var arr=groups[ch],pairs=arr.map(function(st){return st.pair});fetch('/api/market/prices?chain='+encodeURIComponent(ch)+'&pairs='+encodeURIComponent(pairs.join(',')),{credentials:'include',cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(d){if(!d||!d.prices)return;arr.forEach(function(st){var p=Number(d.prices[(st.pair||'').toLowerCase()]);if(p>0)animateTick(st,p)})}).catch(function(){arr.forEach(function(st){var p=domPrice(st.card);if(p>0)animateTick(st,p)})})});
  charts.forEach(function(st){if(!st.pair&&st.data){var p=domPrice(st.card);if(p>0)animateTick(st,p)}});
}
function boot(){ensureStyles();installModeObserver();scan();new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});setInterval(scan,2500);setInterval(pollLivePrices,1500);setInterval(function(){if(document.hidden)return;charts.forEach(load)},30000);document.addEventListener('visibilitychange',function(){if(!document.hidden){scan();pollLivePrices()}})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
