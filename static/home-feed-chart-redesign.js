/* OrcAgent Home feed chart-card redesign.
 * Rebuilds existing __CHART__ cards into the approved compact premium layout
 * while preserving the data-cc hooks used by the existing live updater.
 */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/')return;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function num(v){var n=Number(v);return isFinite(n)?n:null}
function fmtMoney(v){var n=num(v);if(n==null)return '—';if(Math.abs(n)>=1e9)return '$'+(n/1e9).toFixed(2)+'B';if(Math.abs(n)>=1e6)return '$'+(n/1e6).toFixed(2)+'M';if(Math.abs(n)>=1e3)return '$'+Math.round(n).toLocaleString('en-US');return '$'+n.toFixed(2)}
function fmtPrice(v){var n=num(v);if(!n)return '—';if(n>=1)return '$'+n.toFixed(2);if(n>=.01)return '$'+n.toFixed(4);if(n>=.001)return '$'+n.toFixed(6);return '$'+n.toFixed(8).replace(/0+$/,'').replace(/\.$/,'')}
function fmtPct(v){var n=num(v);return n==null?'—':(n>=0?'+':'')+n.toFixed(2)+'%'}
function chainLabel(c){c=String(c||'').toLowerCase();return {solana:'SOLANA',bsc:'BNB CHAIN',base:'BASE',arbitrum:'ARBITRUM',polygon:'POLYGON',robinhood:'ROBINHOOD'}[c]||String(c||'CHAIN').toUpperCase()}
function shortPair(s){s=String(s||'');return s.length>14?s.slice(0,7)+'…'+s.slice(-5):s||'—'}
function pctChip(label,v){var n=num(v),cl=n!=null&&n<0?' neg':'';return '<div class="oa-fc-pct'+cl+'"><span>'+esc(label)+'</span><br><b>'+esc(fmtPct(v))+'</b></div>'}
function parseData(card){var host=card.closest('[data-post-content]'),raw=host&&host.getAttribute('data-post-content')||'',i=raw.indexOf('__CHART__');if(i<0)return null;try{return JSON.parse(raw.slice(i+9))}catch(_){return null}}
function render(card,c){
  if(!card||card.dataset.oaChartV2==='1')return;
  card.dataset.oaChartV2='1';card.classList.add('oa-feed-chart-v2');
  var buys=num(c.buys)||0,sells=num(c.sells)||0,total=buys+sells,bpct=total?Math.max(0,Math.min(100,buys/total*100)):50;
  var sym=String(c.symbol||'?'),name=String(c.name||''),chain=chainLabel(c.chain),dex=String(c.dexId||c.dex||'').toUpperCase(),banner=c.banner||'',image=c.image||'',pair=c.pairAddress||'';
  card.innerHTML=''
    +'<div class="oa-fc-hero"><div class="oa-fc-banner" data-cc="banner"'+(banner?' style="background-image:url(\''+esc(banner)+'\')"':'')+'></div><div class="oa-fc-hero-shade"></div><div class="oa-fc-chain"><span class="oa-fc-chain-dot"></span><span data-cc="chain">'+esc(chain)+'</span></div></div>'
    +'<div class="oa-fc-head"><div class="oa-fc-logo" data-cc="logo">'+(image?'<img src="'+esc(image)+'" alt="" onerror="this.remove()">':esc(sym.slice(0,2).toUpperCase()))+'</div><div class="oa-fc-title"><div class="oa-fc-symbol">$'+esc(sym)+'</div><div class="oa-fc-subrow"><span class="oa-fc-name">'+esc(name)+'</span>'+(dex?'<span class="oa-fc-tag">'+esc(dex)+'</span>':'')+'</div></div></div>'
    +'<div class="oa-fc-main"><div class="oa-fc-price-row"><div><div class="oa-fc-price" data-cc="price">'+esc(fmtPrice(c.price))+'</div><div class="oa-fc-change '+((num(c.chg24h)||0)<0?'neg':'')+'" data-cc="chg">'+esc(fmtPct(c.chg24h))+' <small>(24h)</small></div></div><svg class="oa-fc-spark" viewBox="0 0 220 44" preserveAspectRatio="none" aria-hidden="true"><polyline data-cc="line" points="" fill="none" stroke="#36d7a0" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
    +'<div class="oa-fc-stats"><div class="oa-fc-stat"><div class="oa-fc-stat-label">24H Volume</div><div class="oa-fc-stat-value" data-cc="vol">'+esc(fmtMoney(c.vol24h))+'</div></div><div class="oa-fc-stat"><div class="oa-fc-stat-label">Liquidity</div><div class="oa-fc-stat-value" data-cc="liq">'+esc(fmtMoney(c.liq))+'</div></div><div class="oa-fc-stat"><div class="oa-fc-stat-label">Market Cap</div><div class="oa-fc-stat-value" data-oa="mcap">'+esc(fmtMoney(c.marketCap))+'</div></div><div class="oa-fc-stat"><div class="oa-fc-stat-label">FDV</div><div class="oa-fc-stat-value" data-oa="fdv">'+esc(fmtMoney(c.fdv))+'</div></div><div class="oa-fc-flow"><div class="oa-fc-flow-top"><div><div class="oa-fc-flow-label">Buys / Sells (24h)</div><div class="oa-fc-flow-values"><span class="oa-fc-buys" data-cc="buys">'+buys+'</span><span> / </span><span class="oa-fc-sells" data-cc="sells">'+sells+'</span></div></div><div class="oa-fc-flow-label"><span class="oa-fc-buys">'+Math.round(bpct)+'%</span> / <span class="oa-fc-sells">'+Math.round(100-bpct)+'%</span></div></div><div class="oa-fc-bar"><span data-cc="buysbar" style="width:'+bpct.toFixed(1)+'%"></span></div></div></div>'
    +'<div class="oa-fc-pcts">'+pctChip('5m',c.chg5m)+pctChip('1h',c.chg1h)+pctChip('6h',c.chg6h)+pctChip('24h',c.chg24h)+'</div><div class="oa-fc-pair"><span>PAIR</span><code>'+esc(shortPair(pair))+'</code><span style="margin-left:auto">⧉</span></div><div class="oa-fc-cta">▥ <span>View Token</span> <span>›</span></div></div>';
  hydrateStatic(card,c);
}
function hydrateStatic(card,c){var mint=c&&c.mint;if(!mint)return;fetch('/api/token/info/'+encodeURIComponent(mint),{credentials:'include'}).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(info){if(!info)return;var m=card.querySelector('[data-oa="mcap"]'),f=card.querySelector('[data-oa="fdv"]');if(m&&info.market_cap!=null)m.textContent=fmtMoney(info.market_cap);if(f&&info.fdv!=null)f.textContent=fmtMoney(info.fdv);var banner=card.querySelector('[data-cc="banner"]');if(banner&&info.banner_url&&!banner.style.backgroundImage)banner.style.backgroundImage='url("'+String(info.banner_url).replace(/"/g,'%22')+'")';var logo=card.querySelector('[data-cc="logo"]');if(logo&&info.image_url&&!logo.querySelector('img'))logo.innerHTML='<img src="'+esc(info.image_url)+'" alt="">';var tag=card.querySelector('.oa-fc-tag');if(!tag&&info.dex_name){var row=card.querySelector('.oa-fc-subrow');if(row)row.insertAdjacentHTML('beforeend','<span class="oa-fc-tag">'+esc(String(info.dex_name).toUpperCase())+'</span>')}}).catch(function(){})}
function apply(root){(root||document).querySelectorAll('[id^="cc-"][data-chart-sym]').forEach(function(card){var d=parseData(card);if(d)render(card,d)})}
function boot(){apply(document);try{new MutationObserver(function(ms){ms.forEach(function(m){m.addedNodes.forEach(function(n){if(n.nodeType===1){if(n.matches&&n.matches('[id^="cc-"][data-chart-sym]')){var d=parseData(n);if(d)render(n,d)}apply(n)}})})}).observe(document.body,{childList:true,subtree:true})}catch(_){}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
