/* OrcAgent shared token/trade card v2.
   One renderer for standalone surfaces (Groups, Messages and future pages).
   Home remains the reference surface; legacy records without a mint fall back
   to the page's original renderer so old posts/conversations stay readable. */
(function(){
'use strict';
if(window.OrcAgentTradeCard && window.OrcAgentTradeCard.version>=2)return;

var infoCache={};
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function num(v){var n=parseFloat(v);return isFinite(n)?n:0}
function first(o,keys,def){for(var i=0;i<keys.length;i++){var v=o&&o[keys[i]];if(v!==undefined&&v!==null&&v!=='')return v}return def}
function fmtPrice(v){var n=num(v);if(!n)return '—';if(n<0.000001)return '$'+n.toFixed(10).replace(/\.?0+$/,'');if(n<0.001)return '$'+n.toFixed(8).replace(/\.?0+$/,'');return '$'+n.toFixed(6).replace(/\.?0+$/,'')}
function fmtPct(v){var n=num(v);return (n>=0?'+':'')+n.toFixed(2)+'%'}
function fmtPnl(v,c){var n=num(v),cur=String(c||'SOL').toUpperCase();return (n>=0?'+':'')+n.toFixed(4)+' '+esc(cur)}

function normalize(raw){
  raw=raw||{};
  var t=(raw.trade&&typeof raw.trade==='object')?Object.assign({},raw,raw.trade):raw;
  var mint=String(first(t,['token_address','mint_address','mint','address','token_mint'],'')||'').trim();
  var symbol=String(first(t,['symbol','token_symbol','ticker','token'],'?')||'?').replace(/^\$/,'');
  var side=String(first(t,['side','action','trade_side','type'],'SELL')||'SELL').toUpperCase();
  if(side!=='BUY'&&side!=='SELL') side=num(first(t,['pnl_pct','pnl_percent'],0))>=0?'SELL':'SELL';
  var entry=num(first(t,['entry_price','entry','buy_price','price_in'],0));
  var exit=num(first(t,['exit_price','exit','sell_price','price_out'],0));
  var current=num(first(t,['current_price','live_price','price','now_price'],exit||entry));
  var pnl=num(first(t,['pnl_sol','pnl_value','pnl','profit'],0));
  var pctRaw=first(t,['pnl_pct','pnl_percent','profit_pct','percentage'],null);
  var pct=pctRaw!==null?num(pctRaw):(entry&&(exit||current)?(((exit||current)-entry)/entry*100):0);
  var currency=String(first(t,['pnl_currency','currency'],'SOL')||'SOL');
  var chain=String(first(t,['chain','chain_id'],'solana')||'solana');
  var banner=String(first(t,['banner_url','token_banner','image_url','banner'],'')||'');
  return {raw:t,mint:mint,symbol:symbol,side:side,entry:entry,exit:exit,current:current,pnl:pnl,pct:pct,currency:currency,chain:chain,banner:banner};
}

function render(raw,fallback){
  var t=normalize(raw);
  if(!t.mint){return typeof fallback==='function'?fallback(raw):''}
  var route='/live-market?addr='+encodeURIComponent(t.mint);
  var pos=t.pct>=0, side=t.side==='BUY'?'buy':'sell';
  return '<div class="oa-stc '+(pos?'pos':'neg')+'" data-oa-stc="1" data-mint="'+esc(t.mint)+'" data-route="'+esc(route)+'" data-entry="'+esc(t.entry)+'" data-current="'+esc(t.current)+'" data-chain="'+esc(t.chain)+'" role="link" tabindex="0">'
    +'<div class="oa-stc-banner" data-oa-stc-banner'+(t.banner?' style="background-image:url(\''+esc(t.banner).replace(/'/g,'%27')+'\')"':'')+'></div>'
    +'<div class="oa-stc-shade"></div>'
    +'<div class="oa-stc-content">'
      +'<div class="oa-stc-main">'
        +'<div class="oa-stc-left">'
          +'<div class="oa-stc-title"><span class="oa-stc-side '+side+'">'+esc(t.side)+'</span><strong>$'+esc(t.symbol)+'</strong></div>'
          +'<div class="oa-stc-prices"><span><b>Entry</b> '+fmtPrice(t.entry)+'</span><span>•</span><span><b>Now</b> <em data-oa-stc-live>'+fmtPrice(t.current)+'</em></span></div>'
          +'<div class="oa-stc-pnl">'+fmtPnl(t.pnl,t.currency)+'</div>'
        +'</div>'
        +'<div class="oa-stc-pct '+(pos?'pos':'neg')+'">'+fmtPct(t.pct)+'</div>'
      +'</div>'
      +'<div class="oa-stc-footer"><span>View token</span><span aria-hidden="true">→</span></div>'
    +'</div>'
  +'</div>';
}

function applyInfo(card,info){
  if(!card||!info)return;
  var banner=card.querySelector('[data-oa-stc-banner]');
  var bannerUrl=info.banner_url||info.banner||info.image_url||'';
  if(banner&&bannerUrl)banner.style.backgroundImage='url("'+String(bannerUrl).replace(/"/g,'%22')+'")';
  var px=card.querySelector('[data-oa-stc-live]');
  var live=num(info.price_usd!=null?info.price_usd:info.price);
  if(px&&live)px.textContent=fmtPrice(live);
}
function hydrate(card){
  if(!card||card.dataset.oaStcHydrated==='1')return;
  card.dataset.oaStcHydrated='1';
  var route=card.dataset.route||'', mint=card.dataset.mint||'';
  function go(e){if(e&&e.target&&e.target.closest&&e.target.closest('button,a,input,textarea,select'))return;if(route)window.location.href=route}
  card.addEventListener('click',go);
  card.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();go(e)}});
  if(!mint)return;
  if(Object.prototype.hasOwnProperty.call(infoCache,mint)){applyInfo(card,infoCache[mint]);return}
  fetch('/api/token/info/'+encodeURIComponent(mint),{credentials:'include'})
    .then(function(r){return r.ok?r.json():null})
    .then(function(d){infoCache[mint]=(d&&d.ok)?d:null;applyInfo(card,infoCache[mint])})
    .catch(function(){infoCache[mint]=null});
}
function hydrateAll(root){(root||document).querySelectorAll('[data-oa-stc="1"]').forEach(hydrate)}

var originals={};
function patch(name){
  var fn=window[name];
  if(typeof fn!=='function'||fn.__oaSharedTradeCardV2)return false;
  originals[name]=originals[name]||fn;
  var original=originals[name];
  var wrapped=function(t){return render(t,original)};
  wrapped.__oaSharedTradeCardV2=true;
  window[name]=wrapped;
  return true;
}
function install(){
  patch('_renderTradeCardHtml');     // Groups / group composer previews
  patch('_renderDmTokenCard');       // standalone Messages
  // Do not replace Home's _renderTradeTerminalCard: Home is the visual and
  // behavioural reference and contains extra feed-only actions. Other pages
  // now converge on its current compact/banner language without risking those.
  hydrateAll(document);
}

window.OrcAgentTradeCard={version:2,render:render,normalize:normalize,hydrate:hydrate,hydrateAll:hydrateAll};
var tries=0,t=setInterval(function(){tries++;install();if(tries>80)clearInterval(t)},50);
var mo=new MutationObserver(function(ms){for(var i=0;i<ms.length;i++){if(ms[i].addedNodes&&ms[i].addedNodes.length){requestAnimationFrame(function(){hydrateAll(document)});break}}});
function start(){install();if(document.body)mo.observe(document.body,{childList:true,subtree:true});hydrateAll(document)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
