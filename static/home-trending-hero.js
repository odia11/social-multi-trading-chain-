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
var POLL_MS = 20000, AUTOPLAY_MS = 6500, SLIDE_MS = 850;
var host = null, current = null, busy = false, slides = [], slideIndex = 0, autoplayTimer = null;
var sparkCache = Object.create(null), sparkLoaded = Object.create(null);

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
var CHAINS={solana:['S','#9945ff','Solana']};

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

function tokenText(t){
  var chain=CHAINS[t.chain]||[t.chain.charAt(0).toUpperCase(),'#6f7b88',t.chain];
  var up=Number(t.price_change_24h)>=0;
  var chg=(up?'+':'')+(Number(t.price_change_24h)||0).toFixed(1)+'%';
  return '<b>$'+esc(t.symbol||'?')+'</b> is trending on '+esc(chain[2])+' 🔥 '
    +'<span class="'+(up?'b':'s')+'">'+chg+'</span> in 24h with '+fmtUsd(t.volume_24h)+' volume.';
}
function slideHtml(entry,idx,clone){
  var t=entry.token,chain=CHAINS[t.chain]||[t.chain.charAt(0).toUpperCase(),'#6f7b88',t.chain];
  var up=Number(t.price_change_24h)>=0,total=(Number(t.buys_24h)+Number(t.sells_24h))||1;
  var buyPct=Math.round(Number(t.buys_24h)/total*100);
  var logo=/^https:\/\//.test(t.image_url||'')?'<img src="'+esc(t.image_url)+'" alt="" loading="lazy" decoding="async">':'';
  var banner=/^https:\/\//.test(t.banner_url||'')?t.banner_url:(/^https:\/\//.test(t.image_url||'')?t.image_url:'');
  var sym=esc(t.symbol||'?'),chg=(up?'+':'')+(Number(t.price_change_24h)||0).toFixed(1)+'%';
  return '<div class="oa-th-embed oa-th-slide'+(clone?' oa-th-clone':'')+'" data-slide-index="'+idx+'" data-mint="'+esc(t.mint)+'" data-banner="'+esc(banner)+'">'
    +'<div class="oa-th-slide-shade" aria-hidden="true"></div>'
    +'<div class="oa-th-slide-content">'
      +'<div class="oa-th-head">'
        +'<div class="oa-th-logo"><span>'+esc((t.symbol||'?').charAt(0).toUpperCase())+'</span>'+logo
          +'<b style="background:'+chain[1]+'" title="'+esc(chain[2])+'">'+esc(chain[0])+'</b></div>'
        +'<div class="oa-th-id"><strong>$'+sym+'</strong><small>'+esc(t.name||t.symbol)+'</small></div>'
        +'<div class="oa-th-px"><strong>'+fmtPrice(t.price_usd)+'</strong>'
          +'<span class="oa-th-chg '+(up?'up':'down')+'">'+(up?'↗ ':'↘ ')+chg+'</span></div>'
      +'</div>'
      +'<svg class="oa-th-spark" viewBox="0 0 300 72" preserveAspectRatio="none" aria-hidden="true"></svg>'
      +'<div class="oa-th-slide-bottom">'
        +'<div class="oa-th-stats">'
          +'<div><strong class="b">'+fmtInt(t.buys_24h)+'</strong><small>Buys</small></div>'
          +'<div><strong>'+fmtUsd(t.volume_24h)+'</strong><small>Vol · 24h</small></div>'
          +'<div><strong class="s">'+fmtInt(t.sells_24h)+'</strong><small>Sells</small></div>'
        +'</div>'
        +'<a class="oa-th-trade" href="/live-market?mint='+encodeURIComponent(t.mint)+'" aria-label="Trade $'+sym+'">Trade <span aria-hidden="true">→</span></a>'
      +'</div>'
      +'<div class="oa-th-pressure-mini"><span style="width:'+buyPct+'%"></span></div>'
    +'</div>'
  +'</div>';
}
function stopAutoplay(){if(autoplayTimer){clearInterval(autoplayTimer);autoplayTimer=null;}}
function moveVisual(index,animate){
  var track=document.getElementById('oa-th-track');if(!track)return;
  var cards=track.children,card=cards[index];if(!card)return;
  track.style.transition=animate?'transform '+SLIDE_MS+'ms cubic-bezier(.22,.72,.22,1)':'none';
  track.style.transform='translate3d(-'+card.offsetLeft+'px,0,0)';
}
function paintBackgrounds(){
  if(!host)return;
  host.querySelectorAll('.oa-th-slide').forEach(function(card){
    var url=card.dataset.banner||'';
    if(/^https:\/\//.test(url))card.style.backgroundImage='url('+JSON.stringify(url)+')';
    var img=card.querySelector('.oa-th-logo img');
    if(img)img.addEventListener('error',function(){img.remove()},{once:true});
  });
}
function sparkNodes(mint){
  if(!host)return [];
  return Array.prototype.filter.call(host.querySelectorAll('.oa-th-slide'),function(card){return card.dataset.mint===mint})
    .map(function(card){return card.querySelector('.oa-th-spark')}).filter(Boolean);
}
function paintSpark(mint){
  var html=sparkCache[mint]||'';
  sparkNodes(mint).forEach(function(svg){svg.innerHTML=html;svg.classList.toggle('empty',!html)});
}
function loadSpark(t){
  if(!t||!t.mint)return;
  if(sparkLoaded[t.mint]){paintSpark(t.mint);return;}
  sparkLoaded[t.mint]=true;
  var qs='?tf=5m'+(t.pair_address?'&pair='+encodeURIComponent(t.pair_address):'')+'&chain='+encodeURIComponent(t.chain);
  fetch('/api/chart/'+encodeURIComponent(t.mint)+qs,{credentials:'same-origin'})
    .then(function(r){return r.json()}).then(function(d){
      var c=(d&&d.candles||[]).map(function(x){return Number(x.c)}).filter(function(v){return v>0});
      var last=c[c.length-1],ratio=last/Number(t.price_usd||0);
      if(c.length<2||!(ratio<10&&ratio>0.1)){sparkCache[t.mint]='';paintSpark(t.mint);return;}
      c=c.slice(-40);var min=Math.min.apply(null,c),max=Math.max.apply(null,c);if(max===min){max*=1.01;min*=0.99}
      var pts=c.map(function(v,i){return [(i/(c.length-1))*300,6+(1-(v-min)/(max-min))*58]});
      var line=pts.map(function(p,i){return(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)}).join(' ');
      var up=Number(t.price_change_24h)>=0,col=up?'#5fd39b':'#f07178',lp=pts[pts.length-1];
      var gid='oaThG'+String(t.mint).slice(0,8).replace(/[^a-zA-Z0-9]/g,'');
      sparkCache[t.mint]='<defs><linearGradient id="'+gid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+col+'" stop-opacity=".38"/><stop offset="1" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'
        +'<path d="'+line+' L300 72 L0 72Z" fill="url(#'+gid+')"/><path d="'+line+'" fill="none" stroke="'+col+'" stroke-width="2.3" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        +'<circle cx="'+lp[0].toFixed(1)+'" cy="'+lp[1].toFixed(1)+'" r="3.5" fill="'+col+'"/>';
      paintSpark(t.mint);
    }).catch(function(){sparkLoaded[t.mint]=false});
}
function syncActive(index){
  if(!slides.length)return;
  slideIndex=Math.max(0,Math.min(index,slides.length-1));
  current=slides[slideIndex].token;
  var text=document.getElementById('oa-th-text');if(text)text.innerHTML=tokenText(current);
  var tm=document.getElementById('oa-th-time');if(tm)tm.textContent=ago(current.trending_since);
  var tag=document.getElementById('oa-th-tag-label');if(tag)tag.textContent=current.surging?'Surging':'Trending';
  renderSocial(slides[slideIndex].social);
  var dots=document.querySelectorAll('#oa-th-dots i');
  dots.forEach(function(dot,i){dot.classList.toggle('active',i===slideIndex)});
  loadSpark(current);
  if(slides.length>1)loadSpark(slides[(slideIndex+1)%slides.length].token);
}
function advance(){
  if(document.hidden||slides.length<2)return;
  var n=slides.length,next=slideIndex+1;
  if(next<n){syncActive(next);moveVisual(next,true);return;}
  // The extra first-card clone makes the last -> first movement continue left;
  // after it lands, snap invisibly back to the real first card.
  syncActive(0);moveVisual(n,true);
  setTimeout(function(){if(slides.length)moveVisual(0,false)},SLIDE_MS+40);
}
function startAutoplay(){
  stopAutoplay();
  if(slides.length<2||document.hidden)return;
  if(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  autoplayTimer=setInterval(advance,AUTOPLAY_MS);
}
function render(slideData){
  var h=ensureHost();if(!h)return;
  var previous=current&&current.mint;
  slides=(slideData||[]).filter(function(x){return x&&x.token&&x.token.mint});
  if(!slides.length){current=null;hide();return;}
  var found=slides.findIndex(function(x){return x.token.mint===previous});
  slideIndex=found>=0?found:0;current=slides[slideIndex].token;
  var cards=slides.map(function(x,i){return slideHtml(x,i,false)}).join('');
  if(slides.length>1)cards+=slideHtml(slides[0],0,true);
  h.innerHTML=
    '<div class="fc-avatar oa-th-avatar">'+ORC_MARK+'</div>'
    +'<div class="fc-body">'
      +'<div class="fc-header"><span class="fc-name">OrcAgent</span>'+VERIFIED
        +'<span class="oa-th-tag"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c1 4 5 5.5 5 11a5 5 0 0 1-10 0c0-2.5 1.2-4 2.5-5.3C9.8 10 11 10.5 11.5 12c1.3-2.6.5-6 .5-10Z"/></svg><span id="oa-th-tag-label">Trending</span></span>'
        +'<span class="fc-sep">·</span><span class="fc-time" id="oa-th-time"></span>'
        +'<span class="oa-th-live" title="Live"><i></i>LIVE</span></div>'
      +'<div class="oa-th-text" id="oa-th-text"></div>'
      +'<div class="oa-th-carousel"><div class="oa-th-track" id="oa-th-track">'+cards+'</div></div>'
      +'<div class="oa-th-dots" id="oa-th-dots">'+slides.map(function(_,i){return '<i'+(i===slideIndex?' class="active"':'')+'></i>'}).join('')+'</div>'
      +'<div class="oa-th-social" id="oa-th-social"></div>'
    +'</div>';
  paintBackgrounds();
  slides.forEach(function(x){if(sparkLoaded[x.token.mint])paintSpark(x.token.mint)});
  syncActive(slideIndex);
  requestAnimationFrame(function(){moveVisual(slideIndex,false)});
  startAutoplay();
  h.classList.remove('oa-th-leaving');
  requestAnimationFrame(function(){h.classList.add('oa-th-in')});
}

// The post's action row, in the feed's own style: icon + count.
function renderSocial(s){
  var box=document.getElementById('oa-th-social');if(!box||!s)return;
  // Reaction buttons cast/toggle the current user's vote or like. Their
  // adjacent counters are independent buttons that open the real user list.
  // No ambiguous long press, and viewing users never changes your vote.
  box.innerHTML=
    '<div class="oa-th-reaction-group">'
      +'<button type="button" class="oa-th-act oa-th-vote bull'+(s.my_vote===1?' on':'')+'" data-vote="bull" aria-pressed="'+(s.my_vote===1)+'" aria-label="Vote Bullish">'
        +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 17l6-6 4 4 7-8"/><path d="M15 7h6v6"/></svg><span>Bullish</span></button>'
      +'<button type="button" class="oa-th-people-count bull" data-people="bull" aria-label="See who voted Bullish">'+fmtInt(s.bull)+'</button>'
    +'</div>'
    +'<div class="oa-th-reaction-group">'
      +'<button type="button" class="oa-th-act oa-th-vote bear'+(s.my_vote===-1?' on':'')+'" data-vote="bear" aria-pressed="'+(s.my_vote===-1)+'" aria-label="Vote Bearish">'
        +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7l6 6 4-4 7 8"/><path d="M15 17h6v-6"/></svg><span>Bearish</span></button>'
      +'<button type="button" class="oa-th-people-count bear" data-people="bear" aria-label="See who voted Bearish">'+fmtInt(s.bear)+'</button>'
    +'</div>'
    +'<div class="oa-th-reaction-group">'
      +'<button type="button" class="oa-th-act oa-th-like'+(s.liked?' on':'')+'" aria-pressed="'+(!!s.liked)+'" aria-label="'+(s.liked?'Unlike':'Like')+'">'
        +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-8-5.4-9.4-10A5 5 0 0 1 12 6a5 5 0 0 1 9.4 5C20 15.6 12 21 12 21Z"/></svg></button>'
      +'<button type="button" class="oa-th-people-count like" data-people="like" aria-label="See who liked">'+fmtInt(s.likes)+'</button>'
    +'</div>'
    +'<button type="button" class="oa-th-act oa-th-share" aria-label="Share" aria-haspopup="menu">'
      +'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"/><path d="M7 8l5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg><span>Share</span></button>';
}

// ── real accounts behind each Bullish / Bearish / Like total ─────────────
var peopleModal=null,peopleSeq=0,peopleBusy=false,peopleNext=null;
var peopleContext=null;
function ensurePeopleModal(){
  if(peopleModal&&document.body.contains(peopleModal))return peopleModal;
  peopleModal=document.createElement('div');
  peopleModal.className='oa-th-people-overlay';
  peopleModal.hidden=true;
  peopleModal.innerHTML='<section class="oa-th-people-panel" role="dialog" aria-modal="true" aria-labelledby="oa-th-people-title">'
    +'<button type="button" class="oa-th-people-close" aria-label="Close user list">×</button>'
    +'<h2 id="oa-th-people-title">Users</h2>'
    +'<p class="oa-th-people-sub" id="oa-th-people-sub"></p>'
    +'<div class="oa-th-people-list" id="oa-th-people-list" aria-live="polite"></div>'
    +'<button type="button" class="oa-th-people-more" hidden>Load more</button>'
    +'</section>';
  document.body.appendChild(peopleModal);
  peopleModal.addEventListener('click',function(e){
    if(e.target===peopleModal||e.target.closest('.oa-th-people-close'))closePeople();
    else if(e.target.closest('.oa-th-people-more'))fetchPeople();
    else if(e.target.closest('.oa-th-person'))closePeople();
  });
  return peopleModal;
}
function closePeople(){
  if(!peopleModal)return;
  peopleModal.hidden=true;peopleSeq++;peopleContext=null;
}
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'&&peopleModal&&!peopleModal.hidden)closePeople();
});
function peopleRow(u){
  var wallet=String(u.wallet||''),name=String(u.username||wallet.slice(0,6)+'…'+wallet.slice(-4)||'User');
  var initial=esc(name.slice(0,1).toUpperCase());
  var image=String(u.avatar_url||'');
  // Photos are public and cacheable; never let an API-provided URL insert JS.
  var validImage=/^\/avatar\/(?:photo|default)\//.test(image)||/^https:\/\//.test(image);
  var img=validImage?'<img src="'+esc(image)+'" alt="" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">':'';
  var badge=u.verified?'<span class="oa-th-people-verified" aria-label="Verified">✓</span>':'';
  var handle=u.username?'@'+esc(u.username):esc(wallet.slice(0,6)+'…'+wallet.slice(-4));
  return '<a class="oa-th-person" href="/profile/'+encodeURIComponent(wallet)+'">'
    +'<span class="oa-th-person-avatar">'+initial+img+'</span>'
    +'<span class="oa-th-person-copy"><strong>'+esc(name)+badge+'</strong><small>'+handle+'</small></span>'
    +'<span class="oa-th-person-arrow" aria-hidden="true">›</span>'
    +'</a>';
}
function openPeople(kind){
  if(!current||!['bull','bear','like'].includes(kind))return;
  var modal=ensurePeopleModal(),mint=current.mint;
  peopleContext={mint:mint,kind:kind};peopleNext=0;
  peopleSeq++;peopleBusy=false;
  modal.hidden=false;
  modal.querySelector('#oa-th-people-title').textContent={bull:'Bullish voters',bear:'Bearish voters',like:'Liked by'}[kind];
  modal.querySelector('#oa-th-people-sub').textContent='Loading users…';
  modal.querySelector('#oa-th-people-list').innerHTML='<p class="oa-th-people-empty">Loading…</p>';
  modal.querySelector('.oa-th-people-more').hidden=true;
  modal.querySelector('.oa-th-people-close').focus();
  fetchPeople();
}
function fetchPeople(){
  if(!peopleContext||peopleBusy||peopleNext===null)return;
  var context=peopleContext, offset=peopleNext,seq=peopleSeq,modal=ensurePeopleModal();
  peopleBusy=true;
  modal.querySelector('.oa-th-people-more').disabled=true;
  fetch('/api/home/trending-hero/users?mint='+encodeURIComponent(context.mint)
    +'&kind='+encodeURIComponent(context.kind)+'&offset='+offset,{credentials:'same-origin'})
    .then(function(r){if(!r.ok)throw new Error('users endpoint failed');return r.json()})
    .then(function(d){
      if(seq!==peopleSeq||modal.hidden||!d.ok)return;
      var list=modal.querySelector('#oa-th-people-list');
      if(offset===0)list.innerHTML='';
      list.insertAdjacentHTML('beforeend',(d.users||[]).map(peopleRow).join(''));
      if(!d.count)list.innerHTML='<p class="oa-th-people-empty">No users yet</p>';
      modal.querySelector('#oa-th-people-sub').textContent=fmtInt(d.count)+' '+(d.count===1?'person':'people');
      peopleNext=d.next_offset;
      modal.querySelector('.oa-th-people-more').hidden=peopleNext===null;
    })
    .catch(function(){
      if(seq!==peopleSeq||modal.hidden)return;
      var list=modal.querySelector('#oa-th-people-list');
      if(offset===0)list.innerHTML='<p class="oa-th-people-empty">Could not load users. Try again.</p>';
      modal.querySelector('#oa-th-people-sub').textContent='Connection error';
      modal.querySelector('.oa-th-people-more').hidden=false;
    })
    .then(function(){
      if(seq!==peopleSeq)return;
      peopleBusy=false;modal.querySelector('.oa-th-people-more').disabled=false;
    });
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
  stopAutoplay();
  var h=host;host=null;slides=[];current=null;slideIndex=0;
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
      var incoming=(Array.isArray(d.slides)&&d.slides.length)?d.slides:(d.token?[{token:d.token,social:d.social}]:[]);
      if(!incoming.length){hide();return;}
      render(incoming);
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
  // Counters are separate from voting; guests can see the public user lists.
  if(b.dataset.people){openPeople(b.dataset.people);return;}
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
  document.addEventListener('visibilitychange',function(){
    if(document.hidden)stopAutoplay();else{refresh();startAutoplay()}
  });
  window.addEventListener('resize',function(){if(slides.length)moveVisual(slideIndex,false)},{passive:true});
}
window.OrcAgentRefreshTrendingHero=refresh;
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
