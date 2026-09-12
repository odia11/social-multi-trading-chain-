/* OrcAgent Live Market critical controller — single gold chart + mobile search. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/live-market') return;

var GOLD='#f7b955', states=new Map();

function fmt(n){
  n=Number(n);
  if(!isFinite(n)) return '—';
  if(n>=1) return '$'+n.toFixed(2);
  if(n>=.01) return '$'+n.toFixed(4);
  if(n>=.0001) return '$'+n.toFixed(6);
  return '$'+n.toFixed(8);
}
function tfCfg(tf){
  return ({
    '1m':{sec:60,gt:'minute',agg:1,limit:120},
    '5m':{sec:300,gt:'minute',agg:5,limit:120},
    '1h':{sec:3600,gt:'hour',agg:1,limit:120},
    '4h':{sec:14400,gt:'hour',agg:4,limit:120},
    'D':{sec:86400,gt:'day',agg:1,limit:120}
  })[tf]||{sec:300,gt:'minute',agg:5,limit:120};
}
function getChain(card){
  var b=card.querySelector('.pt-chain-badge');
  var m=b&&String(b.className).match(/chain-([a-z0-9_-]+)/i);
  return (m&&m[1])||'solana';
}
function getMint(card){ return card.dataset.mint||''; }
function getPair(card){ return card.dataset.pair||''; }
function domPrice(card){
  var e=card.querySelector('.pt-price');
  var v=Number(((e&&e.textContent)||'').replace(/[$,]/g,''));
  return isFinite(v)&&v>0?v:0;
}

function injectCss(){
  if(document.getElementById('oa-critical-css')) return;
  var s=document.createElement('style');
  s.id='oa-critical-css';
  s.textContent=[
    '.pt-chart-wrap{position:relative!important;overflow:hidden!important}',
    '.pt-chart-wrap>.pt-chart-svg,.pt-chart-wrap>.oa-gold-live,.pt-chart-wrap>.oa-gold-v2,.pt-chart-wrap>.oa-live-canvas,.pt-chart-wrap>.pt-price-pill,.pt-chart-wrap>.pt-chart-axis{opacity:0!important;pointer-events:none!important}',
    '.pt-chart-live,.pt-chart-tfs{z-index:50!important;position:absolute!important}',
    '.oa-critical-chart{position:absolute!important;left:0!important;right:0!important;top:38px!important;bottom:24px!important;width:100%!important;height:calc(100% - 62px)!important;display:block!important;opacity:1!important;visibility:visible!important;z-index:10!important;touch-action:none!important}',
    '.oa-critical-tip{position:absolute!important;z-index:60!important;display:none;pointer-events:none;background:#f7b955;color:#111820;border-radius:7px;padding:6px 9px;font:800 10px/1 "JetBrains Mono",monospace;white-space:nowrap;box-shadow:0 4px 18px rgba(0,0,0,.45)}',
    '.oa-critical-vline{position:absolute!important;z-index:55!important;top:38px!important;bottom:24px!important;width:1px;background:rgba(247,185,85,.72);display:none;pointer-events:none}',
    '.oa-critical-dot{position:absolute!important;z-index:56!important;width:9px;height:9px;border-radius:50%;background:#ffd36a;box-shadow:0 0 0 4px rgba(247,185,85,.18);display:none;pointer-events:none}',
    '@keyframes oaPulse{0%,100%{opacity:.48}50%{opacity:1}} .oa-critical-pulse{animation:oaPulse 1.1s ease-in-out infinite}',
    'body.oa-critical-search-open{overflow:hidden!important}',
    'body.oa-critical-search-open .pt-nb-topbar{display:none!important}',
    '#oa-mobile-search-layer{position:fixed!important;inset:0!important;z-index:10000!important;background:#080d12!important;padding:calc(env(safe-area-inset-top,0px) + 12px) 14px 14px!important;box-sizing:border-box!important;overflow:hidden!important}',
    '#oa-mobile-search-layer>.pt-nb-search-wrap{display:grid!important;grid-template-columns:minmax(0,1fr) 48px!important;grid-template-rows:48px auto!important;gap:10px!important;width:100%!important;max-width:none!important;margin:0!important;padding:0!important;position:relative!important;inset:auto!important;transform:none!important;background:transparent!important}',
    '#oa-mobile-search-layer .pt-nb-search{grid-column:1!important;grid-row:1!important;width:100%!important;height:48px!important;min-height:48px!important;margin:0!important;padding:0 15px!important;border:1px solid #263746!important;border-radius:14px!important;background:#0b151f!important;color:#eef1f5!important;font-size:17px!important;line-height:48px!important;box-shadow:none!important;outline:none!important;-webkit-appearance:none!important;appearance:none!important}',
    '#oa-mobile-search-layer .pt-nb-search::-webkit-search-cancel-button{display:none!important;-webkit-appearance:none!important}',
    '#oa-mobile-search-layer .pt-nb-search-icon{display:none!important}',
    '#oa-mobile-search-layer .pt-nb-search-close{display:flex!important;grid-column:2!important;grid-row:1!important;align-items:center!important;justify-content:center!important;width:48px!important;height:48px!important;margin:0!important;padding:0!important;border:1px solid #263746!important;border-radius:14px!important;background:#0b151f!important;color:#eef1f5!important;font-size:30px!important;line-height:1!important}',
    '#oa-mobile-search-layer .pt-nb-search-results{grid-column:1/-1!important;grid-row:2!important;position:relative!important;top:auto!important;left:auto!important;right:auto!important;width:100%!important;max-height:calc(100dvh - env(safe-area-inset-top,0px) - 92px)!important;margin:0!important;border-radius:14px!important;overflow-y:auto!important}',
    '#oa-mobile-search-layer .pt-nb-search-results.open{display:block!important}'
  ].join('\n');
  document.head.appendChild(s);
}

function installSearch(){
  if(!matchMedia('(max-width:767px)').matches) return;
  var input=document.getElementById('pt-nb-search-input');
  if(!input) return;
  var wrap=input.closest('.pt-nb-search-wrap');
  if(!wrap||wrap.dataset.oaSearchFixed==='1') return;
  wrap.dataset.oaSearchFixed='1';
  var homeParent=wrap.parentNode, homeNext=wrap.nextSibling, layer=null;

  function open(){
    if(layer) return;
    layer=document.createElement('div');
    layer.id='oa-mobile-search-layer';
    document.body.appendChild(layer);
    layer.appendChild(wrap);
    document.body.classList.add('oa-critical-search-open');
    wrap.classList.add('mobile-search-open');
    requestAnimationFrame(function(){ input.focus({preventScroll:true}); });
  }
  function close(){
    if(!layer) return;
    document.body.classList.remove('oa-critical-search-open');
    wrap.classList.remove('mobile-search-open');
    if(homeNext&&homeNext.parentNode===homeParent) homeParent.insertBefore(wrap,homeNext);
    else homeParent.appendChild(wrap);
    layer.remove(); layer=null;
  }

  input.addEventListener('focus',open,true);
  input.addEventListener('click',open,true);
  document.addEventListener('click',function(e){
    if(e.target.closest('#pt-nb-search-close')) setTimeout(close,0);
  },true);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape') setTimeout(close,0);
  },true);
}

function smooth(pts){
  if(pts.length<2) return '';
  var d='M'+pts[0].x.toFixed(2)+','+pts[0].y.toFixed(2);
  for(var i=0;i<pts.length-1;i++){
    var p0=pts[i===0?0:i-1],p1=pts[i],p2=pts[i+1],p3=pts[i+2]||p2;
    var c1x=p1.x+(p2.x-p0.x)/6,c1y=p1.y+(p2.y-p0.y)/6;
    var c2x=p2.x-(p3.x-p1.x)/6,c2y=p2.y-(p3.y-p1.y)/6;
    d+=' C'+c1x.toFixed(2)+','+c1y.toFixed(2)+' '+c2x.toFixed(2)+','+c2y.toFixed(2)+' '+p2.x.toFixed(2)+','+p2.y.toFixed(2);
  }
  return d;
}
function draw(st){
  if(!st.data||st.data.length<2||!st.svg.isConnected) return;
  var r=st.svg.getBoundingClientRect();
  var w=Math.max(260,Math.round(r.width||st.wrap.clientWidth||320));
  var h=Math.max(160,Math.round(r.height||260));
  var L=6,R=62,T=8,B=24,pw=w-L-R,ph=h-T-B;
  var vals=st.data.map(function(c){return Number(c.c)||0;}).filter(function(v){return v>0;});
  if(vals.length<2) return;
  var cur=Number(st.current)||vals[vals.length-1];
  vals.push(cur);
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);
  if(mn===mx){mn*=.995;mx=mx*1.005||1;}
  var pad=(mx-mn)*.10; mn-=pad; mx+=pad;
  function X(i){return L+i/(st.data.length-1)*pw;}
  function Y(v){return T+(mx-Number(v))/(mx-mn)*ph;}
  var pts=st.data.map(function(c,i){return{x:X(i),y:Y(c.c),v:Number(c.c),t:Number(c.t)};});
  pts[pts.length-1].y=Y(cur);
  st.pts=pts; st.geom={w:w,h:h,L:L,R:R,T:T,B:B,pw:pw,ph:ph};
  var path=smooth(pts);
  var area=path+' L'+X(st.data.length-1).toFixed(2)+','+(T+ph)+' L'+X(0).toFixed(2)+','+(T+ph)+' Z';
  var gid='oaGrad'+st.id;
  var html='<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+GOLD+'" stop-opacity=".34"/><stop offset="100%" stop-color="'+GOLD+'" stop-opacity=".015"/></linearGradient></defs>';
  for(var g=0;g<5;g++){
    var gy=T+ph/4*g,lab=mx-(mx-mn)/4*g;
    html+='<line x1="'+L+'" y1="'+gy+'" x2="'+(L+pw)+'" y2="'+gy+'" stroke="#18232d" stroke-width="1"/>';
    html+='<text x="'+(L+pw+7)+'" y="'+(gy+3)+'" fill="#718091" font-size="9" font-family="monospace">'+fmt(lab).replace('$','')+'</text>';
  }
  html+='<path d="'+area+'" fill="url(#'+gid+')"/>';
  html+='<path d="'+path+'" fill="none" stroke="'+GOLD+'" stroke-width="2.35" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>';
  var py=Math.max(T,Math.min(T+ph,Y(cur)));
  html+='<line x1="'+L+'" y1="'+py+'" x2="'+(L+pw)+'" y2="'+py+'" stroke="'+GOLD+'" stroke-dasharray="5 5" opacity=".78"/>';
  html+='<circle cx="'+(L+pw)+'" cy="'+py+'" r="3.8" fill="#ffd36a" class="oa-critical-pulse"/>';
  html+='<rect x="'+(L+pw+2)+'" y="'+(py-10)+'" rx="5" width="58" height="20" fill="'+GOLD+'"/>';
  html+='<text x="'+(L+pw+6)+'" y="'+(py+3)+'" fill="#111820" font-size="8" font-weight="800" font-family="monospace">'+fmt(cur).replace('$','')+'</text>';
  [0,.25,.5,.75,1].forEach(function(q,k){
    var j=Math.round((st.data.length-1)*q),d=new Date(Number(st.data[j].t)*1000);
    var t=('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2);
    html+='<text x="'+X(j)+'" y="'+(h-6)+'" fill="#718091" font-size="9" text-anchor="'+(k===0?'start':k===4?'end':'middle')+'" font-family="monospace">'+t+'</text>';
  });
  st.svg.setAttribute('viewBox','0 0 '+w+' '+h);
  st.svg.innerHTML=html;
}

function backendUrl(st){
  var u='/api/chart/'+encodeURIComponent(st.mint)+'?tf='+encodeURIComponent(st.tf)+'&chain='+encodeURIComponent(st.chain);
  if(st.pair) u+='&pair='+encodeURIComponent(st.pair);
  return u;
}
function geckoNetwork(chain){
  return ({solana:'solana',bsc:'bsc',base:'base',arbitrum:'arbitrum',polygon:'polygon_pos',robinhood:'robinhood'})[chain]||'';
}
function fetchBackend(st){
  return fetch(backendUrl(st),{credentials:'include',cache:'no-store'}).then(function(r){
    if(!r.ok) return null;
    return r.json();
  }).then(function(j){
    if(j&&j.pair_address&&!st.pair) st.pair=j.pair_address;
    var a=j&&Array.isArray(j.candles)?j.candles:[];
    if(a.length>1) return {candles:a,current:Number(j.current_price)||0};
    return null;
  }).catch(function(){return null;});
}
function fetchGecko(st){
  var net=geckoNetwork(st.chain),cfg=tfCfg(st.tf);
  if(!net||!st.pair) return Promise.resolve(null);
  var u='https://api.geckoterminal.com/api/v2/networks/'+encodeURIComponent(net)+'/pools/'+encodeURIComponent(st.pair)+'/ohlcv/'+cfg.gt+'?aggregate='+cfg.agg+'&limit='+cfg.limit+'&currency=usd';
  return fetch(u,{cache:'no-store'}).then(function(r){
    if(!r.ok) return null;
    return r.json();
  }).then(function(j){
    var rows=j&&j.data&&j.data.attributes&&j.data.attributes.ohlcv_list;
    if(!Array.isArray(rows)||rows.length<2) return null;
    var a=rows.map(function(x){
      return {t:Number(x[0]),o:Number(x[1]),h:Number(x[2]),l:Number(x[3]),c:Number(x[4]),v:Number(x[5])||0};
    }).filter(function(c){return c.t&&c.c>0;}).sort(function(a,b){return a.t-b.t;});
    return a.length>1?{candles:a,current:Number(a[a.length-1].c)||0}:null;
  }).catch(function(){return null;});
}
function applyData(st,res){
  if(!res||!res.candles||res.candles.length<2) return false;
  st.data=res.candles.slice(-160);
  st.current=Number(res.current)||domPrice(st.card)||Number(st.data[st.data.length-1].c)||0;
  draw(st);
  return true;
}
function load(st){
  if(st.loading||!st.mint) return;
  st.loading=true;
  var primary=st.chain==='robinhood'?fetchGecko(st):fetchBackend(st);
  var secondary=st.chain==='robinhood'?fetchBackend(st):fetchGecko(st);
  primary.then(function(res){
    if(applyData(st,res)) return true;
    return secondary.then(function(res2){return applyData(st,res2);});
  }).then(function(ok){
    if(ok) return;
    var p=domPrice(st.card);
    if(p>0){
      var cfg=tfCfg(st.tf),now=Math.floor(Date.now()/1000),b=Math.floor(now/cfg.sec)*cfg.sec;
      st.data=[{t:b-cfg.sec,o:p,h:p,l:p,c:p,v:0},{t:b,o:p,h:p,l:p,c:p,v:0}];
      st.current=p; draw(st);
    }
  }).finally(function(){st.loading=false;});
}
function tick(st,p){
  p=Number(p); if(!(p>0)) return;
  var cfg=tfCfg(st.tf),now=Math.floor(Date.now()/1000),bucket=Math.floor(now/cfg.sec)*cfg.sec;
  if(!st.data||!st.data.length){
    st.data=[{t:bucket-cfg.sec,o:p,h:p,l:p,c:p,v:0},{t:bucket,o:p,h:p,l:p,c:p,v:0}];
  }
  var last=st.data[st.data.length-1],prev=Number(last.c)||p;
  if(Number(last.t)<bucket) st.data.push({t:bucket,o:prev,h:p,l:p,c:p,v:0});
  else{
    last.c=p; last.h=Math.max(Number(last.h||p),p); last.l=Math.min(Number(last.l||p),p);
  }
  if(st.data.length>160) st.data=st.data.slice(-160);
  st.current=p; draw(st);
}
function animate(st,next){
  next=Number(next); if(!(next>0)) return;
  if(st.anim) cancelAnimationFrame(st.anim);
  var from=Number(st.current)||next,t0=performance.now();
  function frame(now){
    var q=Math.min(1,(now-t0)/480),e=1-Math.pow(1-q,3);
    tick(st,from+(next-from)*e);
    if(q<1) st.anim=requestAnimationFrame(frame);
    else{st.anim=null;tick(st,next);}
  }
  st.anim=requestAnimationFrame(frame);
}
function scrub(st,clientX){
  if(!st.pts||!st.pts.length||!st.geom) return;
  var r=st.svg.getBoundingClientRect(),wr=st.wrap.getBoundingClientRect();
  var local=Math.max(0,Math.min(r.width,clientX-r.left)),vx=local/r.width*st.geom.w;
  var best=0,diff=Math.abs(st.pts[0].x-vx);
  for(var i=1;i<st.pts.length;i++){var d=Math.abs(st.pts[i].x-vx);if(d<diff){best=i;diff=d;}}
  var pt=st.pts[best],c=st.data[best]; if(!pt||!c) return;
  var px=pt.x/st.geom.w*r.width+(r.left-wr.left),py=pt.y/st.geom.h*r.height+(r.top-wr.top);
  var dt=new Date(Number(c.t)*1000);
  st.line.style.display='block'; st.line.style.transform='translateX('+px+'px)';
  st.dot.style.display='block'; st.dot.style.transform='translate('+(px-4.5)+'px,'+(py-4.5)+'px)';
  st.tip.textContent=fmt(c.c)+' · '+('0'+dt.getHours()).slice(-2)+':'+('0'+dt.getMinutes()).slice(-2);
  st.tip.style.display='block';
  var tx=Math.max(6,Math.min(wr.width-st.tip.offsetWidth-6,px-st.tip.offsetWidth/2));
  var ty=Math.max(42,Math.min(wr.height-st.tip.offsetHeight-8,py-st.tip.offsetHeight-12));
  st.tip.style.transform='translate('+tx+'px,'+ty+'px)';
  var pe=st.card.querySelector('.pt-price'); if(pe) pe.textContent=fmt(c.c);
}
function clearScrub(st){
  st.line.style.display='none'; st.dot.style.display='none'; st.tip.style.display='none';
  var pe=st.card.querySelector('.pt-price'); if(pe&&st.current>0) pe.textContent=fmt(st.current);
}
function bind(st){
  var active=false,raf=null,pending=0;
  function run(x){pending=x;if(raf)return;raf=requestAnimationFrame(function(){raf=null;scrub(st,pending);});}
  st.svg.addEventListener('pointerdown',function(e){active=true;e.preventDefault();run(e.clientX);try{st.svg.setPointerCapture(e.pointerId);}catch(_){}});
  st.svg.addEventListener('pointermove',function(e){if(active||e.pointerType==='mouse'){if(active)e.preventDefault();run(e.clientX);}});
  function end(){active=false;if(raf){cancelAnimationFrame(raf);raf=null;}clearScrub(st);}
  st.svg.addEventListener('pointerup',end); st.svg.addEventListener('pointercancel',end);
  st.svg.addEventListener('pointerleave',function(e){if(e.pointerType==='mouse'&&!active)clearScrub(st);});
}
function setup(card){
  var wrap=card.querySelector('.pt-chart-wrap'),m=getMint(card);
  if(!wrap||!m) return;
  var old=states.get(card);
  if(old&&old.svg&&old.svg.isConnected) return;
  card.dataset.oaCritical='1';
  wrap.querySelectorAll('.oa-critical-chart,.oa-critical-tip,.oa-critical-vline,.oa-critical-dot').forEach(function(n){n.remove();});
  var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.classList.add('oa-critical-chart'); svg.setAttribute('preserveAspectRatio','none');
  var tip=document.createElement('div');tip.className='oa-critical-tip';
  var line=document.createElement('div');line.className='oa-critical-vline';
  var dot=document.createElement('div');dot.className='oa-critical-dot';
  wrap.appendChild(svg);wrap.appendChild(line);wrap.appendChild(dot);wrap.appendChild(tip);
  var st={id:Math.random().toString(36).slice(2),card:card,wrap:wrap,svg:svg,tip:tip,line:line,dot:dot,mint:m,pair:getPair(card),chain:getChain(card),tf:'5m',data:[],current:domPrice(card),loading:false,anim:null,pts:null,geom:null};
  states.set(card,st); bind(st); load(st);
}
function scan(){
  document.querySelectorAll('.pt-card').forEach(setup);
  states.forEach(function(st,card){
    if(!card.isConnected){if(st.anim)cancelAnimationFrame(st.anim);states.delete(card);}
  });
}
function handleTf(e){
  var b=e.target.closest('.pt-tf-pill'); if(!b) return;
  var card=b.closest('.pt-card'),st=states.get(card); if(!st) return;
  e.preventDefault(); e.stopImmediatePropagation();
  st.tf=b.dataset.tf||'5m';
  b.parentNode.querySelectorAll('.pt-tf-pill').forEach(function(x){x.classList.toggle('active',x===b);});
  st.data=[]; clearScrub(st); load(st);
}
function prices(){
  if(document.hidden) return;
  var groups={};
  states.forEach(function(st){
    if(st.card.isConnected&&st.pair) (groups[st.chain]=groups[st.chain]||[]).push(st);
  });
  Object.keys(groups).forEach(function(ch){
    var arr=groups[ch],pairs=arr.map(function(st){return st.pair;});
    fetch('/api/market/prices?chain='+encodeURIComponent(ch)+'&pairs='+encodeURIComponent(pairs.join(',')),{credentials:'include',cache:'no-store'})
      .then(function(r){return r.ok?r.json():null;})
      .then(function(j){
        if(!j||!j.prices) return;
        arr.forEach(function(st){
          var p=Number(j.prices[(st.pair||'').toLowerCase()]);
          if(p>0) animate(st,p);
        });
      }).catch(function(){});
  });
}
function boot(){
  injectCss(); installSearch(); scan();
  document.addEventListener('click',handleTf,true);
  new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});
  setInterval(prices,1500);
  setInterval(function(){if(!document.hidden)states.forEach(load);},30000);
  window.addEventListener('resize',function(){states.forEach(draw);});
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot);
else boot();
})();
