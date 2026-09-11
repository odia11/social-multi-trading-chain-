/* OrcAgent mobile Home composition. Reuses existing dashboard functionality. */
(function(){
'use strict';
var path=location.pathname.replace(/\/+$/,'')||'/';
if(path!=='/' || !window.matchMedia('(max-width:767px)').matches) return;
function money(v){var n=Number(v||0);if(!isFinite(n))n=0;return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(n)}
function num(v){var n=Number(v||0);return isFinite(n)?n:0}
function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn);else fn()}

function hero(){
 var wrap=document.querySelector('.wrap');if(!wrap||document.getElementById('oa-m-hero'))return;
 var el=document.createElement('section');el.className='oa-m-hero';el.id='oa-m-hero';
 el.innerHTML='<div class="oa-m-icon" aria-hidden="true"><span class="oa-m-triangle"></span></div>'
  +'<h1>Smarter Trading.<br><span>Stronger Together.</span></h1>'
  +'<p>AI-powered trading, social insights and real-time opportunities — all inside OrcAgent.</p>'
  +'<a class="oa-m-primary" href="/live-market">Start Trading <span>→</span></a>';
 wrap.insertBefore(el,wrap.firstChild);
}
function bot(){
 var wrap=document.querySelector('.wrap');if(!wrap||document.getElementById('oa-m-bot'))return;
 var el=document.createElement('section');el.className='oa-m-bot';el.id='oa-m-bot';
 el.innerHTML='<div class="oa-m-bot-ic">AI</div><div class="oa-m-bot-main"><div class="oa-m-bot-title">Your bot is <span class="oa-m-bot-state" id="oa-m-bot-state">checking…</span><span class="oa-m-bot-dot" id="oa-m-bot-dot"></span></div><div class="oa-m-bot-meta"><span id="oa-m-bot-ready">$0.00 ready</span><span>•</span><span id="oa-m-bot-open">— open</span><span>•</span><span id="oa-m-bot-pnl">PnL —</span></div></div><a class="oa-m-bot-btn" href="/bot">Open AI Bot →</a>';
 var heroEl=document.getElementById('oa-m-hero');if(heroEl&&heroEl.nextSibling)wrap.insertBefore(el,heroEl.nextSibling);else wrap.appendChild(el);
 fetch('/api/bot/status',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){
   var running=!!(d&&(d.running||d.status==='running'));var state=document.getElementById('oa-m-bot-state'),dot=document.getElementById('oa-m-bot-dot');
   if(state){state.textContent=running?'running':'idle';state.classList.toggle('running',running)}if(dot)dot.classList.toggle('running',running);
   var open=d&&((d.open_positions!=null&&d.open_positions)||(d.positions_open!=null&&d.positions_open));if(open!=null)document.getElementById('oa-m-bot-open').textContent=open+' open';
   var pnl=d&&(d.pnl_usd!=null?d.pnl_usd:(d.total_pnl_usd!=null?d.total_pnl_usd:null));if(pnl!=null)document.getElementById('oa-m-bot-pnl').textContent='PnL '+money(pnl);
 }).catch(function(){var s=document.getElementById('oa-m-bot-state');if(s)s.textContent='idle'});
 fetch('/api/wallet/usdc-summary',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){if(d&&d.ok&&document.getElementById('oa-m-bot-ready'))document.getElementById('oa-m-bot-ready').textContent=money(d.total_usdc)+' ready'}).catch(function(){});
}
function shortcuts(){
 var composer=document.getElementById('feed-composer');if(!composer||document.getElementById('oa-m-shortcuts'))return;
 var el=document.createElement('nav');el.className='oa-m-shortcuts';el.id='oa-m-shortcuts';el.setAttribute('aria-label','OrcAgent shortcuts');
 el.innerHTML='<a class="oa-m-shortcut" href="/live-market"><span>🔥</span><span>Live Market</span></a>'
 +'<a class="oa-m-shortcut" href="/live-market"><span>⇄</span><span>Trade</span></a>'
 +'<a class="oa-m-shortcut" href="/wallet"><span>▣</span><span>Portfolio</span></a>'
 +'<a class="oa-m-shortcut" href="/"><span>◎</span><span>Social</span></a>'
 +'<a class="oa-m-shortcut" href="/groups"><span>♙</span><span>Groups</span></a>';
 composer.insertAdjacentElement('afterend',el);
 var lab=document.createElement('div');lab.className='oa-m-feed-label';lab.innerHTML='<b>For You</b><span>Following</span><span>Trends</span>';el.insertAdjacentElement('afterend',lab);
}
function marketAndPortfolio(){
 var wrap=document.querySelector('.wrap');if(!wrap)return;
 if(!document.getElementById('oa-m-market')){
   var m=document.createElement('section');m.className='oa-m-market';m.id='oa-m-market';m.innerHTML='<div class="oa-m-card-head"><div class="oa-m-card-title"><i>🔥</i>Live Market</div><a href="/live-market">View all →</a></div><div class="oa-m-market-tabs"><span class="oa-m-pill active">Trending</span><span class="oa-m-pill">New Pairs</span><span class="oa-m-pill">Gainers</span><span class="oa-m-pill">Losers</span></div><div class="oa-m-market-list" id="oa-m-market-list"><div class="oa-m-market-row"><div><div class="oa-m-market-name">Loading market…</div><div class="oa-m-market-sub">Live OrcAgent market data</div></div><div class="oa-m-market-pct">—</div></div></div>';
   wrap.appendChild(m);
   fetch('/api/dexscreener/search?q=solana',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){var pairs=(d&&d.pairs)||[];var list=document.getElementById('oa-m-market-list');if(!list)return;list.innerHTML=pairs.slice(0,3).map(function(p){var sym=(p.baseToken&&p.baseToken.symbol)||'Token';var ch=Number(p.priceChange&&p.priceChange.h24);if(!isFinite(ch))ch=0;var addr=(p.baseToken&&p.baseToken.address)||'';return '<div class="oa-m-market-row" data-mint="'+addr+'"><div><div class="oa-m-market-name">$'+sym+'</div><div class="oa-m-market-sub">'+((p.chainId||'market').toUpperCase())+'</div></div><div class="oa-m-market-pct" style="color:'+(ch>=0?'#3ad29b':'#f76b62')+'">'+(ch>=0?'+':'')+ch.toFixed(1)+'%</div></div>'}).join('')||'<div class="oa-m-market-row"><div><div class="oa-m-market-name">Open Live Market</div><div class="oa-m-market-sub">See trending tokens</div></div><div class="oa-m-market-pct">→</div></div>';list.addEventListener('click',function(e){var row=e.target.closest('[data-mint]');if(row&&row.dataset.mint)location.href='/live-market?mint='+encodeURIComponent(row.dataset.mint)});}).catch(function(){});
 }
 if(!document.getElementById('oa-m-portfolio')){
   var p=document.createElement('section');p.className='oa-m-portfolio';p.id='oa-m-portfolio';p.innerHTML='<div class="oa-m-card-head"><div class="oa-m-card-title"><i>▣</i>Portfolio</div><a href="/wallet">View all →</a></div><div class="oa-m-pf-body"><div class="oa-m-pf-kicker">Total value</div><div class="oa-m-pf-value" id="oa-m-pf-value">$0.00</div><div class="oa-m-pf-split"><div class="oa-m-pf-chip"><b>USDC</b><span id="oa-m-pf-usdc">$0.00</span></div><div class="oa-m-pf-chip"><b>SOL</b><span id="oa-m-pf-sol">$0.00</span></div><div class="oa-m-pf-chip"><b>Other</b><span id="oa-m-pf-other">$0.00</span></div></div></div>';wrap.appendChild(p);
   Promise.allSettled([fetch('/api/wallet/usdc-summary',{credentials:'include'}).then(function(r){return r.json()}),fetch('/api/wallet/tokens',{credentials:'include'}).then(function(r){return r.json()}),fetch('/api/wallet/balance',{credentials:'include'}).then(function(r){return r.json()})]).then(function(res){var s=res[0].status==='fulfilled'?res[0].value||{}:{};var t=res[1].status==='fulfilled'?res[1].value||{}:{};var b=res[2].status==='fulfilled'?res[2].value||{}:{};var usdc=num(s.total_usdc!=null?s.total_usdc:s.total);var solValue=num(b.sol)*num(b.sol_price||s.sol_price);var tokens=Array.isArray(t.tokens)?t.tokens:[];var other=tokens.reduce(function(sum,x){var sym=String(x.symbol||x.ticker||'').toUpperCase();if(sym==='USDC'||sym==='USDT'||sym==='SOL')return sum;var v=x.usd_value;if(v==null)v=x.value_usd;if(v==null)v=num(x.balance||x.amount)*num(x.price_usd||x.price);return sum+num(v)},0);document.getElementById('oa-m-pf-value').textContent=money(usdc+solValue+other);document.getElementById('oa-m-pf-usdc').textContent=money(usdc);document.getElementById('oa-m-pf-sol').textContent=money(solValue);document.getElementById('oa-m-pf-other').textContent=money(other)}).catch(function(){});
 }
}
ready(function(){document.body.classList.add('oa-home-mobile');hero();bot();shortcuts();setTimeout(marketAndPortfolio,300);});
})();
