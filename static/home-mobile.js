/* OrcAgent mobile Home — final dashboard composition. Reuses existing backend/feed/nav. */
(function(){
'use strict';
var path=location.pathname.replace(/\/+$/,'')||'/';
if(path!=='/' || !window.matchMedia('(max-width:767px)').matches) return;
/* Do not rely on CSS :has() to unlock document scrolling. Older Android
   WebViews either do not support it or can evaluate it too late, leaving the
   dashboard's base html{overflow:hidden} rule active for the whole page. */
document.documentElement.classList.add('oa-home-mobile-root');
var polish=document.createElement('link');polish.rel='stylesheet';polish.href='/static/home-mobile-polish.css?v=9';document.head.appendChild(polish);
function money(v){var n=Number(v||0);if(!isFinite(n))n=0;return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:n>=1000?0:2,maximumFractionDigits:n>=1000?0:2}).format(n)}
function num(v){var n=Number(v||0);return isFinite(n)?n:0}
function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn);else fn()}
function spark(){return '<svg class="oa-m-spark" viewBox="0 0 80 28" aria-hidden="true"><polyline points="1,23 8,19 14,21 21,13 28,16 36,9 44,12 51,5 59,8 67,3 79,1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'}
function startWalletConnect(){var phantomBtn=document.getElementById('phantom-ob-btn');if(phantomBtn){try{phantomBtn.click();return true}catch(_){}}if(typeof window.connectWalletOnboard==='function'){try{window.connectWalletOnboard('phantom');return true}catch(_){}}if(typeof window.connectWallet==='function'){try{window.connectWallet();return true}catch(_){}}return false}
function buildHero(wrap){var old=document.getElementById('oa-m-hero');if(old)old.remove();var el=document.createElement('section');el.className='oa-m-hero';el.id='oa-m-hero';el.innerHTML='<div class="oa-m-hero-left"><div class="oa-m-icon" aria-hidden="true"><span class="oa-m-triangle"></span></div><div class="oa-m-hero-copy"><h1>Smarter Trading.<br><span>Stronger Together.</span></h1><p>AI-powered trading, social insights and real-time opportunities — all inside OrcAgent.</p></div><div class="oa-m-values"><span>◎<small>TRADE<br>TOGETHER</small></span><span>▥<small>SHARE<br>INSIGHTS</small></span><span>◇<small>LEARN<br>&amp; GROW</small></span><span>◉<small>REAL-TIME<br>OPPORTUNITIES</small></span></div><a class="oa-m-primary" href="/auto-trading-bot">Start Trading <b>→</b></a></div><div class="oa-m-hero-art" aria-hidden="true"><img src="/static/orcagent-mobile-hero.svg?v=1" alt="" loading="eager"></div>';wrap.insertBefore(el,wrap.firstChild);return el}
function buildBot(wrap,afterEl){var old=document.getElementById('oa-m-bot');if(old)old.remove();var el=document.createElement('section');el.className='oa-m-bot';el.id='oa-m-bot';el.innerHTML='<div class="oa-m-bot-avatar"><img src="/static/ai-bot-icon.svg?v=1" alt="AI Bot"></div><div class="oa-m-bot-main"><div class="oa-m-bot-title"><span class="oa-m-bot-dot" id="oa-m-bot-dot"></span> AI Bot</div><div class="oa-m-bot-status">Status: <b id="oa-m-bot-state">checking…</b></div><div class="oa-m-bot-meta"><span id="oa-m-bot-ready">— USDC capital</span><span>•</span><span id="oa-m-bot-open">0/— open trades</span><span>•</span><span id="oa-m-bot-win">— win rate</span></div></div><a class="oa-m-bot-settings" href="/settings" aria-label="Bot settings">⚙</a><a class="oa-m-bot-btn" href="/auto-trading-bot">Open AI Bot <span>→</span></a>';afterEl.insertAdjacentElement('afterend',el);refreshBot();return el}
function refreshBot(){return fetch('/api/bot/overview',{credentials:'include',cache:'no-store'}).then(function(r){return r.json()}).then(function(d){if(!d||!d.ok)return;var running=!!d.running,state=document.getElementById('oa-m-bot-state'),dot=document.getElementById('oa-m-bot-dot');if(state){state.textContent=running?'Running':'Idle';state.classList.toggle('running',running)}if(dot)dot.classList.toggle('running',running);var open=Number(d.open_positions||0),max=d.max_positions!=null?Number(d.max_positions):null,op=document.getElementById('oa-m-bot-open');if(op)op.textContent=open+'/'+(max&&Number.isFinite(max)?max:'—')+' open trades';var wr=d.win_rate!=null?Number(d.win_rate):null,w=document.getElementById('oa-m-bot-win');if(w&&wr!=null&&Number.isFinite(wr))w.textContent=wr.toFixed(0)+'% win rate';var cap=d.trading_wallet_usdc!=null?Number(d.trading_wallet_usdc):null,x=document.getElementById('oa-m-bot-ready');if(x&&cap!=null&&Number.isFinite(cap))x.textContent=cap.toFixed(2)+' USDC capital'}).catch(function(){var s=document.getElementById('oa-m-bot-state');if(s)s.textContent='Unavailable'})}
var _oaPortfolioTimer=null,_oaPortfolioBusy=false;
var _oaScopeNode=document.querySelector('[data-orca-wallet-scope]');
var _oaScope=_oaScopeNode?_oaScopeNode.getAttribute('data-orca-wallet-scope'):'';
var _oaPortfolioCacheKey='orcaPortfolioLastConfirmedUSDCValue:v3:'+_oaScope;
var _oaPortfolioCacheAtKey='orcaPortfolioLastConfirmedUSDCValueAt:v3:'+_oaScope;
function _homeCachedPortfolio(){
  if(!_oaScope)return null;
  try{
    var raw=localStorage.getItem(_oaPortfolioCacheKey);
    var at=Number(localStorage.getItem(_oaPortfolioCacheAtKey));
    var n=Number(raw);
    if(raw==null||!Number.isFinite(n)||n<0||!Number.isFinite(at)||Date.now()-at>86400000)return null;
    return n;
  }catch(_){return null}
}
function _paintHomePortfolio(total,live,persist){
  if(total==null)return false;
  total=Number(total);
  if(!Number.isFinite(total)||total<0)return false;
  var value=document.getElementById('oa-m-pf-value');
  if(value)value.textContent=total.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+' USDC';
  var card=document.getElementById('oa-m-portfolio');
  if(card)card.title=live?'Live portfolio value':'Last confirmed portfolio value · refreshing';
  if(persist&&_oaScope){
    try{
      localStorage.setItem(_oaPortfolioCacheKey,String(total));
      localStorage.setItem(_oaPortfolioCacheAtKey,String(Date.now()));
    }catch(_){}
    window.__orcaPortfolioValue=total;
    document.dispatchEvent(new CustomEvent('orca:portfolio-value',{detail:{total:total}}));
  }
  return true;
}
async function refreshHomePortfolio(){
  var value=document.getElementById('oa-m-pf-value');
  if(!value||document.hidden||_oaPortfolioBusy)return;
  _oaPortfolioBusy=true;
  try{
    var response=await fetch('/api/portfolio/snapshot?t='+Date.now(),{
      credentials:'include',cache:'no-store'
    });
    if(!response.ok)throw Error('Portfolio snapshot unavailable');
    var d=await response.json();
    if(!d||!d.ok||!_paintHomePortfolio(d.total_usd,!d.stale&&d.inventory_complete!==false&&d.valuation_complete!==false,!d.stale&&d.inventory_complete!==false&&d.valuation_complete!==false))throw Error('Invalid portfolio snapshot');
  }catch(e){
    var cached=_homeCachedPortfolio();
    if(cached!==null)_paintHomePortfolio(cached,false,false);
    var card=document.getElementById('oa-m-portfolio');
    if(card&&cached===null)card.title='Portfolio update temporarily unavailable';
  }finally{_oaPortfolioBusy=false}
}
function buildPortfolio(afterEl){
  var old=document.getElementById('oa-m-portfolio');if(old)old.remove();
  if(_oaPortfolioTimer)OrcPageLifecycle.clearInterval(_oaPortfolioTimer);
  var el=document.createElement('section');el.className='oa-m-portfolio';el.id='oa-m-portfolio';
  el.innerHTML='<div class="oa-m-pf-icon">▣</div><div class="oa-m-pf-main"><div class="oa-m-pf-label">Total Portfolio Value</div><div class="oa-m-pf-row"><strong id="oa-m-pf-value">—</strong><span>Live</span></div></div><div class="oa-m-pf-chart">'+spark()+'</div><a href="/wallet" class="oa-m-pf-btn">View Portfolio <span>→</span></a>';
  afterEl.insertAdjacentElement('afterend',el);
  startPortfolio();
  return el;
}
function startPortfolio(){
  var cached=_homeCachedPortfolio();
  if(cached!==null)_paintHomePortfolio(cached,false,false);
  refreshHomePortfolio();
  if(_oaPortfolioTimer)OrcPageLifecycle.clearInterval(_oaPortfolioTimer);
  _oaPortfolioTimer=OrcPageLifecycle.setInterval(refreshHomePortfolio,30000);
}
/* ── Signed-in Home: a cockpit instead of the marketing hero ──────────────
   The hero ("Smarter Trading. Stronger Together.") is a pitch for someone
   who has not joined yet; its four icons do nothing. A signed-in trader
   gets what they came for instead: their portfolio, the four things they
   do most, and what is moving right now. */
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function signedIn(){var w=window.__SESSION_WALLET;return !!(w&&w!=='__SESSION_WALLET__')}
function greeting(){var h=new Date().getHours();return h<5?'Good night':h<12?'Good morning':h<18?'Good afternoon':'Good evening'}
function actionIcon(t){var p={
  deposit:'<path d="M12 4v11M7 10l5 5 5-5"/><path d="M4 19h16"/>',
  trade:'<path d="M4 16l5-5 4 4 7-7"/><path d="M15 8h5v5"/>',
  launch:'<path d="M12 3c3 2 5 6 5 10l-2 3H9l-2-3c0-4 2-8 5-10z"/><circle cx="12" cy="10" r="1.6"/><path d="M9 16l-2 4 3-1M15 16l2 4-3-1"/>',
  call:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2.4" fill="currentColor"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>'
};return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+p[t]+'</svg>'}
function buildToday(wrap){
  var old=document.getElementById('oa-m-portfolio');if(old)old.remove();
  var el=document.createElement('section');el.className='oa-m-today';el.id='oa-m-portfolio';
  el.innerHTML='<div class="oa-m-today-hi">'+greeting()+'</div>'
    +'<a class="oa-m-today-value" href="/wallet"><span class="oa-m-today-label">Portfolio</span>'
    +'<strong id="oa-m-pf-value">—</strong><span class="oa-m-today-go">View →</span></a>'
    +'<div class="oa-m-actions">'
    +'<a href="/wallet#deposit" class="primary">'+actionIcon('deposit')+'<span>Deposit</span></a>'
    +'<a href="/live-market">'+actionIcon('trade')+'<span>Trade</span></a>'
    +'<a href="/token-launch">'+actionIcon('launch')+'<span>Launch</span></a>'
    +'<button type="button" id="oa-m-action-call">'+actionIcon('call')+'<span>Call</span></button>'
    +'</div>';
  wrap.insertBefore(el,wrap.firstChild);
  document.getElementById('oa-m-action-call').onclick=function(){
    if(typeof window._openCallSheet==='function')window._openCallSheet();else location.href='/calls';
  };
  startPortfolio();
  return el;
}
function oppAge(ts){var s=Math.max(0,Date.now()/1000-(Number(ts)||0));if(!ts)return '';if(s<3600)return Math.max(1,Math.floor(s/60))+'m';if(s<86400)return Math.floor(s/3600)+'h';return Math.floor(s/86400)+'d'}
function oppCard(href,img,sym,sub,subCls){
  return '<a class="oa-m-opp" href="'+href+'">'
    +(img?'<img src="'+esc(img)+'" alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">':'<span class="oa-m-opp-ph"></span>')
    +'<span class="oa-m-opp-txt"><b>$'+esc(sym)+'</b><small class="'+(subCls||'')+'">'+sub+'</small></span></a>';
}
function buildOpps(afterEl){
  var old=document.getElementById('oa-m-opps');if(old)old.remove();
  var el=document.createElement('section');el.className='oa-m-opps';el.id='oa-m-opps';
  el.innerHTML='<div class="oa-m-opps-block" id="oa-m-surge" hidden><div class="oa-m-opps-hd"><span class="hot">Surging now</span><a href="/live-market">Live Market →</a></div><div class="oa-m-opps-rail" id="oa-m-surge-rail"></div></div>'
    +'<div class="oa-m-opps-block" id="oa-m-launches" hidden><div class="oa-m-opps-hd"><span>New on OrcAgent</span><a href="/launches">All launches →</a></div><div class="oa-m-opps-rail" id="oa-m-launch-rail"></div></div>';
  afterEl.insertAdjacentElement('afterend',el);
  loadOpps();
  OrcPageLifecycle.setInterval(function(){if(!document.hidden)loadOpps()},60000);
  return el;
}
function loadOpps(){
  var surge=fetch('/api/market/surges',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){
    var list=((d&&d.surges)||[]).slice(0,10),box=document.getElementById('oa-m-surge'),rail=document.getElementById('oa-m-surge-rail');
    if(!box||!rail)return;box.hidden=!list.length;
    rail.innerHTML=list.map(function(s){
      var chg=Number(s.price_change_5m)||Number(s.price_change_obs)||0;
      return oppCard('/live-market?mint='+encodeURIComponent(s.mint)+'&profile=1',s.image_url,s.symbol||'TOKEN',
        (Math.abs(chg)>=0.05?(chg>=0?'+':'')+chg.toFixed(1)+'%':'surging'),chg>=0?'up':'down');
    }).join('');
  }).catch(function(){});
  var launches=fetch('/api/token-launches?page=1',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){
    var list=((d&&d.launches)||[]).slice(0,10),box=document.getElementById('oa-m-launches'),rail=document.getElementById('oa-m-launch-rail');
    if(!box||!rail)return;box.hidden=!list.length;
    rail.innerHTML=list.map(function(l){
      return oppCard(l.trade_url||('/token/'+encodeURIComponent(l.mint)),l.logo_url,l.symbol,esc(l.quote_asset)+' · '+oppAge(l.finalized_at||l.created_at));
    }).join('');
  }).catch(function(){});
  return Promise.allSettled([surge,launches]);
}
document.addEventListener('visibilitychange',function(){if(!document.hidden)refreshHomePortfolio()});
// Pull-to-refresh on Home (wired up in dashboard.js) refreshes these cards
// in place along with the feed.
window.OrcAgentRefreshHome=function(){return Promise.allSettled([refreshHomePortfolio(),updateMajorMarkets(),refreshBot(),document.getElementById('oa-m-opps')?loadOpps():null])};
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
  if(_oaMarketTimer)OrcPageLifecycle.clearInterval(_oaMarketTimer);
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
  _oaMarketTimer=OrcPageLifecycle.setInterval(updateMajorMarkets,15000);
  return el;
}
document.addEventListener('visibilitychange',function(){if(!document.hidden)updateMajorMarkets()});
window.addEventListener('pageshow',function(){updateMajorMarkets()});
// Duotone glyphs (amber primary #f7b955, darker amber secondary #a9762f, dark
// cutouts #080d12) so each shortcut reads distinctly at a glance -- Social and
// Groups used to both be generic "people" outlines and were easy to mix up.
// Kept in sync with the nth-child background-image icons in
// home-mobile-polish.css, which is what actually paints on mobile (this
// inline SVG is hidden there via `.oa-m-shortcuts b svg{display:none}`) but
// still renders wherever that stylesheet doesn't apply.
function shortcutIcon(type){var p={
  market:'<rect fill="#a9762f" x="8.25" y="13" width="1" height="12"/><rect fill="#f7b955" x="7" y="16" width="3.5" height="8" rx="0.75"/><rect fill="#a9762f" x="15.5" y="7" width="1" height="18"/><rect fill="#f7b955" x="14.25" y="10" width="3.5" height="14" rx="0.75"/><rect fill="#a9762f" x="22.75" y="2" width="1" height="23"/><rect fill="#f7b955" x="21.5" y="4" width="3.5" height="20" rx="0.75"/>',
  trade:'<rect fill="#a9762f" x="6" y="10" width="15" height="2" rx="1"/><polygon fill="#f7b955" points="18,6.5 24,11 18,15.5"/><rect fill="#a9762f" x="11" y="20" width="15" height="2" rx="1"/><polygon fill="#f7b955" points="14,16.5 8,21 14,25.5"/>',
  portfolio:'<rect fill="#a9762f" x="8" y="5" width="14" height="8" rx="2"/><rect fill="#f7b955" x="4.5" y="11" width="23" height="16" rx="3.5"/><circle fill="#080d12" cx="22" cy="19" r="1.7"/>',
  social:'<rect fill="#f7b955" x="4.5" y="6.5" width="23" height="16" rx="7.5"/><polygon fill="#f7b955" points="10,22.5 10,28 16,22.5"/><circle fill="#080d12" cx="11" cy="14.5" r="1.4"/><circle fill="#080d12" cx="16" cy="14.5" r="1.4"/><circle fill="#080d12" cx="21" cy="14.5" r="1.4"/>',
  groups:'<circle fill="#a9762f" cx="9" cy="15" r="5.5"/><circle fill="#a9762f" cx="23" cy="15" r="5.5"/><circle fill="#080d12" cx="16" cy="11" r="7.5"/><circle fill="#f7b955" cx="16" cy="11" r="6.5"/>'
};return '<svg class="oa-m-shortcut-icon" viewBox="0 0 32 32" aria-hidden="true">'+p[type]+'</svg>'}
function buildShortcuts(afterEl){var old=document.getElementById('oa-m-shortcuts');if(old)old.remove();var el=document.createElement('nav');el.className='oa-m-shortcuts';el.id='oa-m-shortcuts';el.innerHTML='<a href="/live-market"><b>'+shortcutIcon('market')+'</b><span>Live Market</span></a><a href="/live-market"><b>'+shortcutIcon('trade')+'</b><span>Trade</span></a><a href="/wallet"><b>'+shortcutIcon('portfolio')+'</b><span>Portfolio</span></a><a href="#feed-composer"><b>'+shortcutIcon('social')+'</b><span>Social</span></a><a href="/groups"><b>'+shortcutIcon('groups')+'</b><span>Groups</span></a>';afterEl.insertAdjacentElement('afterend',el);return el}
function moveComposer(afterEl){var c=document.getElementById('feed-composer');if(c){afterEl.insertAdjacentElement('afterend',c);c.onclick=function(e){if(!e.target.closest('button,a,input,textarea')){var t=document.getElementById('postText');if(t)t.focus()}}}return c}
function keepComposerOpen(c){if(!c)return;var t=document.getElementById('postText');c.classList.add('expanded');if(!t)return;t.addEventListener('focus',function(){c.classList.add('expanded')});t.addEventListener('blur',function(){requestAnimationFrame(function(){c.classList.add('expanded')})});t.addEventListener('input',function(){c.classList.add('expanded')})}
function feedTabs(afterEl){var nativeTabs=document.querySelector('.feed-tabs');if(nativeTabs)nativeTabs.style.display='none';var old=document.getElementById('oa-m-feed-label');if(old)old.remove();var e=document.createElement('div');e.className='oa-m-feed-label';e.id='oa-m-feed-label';e.innerHTML='<button class="active" data-feed="foryou">For You</button><button data-feed="following">Following</button><button data-feed="calls">Calls</button><button data-feed="trends">Trends</button>';afterEl.insertAdjacentElement('afterend',e);var trending=document.getElementById('oa-trend-hero');if(trending)e.insertAdjacentElement('afterend',trending);e.addEventListener('click',function(ev){var b=ev.target.closest('button');if(!b)return;if(b.dataset.feed==='trends'){location.href='/live-market';return}e.querySelectorAll('button').forEach(function(x){x.classList.toggle('active',x===b)});var native=document.querySelector('.feed-tab[data-tab="'+b.dataset.feed+'"]');if(native)native.click()});if(typeof window.OrcAgentRefreshTrendingHero==='function')window.OrcAgentRefreshTrendingHero();return e}
function hideLegacyDuplicate(){document.querySelectorAll('.botbar,.feed-bot-card').forEach(function(el){el.classList.add('oa-m-legacy-hidden')})}
ready(function(){document.body.classList.add('oa-home-mobile');var wrap=document.querySelector('.wrap');if(!wrap)return;hideLegacyDuplicate();var composer;if(signedIn()){var today=buildToday(wrap),opps=buildOpps(today),bot=buildBot(wrap,opps),market=buildMarkets(bot);composer=moveComposer(market)}else{var hero=buildHero(wrap),gbot=buildBot(wrap,hero),pf=buildPortfolio(gbot),gmarket=buildMarkets(pf),shortcuts=buildShortcuts(gmarket);composer=moveComposer(shortcuts)}keepComposerOpen(composer);if(composer)feedTabs(composer);setTimeout(hideLegacyDuplicate,500)});
})();
