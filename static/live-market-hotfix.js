/* Live Market production layer: guaranteed gold charts, live ticks + Buy/Sell switching. */
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
function ensureStyles(){if(document.getElementById('oa-chart-hotfix-style'))return;var s=document.createElement('style');s.id='oa-chart-hotfix-style';s.textContent='body.oa-live-v2 .pt-chart-wrap{position:relative!important}body.oa-live-v2 .oa-chart-hotfix{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;display:block!important;z-index:4!important;pointer-events:none!important}body.oa-live-v2 .pt-chart-live,body.oa-live-v2 .pt-chart-tfs{z-index:8!important}.oa-chart-hotfix-status{position:absolute;left:50%;top:55%;transform:translate(-50%,-50%);z-index:5;color:#718091;font:600 11px Geist,system-ui,sans-serif;white-space:nowrap}.oa-swipe-mode button.active{color:#111820!important}.oa-live-pulse{animation:oaLivePulse 1.1s ease-in-out infinite}@keyframes oaLivePulse{0%,100%{opacity:.55}50%{opacity:1}}';document.head.appendChild(s)}
function mint(card){return card.dataset.mint||((card.querySelector('[data-action="copy-ca"][data-mint],.pt-tok-ca[data-mint]')||{}).dataset||{}).mint||''}
function pair(card){return card.dataset.pair||''}
function chain(card){var b=card.querySelector('.pt-chain-badge'),m=b&&b.className.match(/chain-([a-z0-9_-]+)/i);return(m&&m[1])||'solana'}
function domPrice(card){var e=card.querySelector('.pt-price'),v=Number(((e&&e.textContent)||'').replace(/[$,]/g,''));return isFinite(v)&&v>0?v:0}
function fmt(n){n=Number(n);if(!isFinite(n))return'—';if(n>=1)return'$'+n.toFixed(2);if(n>=.01)return'$'+n.toFixed(4);if(n>=.0001)return'$'+n.toFixed(6);return'$'+n.toFixed(8)}
function tfSeconds(tf){return({'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'D':86400})[tf]||300}
function chartUrl(st,tf){var u='/api/chart/'+encodeURIComponent(st.mint)+'?tf='+encodeURIComponent(tf)+'&chain='+encodeURIComponent(st.chain);if(st.pair)u+='&pair='+encodeURIComponent(st.pair);return u}
var charts=new Map();

function draw(st){
  if(!st.data||st.data.length<2||!st.svg.isConnected)return;
  var r=st.wrap.getBoundingClientRect(),w=Math.max(260,r.width||320),h=Math.max(180,r.height||286),L=10,R=54,T=48,B=27,pw=w-L-R,ph=h-T-B;
  var vals=st.data.map(function(c){return Number(c.c)||0}).filter(function(v){return v>0});if(vals.length<2)return;
  var cur=Number(st.current)||vals[vals.length-1];vals.push(cur);
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);if(mn===mx){mn*=.99;mx=mx*1.01||1}var pad=(mx-mn)*.1;mn-=pad;mx+=pad;
  function X(i){return L+i/(st.data.length-1)*pw}function Y(v){return T+(mx-Number(v))/(mx-mn)*ph}
  var path='M'+X(0).toFixed(1)+' '+Y(st.data[0].c).toFixed(1);for(var i=1;i<st.data.length;i++)path+=' L'+X(i).toFixed(1)+' '+Y(st.data[i].c).toFixed(1);
  var gid='hf'+st.id,area=path+' L'+X(st.data.length-1).toFixed(1)+' '+(T+ph)+' L'+X(0).toFixed(1)+' '+(T+ph)+' Z';
  var html='<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#f7b955" stop-opacity=".32"/><stop offset="100%" stop-color="#f7b955" stop-opacity=".015"/></linearGradient></defs>';
  for(var g=0;g<5;g++){var gy=T+ph/4*g,lab=mx-(mx-mn)/4*g;html+='<line x1="'+L+'" y1="'+gy+'" x2="'+(L+pw)+'" y2="'+gy+'" stroke="#18232d"/><text x="'+(L+pw+6)+'" y="'+(gy+3)+'" fill="#6e7b8a" font-size="9" font-family="monospace">'+fmt(lab).replace('$','')+'</text>'}
  html+='<path d="'+area+'" fill="url(#'+gid+')"/><path d="'+path+'" fill="none" stroke="#f7b955" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"/>';
  var py=Math.max(T,Math.min(T+ph,Y(cur)));html+='<line x1="'+L+'" y1="'+py+'" x2="'+(L+pw)+'" y2="'+py+'" stroke="#f7b955" stroke-dasharray="4 4" opacity=".72"/><circle cx="'+(L+pw)+'" cy="'+py+'" r="3.5" fill="#ffd36a" class="oa-live-pulse"/><rect x="'+(L+pw+2)+'" y="'+(py-10)+'" rx="5" width="50" height="20" fill="#f7b955"/><text x="'+(L+pw+6)+'" y="'+(py+3)+'" fill="#111820" font-size="8" font-weight="800" font-family="monospace">'+fmt(cur).replace('$','')+'</text>';
  [0,.25,.5,.75,1].forEach(function(q,k){var j=Math.round((st.data.length-1)*q),d=new Date((Number(st.data[j].t)||0)*1000),t=('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2);html+='<text x="'+X(j)+'" y="'+(h-7)+'" fill="#718091" font-size="9" text-anchor="'+(k===0?'start':k===4?'end':'middle')+'" font-family="monospace">'+t+'</text>'});
  st.svg.setAttribute('viewBox','0 0 '+w+' '+h);st.svg.innerHTML=html;if(st.status)st.status.style.display='none';
}

function applyTick(st,p){
  p=Number(p);if(!(p>0)||!st.data||!st.data.length)return;
  var now=Math.floor(Date.now()/1000),sec=tfSeconds(st.tf),bucket=Math.floor(now/sec)*sec,last=st.data[st.data.length-1],prev=Number(last.c)||p;
  if(!last.t||bucket>Number(last.t)+Math.max(1,sec/2)){
    st.data.push({t:bucket,o:prev,h:p,l:p,c:p,v:0});
    if(st.data.length>120)st.data=st.data.slice(-120);
  }else{
    last.c=p;last.h=Math.max(Number(last.h||last.c)||p,p);last.l=Math.min(Number(last.l||last.c)||p,p);
  }
  st.current=p;draw(st);
}
function animateTick(st,next){
  next=Number(next);if(!(next>0)||!st.data)return;
  if(st.raf)cancelAnimationFrame(st.raf);
  var from=Number(st.current)||Number(st.data[st.data.length-1].c)||next,start=performance.now(),dur=650;
  function frame(now){if(!st.card.isConnected){st.raf=null;return}var t=Math.min(1,(now-start)/dur),e=1-Math.pow(1-t,3),p=from+(next-from)*e;applyTick(st,p);if(t<1)st.raf=requestAnimationFrame(frame);else{st.raf=null;applyTick(st,next)}}
  st.raf=requestAnimationFrame(frame);
}

function derivedFallback(st){return fetch('/api/token/info/'+encodeURIComponent(st.mint),{credentials:'include',cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(d){var cur=Number((d&&d.price_usd)||domPrice(st.card));if(!(cur>0))return false;var pc=(d&&d.price_change)||{},now=Math.floor(Date.now()/1000),defs=[['h24',86400],['h6',21600],['h1',3600],['m5',300]],out=[];defs.forEach(function(x){var p=Number(pc[x[0]]);if(!isFinite(p)||p<=-99.9)return;var v=cur/(1+p/100);if(v>0)out.push({t:now-x[1],c:v,o:v,h:v,l:v,v:0})});out.sort(function(a,b){return a.t-b.t});out.push({t:now,c:cur,o:cur,h:cur,l:cur,v:0});if(out.length<2)out.unshift({t:now-3600,c:cur,o:cur,h:cur,l:cur,v:0});st.data=out;st.current=cur;draw(st);return true}).catch(function(){return false})}
function load(st){if(st.loading||!st.mint)return;st.loading=true;var tfs=[st.tf,'5m','1m','1h','4h','D'].filter(function(v,i,a){return a.indexOf(v)===i});function next(i){if(i>=tfs.length)return derivedFallback(st).then(function(ok){if(!ok){st.status.textContent='Live price only';st.status.style.display='block'}});return fetch(chartUrl(st,tfs[i]),{credentials:'include',cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(j){if(j&&j.candles&&j.candles.length>1){st.data=j.candles.slice(-120);st.current=Number(j.current_price)||domPrice(st.card)||Number(st.data[st.data.length-1].c)||0;draw(st);return true}return next(i+1)}).catch(function(){return next(i+1)})}return next(0).finally(function(){st.loading=false})}

function setup(card){
  if(card.dataset.oaChartHotfix==='3')return;
  var wrap=card.querySelector('.pt-chart-wrap'),m=mint(card);if(!wrap||!m)return;
  card.dataset.oaChartHotfix='3';wrap.querySelectorAll('.oa-chart-hotfix,.oa-chart-hotfix-status').forEach(function(x){x.remove()});
  var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('oa-chart-hotfix');var status=document.createElement('div');status.className='oa-chart-hotfix-status';status.textContent='Loading chart…';wrap.insertBefore(svg,wrap.firstChild);wrap.appendChild(status);
  var st={id:Math.random().toString(36).slice(2),card:card,wrap:wrap,svg:svg,status:status,mint:m,pair:pair(card),chain:chain(card),tf:'5m',data:null,current:0,loading:false,raf:null};charts.set(card,st);
  var tf=wrap.querySelector('.pt-chart-tfs');if(tf)tf.addEventListener('click',function(e){var b=e.target.closest('.pt-tf-pill');if(!b)return;st.tf=b.dataset.tf||'5m';st.data=null;load(st)});load(st);
}
function scan(){document.querySelectorAll('.pt-card').forEach(setup);charts.forEach(function(st,c){if(!c.isConnected){if(st.raf)cancelAnimationFrame(st.raf);charts.delete(c)}})}

/* One batched live-price request per chain. The endpoint already powers the
   Live Market price labels; using it here avoids re-fetching all candles just
   to move the last chart point. */
function pollLivePrices(){
  if(document.hidden)return;
  var groups={};charts.forEach(function(st){if(!st.card.isConnected||!st.data||!st.pair)return;(groups[st.chain]=groups[st.chain]||[]).push(st)});
  Object.keys(groups).forEach(function(ch){var arr=groups[ch],pairs=arr.map(function(st){return st.pair});fetch('/api/market/prices?chain='+encodeURIComponent(ch)+'&pairs='+encodeURIComponent(pairs.join(',')),{credentials:'include',cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(d){if(!d||!d.prices)return;arr.forEach(function(st){var p=Number(d.prices[(st.pair||'').toLowerCase()]);if(!(p>0))return;var pe=st.card.querySelector('.pt-price');if(pe)pe.textContent=fmt(p);animateTick(st,p)})}).catch(function(){arr.forEach(function(st){var p=domPrice(st.card);if(p>0)animateTick(st,p)})})});
  charts.forEach(function(st){if(!st.pair&&st.data){var p=domPrice(st.card);if(p>0)animateTick(st,p)}});
}
function boot(){ensureStyles();installModeObserver();scan();new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});setInterval(scan,2500);setInterval(pollLivePrices,1500);setInterval(function(){if(document.hidden)return;charts.forEach(load)},30000);document.addEventListener('visibilitychange',function(){if(!document.hidden){scan();pollLivePrices()}})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
