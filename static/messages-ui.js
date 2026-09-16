/* messages-premium-v3.js */
/* OrcAgent Messages Premium v3 runtime enhancements. */
(function(){
'use strict';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function fmtPct(n){n=parseFloat(n||0);return (n>=0?'+':'')+n.toFixed(2)+'%'}
function upgradeBack(){var h=document.getElementById('msgs-thread-hdr');if(!h)return;var b=h.querySelector('.msgs-back');if(!b){b=document.createElement('button');b.type='button';b.className='msgs-back';b.setAttribute('aria-label','Back to messages');b.onclick=function(){if(typeof window._backToList==='function')window._backToList()};h.insertBefore(b,h.firstChild)}else{b.setAttribute('aria-label','Back to messages')}}
function upgradeTradeCards(root){(root||document).querySelectorAll('.msg-bubble.msg-trade:not(.oa-trade-v3)').forEach(function(card){var txt=(card.innerText||card.textContent||'').replace(/\s+/g,' ').trim();var sym=(txt.match(/\$([^\s$]+)/)||[])[1]||'';var prices=txt.match(/\$([0-9][0-9.,]*(?:e[-+]?\d+)?)\s*(?:→|->)\s*\$([0-9][0-9.,]*(?:e[-+]?\d+)?)/i);var pnlm=txt.match(/([+-]\d+(?:\.\d+)?)\s*(SOL|USDC|USDG|USD)/i);var pctm=txt.match(/([+-]\d+(?:\.\d+)?)%/);if(!sym||!prices||!pctm)return;var entry='$'+prices[1],exit='$'+prices[2],pct=parseFloat(pctm[1]||0),pnl=pnlm?(pnlm[1]+' '+pnlm[2].toUpperCase()):'—';var pos=pct>=0?'pos':'neg';var holder=card.closest('[data-mint]');var mint=card.getAttribute('data-mint')||(holder&&holder.getAttribute('data-mint'))||'';var mintOk=/^(?:[1-9A-HJ-NP-Za-km-z]{32,44}|0x[a-fA-F0-9]{40})$/.test(mint);card.classList.add('oa-trade-v3');card.innerHTML='<div class="oa-dm-trade-card"><div class="oa-dm-trade-top"><div class="oa-dm-trade-token">$'+esc(sym)+'</div><div class="oa-dm-trade-pct '+pos+'">'+esc(fmtPct(pct))+'</div></div><div class="oa-dm-trade-stats"><div class="oa-dm-trade-stat"><span class="oa-dm-trade-label">Entry</span><span class="oa-dm-trade-value">'+esc(entry)+'</span></div><div class="oa-dm-trade-stat"><span class="oa-dm-trade-label">Exit</span><span class="oa-dm-trade-value">'+esc(exit)+'</span></div><div class="oa-dm-trade-stat"><span class="oa-dm-trade-label">Result</span><span class="oa-dm-trade-value oa-dm-trade-pnl '+pos+'">'+esc(pnl)+'</span></div></div><div class="oa-dm-trade-bottom"><span class="oa-dm-trade-caption">Shared trade</span><span class="oa-dm-trade-pnl '+pos+'">'+esc(fmtPct(pct))+'</span></div>'+(mintOk?'<a class="oa-dm-trade-link" href="/token/'+encodeURIComponent(mint)+'">View Trade Details →</a>':'')+'</div>'})}
function run(){upgradeBack();upgradeTradeCards(document)}
var mo=new MutationObserver(function(ms){for(var i=0;i<ms.length;i++){if(ms[i].addedNodes&&ms[i].addedNodes.length){requestAnimationFrame(run);break}}});
function start(){run();mo.observe(document.body,{childList:true,subtree:true})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

/* messages-composer-v4.js */
/* OrcAgent Messages Composer v5 — compact premium composer matching approved design. */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;

function install(){
  var bar=document.querySelector('.msgs-input-bar');
  var old=document.getElementById('msgs-input');
  if(!bar||!old||bar.classList.contains('oa-composer-v4'))return;

  var ta=document.createElement('textarea');
  ta.id='msgs-input';
  ta.className=(old.className||'msgs-input')+' oa-msgs-textarea';
  ta.placeholder='Message…';
  ta.maxLength=2000;
  ta.rows=1;
  ta.setAttribute('aria-label','Message');
  ta.value=old.value||'';
  ta.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&!e.shiftKey){
      e.preventDefault();
      if(typeof window._sendMessage==='function')window._sendMessage();
    }
  });

  var wrap=document.createElement('div');
  wrap.className='oa-compose-text-wrap';
  var counter=document.createElement('span');
  counter.className='oa-msg-counter';
  counter.textContent='0/2000';
  wrap.appendChild(ta);
  wrap.appendChild(counter);
  old.replaceWith(wrap);
  bar.classList.add('oa-composer-v4');

  function resize(){
    ta.style.height='54px';
    var h=Math.max(54,Math.min(116,ta.scrollHeight));
    ta.style.height=h+'px';
    counter.textContent=(ta.value||'').length+'/2000';
  }
  ta.addEventListener('input',resize);
  resize();

  function setTyping(on){
    document.body.classList.toggle('oa-msgs-typing',on);
    if(!on)document.documentElement.style.removeProperty('--oa-kb-offset');
    updateViewport();
  }
  function updateViewport(){
    if(!document.body.classList.contains('oa-msgs-typing'))return;
    var vv=window.visualViewport;
    if(!vv){document.documentElement.style.setProperty('--oa-kb-offset','0px');return;}
    var offset=Math.max(0,window.innerHeight-vv.height-vv.offsetTop);
    document.documentElement.style.setProperty('--oa-kb-offset',offset+'px');
    var area=document.getElementById('msgs-area');
    if(area){requestAnimationFrame(function(){area.scrollTop=area.scrollHeight;});}
  }

  ta.addEventListener('focus',function(){setTyping(true);});
  ta.addEventListener('blur',function(){setTimeout(function(){if(document.activeElement!==ta)setTyping(false);},120);});
  if(window.visualViewport){
    window.visualViewport.addEventListener('resize',updateViewport);
    window.visualViewport.addEventListener('scroll',updateViewport);
  }

  document.addEventListener('click',function(e){
    if(e.target.closest('#msgs-send,.msgs-send,.msgs-send-btn'))setTimeout(resize,60);
  });
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
var tries=0,t=setInterval(function(){tries++;install();if(document.querySelector('.msgs-input-bar.oa-composer-v4')||tries>20)clearInterval(t);},100);
})();

