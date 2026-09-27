/* OrcAgent verified-token directory; DOM textContent only, no untrusted HTML. */
(function(){'use strict';
 var state={owner:'all',pair:'all',query:'',page:1,seq:0};var timeout;
 function el(id){return document.getElementById(id)}
 function text(id,value){el(id).textContent=String(value)}
 function dom(tag,cls,value){var x=document.createElement(tag);if(cls)x.className=cls;if(value!==undefined)x.textContent=value;return x}
 function short(a){return a?a.slice(0,6)+'…'+a.slice(-5):'—'}
 function line(label,value,mono){var wrap=dom('div','line');wrap.appendChild(dom('label','',label));wrap.appendChild(dom('b',mono?'mint':'',value));return wrap}
 function action(parent,title,url,external){var a=dom('a','',title);a.href=url;if(external){a.target='_blank';a.rel='noopener noreferrer'}parent.appendChild(a)}
 function showOne(data){
  var card=dom('article','token'),top=dom('div','token-top');
  var logo=dom('img');logo.src=data.logo_url;logo.alt=data.name+' logo';logo.loading='lazy';
  top.appendChild(logo);var labels=dom('div');labels.style.minWidth='0';
  labels.appendChild(dom('div','token-name',data.name));labels.appendChild(dom('div','token-ticker',data.symbol+' / '+data.quote_asset));top.appendChild(labels);
  top.appendChild(dom('span','token-chip','● Live'));card.appendChild(top);
  card.appendChild(dom('p','description',data.description||'Launched on OrcAgent'));
  var details=dom('div','details');details.appendChild(line('Trading pair',data.quote_asset));
  var share=data.reward_mode==='community'?(100-data.community_bps/100).toFixed(2)+'% creator / '+(data.community_bps/100).toFixed(2)+'% community':data.reward_mode==='holder'?'Holder Rewards':'100% creator';
  details.appendChild(line('Rewards',share));details.appendChild(line('Creator',short(data.wallet),true));
  details.appendChild(line('Mint',short(data.mint),true));
  var time=data.finalized_at||data.created_at;
  if(time)details.appendChild(line('Launched',new Date(time*1000).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'})));
  card.appendChild(details);var actions=dom('div','actions');action(actions,'Trade on Pump ↗',data.pump_url,true);
  var copy=dom('button','','Copy mint');copy.type='button';copy.onclick=async function(){
    try{await navigator.clipboard.writeText(data.mint);copy.textContent='Copied ✓'}
    catch(e){copy.textContent='Copy unavailable'}
  };actions.appendChild(copy);card.appendChild(actions);return card;
 }
 async function load(){
  var id=++state.seq;var args=new URLSearchParams({owner:state.owner,asset:state.pair,q:state.query,page:String(state.page)});
  text('notice','');text('summary','Loading confirmed launches…');
  try{
   var res=await fetch('/api/token-launches?'+args.toString(),{credentials:'same-origin'});
   var data=await res.json();if(!res.ok||!data.ok)throw Error(data.msg||'Unable to load launches');
   if(id!==state.seq)return;
   var all=Number(data.counts.USDC||0)+Number(data.counts.SOL||0);
   text('stat-all',all);text('stat-usdc',data.counts.USDC||0);text('stat-sol',data.counts.SOL||0);
   text('summary',data.total+' confirmed launch'+(data.total===1?'':'es')+' · newest first');
   var wrap=el('cards');wrap.replaceChildren();
   if(!data.launches.length){var empty=dom('div','empty');empty.appendChild(dom('h2','',state.owner==='mine'?'No confirmed launches in this wallet yet':'No launches found'));
    empty.appendChild(dom('p','',state.owner==='mine'?'Confirm a token on Solana to show it here.':'Try a different token name or trading pair.'));
    wrap.appendChild(empty)}else data.launches.forEach(function(item){wrap.appendChild(showOne(item))});
   el('pager').hidden=data.total<=data.page_size;el('prev').disabled=state.page===1;el('next').disabled=state.page*data.page_size>=data.total;
   text('page-label','Page '+state.page+' / '+Math.max(1,Math.ceil(data.total/data.page_size)));
  }catch(err){if(id!==state.seq)return;text('summary','Directory temporarily unavailable');text('notice',err.message||'Unable to load launches');el('notice').className='error'}
 }
 function owner(v){state.owner=v;state.page=1;el('all-tab').classList.toggle('active',v==='all');el('mine-tab').classList.toggle('active',v==='mine');el('all-tab').setAttribute('aria-pressed',String(v==='all'));el('mine-tab').setAttribute('aria-pressed',String(v==='mine'));load()}
 el('all-tab').onclick=function(){owner('all')};el('mine-tab').onclick=function(){owner('mine')};
 el('pair').onchange=function(){state.pair=this.value;state.page=1;load()};
 el('search').oninput=function(){clearTimeout(timeout);var v=this.value;timeout=setTimeout(function(){state.query=v.trim();state.page=1;load()},220)};
 el('prev').onclick=function(){if(state.page>1){state.page--;load()}};
 el('next').onclick=function(){state.page++;load()};
 load();
})();
