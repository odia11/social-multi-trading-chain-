/* OrcAgent mobile Home — final dashboard composition. Reuses existing backend/feed/nav. */
(function(){
'use strict';
var path=location.pathname.replace(/\/+$/,'')||'/';
if(path!=='/' || !window.matchMedia('(max-width:768px)').matches) return;
/* Do not rely on CSS :has() to unlock document scrolling. Older Android
   WebViews either do not support it or can evaluate it too late, leaving the
   dashboard's base html{overflow:hidden} rule active for the whole page. */
document.documentElement.classList.add('oa-home-mobile-root');
var polish=document.createElement('link');polish.rel='stylesheet';polish.href='/static/home-mobile-polish.css?v=5';document.head.appendChild(polish);
function money(v){var n=Number(v||0);if(!isFinite(n))n=0;return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:n>=1000?0:2,maximumFractionDigits:n>=1000?0:2}).format(n)}
function num(v){var n=Number(v||0);return isFinite(n)?n:0}
function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn);else fn()}
function spark(){return '<svg class="oa-m-spark" viewBox="0 0 80 28" aria-hidden="true"><polyline points="1,23 8,19 14,21 21,13 28,16 36,9 44,12 51,5 59,8 67,3 79,1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'}
function startWalletConnect(){var phantomBtn=document.getElementById('phantom-ob-btn');if(phantomBtn){try{phantomBtn.click();return true}catch(_){}}if(typeof window.connectWalletOnboard==='function'){try{window.connectWalletOnboard('phantom');return true}catch(_){}}if(typeof window.connectWallet==='function'){try{window.connectWallet();return true}catch(_){}}return false}
function buildHero(wrap){var old=document.getElementById('oa-m-hero');if(old)old.remove();var el=document.createElement('section');el.className='oa-m-hero';el.id='oa-m-hero';el.innerHTML='<div class="oa-m-hero-left"><div class="oa-m-icon" aria-hidden="true"><span class="oa-m-triangle"></span></div><div class="oa-m-hero-copy"><h1>Smarter Trading.<br><span>Stronger Together.</span></h1><p>AI-powered trading, social insights and real-time opportunities — all inside OrcAgent.</p></div><div class="oa-m-values"><span>◎<small>TRADE<br>TOGETHER</small></span><span>▥<small>SHARE<br>INSIGHTS</small></span><span>◇<small>LEARN<br>&amp; GROW</small></span><span>◉<small>REAL-TIME<br>OPPORTUNITIES</small></span></div><a class="oa-m-primary" href="/auto-trading-bot">Start Trading <b>→</b></a></div><div class="oa-m-hero-art" aria-hidden="true"><img src="/static/orcagent-mobile-hero.svg?v=1" alt="" loading="eager"></div>';wrap.insertBefore(el,wrap.firstChild);return el}
function buildBot(wrap,afterEl){var old=document.getElementById('oa-m-bot');if(old)old.remove();var el=document.createElement('section');el.className='oa-m-bot';el.id='oa-m-bot';el.innerHTML='<div class="oa-m-bot-avatar"><img src="/static/ai-bot-icon.svg?v=1" alt="AI Bot"></div><div class="oa-m-bot-main"><div class="oa-m-bot-title"><span class="oa-m-bot-dot" id="oa-m-bot-dot"></span> AI Bot</div><div class="oa-m-bot-status">Status: <b id="oa-m-bot-state">checking…</b></div><div class="oa-m-bot-meta"><span id="oa-m-bot-ready">$0.00 capital</span><span>•</span><span id="oa-m-bot-open">0/5 open trades</span><span>•</span><span id="oa-m-bot-win">— win rate</span></div></div><a class="oa-m-bot-settings" href="/settings" aria-label="Bot settings">⚙</a><a class="oa-m-bot-btn" href="/auto-trading-bot">Open AI Bot <span>→</span></a>';afterEl.insertAdjacentElement('afterend',el);fetch('/api/bot/status',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){var running=!!(d&&(d.running||d.status==='running')),state=document.getElementById('oa-m-bot-state'),dot=document.getElementById('oa-m-bot-dot');if(state){state.textContent=running?'Running':'Idle';state.classList.toggle('running',running)}if(dot)dot.classList.toggle('running',running);var open=d&&(d.open_positions!=null?d.open_positions:d.positions_open);if(open!=null)document.getElementById('oa-m-bot-open').textContent=open+'/5 open trades';var wr=d&&(d.win_rate!=null?d.win_rate:d.winrate);if(wr!=null)document.getElementById('oa-m-bot-win').textContent=Number(wr).toFixed(0)+'% win rate'}).catch(function(){var s=document.getElementById('oa-m-bot-state');if(s)s.textContent='Idle'});fetch('/api/wallet/usdc-summary',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){if(d&&d.ok){var x=document.getElementById('oa-m-bot-ready');if(x)x.textContent=money(d.total_usdc!=null?d.total_usdc:d.total)+' capital'}}).catch(function(){});return el}
var _oaPortfolioTimer=null,_oaPortfolioBusy=false;
async function refreshHomePortfolio(){
  var value=document.getElementById('oa-m-pf-value');
  if(!value||document.hidden||_oaPortfolioBusy)return;
  _oaPortfolioBusy=true;
  try{
    var urls=['/api/wallet/usdc-summary','/api/wallet/tokens','/api/wallet/balance'];
    var data=await Promise.all(urls.map(async function(url){
      var response=await fetch(url,{credentials:'include',cache:'no-store'});
      if(!response.ok)throw Error('Balance request unavailable');
      return response.json();
    }));
    var s=data[0]||{},t=data[1]||{},b=data[2]||{};
    if(!s.ok||!t.ok||!b.ok)return;
    var usdc=num(s.total_usdc!=null?s.total_usdc:s.total);
    var solValue=num(b.sol)*num(b.sol_price||s.sol_price);
    var tokens=Array.isArray(t.tokens)?t.tokens:[];
    var other=tokens.reduce(function(sum,x){
      var sym=String(x.symbol||x.ticker||'').toUpperCase();
      if(sym==='USDC'||sym==='USDT'||sym==='SOL')return sum;
      var v=x.usd_value;
      if(v==null)v=x.value_usd;
      if(v==null)v=num(x.balance||x.amount)*num(x.price_usd||x.price);
      return sum+num(v);
    },0);
    value.textContent=money(usdc+solValue+other);
    var card=document.getElementById('oa-m-portfolio');
    if(card)card.title='Portfolio value refreshed from current wallet balances';
  }catch(e){
    var card=document.getElementById('oa-m-portfolio');
    if(card)card.title='Portfolio update temporarily unavailable';
  }finally{_oaPortfolioBusy=false}
}
function buildPortfolio(afterEl){
  var old=document.getElementById('oa-m-portfolio');if(old)old.remove();
  if(_oaPortfolioTimer)clearInterval(_oaPortfolioTimer);
  var el=document.createElement('section');el.className='oa-m-portfolio';el.id='oa-m-portfolio';
  el.innerHTML='<div class="oa-m-pf-icon">▣</div><div class="oa-m-pf-main"><div class="oa-m-pf-label">Total Portfolio Value</div><div class="oa-m-pf-row"><strong id="oa-m-pf-value">—</strong><span>Live</span></div></div><div class="oa-m-pf-chart">'+spark()+'</div><a href="/wallet" class="oa-m-pf-btn">View Portfolio <span>→</span></a>';
  afterEl.insertAdjacentElement('afterend',el);
  refreshHomePortfolio();
  _oaPortfolioTimer=setInterval(refreshHomePortfolio,30000);
  return el;
}
document.addEventListener('visibilitychange',function(){if(!document.hidden)refreshHomePortfolio()});
window.addEventListener('pageshow',refreshHomePortfolio);
function choosePair(d){var a=(d&&d.pairs)||[];if(!a.length)return null;a.sort(function(x,y){return num(y.liquidity&&y.liquidity.usd)-num(x.liquidity&&x.liquidity.usd)});return a[0]}
function formatPrice(n){n=num(n);if(n>=1000)return '$'+n.toLocaleString('en-US',{maximumFractionDigits:0});if(n>=1)return '$'+n.toLocaleString('en-US',{maximumFractionDigits:2});if(n>0)return '$'+n.toPrecision(4);return '—'}
// Market quotes are USD spot quotes, not a DexScreener text-search result.
var _oaMarketTimer=null,_oaMarketBusy=false,_oaMarketSamples={BTC:[],ETH:[],SOL:[]};
function updateMarketSpark(sym,price,card){
  var series=_oaMarketSamples[sym];
  if(series.length && series[series.length-1]!==price)series.push(price);
  else if(!series.length)series.push(price);
  if(series.length>22)series.shift();
  var svg=card&&card.querySelector('.oa-m-spark'),line=svg&&svg.querySelector('polyline');
  if(!svg||!line)return;
  svg.hidden=series.length<2;
  if(series.length<2)return;
  var low=Math.min.apply(null,series),high=Math.max.apply(null,series),span=high-low||1;
  line.setAttribute('points',series.map(function(v,i){
    return (1+78*i/Math.max(1,series.length-1)).toFixed(1)+','+
      (25-22*(v-low)/span).toFixed(1);
  }).join(' '));
}
async function updateMajorMarkets(){
  if(_oaMarketBusy||document.hidden||!document.getElementById('oa-m-market-strip'))return;
  _oaMarketBusy=true;
  var controller=new AbortController(),timeout=setTimeout(function(){controller.abort()},6500);
  try{
    var resp=await fetch('/api/home/major-prices',{credentials:'same-origin',cache:'no-store',signal:controller.signal});
    if(!resp.ok)throw Error('Price feed unavailable');
    var data=await resp.json();
    if(!data.ok||!data.prices)throw Error('Price feed unavailable');
    ['BTC','ETH','SOL'].forEach(function(sym){
      var q=data.prices[sym],card=document.querySelector('.oa-m-coin[data-sym="'+sym+'"]');
      if(!q||!card||!(Number(q.price)>0))return;
      var price=card.querySelector('#oa-m-'+sym.toLowerCase()+'-price');
      var change=card.querySelector('#oa-m-'+sym.toLowerCase()+'-change');
      if(price)price.textContent=formatPrice(q.price);
      var pct=Number(q.change24h);
      if(change&&Number.isFinite(pct)){
        change.textContent=(pct>=0?'+':'')+pct.toFixed(2)+'%';
        change.classList.toggle('neg',pct<0);
      }
      card.title=data.stale?'Last received market price (temporarily delayed)':'Live '+sym+'/USD quote, 24h change';
      updateMarketSpark(sym,Number(q.price),card);
    });
  }catch(err){
    ['BTC','ETH','SOL'].forEach(function(sym){
      var card=document.querySelector('.oa-m-coin[data-sym="'+sym+'"]');
      if(card)card.title='Market prices temporarily unavailable';
    });
  }finally{clearTimeout(timeout);_oaMarketBusy=false}
}
function buildMarkets(afterEl){
  var old=document.getElementById('oa-m-market-strip');if(old)old.remove();
  if(_oaMarketTimer)clearInterval(_oaMarketTimer);
  var el=document.createElement('section');el.className='oa-m-market-strip';el.id='oa-m-market-strip';
  el.innerHTML=['BTC','ETH','SOL'].map(function(sym){
    return '<button class="oa-m-coin" data-sym="'+sym+'" aria-label="'+sym+' live USD price">'+
      '<span class="oa-m-coin-logo '+sym.toLowerCase()+'">'+sym.charAt(0)+'</span>'+
      '<span class="oa-m-coin-name">'+sym+'</span>'+
      '<strong id="oa-m-'+sym.toLowerCase()+'-price">—</strong>'+
      '<span class="oa-m-coin-change" id="oa-m-'+sym.toLowerCase()+'-change">—</span>'+
      '<svg class="oa-m-spark" viewBox="0 0 80 28" aria-hidden="true" hidden><polyline fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>'
  }).join('')+'<a class="oa-m-view-market" href="/live-market"><b>▥</b><span>View Market</span><i>→</i></a>';
  afterEl.insertAdjacentElement('afterend',el);
  el.querySelectorAll('.oa-m-coin').forEach(function(card){
    card.onclick=function(){location.href='/live-market'};
  });
  updateMajorMarkets();
  _oaMarketTimer=setInterval(updateMajorMarkets,15000);
  return el;
}
document.addEventListener('visibilitychange',function(){if(!document.hidden)updateMajorMarkets()});
window.addEventListener('pageshow',function(){updateMajorMarkets()});
function shortcutIcon(type){var p={market:'<path d="M4 18V9m5 9V5m5 13v-7m5 7V3"/><path d="M3 21h18"/>',trade:'<path d="M4 7h15"/><path d="m16 4 3 3-3 3"/><path d="M20 17H5"/><path d="m8 14-3 3 3 3"/>',portfolio:'<rect x="3" y="5" width="18" height="15" rx="3"/><path d="M8 5V3h8v2"/><path d="M3 10h18"/><path d="M9 14h6"/>',social:'<path d="M21 12a8 8 0 0 1-8 8H6l-4 2 1.3-4.2A9 9 0 1 1 21 12Z"/><path d="M8 12h.01M12 12h.01M16 12h.01"/>',groups:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'};return '<svg class="oa-m-shortcut-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+p[type]+'</svg>'}
function buildShortcuts(afterEl){var old=document.getElementById('oa-m-shortcuts');if(old)old.remove();var el=document.createElement('nav');el.className='oa-m-shortcuts';el.id='oa-m-shortcuts';el.innerHTML='<a href="/live-market"><b>'+shortcutIcon('market')+'</b><span>Live Market</span></a><a href="/live-market"><b>'+shortcutIcon('trade')+'</b><span>Trade</span></a><a href="/wallet"><b>'+shortcutIcon('portfolio')+'</b><span>Portfolio</span></a><a href="#feed-composer"><b>'+shortcutIcon('social')+'</b><span>Social</span></a><a href="/groups"><b>'+shortcutIcon('groups')+'</b><span>Groups</span></a>';afterEl.insertAdjacentElement('afterend',el);return el}
function moveComposer(afterEl){var c=document.getElementById('feed-composer');if(c){afterEl.insertAdjacentElement('afterend',c);c.onclick=function(e){if(!e.target.closest('button,a,input,textarea')){var t=document.getElementById('postText');if(t)t.focus()}}}return c}
function keepComposerOpen(c){if(!c)return;var t=document.getElementById('postText');c.classList.add('expanded');if(!t)return;t.addEventListener('focus',function(){c.classList.add('expanded')});t.addEventListener('blur',function(){requestAnimationFrame(function(){c.classList.add('expanded')})});t.addEventListener('input',function(){c.classList.add('expanded')})}
function feedTabs(afterEl){var nativeTabs=document.querySelector('.feed-tabs');if(nativeTabs)nativeTabs.style.display='none';var old=document.getElementById('oa-m-feed-label');if(old)old.remove();var e=document.createElement('div');e.className='oa-m-feed-label';e.id='oa-m-feed-label';e.innerHTML='<button class="active" data-feed="foryou">For You</button><button data-feed="following">Following</button><button data-feed="trends">Trends</button>';afterEl.insertAdjacentElement('afterend',e);e.addEventListener('click',function(ev){var b=ev.target.closest('button');if(!b)return;if(b.dataset.feed==='trends'){location.href='/live-market';return}e.querySelectorAll('button').forEach(function(x){x.classList.toggle('active',x===b)});var native=document.querySelector('.feed-tab[data-tab="'+b.dataset.feed+'"]');if(native)native.click()});return e}
function hideLegacyDuplicate(){document.querySelectorAll('.botbar,.feed-bot-card').forEach(function(el){el.classList.add('oa-m-legacy-hidden')})}
ready(function(){document.body.classList.add('oa-home-mobile');var wrap=document.querySelector('.wrap');if(!wrap)return;hideLegacyDuplicate();var hero=buildHero(wrap),bot=buildBot(wrap,hero),pf=buildPortfolio(bot),market=buildMarkets(pf),shortcuts=buildShortcuts(market),composer=moveComposer(shortcuts);keepComposerOpen(composer);if(composer)feedTabs(composer);setTimeout(hideLegacyDuplicate,500)});
})();