/* messages-thread-v5.js */
/* OrcAgent Messages Thread v5 runtime — completes approved fullscreen chat layout. */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;

function peerAvatarTemplate(){
  var hdr=document.getElementById('msgs-thread-hdr');
  if(!hdr)return null;
  var src=hdr.querySelector('.msgs-thread-avatar');
  if(!src)return null;
  var el=document.createElement('div');
  el.className='oa-peer-mini-avatar';
  var img=src.querySelector('img');
  if(img&&img.src){
    var copy=document.createElement('img');copy.src=img.src;copy.alt='';el.appendChild(copy);
  }else{
    el.style.background=src.style.background||'#111720';
    el.textContent=(src.textContent||'?').trim().slice(0,2);
  }
  return el;
}

function decorateIncoming(){
  var template=peerAvatarTemplate();
  if(!template)return;
  document.querySelectorAll('#msgs-area .msg-wrap.theirs').forEach(function(row){
    if(row.querySelector(':scope > .oa-peer-mini-avatar'))return;
    row.insertBefore(template.cloneNode(true),row.firstChild);
  });
}

function markThreadState(){
  var main=document.querySelector('.msgs-main');
  var open=!!(main&&main.classList.contains('thread-open'));
  document.body.classList.toggle('oa-thread-open',open);
  if(open)decorateIncoming();
}

