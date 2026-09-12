/* OrcAgent Live Market gold line/area chart layer.
   Draws one chart for every token card and keeps visible charts live without
   disturbing the existing scanner/trading controller. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/live-market')return;

var states=new Map(), io=null, refreshTimer=null, scanTimer=null;
function escId(s){return String(s||'').replace(/[^a-zA-Z0-9_-]/g,'_')}
function parsePrice(card){var el=card.querySelector('.pt-price'),v=el?(el.textContent||'').replace(/[$,]/g,''):'';v=Number(v);return isFinite(v)&&v>0?v:null}
function chainOf(card){var b=card.querySelector('.pt-chain-badge'),m=b&&String(b.className).match(/chain-([a-z0-9_-]+)/i);return m?m[1]:'solana'}
function fmt(n){n=Number(n);if(!isFinite(n))return'—';if(n>=1)return'$'+n.toFixed(2);if(n>=.01)return'$'+n.toFixed(4);if(n>=.0001)return'$'+n.toFixed(6);return'$'+n.toFixed(8)}
function chartUrl(st){var u='/api/chart/'+encodeURIComponent(st.mint)+'?tf='+encodeURIComponent(st.tf||'5m');if(st.pair)u+='&pair='+encodeURIComponent(st.pair);if(st.chain)u+='&chain='+encodeURIComponent(st.chain);return u}
function dims(st){var r=st.wrap.getBoundingClientRect();return{w:Math.max(260,Math.round(r.width||320)),h:Math.max(180,Math.round(r.height||286))}}
function render(st){
  if(!st.svg||!st.svg.isConnected||!st.data||st.data.length<2)return;
  var d=dims(st),w=d.w,h=d.h,left=12,right=54,top=48,bottom=30,pw=w-left-right,ph=h-top-bottom;
  var vals=st.data.map(function(c){return Number(c.c)||0}).filter(function(v){return v>0});if(vals.length<2)return;
  var current=parsePrice(st.card)||st.current||vals[vals.length-1];st.current=current;vals.push(current);
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);if(mn===mx){mn*=.985;mx=mx*1.015||1}var pad=(mx-mn)*.12;mn-=pad;mx+=pad;
  function X(i){return left+(i/(st.data.length-1))*pw}function Y(v){return top+((mx-Number(v))/(mx-mn))*ph}
  var pts=st.data.map(function(c,i){return{x:X(i),y:Y(c.c),v:Number(c.c)||0,t:Number(c.t)||0}});pts[pts.length-1].y=Y(current);pts[pts.length-1].v=current;
  var path='M'+pts[0].x.toFixed(2)+' '+pts[0].y.toFixed(2);for(var i=1;i<pts.length;i++)path+=' L'+pts[i].x.toFixed(2)+' '+pts[i].y.toFixed(2);
  var area=path+' L'+pts[pts.length-1].x.toFixed(2)+' '+(top+ph)+' L'+pts[0].x.toFixed(2)+' '+(top+ph)+' Z';
  var gid='oaGoldGrad'+escId(st.key),html='<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#f7b955" stop-opacity=".32"/><stop offset="100%" stop-color="#f7b955" stop-opacity=".02"/></linearGradient></defs>';
  for(var g=0;g<5;g++){var gy=top+ph/4*g,lab=mx-(mx-mn)/4*g;html+='<line x1="'+left+'" y1="'+gy.toFixed(2)+'" x2="'+(left+pw)+'" y2="'+gy.toFixed(2)+'" stroke="#17232e" stroke-width="1"/>';html+='<text x="'+(left+pw+7)+'" y="'+(gy+3).toFixed(2)+'" fill="#6f7d8c" font-size="9" font-family="JetBrains Mono,monospace">'+fmt(lab).replace('$','')+'</text>'}
  html+='<path d="'+area+'" fill="url(#'+gid+')"/>';
  html+='<path d="'+path+'" fill="none" stroke="#f7b955" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>';
  var py=Math.max(top,Math.min(top+ph,Y(current)));html+='<line x1="'+left+'" y1="'+py.toFixed(2)+'" x2="'+(left+pw)+'" y2="'+py.toFixed(2)+'" stroke="#f7b955" stroke-width="1" stroke-dasharray="4 4" opacity=".7"/>';
  html+='<rect x="'+(left+pw+2)+'" y="'+(py-10).toFixed(2)+'" rx="5" width="50" height="20" fill="#f7b955"/><text x="'+(left+pw+7)+'" y="'+(py+3).toFixed(2)+'" fill="#111820" font-size="8.5" font-weight="800" font-family="JetBrains Mono,monospace">'+fmt(current).replace('$','')+'</text>';
  [0,.25,.5,.75,1].forEach(function(q,k){var i=Math.round((st.data.length-1)*q),c=st.data[i],dt=new Date((Number(c.t)||0)*1000),t=('0'+dt.getHours()).slice(-2)+':'+('0'+dt.getMinutes()).slice(-2),xx=X(i);html+='<text x="'+xx.toFixed(2)+'" y="'+(h-8)+'" fill="#718091" font-size="9" text-anchor="'+(k===0?'start':(k===4?'end':'middle'))+'" font-family="JetBrains Mono,monospace">'+t+'</text>'});
  st.svg.setAttribute('viewBox','0 0 '+w+' '+h);st.svg.innerHTML=html;st.points=pts;st.geom={left:left,pw:pw,top:top,ph:ph,w:w,h:h};
}
function load(st){if(st.loading||!st.card.isConnected)return;st.loading=true;fetch(chartUrl(st),{credentials:'include'}).then(function(r){return r.ok?r.json():null}).then(function(j){if(j&&j.candles&&j.candles.length>1){st.data=j.candles;st.current=Number(j.current_price)||parsePrice(st.card)||Number(j.candles[j.candles.length-1].c)||0;render(st)}else if(st.tf!=='1h'){var old=st.tf;st.tf='1h';return fetch(chartUrl(st),{credentials:'include'}).then(function(r){return r.ok?r.json():null}).then(function(k){st.tf=old;if(k&&k.candles&&k.candles.length>1){st.data=k.candles;st.current=Number(k.current_price)||parsePrice(st.card)||Number(k.candles[k.candles.length-1].c)||0;render(st)}})}}).catch(function(){}).finally(function(){st.loading=false})}
function scrub(st,clientX){if(!st.points||!st.points.length||!st.geom)return;var r=st.svg.getBoundingClientRect(),x=(clientX-r.left)/Math.max(1,r.width)*st.geom.w,best=st.points[0],bd=Math.abs(st.points[0].x-x);for(var i=1;i<st.points.length;i++){var dd=Math.abs(st.points[i].x-x);if(dd<bd){bd=dd;best=st.points[i]}}if(!st.tip){st.tip=document.createElement('div');st.tip.className='oa-goldline-tip';st.wrap.appendChild(st.tip)}var dt=new Date(best.t*1000);st.tip.textContent=fmt(best.v)+' · '+('0'+dt.getHours()).slice(-2)+':'+('0'+dt.getMinutes()).slice(-2);st.tip.style.display='block';var px=best.x/st.geom.w*r.width;st.tip.style.left=Math.max(6,Math.min(r.width-st.tip.offsetWidth-6,px-st.tip.offsetWidth/2))+'px';st.tip.style.top='42px'}
function clearTip(st){if(st.tip)st.tip.style.display='none'}
function setup(card){if(card.dataset.oaGoldline==='1')return;var wrap=card.querySelector('.pt-chart-wrap');if(!wrap)return;card.dataset.oaGoldline='1';var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('class','oa-goldline-svg');svg.setAttribute('preserveAspectRatio','none');wrap.insertBefore(svg,wrap.firstChild);var st={key:card.dataset.idx||Math.random().toString(36).slice(2),card:card,wrap:wrap,svg:svg,mint:card.dataset.mint||'',pair:card.dataset.pair||'',chain:chainOf(card),tf:'5m',data:null,current:0,loading:false,visible:true,tip:null};states.set(card,st);var tfs=wrap.querySelector('.pt-chart-tfs');if(tfs)tfs.addEventListener('click',function(e){var b=e.target.closest('.pt-tf-pill');if(!b)return;st.tf=b.dataset.tf||'5m';setTimeout(function(){load(st)},0)});var dragging=false;svg.addEventListener('mousemove',function(e){scrub(st,e.clientX)});svg.addEventListener('mouseleave',function(){clearTip(st)});svg.addEventListener('pointerdown',function(e){dragging=true;scrub(st,e.clientX)});svg.addEventListener('pointermove',function(e){if(dragging)scrub(st,e.clientX)});svg.addEventListener('pointerup',function(){dragging=false;clearTip(st)});svg.addEventListener('pointercancel',function(){dragging=false;clearTip(st)});if(io)io.observe(card);setTimeout(function(){load(st)},Number(st.key)%12*70)}
function scan(){document.querySelectorAll('.pt-card').forEach(setup);states.forEach(function(st,card){if(!card.isConnected){if(io)try{io.unobserve(card)}catch(e){};states.delete(card)}})}
function refresh(){states.forEach(function(st){if(!st.card.isConnected)return;var p=parsePrice(st.card);if(p&&Math.abs((st.current||0)-p)>0){st.current=p;render(st)}if(st.visible)load(st)})}
function boot(){io=new IntersectionObserver(function(es){es.forEach(function(e){var st=states.get(e.target);if(st){st.visible=e.isIntersecting;if(st.visible){render(st);load(st)}}})},{rootMargin:'220px 0px',threshold:.01});scan();new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});refreshTimer=setInterval(function(){if(document.visibilityState==='visible')refresh()},15000);scanTimer=setInterval(function(){scan();states.forEach(function(st){if(st.visible){var p=parsePrice(st.card);if(p&&p!==st.current){st.current=p;render(st)}}})},1800);window.addEventListener('resize',function(){states.forEach(render)})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
