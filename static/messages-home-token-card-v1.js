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
  var route=mint?'/token/'+encodeURIComponent(mint):'';
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
