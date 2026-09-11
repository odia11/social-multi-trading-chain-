/* OrcAgent mobile Home composition. Reuses existing dashboard functionality. */
(function(){
'use strict';
var path=location.pathname.replace(/\/+$/,'')||'/';
if(path!=='/' || !window.matchMedia('(max-width:767px)').matches) return;
function money(v){var n=Number(v||0);if(!isFinite(n))n=0;return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(n)}
function num(v){var n=Number(v||0);return isFinite(n)?n:0}
function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn);else fn()}
function insertAfter(node,ref){if(!ref||!ref.parentNode)return;ref.parentNode.insertBefore(node,ref.nextSibling)}

function hero(){
 var wrap=document.querySelector('.wrap');if(!wrap||document.getElementById('oa-m-hero'))return;
 var el=document.createElement('section');el.className='oa-m-hero';el.id='oa-m-hero';
 el.innerHTML='<div class="oa-m-icon" aria-hidden="true"><span class="oa-m-triangle"></span></div>'
  +'<div class="oa-m-hero-copy"><h1>Smarter Trading.<br><span>Stronger Together.</span></h1>'
  +'<p>AI-powered trading, social insights and real-time opportunities — all inside OrcAgent.</p>'
  +'<a class="oa-m-primary" href="/live-market">Start Trading <span>→</span></a></div>';
 wrap.insertBefore(el,wrap.firstChild);
}

function bot(){
 var wrap=document.querySelector('.wrap');if(!wrap||document.getElementById('oa-m-bot'))return;
 var el=document.createElement('section');el.className='oa-m-bot';el.id='oa-m-bot';
 el.innerHTML='<div class="oa-m-bot-ic">AI</div><div class="oa-m-bot-main"><div class="oa-m-bot-title">AI Bot <span class="oa-m-bot-dot" id="oa-m-bot-dot"></span></div><div class="oa-m-bot-state-line">Status: <span class="oa-m-bot-state" id="oa-m-bot-state">checking…</span></div><div class="oa-m-bot-meta"><span id="oa-m-bot-ready">$0.00 capital</span><span>•</span><span id="oa-m-bot-open">0 open trades</span><span>•</span><span id="oa-m-bot-pnl">PnL —</span></div></div><a class="oa-m-bot-btn" href="/bot">Open AI Bot →</a>';
 insertAfter(el,document.getElementById('oa-m-hero'));
 fetch('/api/bot/status',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){
   var running=!!(d&&(d.running||d.status==='running'));var state=document.getElementById('oa-m-bot-state'),dot=document.getElementById('oa-m-bot-dot');
   if(state){state.textContent=running?'Running':'Idle';state.classList.toggle('running',running)}if(dot)dot.classList.toggle('running',running);
   var open=d&&((d.open_positions!=null&&d.open_positions)||(d.positions_open!=null&&d.positions_open));if(open!=null)document.getElementById('oa-m-bot-open').textContent=open+' open trade'+(Number(open)===1?'':'s');
   var pnl=d&&(d.pnl_usd!=null?d.pnl_usd:(d.total_pnl_usd!=null?d.total_pnl_usd:null));if(pnl!=null)document.getElementById('oa-m-bot-pnl').textContent='PnL '+money(pnl);
 }).catch(function(){var s=document.getElementById('oa-m-bot-state');if(s)s.textContent='Idle'});
 fetch('/api/wallet/usdc-summary',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){if(d&&d.ok&&document.getElementById('oa-m-bot-ready'))document.getElementById('oa-m-bot-ready').textContent=money(d.total_usdc)+' capital'}).catch(function(){});
}

