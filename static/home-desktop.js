/* Desktop-only OrcAgent home composition.
   Keeps the current dashboard/feed/search/market components and adds only
   presentation blocks that reuse real routes and real API data. */
(function(){
'use strict';
var path=location.pathname.replace(/\/+$/,'')||'/';
if(path!=='/' || !window.matchMedia('(min-width:1025px)').matches) return;

function money(v){
  var n=Number(v||0); if(!isFinite(n)) n=0;
  return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(n);
}
function num(v){var n=Number(v||0);return isFinite(n)?n:0;}
function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn);else fn();}

function buildHero(wrap){
  if(document.getElementById('oa-home-hero')) return;
  var hero=document.createElement('section');
  hero.className='oa-home-hero';hero.id='oa-home-hero';
  hero.innerHTML='<div class="oa-home-hero-copy">'
    +'<div class="oa-home-eyebrow">ORCAGENT</div>'
    +'<h1>Smarter Trading.<br><span>Stronger Together.</span></h1>'
    +'<p>AI-powered trading, live market intelligence, social insights and real-time opportunities — all inside one OrcAgent platform.</p>'
    +'<a class="oa-home-primary" href="/live-market">Start Trading <span>→</span></a>'
    +'</div>';
  wrap.insertBefore(hero,wrap.firstChild);
}

function buildBot(wrap){
  if(document.getElementById('oa-home-bot')) return;
  var bot=document.createElement('section');bot.className='oa-home-bot';bot.id='oa-home-bot';
  bot.innerHTML='<div class="oa-home-bot-icon">◎</div>'
    +'<div class="oa-home-bot-main">'
      +'<div class="oa-home-bot-title">Your bot is <span id="oa-home-bot-state">checking…</span><span class="oa-home-bot-dot" id="oa-home-bot-dot"></span></div>'
      +'<div class="oa-home-bot-meta"><span id="oa-home-bot-open">— open</span><span>•</span><span id="oa-home-bot-pnl">PnL —</span></div>'
    +'</div>'
    +'<a class="oa-home-bot-btn" href="/bot" id="oa-home-bot-btn">Open AI Bot</a>';
  var anchor=wrap.children[1]||null;
  if(anchor) wrap.insertBefore(bot,anchor); else wrap.appendChild(bot);
  fetch('/api/bot/status',{credentials:'include'}).then(function(r){return r.json();}).then(function(d){
    var running=!!(d&&(d.running||d.status==='running'));
    var state=document.getElementById('oa-home-bot-state'),dot=document.getElementById('oa-home-bot-dot');
    if(state){state.textContent=running?'running':'idle';state.style.color=running?'#3ad29b':'#8a919c';}
    if(dot)dot.classList.toggle('running',running);
    var open=d&&((d.open_positions!=null&&d.open_positions)||(d.positions_open!=null&&d.positions_open));
    if(open!=null)document.getElementById('oa-home-bot-open').textContent=open+' open';
    var pnl=d&&(d.pnl_usd!=null?d.pnl_usd:(d.total_pnl_usd!=null?d.total_pnl_usd:null));
    if(pnl!=null)document.getElementById('oa-home-bot-pnl').textContent='PnL '+money(pnl);
  }).catch(function(){
    var state=document.getElementById('oa-home-bot-state');if(state)state.textContent='idle';
  });
}

function addFeedLabel(wrap){
  if(document.getElementById('oa-home-feed-label'))return;
  var el=document.createElement('div');el.className='oa-home-section-label';el.id='oa-home-feed-label';el.innerHTML='<span>For You</span> &nbsp;&nbsp; Following';
  var bot=document.getElementById('oa-home-bot');
  if(bot&&bot.nextSibling)wrap.insertBefore(el,bot.nextSibling);else wrap.appendChild(el);
}

function buildPortfolio(rail){
  if(!rail||document.getElementById('oa-portfolio-card'))return;
  var card=document.createElement('section');card.className='oa-portfolio-card';card.id='oa-portfolio-card';
  card.innerHTML='<div class="oa-pf-head"><div class="oa-pf-title">Portfolio</div><a class="oa-pf-link" href="/wallet">View all →</a></div>'
    +'<div class="oa-pf-body"><div class="oa-pf-kicker">Total value</div><div class="oa-pf-value" id="oa-pf-value">$0.00</div>'
    +'<div class="oa-pf-meta"><span>●</span><span>Live multi-chain balances</span></div><div class="oa-pf-line"></div>'
    +'<div class="oa-pf-split"><div class="oa-pf-chip"><b>USDC</b><span id="oa-pf-usdc">$0.00</span></div><div class="oa-pf-chip"><b>SOL</b><span id="oa-pf-sol">$0.00</span></div><div class="oa-pf-chip"><b>Other</b><span id="oa-pf-other">$0.00</span></div></div></div>';
  var cards=rail.querySelectorAll('.rr-card');
  if(cards.length>0 && cards[0].nextSibling)rail.insertBefore(card,cards[0].nextSibling);else rail.appendChild(card);
  Promise.allSettled([
    fetch('/api/wallet/usdc-summary',{credentials:'include'}).then(function(r){return r.json();}),
    fetch('/api/wallet/tokens',{credentials:'include'}).then(function(r){return r.json();}),
    fetch('/api/wallet/balance',{credentials:'include'}).then(function(r){return r.json();})
  ]).then(function(res){
    var s=res[0].status==='fulfilled'?res[0].value||{}:{};
    var t=res[1].status==='fulfilled'?res[1].value||{}:{};
    var b=res[2].status==='fulfilled'?res[2].value||{}:{};
    var usdc=num(s.total_usdc!=null?s.total_usdc:s.total);
    var solPrice=num(b.sol_price||s.sol_price||0),solValue=num(b.sol)*solPrice;
    var tokens=Array.isArray(t.tokens)?t.tokens:[];
    var other=tokens.reduce(function(sum,x){
      var sym=String(x.symbol||x.ticker||'').toUpperCase();if(sym==='USDC'||sym==='USDT'||sym==='SOL')return sum;
      var v=x.usd_value;if(v==null)v=x.value_usd;if(v==null)v=num(x.balance||x.amount)*num(x.price_usd||x.price);return sum+num(v);
    },0);
    var total=usdc+solValue+other;
    document.getElementById('oa-pf-value').textContent=money(total);
    document.getElementById('oa-pf-usdc').textContent=money(usdc);
    document.getElementById('oa-pf-sol').textContent=money(solValue);
    document.getElementById('oa-pf-other').textContent=money(other);
  }).catch(function(){});
}

ready(function(){
  document.body.classList.add('oa-home-desktop');
  var wrap=document.querySelector('.wrap');
  if(!wrap)return;
  buildHero(wrap);buildBot(wrap);addFeedLabel(wrap);buildPortfolio(document.getElementById('right-rail'));
});
})();
