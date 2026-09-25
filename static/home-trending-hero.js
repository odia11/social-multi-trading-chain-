/* Home feed "Trending now" hero card.
 *
 * Shows the one token /api/home/trending-hero says is trending right now
 * (see trending_hero.py for the bar), refreshed every 20s. When nothing is
 * trending any more the endpoint returns no token and the card fades out and
 * is removed. Members can vote bull/bear and like it; tapping the same choice
 * again takes it back. "Trade" opens that token on Live Market.
 */
(function(){
'use strict';
var POLL_MS = 20000;
var host = null, current = null, busy = false, chartFor = '', sparkHtml = '';

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function fmtPrice(n){
  n=Number(n)||0;
  if(n>=1)return '$'+n.toLocaleString('en-US',{maximumFractionDigits:2});
  if(n>=0.01)return '$'+n.toFixed(4);
  var dec=Math.min(10,2-Math.floor(Math.log10(n)));      // 3 significant digits
  return '$'+n.toFixed(dec);
}
function fmtUsd(n){
  n=Number(n)||0;
  if(n>=1e9)return '$'+(n/1e9).toFixed(2)+'B';
  if(n>=1e6)return '$'+(n/1e6).toFixed(2)+'M';
  if(n>=1e3)return '$'+Math.round(n/1e3)+'K';
  return '$'+Math.round(n);
}
function fmtInt(n){return (Number(n)||0).toLocaleString('en-US')}
var CHAINS={solana:['S','#9945ff','Solana'],bsc:['B','#f0b90b','BNB Chain'],base:['B','#0052ff','Base'],
  arbitrum:['A','#28a0f0','Arbitrum'],polygon:['P','#8247e5','Polygon'],robinhood:['R','#00c805','Robinhood Chain']};

function ensureHost(){
  if(host&&document.body.contains(host))return host;
  var tabs=document.querySelector('.feed-tabs');
  if(!tabs||!tabs.parentNode)return null;
  host=document.createElement('section');
  host.id='oa-trend-hero';host.className='oa-th';host.setAttribute('aria-label','Trending token');
  tabs.parentNode.insertBefore(host,tabs);
  return host;
}

function render(t,s){
  var h=ensureHost();if(!h)return;
  var chain=CHAINS[t.chain]||[t.chain.charAt(0).toUpperCase(),'#6f7b88',t.chain];
  var up=t.price_change_24h>=0, total=(t.buys_24h+t.sells_24h)||1;
  var buyPct=Math.round(t.buys_24h/total*100), sellPct=100-buyPct;
  // Only http(s) logos; a broken one falls back to the letter underneath.
  var logo=/^https?:\/\//.test(t.image_url||'')?'<img src="'+esc(t.image_url)+'" alt="" loading="lazy">':'';
  var sym=esc(t.symbol||'?');
  h.innerHTML=
    '<div class="oa-th-top"><span class="oa-th-badge"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c1 4 5 5.5 5 11a5 5 0 0 1-10 0c0-2.5 1.2-4 2.5-5.3C9.8 10 11 10.5 11.5 12c1.3-2.6.5-6 .5-10Z"/></svg>'
      +(t.surging?'Surging now':'Trending now')+'</span><span class="oa-th-live"><i></i>LIVE</span></div>'
    +'<div class="oa-th-head">'
      +'<div class="oa-th-logo"><span>'+esc((t.symbol||'?').charAt(0).toUpperCase())+'</span>'+logo
        +'<b style="background:'+chain[1]+'" title="'+esc(chain[2])+'">'+esc(chain[0])+'</b></div>'
      +'<div class="oa-th-id"><strong>$'+sym+'</strong><small>'+esc(t.name||t.symbol)+' · '+esc(chain[2])+'</small></div>'
      +'<div class="oa-th-px"><strong>'+fmtPrice(t.price_usd)+'</strong>'
        +'<span class="oa-th-chg '+(up?'up':'down')+'">'+(up?'↗ +':'↘ ')+t.price_change_24h.toFixed(1)+'%</span></div>'
    +'</div>'
    // The 20s refresh re-renders the card; keep the already-drawn sparkline
    // instead of blanking it until the next chart fetch.
    +'<svg class="oa-th-spark'+(chartFor===t.mint&&!sparkHtml?' empty':'')+'" id="oa-th-spark" viewBox="0 0 300 90" preserveAspectRatio="none" aria-hidden="true">'+(chartFor===t.mint?sparkHtml:'')+'</svg>'
    +'<div class="oa-th-pressure"><span>Buy pressure</span><span><em class="b">'+buyPct+'% buy</em> · <em class="s">'+sellPct+'% sell</em></span></div>'
    +'<div class="oa-th-bar"><i style="width:'+buyPct+'%"></i></div>'
    +'<div class="oa-th-stats">'
      +'<div><strong class="b">'+fmtInt(t.buys_24h)+'</strong><small>Buys</small></div>'
      +'<div><strong>'+fmtUsd(t.volume_24h)+'</strong><small>Vol · 24h</small></div>'
      +'<div><strong class="s">'+fmtInt(t.sells_24h)+'</strong><small>Sells</small></div>'
    +'</div>'
    +'<div class="oa-th-social" id="oa-th-social"></div>'
    +'<a class="oa-th-trade" href="/live-market?mint='+encodeURIComponent(t.mint)+'">Trade $'+sym+' <span aria-hidden="true">→</span></a>';
  var img=h.querySelector('.oa-th-logo img');
  if(img)img.addEventListener('error',function(){img.remove()},{once:true});
  renderSocial(s);
  if(chartFor!==t.mint){chartFor=t.mint;loadSpark(t,up);}
  h.classList.remove('oa-th-leaving');
  requestAnimationFrame(function(){h.classList.add('oa-th-in')});
}

function renderSocial(s){
  var box=document.getElementById('oa-th-social');if(!box||!s)return;
  box.innerHTML=
    '<button type="button" class="oa-th-vote bull'+(s.my_vote===1?' on':'')+'" data-vote="bull" aria-pressed="'+(s.my_vote===1)+'">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5l7 9H5z"/></svg>Bullish <b>'+fmtInt(s.bull)+'</b></button>'
    +'<button type="button" class="oa-th-vote bear'+(s.my_vote===-1?' on':'')+'" data-vote="bear" aria-pressed="'+(s.my_vote===-1)+'">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19l7-9H5z"/></svg>Bearish <b>'+fmtInt(s.bear)+'</b></button>'
    +'<button type="button" class="oa-th-like'+(s.liked?' on':'')+'" aria-pressed="'+(!!s.liked)+'" aria-label="Like">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-8-5.4-9.4-10A5 5 0 0 1 12 6a5 5 0 0 1 9.4 5C20 15.6 12 21 12 21Z"/></svg><b>'+fmtInt(s.likes)+'</b></button>';
}

function loadSpark(t,up){
  var qs='?tf=5m'+(t.pair_address?'&pair='+encodeURIComponent(t.pair_address):'')+'&chain='+encodeURIComponent(t.chain);
  fetch('/api/chart/'+encodeURIComponent(t.mint)+qs,{credentials:'same-origin'})
    .then(function(r){return r.json()})
    .then(function(d){
      var svg=document.getElementById('oa-th-spark');
      if(!svg||!current||current.mint!==t.mint)return;
      var c=(d&&d.candles||[]).map(function(x){return Number(x.c)}).filter(function(v){return v>0});
      // Candles 10x+ away from the live price are the other side of the pool,
      // not this token; never draw them (same guard as Live Market).
      var last=c[c.length-1], ratio=last/t.price_usd;
      if(c.length<2||!(ratio<10&&ratio>0.1)){sparkHtml='';svg.innerHTML='';svg.classList.add('empty');return;}
      c=c.slice(-40);
      var min=Math.min.apply(null,c),max=Math.max.apply(null,c);if(max===min){max*=1.01;min*=0.99}
      var pts=c.map(function(v,i){return [(i/(c.length-1))*300, 8+(1-(v-min)/(max-min))*74]});
      var line=pts.map(function(p,i){return (i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)}).join(' ');
      var col=up?'#5fd39b':'#f07178', lp=pts[pts.length-1];
      svg.classList.remove('empty');
      sparkHtml='<defs><linearGradient id="oaThG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+col+'" stop-opacity=".32"/><stop offset="1" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'
        +'<path d="'+line+' L300 90 L0 90Z" fill="url(#oaThG)"/>'
        +'<path d="'+line+'" fill="none" stroke="'+col+'" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        +'<circle cx="'+lp[0].toFixed(1)+'" cy="'+lp[1].toFixed(1)+'" r="4" fill="'+col+'"/>';
      svg.innerHTML=sparkHtml;
    }).catch(function(){});
}

function hide(){
  if(!host||!document.body.contains(host))return;
  var h=host;host=null;chartFor='';sparkHtml='';
  h.classList.add('oa-th-leaving');h.classList.remove('oa-th-in');
  setTimeout(function(){if(h.parentNode)h.parentNode.removeChild(h)},420);
}

function refresh(){
  if(document.hidden||busy)return;
  busy=true;
  fetch('/api/home/trending-hero',{credentials:'same-origin',cache:'no-store'})
    .then(function(r){return r.json()})
    .then(function(d){
      if(!d||!d.ok)return;
      if(!d.token){current=null;hide();return;}
      if(current&&current.mint!==d.token.mint){chartFor='';sparkHtml='';}
      current=d.token;render(d.token,d.social);
    }).catch(function(){})
    .then(function(){busy=false});
}

function post(path,body){
  return fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json().then(function(j){return {status:r.status,body:j}})});
}
document.addEventListener('click',function(e){
  var b=e.target.closest&&e.target.closest('#oa-th-social button');
  if(!b||!current)return;
  e.preventDefault();
  if(typeof checkGuest==='function'&&checkGuest())return;
  var mint=current.mint, isLike=b.classList.contains('oa-th-like');
  b.disabled=true;
  post(isLike?'/api/home/trending-hero/like':'/api/home/trending-hero/vote',
       isLike?{mint:mint}:{mint:mint,vote:b.dataset.vote})
    .then(function(res){
      if(res.body&&res.body.ok&&current&&current.mint===mint)renderSocial(res.body.social);
      else if(res.status===409)refresh();
    }).catch(function(){}).then(function(){b.disabled=false});
});

function boot(){
  var path=location.pathname.replace(/\/+$/,'')||'/';
  if(path!=='/'&&path!=='/dashboard')return;
  refresh();
  setInterval(refresh,POLL_MS);
  document.addEventListener('visibilitychange',function(){if(!document.hidden)refresh()});
}
window.OrcAgentRefreshTrendingHero=refresh;
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