function portfolio(){
 var anchor=document.getElementById('oa-m-bot');if(!anchor||document.getElementById('oa-m-portfolio'))return;
 var p=document.createElement('section');p.className='oa-m-portfolio';p.id='oa-m-portfolio';
 p.innerHTML='<div class="oa-m-pf-main"><div><div class="oa-m-pf-kicker">Total Portfolio Value</div><div class="oa-m-pf-value" id="oa-m-pf-value">$0.00</div></div><div class="oa-m-pf-spark">⌁</div><a class="oa-m-pf-open" href="/wallet">View Portfolio →</a></div><div class="oa-m-pf-split"><div class="oa-m-pf-chip"><b>USDC</b><span id="oa-m-pf-usdc">$0.00</span></div><div class="oa-m-pf-chip"><b>SOL</b><span id="oa-m-pf-sol">$0.00</span></div><div class="oa-m-pf-chip"><b>Other</b><span id="oa-m-pf-other">$0.00</span></div></div>';
 insertAfter(p,anchor);
 Promise.allSettled([fetch('/api/wallet/usdc-summary',{credentials:'include'}).then(function(r){return r.json()}),fetch('/api/wallet/tokens',{credentials:'include'}).then(function(r){return r.json()}),fetch('/api/wallet/balance',{credentials:'include'}).then(function(r){return r.json()})]).then(function(res){var s=res[0].status==='fulfilled'?res[0].value||{}:{};var t=res[1].status==='fulfilled'?res[1].value||{}:{};var b=res[2].status==='fulfilled'?res[2].value||{}:{};var usdc=num(s.total_usdc!=null?s.total_usdc:s.total);var solValue=num(b.sol)*num(b.sol_price||s.sol_price);var tokens=Array.isArray(t.tokens)?t.tokens:[];var other=tokens.reduce(function(sum,x){var sym=String(x.symbol||x.ticker||'').toUpperCase();if(sym==='USDC'||sym==='USDT'||sym==='SOL')return sum;var v=x.usd_value;if(v==null)v=x.value_usd;if(v==null)v=num(x.balance||x.amount)*num(x.price_usd||x.price);return sum+num(v)},0);var total=usdc+solValue+other;document.getElementById('oa-m-pf-value').textContent=money(total);document.getElementById('oa-m-pf-usdc').textContent=money(usdc);document.getElementById('oa-m-pf-sol').textContent=money(solValue);document.getElementById('oa-m-pf-other').textContent=money(other)}).catch(function(){});
}

function market(){
 var anchor=document.getElementById('oa-m-portfolio');if(!anchor||document.getElementById('oa-m-market'))return;
 var m=document.createElement('section');m.className='oa-m-market';m.id='oa-m-market';
 m.innerHTML='<div class="oa-m-card-head"><div class="oa-m-card-title">Live Market</div><a href="/live-market">View all →</a></div><div class="oa-m-market-list" id="oa-m-market-list"><div class="oa-m-market-tile"><b>Loading…</b><span>Live market data</span></div></div>';
 insertAfter(m,anchor);
 fetch('/api/dexscreener/search?q=solana',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){var pairs=(d&&d.pairs)||[];var seen={};var rows=[];pairs.forEach(function(p){var sym=(p.baseToken&&p.baseToken.symbol)||'';var addr=(p.baseToken&&p.baseToken.address)||'';if(!sym||!addr||seen[addr]||rows.length>=3)return;seen[addr]=1;var ch=Number(p.priceChange&&p.priceChange.h24);if(!isFinite(ch))ch=0;rows.push('<button class="oa-m-market-tile" data-mint="'+addr+'"><b>$'+sym+'</b><span>'+((p.chainId||'market').toUpperCase())+'</span><strong style="color:'+(ch>=0?'#3ad29b':'#f76b62')+'">'+(ch>=0?'+':'')+ch.toFixed(1)+'%</strong></button>')});var list=document.getElementById('oa-m-market-list');if(!list)return;list.innerHTML=rows.join('')||'<a class="oa-m-market-tile" href="/live-market"><b>Live Market</b><span>Explore tokens</span><strong>→</strong></a>';list.addEventListener('click',function(e){var row=e.target.closest('[data-mint]');if(row&&row.dataset.mint)location.href='/live-market?mint='+encodeURIComponent(row.dataset.mint)});}).catch(function(){});
}

function shortcuts(){
 var composer=document.getElementById('feed-composer');var anchor=document.getElementById('oa-m-market');if(!composer||!anchor||document.getElementById('oa-m-shortcuts'))return;
 var el=document.createElement('nav');el.className='oa-m-shortcuts';el.id='oa-m-shortcuts';el.setAttribute('aria-label','OrcAgent shortcuts');
 el.innerHTML='<a class="oa-m-shortcut" href="/live-market"><span>🔥</span><span>Live Market</span></a><a class="oa-m-shortcut" href="/live-market"><span>⇄</span><span>Trade</span></a><a class="oa-m-shortcut" href="/wallet"><span>▣</span><span>Portfolio</span></a><a class="oa-m-shortcut" href="/"><span>◎</span><span>Social</span></a><a class="oa-m-shortcut" href="/groups"><span>♙</span><span>Groups</span></a>';
 insertAfter(el,anchor);
 el.insertAdjacentElement('afterend',composer);
 var lab=document.createElement('div');lab.className='oa-m-feed-label';lab.id='oa-m-feed-label';lab.innerHTML='<b>For You</b><span>Following</span><span>Trends</span>';composer.insertAdjacentElement('afterend',lab);
}

ready(function(){
 document.body.classList.add('oa-home-mobile');
 hero();bot();portfolio();market();shortcuts();
});
})();
