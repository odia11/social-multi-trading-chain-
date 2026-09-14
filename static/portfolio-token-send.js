/* Portfolio Withdraw v2: send any owned token to another wallet. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet')return;

var state={assets:[],selected:null,busy:false};
var CHAIN={solana:'Solana',bsc:'BNB Chain',base:'Base',arbitrum:'Arbitrum',polygon:'Polygon',robinhood:'Robinhood'};
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function n(v){v=Number(v||0);return isFinite(v)&&v>0?v:0}
function fmtAmount(v){v=n(v);if(v>=1e6)return(v/1e6).toFixed(2)+'M';if(v>=1e3)return v.toLocaleString('en-US',{maximumFractionDigits:2});if(v>=1)return v.toLocaleString('en-US',{maximumFractionDigits:6});return v.toLocaleString('en-US',{maximumFractionDigits:9})}
function csrf(){return(document.querySelector('meta[name="csrf-token"]')||{}).content||''}
function chainName(c){return CHAIN[c]||String(c||'').toUpperCase()}
function shortAddr(s){s=String(s||'');return s.length>18?s.slice(0,8)+'…'+s.slice(-6):s}

function styles(){
 if(document.getElementById('oa-send-token-style'))return;
 var s=document.createElement('style');s.id='oa-send-token-style';s.textContent='\
#oa-send-token-modal{position:fixed;inset:0;z-index:12050;display:none;align-items:center;justify-content:center;padding:18px;background:rgba(2,5,9,.76);backdrop-filter:blur(5px)}#oa-send-token-modal.open{display:flex}.oa-st-card{width:min(100%,620px);max-height:min(88dvh,760px);overflow:auto;background:#101319;border:1px solid #27303b;border-radius:28px;padding:24px;box-shadow:0 26px 70px rgba(0,0,0,.58);font-family:Geist,sans-serif}.oa-st-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}.oa-st-title{font-size:24px;font-weight:750;color:#f4f6f8}.oa-st-close{width:38px;height:38px;border:0;background:none;color:#727c89;font-size:30px;line-height:1;cursor:pointer}.oa-st-label{display:block;color:#747d8b;font-size:12px;font-weight:650;letter-spacing:.05em;text-transform:uppercase;margin:0 0 8px}.oa-st-select,.oa-st-input{width:100%;height:58px;border-radius:15px;border:1px solid #29313c;background:#080b10;color:#eef1f5;padding:0 16px;font:600 16px JetBrains Mono,monospace;outline:none}.oa-st-select:focus,.oa-st-input:focus{border-color:rgba(247,185,85,.7)}.oa-st-field{margin-bottom:20px}.oa-st-asset-meta{display:flex;align-items:center;justify-content:space-between;gap:10px;color:#747d8b;font:500 12px JetBrains Mono,monospace;margin-top:9px}.oa-st-chain{color:#f7b955}.oa-st-amount-wrap{display:flex;gap:9px}.oa-st-amount-wrap .oa-st-input{flex:1;min-width:0}.oa-st-max{width:72px;border:1px solid #29313c;border-radius:15px;background:#1a2028;color:#f7b955;font-weight:800;cursor:pointer}.oa-st-note{min-height:20px;color:#747d8b;font-size:12px;line-height:1.45;margin:-4px 0 16px}.oa-st-note.err{color:#f76b62}.oa-st-note.ok{color:#3ad29b}.oa-st-actions{display:grid;grid-template-columns:1fr 1fr;gap:12px}.oa-st-btn{height:56px;border-radius:15px;font-size:15px;font-weight:750;cursor:pointer}.oa-st-cancel{background:#0b0f14;color:#a7aeba;border:1px solid #29313c}.oa-st-send{background:#f7b955;color:#090b0f;border:0}.oa-st-send:disabled,.oa-st-max:disabled{opacity:.45;cursor:not-allowed}.oa-st-empty{padding:18px 8px;color:#747d8b;text-align:center;font-size:13px}@media(max-width:600px){#oa-send-token-modal{align-items:flex-end;padding:0}.oa-st-card{width:100%;max-height:92dvh;border-radius:26px 26px 0 0;padding:22px 20px calc(24px + env(safe-area-inset-bottom))}.oa-st-title{font-size:23px}.oa-st-actions{grid-template-columns:1fr 1fr}}';document.head.appendChild(s)
}

function modal(){
 var m=document.getElementById('oa-send-token-modal');if(m)return m;
 m=document.createElement('div');m.id='oa-send-token-modal';m.setAttribute('aria-hidden','true');
 m.innerHTML='<div class="oa-st-card" role="dialog" aria-modal="true" aria-label="Withdraw asset"><div class="oa-st-head"><div class="oa-st-title">Withdraw</div><button class="oa-st-close" type="button" aria-label="Close">×</button></div><div class="oa-st-field"><label class="oa-st-label" for="oa-st-asset">Asset</label><select class="oa-st-select" id="oa-st-asset"><option>Loading portfolio…</option></select><div class="oa-st-asset-meta"><span id="oa-st-chain">—</span><span id="oa-st-balance">Balance: —</span></div></div><div class="oa-st-field"><label class="oa-st-label" for="oa-st-to">Recipient address</label><input class="oa-st-input" id="oa-st-to" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Wallet address…"></div><div class="oa-st-field"><label class="oa-st-label" for="oa-st-amount">Amount</label><div class="oa-st-amount-wrap"><input class="oa-st-input" id="oa-st-amount" inputmode="decimal" placeholder="0.00"><button class="oa-st-max" id="oa-st-max" type="button">MAX</button></div></div><div class="oa-st-note" id="oa-st-note">Network fees are paid by your trading wallet. OrcAgent does not subsidize withdrawals.</div><div class="oa-st-actions"><button class="oa-st-btn oa-st-cancel" type="button">Cancel</button><button class="oa-st-btn oa-st-send" id="oa-st-send" type="button">Withdraw</button></div></div>';
 document.body.appendChild(m);
 m.addEventListener('click',function(e){if(e.target===m)close()});
 m.querySelector('.oa-st-close').onclick=close;m.querySelector('.oa-st-cancel').onclick=close;
 m.querySelector('#oa-st-asset').addEventListener('change',choose);
 m.querySelector('#oa-st-max').addEventListener('click',setMax);
 m.querySelector('#oa-st-send').addEventListener('click',send);
 return m;
}
function note(text,kind){var e=document.getElementById('oa-st-note');if(!e)return;e.className='oa-st-note'+(kind?' '+kind:'');e.textContent=text}
function close(){var m=document.getElementById('oa-send-token-modal');if(!m)return;m.classList.remove('open');m.setAttribute('aria-hidden','true');state.busy=false}
function normalize(t){
 var chain=String(t.chain||'solana').toLowerCase();
 var sym=String(t.symbol||t.ticker||'TOKEN').replace(/^\$/,'');
 return {chain:chain,symbol:sym,name:String(t.name||sym),amount:n(t.amount!=null?t.amount:t.balance),token:String(t.token_address||t.address||t.mint||''),isNative:(chain==='solana'&&sym.toUpperCase()==='SOL'),usd:n(t.usd_value!=null?t.usd_value:t.value_usd)}
}
function unique(list){var out=[],seen={};list.forEach(function(a){var k=a.chain+'|'+a.token.toLowerCase()+'|'+a.symbol.toUpperCase();if(!a.amount||seen[k])return;seen[k]=1;out.push(a)});return out}
function loadAssets(){
 var sel=document.getElementById('oa-st-asset');if(sel){sel.disabled=true;sel.innerHTML='<option>Loading portfolio…</option>'}
 return fetch('/api/wallet/tokens?bust=1&t='+Date.now(),{credentials:'include',cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('Could not load portfolio');return r.json()}).then(function(d){
   var arr=unique((Array.isArray(d.tokens)?d.tokens:[]).map(normalize));
   state.assets=arr.filter(function(a){return a.amount>0&&(a.isNative||a.token)});
   if(!sel)return;
   if(!state.assets.length){sel.innerHTML='<option value="">No transferable assets found</option>';note('No transferable token balance was found in your trading wallet.','err');return}
   sel.innerHTML=state.assets.map(function(a,i){return '<option value="'+i+'">'+esc(a.symbol)+' · '+esc(chainName(a.chain))+' · '+esc(fmtAmount(a.amount))+'</option>'}).join('');
   sel.disabled=false;sel.value='0';choose();
 }).catch(function(){if(sel)sel.innerHTML='<option value="">Could not load assets</option>';note('Could not load your portfolio assets. Try again.','err')})
}
function choose(){
 var sel=document.getElementById('oa-st-asset'),i=sel?Number(sel.value):-1;state.selected=(i>=0?state.assets[i]:null);
 var a=state.selected,ch=document.getElementById('oa-st-chain'),bal=document.getElementById('oa-st-balance'),to=document.getElementById('oa-st-to');
 if(ch)ch.textContent=a?chainName(a.chain):'—';if(bal)bal.textContent=a?'Balance: '+fmtAmount(a.amount)+' '+a.symbol:'Balance: —';if(to)to.placeholder=a&&a.chain==='solana'?'Solana wallet address…':'0x wallet address…';
 var amount=document.getElementById('oa-st-amount');if(amount)amount.value='';
 note('Network fees are paid by your trading wallet. OrcAgent does not subsidize withdrawals.','');
}
function setMax(){var a=state.selected,inp=document.getElementById('oa-st-amount');if(!a||!inp)return;var v=a.amount;if(a.isNative)v=Math.max(0,v-0.001);inp.value=String(Math.floor(v*1e9)/1e9);if(a.isNative)note('0.001 SOL is left behind for the Solana network fee.','')}
function authHeaders(){var c=csrf();return {'Content-Type':'application/json','X-CSRF-Token':c,'X-CSRFToken':c,'X-Requested-With':'XMLHttpRequest'}}
function send(){
 if(state.busy)return;var a=state.selected,to=(document.getElementById('oa-st-to').value||'').trim(),amount=Number(document.getElementById('oa-st-amount').value||0),btn=document.getElementById('oa-st-send');
 if(!a){note('Choose an asset first.','err');return}if(!to){note('Enter the recipient wallet address.','err');return}if(!(amount>0)){note('Enter an amount greater than zero.','err');return}if(amount>a.amount+1e-12){note('Amount is higher than your portfolio balance.','err');return}
 state.busy=true;if(btn){btn.disabled=true;btn.textContent='Sending…'};note('Submitting transfer…','');
 var url,body;if(a.isNative){url='/api/wallet/send';body={to:to,amount_sol:amount}}else{url='/api/wallet/send-token';body={chain:a.chain,token_address:a.token,to_address:to,amount:amount}}
 fetch(url,{method:'POST',credentials:'include',headers:authHeaders(),body:JSON.stringify(body)}).then(function(r){return r.json().catch(function(){return{}}).then(function(d){if(!r.ok||d.ok===false)throw new Error(d.error||d.msg||'Transfer failed');return d})}).then(function(d){
   var sent=Number(d.amount_sent!=null?d.amount_sent:amount);note('Sent '+fmtAmount(sent)+' '+a.symbol+'.','ok');
   try{document.dispatchEvent(new CustomEvent('orca:portfolio-changed'))}catch(e){}try{document.dispatchEvent(new CustomEvent('orca:trade-complete'))}catch(e){};
   setTimeout(function(){close();if(typeof window.OrcAgentRefreshPortfolio==='function')window.OrcAgentRefreshPortfolio()},850)
 }).catch(function(err){note(err.message||'Transfer failed.','err')}).finally(function(){state.busy=false;if(btn){btn.disabled=false;btn.textContent='Withdraw'}})
}
function open(){
 styles();var m=modal();m.classList.add('open');m.setAttribute('aria-hidden','false');
 var to=document.getElementById('oa-st-to'),am=document.getElementById('oa-st-amount');if(to)to.value='';if(am)am.value='';
 loadAssets();
}

/* Portfolio-redesign resolves _modalSend at click time. Replacing only this
   UI entry point preserves all existing wallet routes while expanding Withdraw
   from native/stable-only to every token actually present in Portfolio. */
window._modalSend=open;
window.OrcAgentOpenWithdraw=open;
styles();modal();
})();
