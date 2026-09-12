/* Live Market production hotfix: guaranteed gold charts + reliable Buy/Sell mode switch. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/live-market')return;

function cleanSymbol(s){return String(s||'').replace(/^\$/,'').trim().toUpperCase()}
function currentCard(){
  var symEl=document.getElementById('pt-sheet-sym'),sym=cleanSymbol(symEl&&symEl.textContent);
  if(!sym)return null;
  var cards=document.querySelectorAll('.pt-card');
  for(var i=0;i<cards.length;i++){
    var x=cards[i].querySelector('.pt-tok-sym');
    if(cleanSymbol(x&&x.textContent).indexOf(sym)===0)return cards[i];
  }
  return null;
}
function switchTradeMode(mode){
  var card=currentCard();if(!card)return false;
  var btn=card.querySelector(mode==='sell'?'[data-action="sell"]':'[data-action="buy-open"]');
  if(!btn)return false;
  btn.click();return true;
}

document.addEventListener('click',function(e){
  var b=e.target.closest('.oa-swipe-mode [data-mode]');if(!b)return;
  e.preventDefault();e.stopImmediatePropagation();switchTradeMode(b.dataset.mode);
},true);

function syncModeButtons(){
  var sheet=document.getElementById('pt-sheet');if(!sheet)return;
  var sell=sheet.classList.contains('sell-mode');
  sheet.querySelectorAll('.oa-swipe-mode [data-mode]').forEach(function(b){
    b.classList.toggle('active',(b.dataset.mode==='sell')===sell);
    b.setAttribute('aria-pressed',((b.dataset.mode==='sell')===sell)?'true':'false');
  });
}

function installModeObserver(){
  var sheet=document.getElementById('pt-sheet');if(!sheet)return;
  syncModeButtons();new MutationObserver(syncModeButtons).observe(sheet,{attributes:true,attributeFilter:['class']});
}

function ensureChartStyles(){if(document.getElementById('oa-chart-hotfix-style'))return;var s=document.createElement('style');s.id='oa-chart-hotfix-style';s.textContent='body.oa-live-v2 .pt-chart-wrap{position:relative!important}body.oa-live-v2 .oa-chart-hotfix{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;display:block!important;z-index:3!important;pointer-events:none!important}body.oa-live-v2 .pt-chart-live,body.oa-live-v2 .pt-chart-tfs{z-index:8!important}.oa-chart-hotfix-status{position:absolute;left:50%;top:55%;transform:translate(-50%,-50%);z-index:4;color:#718091;font:600 11px Geist,system-ui,sans-serif;white-space:nowrap}.oa-swipe-mode button.active{color:#111820!important}.pt-sheet.sell-mode .oa-swipe-mode button.active{color:#111820!important}';document.head.appendChild(s)}
function mint(card){var e=card.querySelector('[data-action="copy-ca"][data-mint],.pt-tok-ca[data-mint],[data-mint]');return (e&&e.dataset.mint)||''}
function chain(card){var b=card.querySelector('.pt-chain-badge'),m=b&&b.className.match(/chain-([a-z0-9_-]+)/i);return (m&&m[1])||'solana'}
function price(card){var e=card.querySelector('.pt-price'),v=Number(((e&&e.textContent)||'').replace(/[$,]/g,''));return isFinite(v)?v:0}
function fmt(n){n=Number(n);if(n>=1)return'$'+n.toFixed(2);if(n>=.01)return'$'+n.toFixed(4);if(n>=.0001)return'$'+n.toFixed(6);return'$'+n.toFixed(8)}
function chartUrl(st,tf){return'/api/chart/'+encodeURIComponent(st.mint)+'?tf='+encodeURIComponent(tf)+'&chain='+encodeURIComponent(st.chain)}
var charts=new Map();
function draw(st){if(!st.data||st.data.length<2)return;var r=st.wrap.getBoundingClientRect(),w=Math.max(260,r.width||320),h=Math.max(180,r.height||286),L=10,R=54,T=48,B=27,pw=w-L-R,ph=h-T-B,vals=st.data.map(function(c){return Number(c.c)||0}).filter(function(v){return v>0});if(vals.length<2)return;var cur=price(st.card)||Number(st.current)||vals[vals.length-1];vals.push(cur);var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals);if(mn===mx){mn*=.985;mx=mx*1.015||1}var pad=(mx-mn)*.1;mn-=pad;mx+=pad;function X(i){return L+i/(st.data.length-1)*pw}function Y(v){return T+(mx-Number(v))/(mx-mn)*ph}var path='M'+X(0).toFixed(1)+' '+Y(st.data[0].c).toFixed(1);for(var i=1;i<st.data.length;i++)path+=' L'+X(i).toFixed(1)+' '+Y(st.data[i].c).toFixed(1);var gid='hf'+st.id,area=path+' L'+X(st.data.length-1).toFixed(1)+' '+(T+ph)+' L'+X(0).toFixed(1)+' '+(T+ph)+' Z',html='<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#f7b955" stop-opacity=".30"/><stop offset="100%" stop-color="#f7b955" stop-opacity=".01"/></linearGradient></defs>';for(var g=0;g<5;g++){var gy=T+ph/4*g,lab=mx-(mx-mn)/4*g;html+='<line x1="'+L+'" y1="'+gy+'" x2="'+(L+pw)+'" y2="'+gy+'" stroke="#18232d"/><text x="'+(L+pw+6)+'" y="'+(gy+3)+'" fill="#6e7b8a" font-size="9" font-family="monospace">'+fmt(lab).replace('$','')+'</text>'}html+='<path d="'+area+'" fill="url(#'+gid+')"/><path d="'+path+'" fill="none" stroke="#f7b955" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>';var py=Y(cur);html+='<line x1="'+L+'" y1="'+py+'" x2="'+(L+pw)+'" y2="'+py+'" stroke="#f7b955" stroke-dasharray="4 4" opacity=".7"/><rect x="'+(L+pw+2)+'" y="'+(py-10)+'" rx="5" width="50" height="20" fill="#f7b955"/><text x="'+(L+pw+6)+'" y="'+(py+3)+'" fill="#111820" font-size="8" font-weight="800" font-family="monospace">'+fmt(cur).replace('$','')+'</text>';[0,.25,.5,.75,1].forEach(function(q,k){var j=Math.round((st.data.length-1)*q),d=new Date((Number(st.data[j].t)||0)*1000),t=('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2);html+='<text x="'+X(j)+'" y="'+(h-7)+'" fill="#718091" font-size="9" text-anchor="'+(k===0?'start':k===4?'end':'middle')+'" font-family="monospace">'+t+'</text>'});st.svg.setAttribute('viewBox','0 0 '+w+' '+h);st.svg.innerHTML=html;if(st.status)st.status.style.display='none'}
function load(st){if(st.loading||!st.mint)return;st.loading=true;var tfs=[st.tf,'5m','1m','1h','4h','D'].filter(function(v,i,a){return a.indexOf(v)===i});function next(i){if(i>=tfs.length){st.status.textContent='Waiting for chart data…';st.status.style.display='block';return Promise.resolve()}return fetch(chartUrl(st,tfs[i]),{credentials:'include',cache:'no-store'}).then(function(r){return r.ok?r.json():null}).then(function(j){if(j&&j.candles&&j.candles.length>1){st.data=j.candles;st.current=Number(j.current_price)||0;draw(st);return}return next(i+1)}).catch(function(){return next(i+1)})}return next(0).finally(function(){st.loading=false})}
function setup(card){if(card.dataset.oaChartHotfix==='1')return;var wrap=card.querySelector('.pt-chart-wrap'),m=mint(card);if(!wrap||!m)return;card.dataset.oaChartHotfix='1';var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('oa-chart-hotfix');var status=document.createElement('div');status.className='oa-chart-hotfix-status';status.textContent='Loading chart…';wrap.insertBefore(svg,wrap.firstChild);wrap.appendChild(status);var st={id:Math.random().toString(36).slice(2),card:card,wrap:wrap,svg:svg,status:status,mint:m,chain:chain(card),tf:'5m',data:null,current:0,loading:false};charts.set(card,st);var tf=wrap.querySelector('.pt-chart-tfs');if(tf)tf.addEventListener('click',function(e){var b=e.target.closest('.pt-tf-pill');if(!b)return;st.tf=b.dataset.tf||'5m';st.data=null;load(st)});load(st)}
function scan(){document.querySelectorAll('.pt-card').forEach(setup);charts.forEach(function(st,c){if(!c.isConnected)charts.delete(c)})}
function boot(){ensureChartStyles();installModeObserver();scan();new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});setInterval(function(){if(document.hidden)return;scan();charts.forEach(function(st){var p=price(st.card);if(p&&st.data){st.current=p;draw(st)}})},2000);setInterval(function(){if(document.hidden)return;charts.forEach(load)},15000)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();