function run(){markThreadState();if(document.body.classList.contains('oa-thread-open'))decorateIncoming();}
var pending=false;
var mo=new MutationObserver(function(){
  if(pending)return;
  pending=true;
  requestAnimationFrame(function(){pending=false;run();});
});
function start(){
  run();
  var main=document.querySelector('.msgs-main');
  if(main)mo.observe(main,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style']});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

/* messages-thread-v6.js */
/* OrcAgent Messages Thread v6 runtime enforcement */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;
var navDisplay='';
function isOpen(){
  var main=document.querySelector('.msgs-main');
  return !!(main&&main.classList.contains('thread-open'));
}
function setImportant(el,prop,val){if(el)el.style.setProperty(prop,val,'important')}
function clear(el,props){if(!el)return;props.forEach(function(p){el.style.removeProperty(p)})}
function sync(){
  var open=isOpen();
  document.body.classList.toggle('oa-thread-open',open);
  document.documentElement.classList.toggle('oa-thread-open',open);

  var nav=document.getElementById('oa-bottom-nav')||document.querySelector('.oa-bottom-nav');
  if(nav){
    if(open){
      if(navDisplay==='')navDisplay=nav.style.display||'';
      nav.style.setProperty('display','none','important');
      nav.setAttribute('aria-hidden','true');
    }else{
      nav.style.removeProperty('display');
      if(navDisplay)nav.style.display=navDisplay;
      nav.removeAttribute('aria-hidden');
    }
  }
  var top=document.querySelector('.pt-nb-topbar');
  if(top){if(open)top.style.setProperty('display','none','important');else top.style.removeProperty('display');}

  var app=document.getElementById('app');
  var main=document.querySelector('.msgs-main');
  var right=document.getElementById('msgs-right');
  var thread=document.getElementById('msgs-thread');
  if(open){
    setImportant(document.body,'padding-bottom','0px');
    [app,main,right].forEach(function(el){
      if(!el)return;
      setImportant(el,'position','fixed');
      setImportant(el,'top','0px');setImportant(el,'right','0px');setImportant(el,'bottom','0px');setImportant(el,'left','0px');
      setImportant(el,'width','100vw');setImportant(el,'height','100dvh');setImportant(el,'max-height','100dvh');
      setImportant(el,'margin','0px');setImportant(el,'padding','0px');setImportant(el,'overflow','hidden');
    });
    if(thread){
      setImportant(thread,'position','absolute');
      setImportant(thread,'top','0px');setImportant(thread,'right','0px');setImportant(thread,'bottom','0px');setImportant(thread,'left','0px');
      setImportant(thread,'display','flex');setImportant(thread,'flex-direction','column');setImportant(thread,'height','100%');setImportant(thread,'overflow','hidden');
    }
  }else{
    document.body.style.removeProperty('padding-bottom');
    document.documentElement.classList.remove('oa-thread-open');
    [app,main,right,thread].forEach(function(el){clear(el,['position','top','right','bottom','left','width','height','max-height','margin','padding','overflow','display','flex-direction'])});
  }
}
var pending=false;
var mo=new MutationObserver(function(){if(pending)return;pending=true;requestAnimationFrame(function(){pending=false;sync();});});
function start(){
  sync();
  var main=document.querySelector('.msgs-main');
  if(main)mo.observe(main,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style']});
  window.addEventListener('pageshow',sync);
  window.addEventListener('resize',sync);
  if(window.visualViewport){window.visualViewport.addEventListener('resize',sync);}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

/* messages-home-token-card-v1.js */
/* OrcAgent DM token/trade card v1 — align standalone Messages with Home. */
(function(){
'use strict';

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function num(v){var n=parseFloat(v);return isFinite(n)?n:0}
function price(n){n=num(n);if(!n)return '—';return n<0.001?'$'+n.toFixed(8).replace(/\.?0+$/,''):'$'+n.toFixed(6).replace(/\.?0+$/,'')}
function pctText(v){v=num(v);return (v>=0?'+':'')+v.toFixed(2)+'%'}
function pnlText(v,c){v=num(v);return (v>=0?'+':'')+v.toFixed(4)+' '+esc(c||'SOL')}

var originalRender=null;
var infoCache={};

function sharedCard(tr){
  tr=tr||{};
  var mint=String(tr.token_address||tr.mint_address||'').trim();
  /* Old DM payloads did not contain a token address. Leave those on the
     original renderer so historical conversations remain fully readable. */
  if(!mint && originalRender)return originalRender(tr);

  var sym=tr.symbol||tr.token||'?';
  var side=String(tr.side||'SELL').toUpperCase();
  var entry=num(tr.entry_price!=null?tr.entry_price:tr.entry);
  var exit=num(tr.exit_price!=null?tr.exit_price:tr.exit);
  var snapCurrent=num(tr.current_price||tr.price||exit||entry);
  var pnl=num(tr.pnl_sol!=null?tr.pnl_sol:tr.pnl);
  var pct=tr.pnl_pct!=null?num(tr.pnl_pct):(entry&&exit?((exit-entry)/entry*100):0);
  var currency=tr.pnl_currency||'SOL';
  /* Live Market owns the current token-detail experience. Passing mint uses
     its existing exact-address startup path (see live-market-pro.js's own
     ?mint= deep-link handling, the same one search/wallet/calls/push already
     use), so the right token opens immediately without ever visiting the
     retired standalone /token page. This used to pass addr= -- the retired
     live_market.html's param name, silently ignored by the page that
     actually replaced it, so tapping this card opened a blank Live Market. */
  var route=mint?'/live-market?mint='+encodeURIComponent(mint):'';
  var sideClass=side==='BUY'?'buy':'sell';
  var pnlClass=pct>=0?'pos':'neg';

  return '<div class="dm-home-token-card '+pnlClass+'" data-mint="'+esc(mint)+'" data-route="'+esc(route)+'" data-entry="'+esc(entry)+'" data-snapshot-current="'+esc(snapCurrent)+'" role="link" tabindex="0">'
    +'<div class="dm-home-token-banner" data-cc="banner"></div>'
    +'<div class="dm-home-token-shade"></div>'
    +'<div class="dm-home-token-content">'
      +'<div class="dm-home-token-main">'
        +'<div class="dm-home-token-left">'
          +'<div class="dm-home-token-title-row">'
            +'<span class="dm-home-token-side '+sideClass+'">'+esc(side)+'</span>'
            +'<span class="dm-home-token-symbol">$'+esc(sym)+'</span>'
          +'</div>'
          +'<div class="dm-home-token-prices">'
            +'<span><b>Entry</b> '+price(entry)+'</span>'
            +'<span class="dm-home-token-dot">•</span>'
            +'<span><b>Now</b> <em data-dm-live-price>'+price(snapCurrent)+'</em></span>'
          +'</div>'
          +'<div class="dm-home-token-pnl">'+pnlText(pnl,currency)+'</div>'
        +'</div>'
        +'<div class="dm-home-token-pct '+pnlClass+'">'+pctText(pct)+'</div>'
      +'</div>'
      +'<div class="dm-home-token-footer">'
        +'<span>View token</span><span aria-hidden="true">→</span>'
      +'</div>'
    +'</div>'
  +'</div>';
}

function hydrateCard(card){
  if(!card||card.dataset.dmHydrated==='1')return;
  card.dataset.dmHydrated='1';
  var mint=card.dataset.mint||'';
  var route=card.dataset.route||'';
  if(route){
    card.addEventListener('click',function(e){if(e.target.closest('button,a,input'))return;window.location.href=route;});
    card.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();window.location.href=route;}});
  }
  if(!mint)return;
  function apply(info){
    if(!info)return;
    var banner=card.querySelector('[data-cc="banner"]');
    if(banner&&info.banner_url)banner.style.backgroundImage='url("'+String(info.banner_url).replace(/"/g,'%22')+'")';
    var px=card.querySelector('[data-dm-live-price]');
    var live=num(info.price_usd!=null?info.price_usd:info.price);
    if(px&&live)px.textContent=price(live);
  }
  if(Object.prototype.hasOwnProperty.call(infoCache,mint)){apply(infoCache[mint]);return;}
  fetch('/api/token/info/'+encodeURIComponent(mint),{credentials:'include'})
    .then(function(r){return r.ok?r.json():null})
    .then(function(info){infoCache[mint]=(info&&info.ok)?info:null;apply(infoCache[mint]);})
    .catch(function(){infoCache[mint]=null;});
}

function hydrateAll(root){
  (root||document).querySelectorAll('.dm-home-token-card').forEach(hydrateCard);
}

function install(){
  if(typeof window._renderDmTokenCard!=='function')return false;
  if(window._renderDmTokenCard.__oaHomeCardV1)return true;
  originalRender=window._renderDmTokenCard;
  window._renderDmTokenCard=sharedCard;
  window._renderDmTokenCard.__oaHomeCardV1=true;

  /* The page already calls _hydrateDmTradeCards after every render. Extend
     that hook instead of replacing message rendering/copy-trade logic. */
  var oldHydrate=typeof window._hydrateDmTradeCards==='function'?window._hydrateDmTradeCards:null;
  window._hydrateDmTradeCards=function(area){
    if(oldHydrate){try{oldHydrate(area)}catch(e){}}
    hydrateAll(area||document);
  };
  hydrateAll(document);
  return true;
}

var tries=0,t=setInterval(function(){tries++;if(install()||tries>60)clearInterval(t)},50);
var mo=new MutationObserver(function(ms){for(var i=0;i<ms.length;i++){if(ms[i].addedNodes&&ms[i].addedNodes.length){requestAnimationFrame(function(){hydrateAll(document)});break;}}});
function start(){install();mo.observe(document.body,{childList:true,subtree:true});hydrateAll(document);}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
