/* OrcAgent approved History mockup, implemented against actual user-scoped data.
   No invented transactions, prices, conversion rates, deposits or wallet totals.
   Backend /api/portfolio/wallet-activity is read-only; tips and trades retain
   their existing authoritative endpoints and execution paths. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet')return;

var state={events:[],filter:'all',chain:'all',recentOpen:true,recentAll:false,
           openDays:{},loaded:false,busy:false,request:0,walletUnavailable:false};
var ICONS={
  activity:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  all:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  tip:'<path d="M12 21s-8-5.4-9.4-10A5 5 0 0 1 12 6a5 5 0 0 1 9.4 5C20 15.6 12 21 12 21Z"/>',
  swap:'<path d="M4 7h15l-4-4m4 4-4 4M20 17H5l4-4m-4 4 4 4"/>',
  wallet:'<rect x="3" y="6" width="18" height="15" rx="2"/><path d="M5 6V4a2 2 0 0 1 2-2h11M16 13h6v5h-6a2.5 2.5 0 0 1 0-5Z"/>',
  deposit:'<path d="M12 3v12m-5-5 5 5 5-5M4 18v3h16v-3"/>',
  receive:'<path d="M12 3v12m-5-5 5 5 5-5M4 18v3h16v-3"/>',
  send:'<path d="M12 21V9m-5 5 5-5 5 5M4 6V3h16v3"/>',
  failed:'<circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4h.01"/>',
  calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/>',
  globe:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c4 4 4 14 0 18M12 3c-4 4-4 14 0 18"/>'
};
var EXPLORERS=[
 /^https:\/\/solscan\.io\/tx\/[1-9A-HJ-NP-Za-km-z]{70,100}$/,
 /^https:\/\/(?:bscscan\.com|basescan\.org|arbiscan\.io|polygonscan\.com|explorer\.testnet\.chain\.robinhood\.com)\/tx\/0x[a-fA-F0-9]{64}$/
];
function $(id){return document.getElementById(id)}
function node(tag,cls,txt){var el=document.createElement(tag);if(cls)el.className=cls;if(txt!==undefined)el.textContent=txt;return el}
function icon(type){var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.innerHTML=ICONS[type]||ICONS.activity;return svg}
function round(n){var x=Number(n);return Number.isFinite(x)?x.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:6}):'—'}
function usd(n){return round(n)}
function amountText(e){
  if(e.amount==null||!Number.isFinite(Number(e.amount)))return '—';
  if(e.unit==='SOL')return (Number(e.amount)<0?'−':'+')+round(Math.abs(e.amount))+' SOL';
  return (Number(e.amount)<0?'−':'+')+'$'+usd(Math.abs(e.amount));
}
function parsedDate(value){
  if(typeof value==='number')return new Date(value*1000);
  if(!value)return new Date(NaN);
  var s=String(value).trim();
  if(/^\d{10}(?:\.\d+)?$/.test(s))return new Date(Number(s)*1000);
  if(/^\d{4}-\d\d-\d\d[ T]\d\d:\d\d/.test(s)&&!/[Zz]|[+-]\d\d:?\d\d$/.test(s))s=s.replace(' ','T')+'Z';
  return new Date(s);
}
function ago(time){
  var sec=Math.max(0,Math.floor((Date.now()-time)/1000));
  if(!Number.isFinite(sec))return '';
  if(sec<60)return 'just now';
  if(sec<3600)return Math.floor(sec/60)+'m ago';
  if(sec<86400)return Math.floor(sec/3600)+'h ago';
  return Math.floor(sec/86400)+'d ago';
}
function safeExplorer(url){return EXPLORERS.some(function(re){return re.test(String(url||''))})}
// Only our own profile paths (/profile/<wallet>), never an arbitrary URL.
function safeProfile(url){return /^\/profile\/[A-Za-z0-9]{20,64}$/.test(String(url||''))}
function openProfile(ev,url){
  ev.preventDefault();ev.stopPropagation();
  if(safeProfile(url))location.href=url;
}
// "To @MJ": the @name opens that member's profile. In the day list the row
// itself is a <button> (it expands the details), and a link inside a button
// is invalid HTML whose clicks also toggle the row -- so the name is a
// role=link span that stops the click from reaching the row.
function subLine(e){
  var small=node('small','');
  if(!(e.peer&&safeProfile(e.profile))){small.textContent=e.sub;return small}
  small.appendChild(document.createTextNode(e.peerPrefix));
  var name=node('span','oa-h-user','@'+e.peer);
  name.setAttribute('role','link');name.tabIndex=0;
  name.setAttribute('aria-label','Open @'+e.peer+"'s profile");
  name.addEventListener('click',function(ev){openProfile(ev,e.profile)});
  name.addEventListener('keydown',function(ev){if(ev.key==='Enter'||ev.key===' ')openProfile(ev,e.profile)});
  small.appendChild(name);
  return small;
}
function normalizeTips(tips){
  return (tips||[]).map(function(t){
    var sent=t.direction==='sent',time=parsedDate(t.created_at);
    return {
      id:'tip:'+t.id,tipId:Number(t.id),type:'tip',filter:'tips',
      icon:'tip',chain:String(t.chain||'solana').toLowerCase(),
      title:sent?'Tip sent':'Tip received',
      sub:(sent?'To ':'From ')+(sent
        ? (t.recipient_username?'@'+t.recipient_username.replace(/^@/,''):'OrcAgent member')
        : (t.sender_username?'@'+t.sender_username.replace(/^@/,''):'OrcAgent member')),
      amount:(sent?-1:1)*Math.abs(Number(t.amount||0)),unit:'USDC',
      time:time.getTime(),status:t.status||'submitted',
      hash:t.tx_hash||'',url:t.explorer_url||'',message:t.message||'',
      profile:sent?t.recipient_profile:t.sender_profile,
      peer:String((sent?t.recipient_username:t.sender_username)||'').replace(/^@/,''),
      peerPrefix:sent?'To ':'From '
    };
  }).filter(function(e){return Number.isFinite(e.time)});
}
function normalizeTrades(trades){
  return (trades||[]).map(function(t){
    var time=parsedDate(t.timestamp),buy=t.side==='buy';
    var symbol=String(t.symbol||'').replace(/^\$/,'');
    if(!symbol){var raw=String(t.token||'');symbol=raw.length>13?raw.slice(0,5)+'…'+raw.slice(-4):raw;}
    return {
      id:'trade:'+String(t.id||''),type:'swap',filter:'swaps',icon:'swap',
      chain:String(t.chain||'solana').toLowerCase(),
      title:'Swap',
      sub:(buy?'Bought ':'Sold ')+(symbol||'token')+' · Live Market',
      // For old sells, amount_usd in the legacy endpoint can actually be
      // denominated in SOL. Do not mislabel it as USD.
      amount:buy&&Number.isFinite(Number(t.amount_usd))?-Math.abs(Number(t.amount_usd)):null,
      unit:buy?'USDC':'',time:time.getTime(),status:'confirmed',
      hash:t.tx_hash||'',url:explorer(t.chain,t.tx_hash),message:'',
      profile:''
    };
  }).filter(function(e){return Number.isFinite(e.time)});
}
function normalizeWallet(events){
  return (events||[]).map(function(e){
    var t=parsedDate(e.timestamp),incoming=e.type==='receive';
    return {
      id:String(e.id||'wallet:'+e.tx_hash),type:incoming?'deposit':'send',
      filter:'wallet',icon:incoming?'deposit':'send',
      chain:'solana',title:incoming?'Deposit':'Send',
      sub:'USDC · '+(incoming?'To your wallet':'From your wallet'),
      amount:Number(e.amount),unit:'USDC',time:t.getTime(),
      status:'confirmed',hash:e.tx_hash||'',url:e.explorer_url||'',message:'',profile:''
    };
  }).filter(function(e){return Number.isFinite(e.time)});
}
function explorer(chain,hash){
  if(!hash)return '';
  var base={
    solana:'https://solscan.io/tx/',base:'https://basescan.org/tx/',
    bsc:'https://bscscan.com/tx/',arbitrum:'https://arbiscan.io/tx/',
    polygon:'https://polygonscan.com/tx/',
    robinhood:'https://explorer.testnet.chain.robinhood.com/tx/'
  }[String(chain||'').toLowerCase()];
  return base?base+hash:'';
}
function visible(){
  return state.events.filter(function(e){
    return (state.filter==='all'||e.filter===state.filter)&&
           (state.chain==='all'||e.chain===state.chain);
  });
}
function iconTile(e){
  var tile=node('span','oa-h-icon '+e.icon+(e.status==='failed'?' failed':''));
  tile.appendChild(icon(e.icon));return tile;
}
function line(e){
  var row=node('div','oa-h-recent-row');
  row.appendChild(iconTile(e));
  var main=node('span','oa-h-main');
  main.appendChild(node('strong','',e.title));
  main.appendChild(subLine(e));
  row.appendChild(main);
  var right=node('span','oa-h-right');
  var amt=node('strong',e.amount>0?'incoming':'',amountText(e));
  right.appendChild(amt);
  right.appendChild(node('time','',ago(e.time)));
  row.appendChild(right);
  return row;
}
function renderRecent(items){
  var box=$('oa-h-recent-list');if(!box)return;
  var show=state.recentAll?items:items.slice(0,3);
  box.replaceChildren();
  if(!items.length){box.appendChild(node('div','oa-h-empty','No activity for this filter yet.'));}
  else show.forEach(function(e){box.appendChild(line(e))});
  var toggle=$('oa-h-recent-toggle'),recent=$('oa-h-recent'),all=$('oa-h-viewall');
  recent.classList.toggle('is-collapsed',!state.recentOpen);
  toggle.textContent=state.recentOpen?'⌃':'⌄';
  toggle.setAttribute('aria-expanded',String(state.recentOpen));
  toggle.setAttribute('aria-label',state.recentOpen?'Collapse recent activity':'Expand recent activity');
  all.textContent=state.recentAll?'Show Less':'View All';
  all.disabled=false;
  all.style.opacity='1';
}
function dateKey(date){
  var d=new Date(date);
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
}
function dateGroup(e){
  var today=new Date(),at=new Date(e.time);
  var start=new Date(today.getFullYear(),today.getMonth(),today.getDate()).getTime();
  var target=new Date(at.getFullYear(),at.getMonth(),at.getDate()).getTime();
  var days=Math.round((start-target)/86400000);
  if(days<=0)return 'today';
  if(days===1)return 'yesterday';
  if(days<7)return 'week';
  return dateKey(e.time);
}
function dayTitle(key){
  if(key==='today')return 'Today';
  if(key==='yesterday')return 'Yesterday';
  if(key==='week')return 'This Week';
  var d=parsedDate(key+'T12:00:00Z');
  return Number.isFinite(d.getTime())?d.toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'}):'Earlier';
}
function daySub(key,items){
  if(key==='today'||key==='yesterday'){
    return new Date(items[0].time).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'});
  }
  if(key==='week')return 'Last 7 days';
  return '';
}
function details(e){
  var block=node('div','oa-h-detail'),grid=node('div','oa-h-detail-grid');
  function pair(a,b){grid.appendChild(node('span','',a));grid.appendChild(node('strong','',b));}
  pair('Status',(e.status||'confirmed').replace(/^./,function(c){return c.toUpperCase()}));
  pair('Network',e.chain.replace(/^./,function(c){return c.toUpperCase()}));
  pair('Amount',amountText(e));
  pair('Date',new Date(e.time).toLocaleString());
  if(e.message)pair('Message',e.message);
  if(e.hash)pair('Tx',e.hash.slice(0,10)+'…'+e.hash.slice(-8));
  block.appendChild(grid);
  if(e.peer&&safeProfile(e.profile)){
    var prof=node('a','oa-h-profile-link','View @'+e.peer+"'s profile →");prof.href=e.profile;
    block.appendChild(prof);
  }
  if(safeExplorer(e.url)){
    var link=node('a','','View on blockchain ↗');link.href=e.url;link.target='_blank';
    link.rel='noopener noreferrer';block.appendChild(link);
  }
  return block;
}
function activityRow(e,highlight){
  var row=node('article','oa-h-day-row'+(highlight?' oa-h-highlight':''));row.id='oa-h-'+e.id.replace(/[^a-zA-Z0-9:_-]/g,'-');
  var button=node('button','oa-h-day-row-head');button.type='button';button.setAttribute('aria-expanded','false');
  button.appendChild(iconTile(e));
  var main=node('span','oa-h-main');
  main.appendChild(node('strong','',e.title));
  main.appendChild(subLine(e));
  button.appendChild(main);
  var right=node('span','oa-h-right');
  right.appendChild(node('strong',e.amount>0?'incoming':'',amountText(e)));
  right.appendChild(node('time','',ago(e.time)));
  button.appendChild(right);
  button.appendChild(node('span','oa-h-day-row-chevron','›'));
  button.addEventListener('click',function(){
    row.classList.toggle('is-open');var open=row.classList.contains('is-open');
    button.setAttribute('aria-expanded',String(open));
    button.querySelector('.oa-h-day-row-chevron').textContent=open?'⌄':'›';
  });
  row.append(button,details(e));
  return row;
}
function renderDays(items){
  var root=$('oa-h-days');if(!root)return;
  root.replaceChildren();
  if(!items.length){
    root.appendChild(node('div','oa-h-empty','No transactions found. Try a different filter or network.'));
    return;
  }
  var groups=new Map();
  items.forEach(function(e){
    var key=dateGroup(e);
    if(!groups.has(key))groups.set(key,[]);
    groups.get(key).push(e);
  });
  var requested=new URLSearchParams(location.search).get('tip');
  groups.forEach(function(arr,key){
    var section=node('section','oa-h-day'),expanded=state.openDays[key];
    if(expanded===undefined)expanded=key==='today'||key===groups.keys().next().value;
    if(requested&&arr.some(function(e){return e.tipId&&String(e.tipId)===requested}))expanded=true;
    if(!expanded)section.classList.add('is-closed');
    var header=node('button','oa-h-day-header');header.type='button';
    header.setAttribute('aria-expanded',String(expanded));
    header.appendChild(icon('calendar'));
    header.appendChild(node('strong','',dayTitle(key)));
    header.appendChild(node('span','oa-h-date',daySub(key,arr)));
    header.appendChild(node('span','oa-h-count',arr.length+' '+(arr.length===1?'activity':'activities')));
    header.appendChild(node('span','oa-h-day-chevron',expanded?'⌃':'⌄'));
    var list=node('div','oa-h-day-list');
    arr.forEach(function(e){
      var matched=!!(requested&&e.tipId&&String(e.tipId)===requested);
      list.appendChild(activityRow(e,matched));
    });
    header.addEventListener('click',function(){
      section.classList.toggle('is-closed');
      state.openDays[key]=!section.classList.contains('is-closed');
      header.setAttribute('aria-expanded',String(state.openDays[key]));
      header.querySelector('.oa-h-day-chevron').textContent=state.openDays[key]?'⌃':'⌄';
    });
    section.append(header,list);root.appendChild(section);
  });
  if(requested){
    var hit=Array.from(root.querySelectorAll('.oa-h-highlight'))[0];
    if(hit)setTimeout(function(){hit.scrollIntoView({block:'center',behavior:'smooth'})},200);
  }
}
function render(){
  var items=visible().slice().sort(function(a,b){return b.time-a.time});
  renderRecent(items);
  renderDays(items);
  var p=$('oa-h-scope');
  if(p)p.textContent=state.walletUnavailable
    ? 'Wallet transfer history is temporarily unavailable; confirmed tips and recorded Live Market trades remain visible.'
    : 'Only actual tips, Live Market trades and recent confirmed Solana USDC wallet transfers are shown. No demo activity.';
}
function get(url){
  return fetch(url,{credentials:'same-origin',cache:'no-store'}).then(function(r){
    if(!r.ok)throw new Error('History source unavailable');
    return r.json();
  }).then(function(d){if(!d.ok)throw new Error('History source unavailable');return d});
}
function load(){
  if(state.busy)return;
  state.busy=true;var seq=++state.request;
  if(!state.loaded){
    $('oa-h-days').replaceChildren(node('div','oa-h-empty','Loading transaction history…'));
  }
  var tipRequest=get('/api/tips/mine?limit=100');
  var tradeRequest=get('/api/portfolio/transactions?limit=100');
  var walletRequest=get('/api/portfolio/wallet-activity');
  // Render tip/trade history as soon as its own sources finish. Solana
  // historical RPC scans may take longer and must not freeze these rows.
  var primary=Promise.allSettled([tipRequest,tradeRequest]).then(function(results){
    if(seq!==state.request)return;
    var events=[];
    if(results[0].status==='fulfilled')events.push.apply(events,normalizeTips(results[0].value.tips));
    if(results[1].status==='fulfilled')events.push.apply(events,normalizeTrades(results[1].value.transactions));
    state.events=events;state.loaded=true;render();
  });
  return Promise.allSettled([primary,walletRequest]).then(function(results){
    if(seq!==state.request)return;
    if(results[1].status==='fulfilled'){
      state.events=state.events.concat(normalizeWallet(results[1].value.events));
      state.walletUnavailable=false;
    }else{
      state.walletUnavailable=true;
    }
    state.loaded=true;render();
  }).finally(function(){state.busy=false});
}
function onPortfolioView(e){
  if(e.detail&&e.detail.view==='history')load();
}
function boot(){
  if(!$('oa-history-page'))return;
  var filters=$('oa-h-filters');
  Object.keys({all:1,tips:1,swaps:1,wallet:1}).forEach(function(type){
    var b=filters.querySelector('[data-oa-h-filter="'+type+'"]');
    if(b)b.querySelector('.oa-h-filter-symbol').appendChild(icon(type==='tips'?'tip':type==='swaps'?'swap':type));
  });
  $('oa-h-recent').querySelector('.oa-h-head-icon').appendChild(icon('activity'));
  $('oa-history-page').querySelector('.oa-h-network-globe').replaceChildren(icon('globe'));
  filters.addEventListener('click',function(e){
    var b=e.target.closest('[data-oa-h-filter]');if(!b)return;
    state.filter=b.dataset.oaHFilter;
    filters.querySelectorAll('[data-oa-h-filter]').forEach(function(x){
      var selected=x===b;x.classList.toggle('active',selected);
      x.setAttribute('aria-pressed',String(selected));
    });render();
  });
  $('oa-h-chain').addEventListener('change',function(e){state.chain=e.target.value;render()});
  $('oa-h-recent-toggle').addEventListener('click',function(){state.recentOpen=!state.recentOpen;renderRecent(visible().slice().sort(function(a,b){return b.time-a.time}))});
  $('oa-h-viewall').addEventListener('click',function(){
    var events=visible().slice().sort(function(a,b){return b.time-a.time});
    if(events.length<=3){
      $('oa-h-days').scrollIntoView({block:'start',behavior:'smooth'});
      return;
    }
    state.recentAll=!state.recentAll;
    state.recentOpen=true;
    renderRecent(events);
  });
  document.addEventListener('orcagent:portfolio-view',onPortfolioView);
  window.OrcAgentRefreshPortfolioHistory=load;
  if(document.body.classList.contains('pf-view-history'))load();
  document.addEventListener('visibilitychange',function(){if(!document.hidden&&document.body.classList.contains('pf-view-history'))load()});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
else boot();
})();
