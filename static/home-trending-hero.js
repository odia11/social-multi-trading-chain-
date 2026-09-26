/* Home feed "Trending now" card, shown as a post from OrcAgent.
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

// Rendered as a POST in the feed: first item under the For You tab, from
// OrcAgent, with the token card as its attachment and Bullish / Bearish /
// Like as its action row. It sits right before #center-feed rather than
// inside it, so the feed's own re-renders never wipe it.
function ensureHost(){
  if(host&&document.body.contains(host))return host;
  var feed=document.getElementById('center-feed');
  if(!feed||!feed.parentNode)return null;
  host=document.createElement('article');
  host.id='oa-trend-hero';host.className='fc-card oa-th-post';host.setAttribute('aria-label','Trending token');
  feed.parentNode.insertBefore(host,feed);
  syncTab();
  return host;
}
// Only on For You: Following is posts from people you follow.
function syncTab(){
  if(!host)return;
  var active=document.querySelector('.feed-tab.active');
  host.hidden=!!(active&&active.dataset.tab&&active.dataset.tab!=='foryou');
}
// Follow whichever tab is active, however it was switched (the mobile home
// has its own tab bar that drives the hidden .feed-tab buttons).
function watchTabs(){
  var bar=document.querySelector('.feed-tabs');
  if(bar&&'MutationObserver' in window)
    new MutationObserver(syncTab).observe(bar,{subtree:true,attributes:true,attributeFilter:['class']});
}
function ago(sec){
  var d=Math.max(0,Math.floor(Date.now()/1000-(Number(sec)||0)));
  if(!sec||d<60)return 'now';
  if(d<3600)return Math.floor(d/60)+'m';
  if(d<86400)return Math.floor(d/3600)+'h';
  return Math.floor(d/86400)+'d';
}
var ORC_MARK='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4 21 19H3Z" fill="#111318"/></svg>';
var VERIFIED='<svg class="oa-th-verified" viewBox="0 0 24 24" aria-label="Verified"><circle cx="12" cy="12" r="12" fill="#f7b955"/><path d="M7 12.5l3.2 3.2L17 9" stroke="#0a0b0e" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function render(t,s){
  var h=ensureHost();if(!h)return;
  var chain=CHAINS[t.chain]||[t.chain.charAt(0).toUpperCase(),'#6f7b88',t.chain];
  var up=t.price_change_24h>=0, total=(t.buys_24h+t.sells_24h)||1;
  var buyPct=Math.round(t.buys_24h/total*100), sellPct=100-buyPct;
  // Only http(s) logos; a broken one falls back to the letter underneath.
  var logo=/^https?:\/\//.test(t.image_url||'')?'<img src="'+esc(t.image_url)+'" alt="" loading="lazy">':'';
  var sym=esc(t.symbol||'?');
  var chg=(up?'+':'')+t.price_change_24h.toFixed(1)+'%';
  h.innerHTML=
    '<div class="fc-avatar oa-th-avatar">'+ORC_MARK+'</div>'
    +'<div class="fc-body">'
      +'<div class="fc-header">'
        +'<span class="fc-name">OrcAgent</span>'+VERIFIED
        +'<span class="oa-th-tag"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c1 4 5 5.5 5 11a5 5 0 0 1-10 0c0-2.5 1.2-4 2.5-5.3C9.8 10 11 10.5 11.5 12c1.3-2.6.5-6 .5-10Z"/></svg>'+(t.surging?'Surging':'Trending')+'</span>'
        +'<span class="fc-sep">·</span><span class="fc-time" id="oa-th-time">'+ago(t.trending_since)+'</span>'
        +'<span class="oa-th-live" title="Live"><i></i>LIVE</span>'
      +'</div>'
      +'<div class="oa-th-text"><b>$'+sym+'</b> is trending on '+esc(chain[2])+' 🔥 '
        +'<span class="'+(up?'b':'s')+'">'+chg+'</span> in 24h with '+fmtUsd(t.volume_24h)+' volume.</div>'
      +'<div class="oa-th-embed">'
        +'<div class="oa-th-head">'
          +'<div class="oa-th-logo"><span>'+esc((t.symbol||'?').charAt(0).toUpperCase())+'</span>'+logo
            +'<b style="background:'+chain[1]+'" title="'+esc(chain[2])+'">'+esc(chain[0])+'</b></div>'
          +'<div class="oa-th-id"><strong>$'+sym+'</strong><small>'+esc(t.name||t.symbol)+' · '+esc(chain[2])+'</small></div>'
          +'<div class="oa-th-px"><strong>'+fmtPrice(t.price_usd)+'</strong>'
            +'<span class="oa-th-chg '+(up?'up':'down')+'">'+(up?'↗ ':'↘ ')+chg+'</span></div>'
        +'</div>'
        // The 20s refresh re-renders the post; keep the already-drawn
        // sparkline instead of blanking it until the next chart fetch.
        +'<svg class="oa-th-spark'+(chartFor===t.mint&&!sparkHtml?' empty':'')+'" id="oa-th-spark" viewBox="0 0 300 90" preserveAspectRatio="none" aria-hidden="true">'+(chartFor===t.mint?sparkHtml:'')+'</svg>'
        +'<div class="oa-th-pressure"><span>Buy pressure</span><span><em class="b">'+buyPct+'% buy</em> · <em class="s">'+sellPct+'% sell</em></span></div>'
        +'<div class="oa-th-bar"><i style="width:'+buyPct+'%"></i></div>'
        +'<div class="oa-th-stats">'
          +'<div><strong class="b">'+fmtInt(t.buys_24h)+'</strong><small>Buys</small></div>'
          +'<div><strong>'+fmtUsd(t.volume_24h)+'</strong><small>Vol · 24h</small></div>'
          +'<div><strong class="s">'+fmtInt(t.sells_24h)+'</strong><small>Sells</small></div>'
        +'</div>'
        +'<a class="oa-th-trade" href="/live-market?mint='+encodeURIComponent(t.mint)+'">Trade $'+sym+' <span aria-hidden="true">→</span></a>'
      +'</div>'
      +'<div class="oa-th-social" id="oa-th-social"></div>'
    +'</div>';
  var img=h.querySelector('.oa-th-logo img');
  if(img)img.addEventListener('error',function(){img.remove()},{once:true});
  renderSocial(s);
  if(chartFor!==t.mint){chartFor=t.mint;loadSpark(t,up);}
  h.classList.remove('oa-th-leaving');
  requestAnimationFrame(function(){h.classList.add('oa-th-in')});
}

// The post's action row, in the feed's own style: icon + count.
function renderSocial(s){
  var box=document.getElementById('oa-th-social');if(!box||!s)return;
  box.innerHTML=
    '<button type="button" class="oa-th-act oa-th-vote bull'+(s.my_vote===1?' on':'')+'" data-vote="bull" aria-pressed="'+(s.my_vote===1)+'" aria-label="Bullish">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 17l6-6 4 4 7-8"/><path d="M15 7h6v6"/></svg><span>Bullish</span><b>'+fmtInt(s.bull)+'</b></button>'
    +'<button type="button" class="oa-th-act oa-th-vote bear'+(s.my_vote===-1?' on':'')+'" data-vote="bear" aria-pressed="'+(s.my_vote===-1)+'" aria-label="Bearish">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7l6 6 4-4 7 8"/><path d="M15 17h6v-6"/></svg><span>Bearish</span><b>'+fmtInt(s.bear)+'</b></button>'
    +'<button type="button" class="oa-th-act oa-th-like'+(s.liked?' on':'')+'" aria-pressed="'+(!!s.liked)+'" aria-label="Like">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-8-5.4-9.4-10A5 5 0 0 1 12 6a5 5 0 0 1 9.4 5C20 15.6 12 21 12 21Z"/></svg><b>'+fmtInt(s.likes)+'</b></button>'
    +'<button type="button" class="oa-th-act oa-th-share" aria-label="Share" aria-haspopup="menu">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"/><path d="M7 8l5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg><span>Share</span></button>';
}

// ── share: a public link that unfurls on X as this card ──────────────────
// /trending/<chain>/<token> (trending_share.py) carries the card image and
// the live numbers; opening it lands on this card in the app.
function shareLink(t){
  // A fresh query per hour so X fetches the current numbers, not an old unfurl.
  return location.origin+'/trending/'+encodeURIComponent(t.chain)+'/'+encodeURIComponent(t.mint)
    +'?s='+Math.floor(Date.now()/3600000);
}
function shareText(t){
  var chg=(Number(t.price_change_24h)>=0?'+':'')+(Number(t.price_change_24h)||0).toFixed(1)+'%';
  return '$'+(t.symbol||'')+' is trending on @Orcagent 🔥 '+chg+' in 24h with '+fmtUsd(t.volume_24h)+' volume';
}
function closeShare(){var m=document.getElementById('oa-th-share-menu');if(m)m.remove();}
function openShare(btn){
  if(document.getElementById('oa-th-share-menu')){closeShare();return;}
  var t=current;if(!t)return;
  var url=shareLink(t), text=shareText(t);
  var m=document.createElement('div');
  m.id='oa-th-share-menu';m.className='oa-th-share-menu';m.setAttribute('role','menu');
  m.innerHTML=
    '<a role="menuitem" class="oa-th-share-x" target="_blank" rel="noopener" href="https://x.com/intent/post?text='
      +encodeURIComponent(text)+'&url='+encodeURIComponent(url)+'">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.8 3h3.1l-6.8 7.8 8 10.2h-6.3l-4.9-6.4L5.3 21H2.2l7.3-8.3L1.8 3h6.4l4.4 5.9L17.8 3Zm-1.1 16.2h1.7L7.4 4.7H5.6l11.1 14.5Z" fill="currentColor" stroke="none"/></svg>'
      +'Post on X</a>'
    +'<button type="button" role="menuitem" class="oa-th-share-copy">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>'
      +'<span>Copy link</span></button>'
    +(navigator.share?'<button type="button" role="menuitem" class="oa-th-share-more">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>'
      +'More…</button>':'');
  btn.parentNode.appendChild(m);
  m.querySelector('.oa-th-share-x').addEventListener('click',function(){setTimeout(closeShare,50)});
  m.querySelector('.oa-th-share-copy').addEventListener('click',function(){
    var lbl=this.querySelector('span');
    var done=function(){lbl.textContent='Link copied';setTimeout(closeShare,900)};
    if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(url).then(done,function(){prompt('Copy this link',url)});
    else prompt('Copy this link',url);
  });
  var more=m.querySelector('.oa-th-share-more');
  if(more)more.addEventListener('click',function(){
    closeShare();
    navigator.share({title:'$'+t.symbol+' is trending on OrcAgent',text:text,url:url}).catch(function(){});
  });
}
document.addEventListener('click',function(e){
  var m=document.getElementById('oa-th-share-menu');
  if(m&&!m.contains(e.target)&&!(e.target.closest&&e.target.closest('.oa-th-share')))closeShare();
});

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

// ── trending alert: arriving from it, and clearing it once seen ─────────
// The push/in-app alert links to /?trending=1#trending. Arriving that way,
// scroll the card into view (below the sticky header) and pulse it once.
var wantScroll=/(?:^|[?&])trending=1(?:&|$)/.test(location.search)||location.hash==='#trending';
var seenFor='', observer=null;
function afterRender(){
  if(wantScroll&&host){
    wantScroll=false;
    var h=host;
    // The feed above (composer, market strip, images) keeps growing for a
    // moment after load, which pushes the card down again. Re-align a few
    // times until it sits just below the header, then stop -- and stop at
    // once if the member starts scrolling themselves.
    var tries=0, userMoved=false;
    function stopOnUser(){userMoved=true}
    window.addEventListener('touchstart',stopOnUser,{passive:true,once:true});
    window.addEventListener('wheel',stopOnUser,{passive:true,once:true});
    function align(){
      if(userMoved||!document.body.contains(h))return;
      var off=h.getBoundingClientRect().top-84;
      if(Math.abs(off)>24)window.scrollTo({top:Math.max(0,window.pageYOffset+off),behavior:tries?'auto':'smooth'});
      if(++tries<6)setTimeout(align,tries===1?700:450);
    }
    setTimeout(align,120);
    h.classList.add('oa-th-focus');
    setTimeout(function(){h.classList.remove('oa-th-focus')},2400);
    try{history.replaceState(null,'',location.pathname)}catch(_){}
  }
  watchSeen();
}
// When the card is actually on screen, the alert has done its job: close
// the phone notification (same tag the server pushes with) and mark the
// in-app one read. Once per hero token.
function watchSeen(){
  if(!host||!current||seenFor===current.mint||!('IntersectionObserver' in window))return;
  if(observer)observer.disconnect();
  var mint=current.mint;
  observer=new IntersectionObserver(function(entries){
    if(!entries.some(function(e){return e.isIntersecting}))return;
    observer.disconnect();observer=null;
    if(seenFor===mint)return;
    seenFor=mint;
    clearTrendingAlert();
  },{threshold:0.5});
  observer.observe(host);
}
function clearTrendingAlert(){
  try{
    if(navigator.serviceWorker&&navigator.serviceWorker.getRegistration){
      navigator.serviceWorker.getRegistration('/sw.js').then(function(reg){
        if(!reg||!reg.getNotifications)return;
        return reg.getNotifications({tag:'orc-trending'}).then(function(list){
          list.forEach(function(n){n.close()});
        });
      }).catch(function(){});
    }
  }catch(_){}
  fetch('/api/home/trending-hero/seen',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},body:'{}'}).catch(function(){});
}
window.OrcAgentClearTrendingAlert=clearTrendingAlert;

function hide(){
  if(!host||!document.body.contains(host))return;
  if(observer){observer.disconnect();observer=null;}
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
      afterRender();
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
  // Anyone may share, signed in or not.
  if(b.classList.contains('oa-th-share')){openShare(b);return;}
  if(b.closest('.oa-th-share-menu'))return;
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
  watchTabs();
  refresh();
  setInterval(refresh,POLL_MS);
  document.addEventListener('visibilitychange',function(){if(!document.hidden)refresh()});
}
window.OrcAgentRefreshTrendingHero=refresh;
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
