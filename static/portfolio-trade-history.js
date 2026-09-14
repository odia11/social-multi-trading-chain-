/* Collapsible Portfolio history for Live Market BUY/SELL transactions only. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet')return;

var state={open:false,side:'all',date:'',busy:false,items:[],visible:5};
var STEP=5;
var chainLabels={solana:'SOL',bsc:'BSC',base:'BASE',arbitrum:'ARB',polygon:'POLY',robinhood:'HOOD'};
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function money(v){var n=Number(v||0);return isFinite(n)?'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'}
function dt(ts){var n=Number(ts||0);if(!n)return '—';try{return new Date(n*1000).toLocaleString(undefined,{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'})}catch(e){return '—'}}
function shortToken(t){t=String(t||'');return t.length>12?t.slice(0,6)+'…'+t.slice(-4):t}
function txUrl(chain,hash){if(!hash)return'';chain=String(chain||'').toLowerCase();if(chain==='solana')return'https://solscan.io/tx/'+encodeURIComponent(hash);var bases={bsc:'https://bscscan.com/tx/',base:'https://basescan.org/tx/',arbitrum:'https://arbiscan.io/tx/',polygon:'https://polygonscan.com/tx/'};return(bases[chain]||'')+encodeURIComponent(hash)}

function css(){
  var st=document.createElement('style');
  st.textContent='\
.oa-tx-card{background:#101216;border:1px solid rgba(255,255,255,.07);border-radius:18px;overflow:hidden;box-shadow:0 1px 0 rgba(255,255,255,.03) inset}.oa-tx-head{width:100%;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:17px 18px;background:none;border:0;color:#eef1f5;font:700 15px Geist,sans-serif;cursor:pointer}.oa-tx-head-r{display:flex;align-items:center;gap:10px;color:#8a919c;font-size:12px;font-weight:500}.oa-tx-chev{font-size:17px;transition:transform .18s ease}.oa-tx-card.open .oa-tx-chev{transform:rotate(180deg)}.oa-tx-body{display:none;border-top:1px solid #16191f}.oa-tx-card.open .oa-tx-body{display:block}.oa-tx-filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:14px 16px;border-bottom:1px solid #16191f}.oa-tx-pill{border:1px solid #252a32;background:#0b0d11;color:#8a919c;border-radius:999px;padding:7px 12px;font:600 11px Geist,sans-serif;cursor:pointer}.oa-tx-pill.active{color:#f7b955;border-color:rgba(247,185,85,.35);background:rgba(247,185,85,.08)}.oa-tx-date{margin-left:auto;min-width:142px;background:#0b0d11;color:#eef1f5;border:1px solid #252a32;border-radius:10px;padding:7px 10px;font:600 11px Geist,sans-serif}.oa-tx-clear{background:none;border:0;color:#f7b955;font:600 11px Geist,sans-serif;cursor:pointer}.oa-tx-list{padding:0 16px}.oa-tx-list.scrollable{max-height:470px;overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain}.oa-tx-row{padding:14px 0;border-bottom:1px solid #16191f}.oa-tx-row:last-child{border-bottom:0}.oa-tx-main{display:grid;grid-template-columns:auto 1fr auto;gap:11px;align-items:center}.oa-tx-side{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font:800 10px Geist,sans-serif;letter-spacing:.04em}.oa-tx-side.buy{background:rgba(58,210,155,.11);color:#3ad29b;border:1px solid rgba(58,210,155,.18)}.oa-tx-side.sell{background:rgba(247,107,98,.10);color:#f76b62;border:1px solid rgba(247,107,98,.18)}.oa-tx-token{font-size:14px;font-weight:700;color:#eef1f5}.oa-tx-meta{font:500 11px JetBrains Mono,monospace;color:#69727e;margin-top:4px}.oa-tx-amount{text-align:right;font:700 13px JetBrains Mono,monospace;color:#eef1f5}.oa-tx-pnl{font:600 10px JetBrains Mono,monospace;margin-top:4px}.oa-tx-pnl.pos{color:#3ad29b}.oa-tx-pnl.neg{color:#f76b62}.oa-tx-extra{display:none;margin:10px 0 0 53px;padding:10px 12px;border:1px solid #1c2128;border-radius:10px;background:#0b0d11;font:500 10px JetBrains Mono,monospace;color:#737c88;line-height:1.65}.oa-tx-row.expanded .oa-tx-extra{display:block}.oa-tx-row-btn{cursor:pointer}.oa-tx-link{color:#f7b955;text-decoration:none}.oa-tx-empty,.oa-tx-loading{padding:24px 16px;text-align:center;color:#69727e;font-size:12px}.oa-tx-more{display:block;width:calc(100% - 32px);margin:12px 16px 16px;padding:11px 14px;border:1px solid rgba(247,185,85,.28);border-radius:11px;background:rgba(247,185,85,.07);color:#f7b955;font:700 12px Geist,sans-serif;cursor:pointer}.oa-tx-scope{padding:0 16px 12px;color:#69727e;font:500 10px JetBrains Mono,monospace}@media(max-width:600px){.oa-tx-date{margin-left:0;flex:1 1 100%}.oa-tx-main{grid-template-columns:auto 1fr auto}.oa-tx-extra{margin-left:0}.oa-tx-filters{gap:7px}}';
  document.head.appendChild(st);
}

function mount(){
  var content=document.querySelector('.wlt-content');if(!content)return;
  if(document.getElementById('oa-portfolio-transactions'))return;
  var card=document.createElement('section');card.className='oa-tx-card';card.id='oa-portfolio-transactions';
  card.innerHTML='<button class="oa-tx-head" type="button" aria-expanded="false"><span>Live Market Transactions</span><span class="oa-tx-head-r"><span id="oa-tx-count">Buy & Sell</span><span class="oa-tx-chev">⌄</span></span></button><div class="oa-tx-body"><div class="oa-tx-filters"><button class="oa-tx-pill active" data-side="all">All</button><button class="oa-tx-pill" data-side="buy">Buys</button><button class="oa-tx-pill" data-side="sell">Sells</button><input class="oa-tx-date" id="oa-tx-date" type="date" aria-label="Search Live Market transactions by date"><button class="oa-tx-clear" id="oa-tx-clear" type="button">Clear date</button></div><div class="oa-tx-scope">Only manual Buy/Sell transactions from Live Market are shown here.</div><div class="oa-tx-list" id="oa-tx-list"><div class="oa-tx-empty">Open to load Live Market transactions</div></div><button class="oa-tx-more" id="oa-tx-more" type="button" style="display:none">Show 5 more</button></div>';
  content.appendChild(card);

  var head=card.querySelector('.oa-tx-head');
  head.addEventListener('click',function(){state.open=!state.open;card.classList.toggle('open',state.open);head.setAttribute('aria-expanded',state.open?'true':'false');if(state.open)load()});
  card.querySelectorAll('[data-side]').forEach(function(b){b.addEventListener('click',function(){state.side=b.dataset.side;state.visible=STEP;card.querySelectorAll('[data-side]').forEach(function(x){x.classList.toggle('active',x===b)});load()})});
  var date=card.querySelector('#oa-tx-date');date.addEventListener('change',function(){state.date=date.value||'';state.visible=STEP;load()});
  card.querySelector('#oa-tx-clear').addEventListener('click',function(){state.date='';date.value='';state.visible=STEP;load()});
  card.querySelector('#oa-tx-more').addEventListener('click',function(){state.visible+=STEP;render()});
  card.addEventListener('click',function(e){var row=e.target.closest('.oa-tx-row-btn');if(row&&!e.target.closest('a'))row.closest('.oa-tx-row').classList.toggle('expanded')});
}

function rowHtml(x){
  var side=String(x.side||'').toLowerCase()==='sell'?'sell':'buy';
  var symbol=esc(x.symbol||shortToken(x.token)||'Token');
  var chain=esc(chainLabels[String(x.chain||'').toLowerCase()]||String(x.chain||'').toUpperCase()||'—');
  var pnl='';if(side==='sell'&&x.pnl_pct!=null){var pp=Number(x.pnl_pct||0);pnl='<div class="oa-tx-pnl '+(pp>=0?'pos':'neg')+'">'+(pp>=0?'+':'')+pp.toFixed(2)+'%</div>'}
  var url=txUrl(x.chain,x.tx_hash);var link=url?'<br><a class="oa-tx-link" href="'+esc(url)+'" target="_blank" rel="noopener">View transaction ↗</a>':'';
  return '<div class="oa-tx-row"><div class="oa-tx-main oa-tx-row-btn"><div class="oa-tx-side '+side+'">'+side.toUpperCase()+'</div><div><div class="oa-tx-token">'+symbol+'</div><div class="oa-tx-meta">'+esc(dt(x.timestamp))+' · '+chain+' · Live Market</div></div><div class="oa-tx-amount">'+money(x.amount_usd)+pnl+'</div></div><div class="oa-tx-extra">Side: '+side.toUpperCase()+'<br>Source: Live Market<br>Chain: '+chain+'<br>Token: '+esc(x.token||x.symbol||'—')+'<br>Value: '+money(x.token_value_usd||x.amount_usd)+(x.price_usd?'<br>Exit price: '+money(x.price_usd):'')+(x.pnl!=null?'<br>Realized PnL: '+money(x.pnl):'')+link+'</div></div>';
}
function render(){
  var list=document.getElementById('oa-tx-list'),more=document.getElementById('oa-tx-more');if(!list)return;
  var items=state.items||[],shown=items.slice(0,state.visible);
  var count=document.getElementById('oa-tx-count');if(count)count.textContent=items.length?Math.min(state.visible,items.length)+' of '+items.length:'Buy & Sell';
  if(!items.length){list.classList.remove('scrollable');list.innerHTML='<div class="oa-tx-empty">No Live Market transactions found'+(state.date?' for this date':'')+'.</div>';if(more)more.style.display='none';return}
  list.innerHTML=shown.map(rowHtml).join('');
  list.classList.toggle('scrollable',shown.length>STEP);
  if(more){var left=items.length-state.visible;more.style.display=left>0?'block':'none';more.textContent=left>0?'Show '+Math.min(STEP,left)+' more':'Show 5 more'}
}
function load(){
  if(!state.open||state.busy)return;state.busy=true;
  var list=document.getElementById('oa-tx-list');if(list)list.innerHTML='<div class="oa-tx-loading">Loading Live Market transactions…</div>';
  var q='?side='+encodeURIComponent(state.side)+'&limit=100';if(state.date)q+='&date='+encodeURIComponent(state.date);
  fetch('/api/portfolio/transactions'+q,{credentials:'include',cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('load failed');return r.json()}).then(function(d){state.items=Array.isArray(d.transactions)?d.transactions:[];render()}).catch(function(){state.items=[];if(list)list.innerHTML='<div class="oa-tx-empty">Could not load Live Market transactions.</div>'}).finally(function(){state.busy=false});
}

css();
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
document.addEventListener('orca:trade-complete',function(){if(state.open)load()});
})();
