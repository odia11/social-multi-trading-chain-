/* USDC-first launch; only user's wallet signs. Never writes an invented reward. */
(function(){
'use strict';
var cfg=window.ORC_TOKEN_LAUNCH||{};
var mine=[];
var readerData='';
var busy=false;
function $(id){return document.getElementById(id)}
function text(id,value){var e=$(id);if(e)e.textContent=value}
function status(msg,err){var e=$('tl-status');if(!e)return;e.textContent=msg;e.className='tl-status '+(err?'err':'ok')}
function dom(tag,cls,value){var el=document.createElement(tag);if(cls)el.className=cls;if(value!==undefined)el.textContent=value;return el}
function choice(name){var el=document.querySelector('input[name="'+name+'"]:checked');return el?el.value:''}
function money(n){return (Number(n)||0).toFixed(2)+'%'}
function toBps(v){var n=Number(v);if(!Number.isFinite(n)||n<=0||n>=100)return 0;var bps=Math.round(n*100);return bps>0&&bps<10000&&Math.abs(bps/100-n)<.000001?bps:0}
function renderPreview(){
 var name=$('tl-name').value.trim()||'Your token name';
 var symbol=($('tl-symbol').value.trim()||'TOKEN').toUpperCase();
 var asset=choice('tl-asset')||'USDC';
 var mode=choice('tl-mode')||'community';
 var bps=toBps($('tl-community-share').value);
 text('tl-preview-name',name);text('tl-preview-symbol',symbol+' / '+asset);
 text('tl-review-pair',asset);
 text('tl-review-mode',{creator:'Creator',community:'Creator + Community',holder:'Holder'}[mode]);
 text('tl-review-creator',mode==='holder'?'Holder rewards':mode==='creator'?'100.00%':money((10000-bps)/100));
 text('tl-review-community',mode==='community'?money(bps/100):'—');
 $('tl-community-fields').style.display=mode==='community'?'block':'none';
}
async function call(path,body){
 var opt={credentials:'include'};
 if(body!==undefined){opt.method='POST';opt.headers={'Content-Type':'application/json','X-CSRF-Token':cfg.csrf};opt.body=JSON.stringify(body)}
 var response=await fetch(path,opt);
 var d=await response.json().catch(function(){return{ok:false,msg:'Unexpected response'}});
 if(!response.ok||!d.ok)throw Error(d.msg||'Request failed ('+response.status+')');
 return d;
}
function selectedWallet(){
 var provider=(window.phantom&&window.phantom.solana)||window.solana||window.solflare;
 if(!provider||typeof provider.signAndSendTransaction!=='function')throw Error('Open OrcAgent in Phantom or connect a compatible Solana wallet first.');
 return provider;
}
async function signWithWallet(tx_b64){
 var provider=selectedWallet();
 if(!provider.publicKey&&typeof provider.connect==='function')await provider.connect();
 if(!provider.publicKey||provider.publicKey.toString()!==cfg.wallet){
    throw Error('Connected Phantom wallet does not match your signed-in OrcAgent wallet.');
 }
 if(!window.OrcAgentSolana||!window.OrcAgentSolana.Transaction){
    throw Error('Solana wallet transaction library has not loaded. Reload and try again.');
 }
 var bytes=Uint8Array.from(atob(tx_b64),function(c){return c.charCodeAt(0)});
 var tx=window.OrcAgentSolana.Transaction.from(bytes);
 // This transaction already has an ephemeral mint signature. Phantom adds
 // only the user's own signature; OrcAgent cannot sign on their behalf.
 var res=await provider.signAndSendTransaction(tx);
 var sig=typeof res==='string'?res:res&&res.signature;
 if(typeof sig!=='string'||sig.length<85)throw Error('Wallet did not return a valid transaction signature. Check Phantom history.');
 return sig;
}
function dialog(title,details,onApprove){
 return new Promise(function(resolve){
  var root=$('tl-dialog');
  text('tl-dialog-title',title);text('tl-dialog-details',details);
  text('tl-dialog-status','');root.classList.add('open');
  var okay=$('tl-dialog-confirm'),cancel=$('tl-dialog-cancel');
  okay.disabled=false;cancel.disabled=false;
  okay.textContent='Approve in Phantom';
  function cleanup(){root.classList.remove('open');okay.onclick=null;cancel.onclick=null}
  cancel.onclick=function(){cleanup();resolve(false)};
  okay.onclick=async function(){
    okay.disabled=true;cancel.disabled=true;
    text('tl-dialog-status','Preparing wallet approval…');
    try{var result=await onApprove();cleanup();resolve(result)}
    catch(e){text('tl-dialog-status',e.message||'Wallet approval failed');okay.disabled=false;cancel.disabled=false}
  };
 });
}
function confirmStage(id,stage,sig){
 return call('/api/token-launch/'+id+'/confirm',{stage:stage,signature:sig});
}
async function launchStage(row,stage){
 if(!cfg.enabled){status('Live token launches remain disabled during mainnet preflight.',true);return}
 if(busy)return;
 busy=true;
 var create=stage==='create';
 var title=create?'Approve token launch':'Lock the community fee split';
 var details=create
  ? 'You will approve a real Solana mainnet token creation. Pair: '+row.quote_asset+'. Mode: '+row.reward_mode+'. Network rent and Pump trading fees apply. OrcAgent adds no launch fee.'
  : 'The token is already created. Its initial creator fee goes 100% to your wallet UNTIL this second transaction is confirmed. Final split: '+((10000-row.community_bps)/100).toFixed(2)+'% creator / '+(row.community_bps/100).toFixed(2)+'% '+row.community_wallet+'. This final allocation is irreversible.';
 try{
   var result=await dialog(title,details,async function(){
     text('tl-dialog-status','Building the Pump transaction…');
     var path='/api/token-launch/'+row.id+'/'+(create?'prepare':'prepare-finalize');
     var prepared=await call(path,{});
     text('tl-dialog-status','Waiting for your wallet signature…');
     var sig=await signWithWallet(prepared.transaction_b64);
     // Store transaction ID only for recovery if Safari suspends the web app.
     try{sessionStorage.setItem('orca-token-launch:'+row.id+':'+stage,sig)}catch(e){}
     text('tl-dialog-status','Verifying the transaction on Solana…');
     var confirmed=await confirmStage(row.id,stage,sig);
     return {sig:sig,result:confirmed};
   });
   if(!result)return;
   if(result.result.confirmed){
     status(create&&row.reward_mode==='community'
       ? 'Token created. Finalize the community fee shares now to complete launch.'
       : 'Transaction confirmed on Solana.');
   }else status('Transaction submitted. Confirmation is still pending. Use Check transaction if needed.');
   await loadMine();
 }catch(e){status(e.message||'Unable to prepare launch',true)}
 finally{busy=false}
}
async function claimRewards(row){
 if(!cfg.enabled){status('Reward claims are disabled during mainnet preflight.',true);return}
 if(row.reward_mode==='holder'){status('Holder Rewards belong to holders; there is no creator claim for this token.',true);return}
 if(busy)return;
 busy=true;
 try{
   var result=await dialog('Review creator-fee claim',
     'This is a real Solana transaction. You pay the network cost and receive only actual Pump fees. The regular creator vault can include fees from other tokens created by this wallet. Community fee distribution sends its allocated shares to both wallets.',
     async function(){
       text('tl-dialog-status','Checking on-chain reward vaults…');
       var ready=await call('/api/token-launch/'+row.id+'/claim/prepare',{});
       var denom=ready.quote_asset==='USDC'?1000000:1000000000;
       var n=(Number(ready.accrued_raw)/denom).toFixed(ready.quote_asset==='USDC'?6:9);
       text('tl-dialog-status','Accrued in vault: '+n+' '+ready.quote_asset+'. '+
         (ready.accrued_scope==='creator_wallet_all_tokens'?'May include fees from OTHER tokens created by this wallet. ':'')+
         'Review the actual transaction in Phantom.');
       var sig=await signWithWallet(ready.transaction_b64);
       try{sessionStorage.setItem('orca-token-claim:'+ready.claim_id,sig)}catch(e){}
       text('tl-dialog-status','Verifying reward transaction on Solana…');
       var confirmed=await call('/api/token-launch/'+row.id+'/claim/confirm',
                    {claim_id:ready.claim_id,signature:sig});
       return confirmed;
     });
   if(result){status(result.confirmed?'Creator-fee claim confirmed on-chain.':'Claim submitted; check your wallet and claim history before retrying.');await loadMine()}
 }catch(e){status(e.message||'Claim could not be prepared',true)}
 finally{busy=false}
}

async function showClaims(row){
 try{
  var r=await call('/api/token-launch/'+row.id+'/claims');
  if(!r.claims.length){status('No creator-fee claims submitted for this token.');return}
  var lines=r.claims.slice(0,6).map(function(c){
    return c.status+' · '+c.quote_asset+' · '+(c.signature?c.signature.slice(0,10)+'…':'awaiting wallet signature')+' · '+new Date(c.created_at*1000).toLocaleDateString();
  });
  status(lines.join(' | '));
  var pending=r.claims.find(function(c){return c.status==='submitted'||c.status==='prepared'});
  if(pending){
    var sig=pending.signature;
    if(!sig){try{sig=sessionStorage.getItem('orca-token-claim:'+pending.id)||''}catch(e){}}
    if(!sig)return;
    var confirmed=await call('/api/token-launch/'+row.id+'/claim/confirm',
       {claim_id:pending.id,signature:sig});
    if(confirmed.confirmed)status('Creator-fee claim confirmed on-chain.');
  }
 }catch(e){status(e.message||'Claim history unavailable',true)}
}

async function checkKnown(row,stage){
 var key='orca-token-launch:'+row.id+':'+stage;
 var sig=stage==='create'?row.launch_signature:row.finalize_signature;
 if(!sig){try{sig=sessionStorage.getItem(key)||''}catch(e){}}
 if(!sig){
   sig=(window.prompt&&window.prompt('Paste the SOLANA transaction signature from your wallet history. Never paste your secret key.',''))||'';
 }
 if(!sig)return;
 try{
  status('Verifying on-chain transaction…');
  var result=await confirmStage(row.id,stage,sig.trim());
  status(result.confirmed?'Transaction verified.':'Not confirmed yet. Check again shortly.');
  await loadMine();
 }catch(e){status(e.message||'Unable to verify',true)}
}
function drawMine(){
 var wrap=$('tl-mine');wrap.replaceChildren();
 if(!mine.length){wrap.appendChild(dom('p','tl-helper','No saved tokens yet. Your first launch starts here.'));return}
 mine.forEach(function(row){
  var el=dom('div','tl-item');var top=dom('div','tl-item-top');
  top.appendChild(dom('strong','',row.symbol+' / '+row.quote_asset));
  top.appendChild(dom('span','tl-flag',row.status.replaceAll('_',' ')));
  el.appendChild(top);
  el.appendChild(dom('p','tl-helper',row.reward_mode==='community'
    ? 'Community '+(row.community_bps/100).toFixed(2)+'% · Creator '+((10000-row.community_bps)/100).toFixed(2)+'%'
    :row.reward_mode==='holder'?'Creator fees belong to holders':'Creator fees belong to creator'));
  if(row.mint)el.appendChild(dom('div','tl-mono',row.mint));
  var actions=dom('div','tl-actions');
  function action(label,fn){var b=dom('button','',label);b.type='button';b.onclick=fn;actions.appendChild(b)}
  if(row.status==='draft')action(cfg.enabled?'Approve launch':'Awaiting preflight',function(){launchStage(row,'create')});
  if(row.status==='draft'&&!cfg.enabled){actions.lastElementChild.disabled=true}
  if(row.status==='draft')action('Delete draft',async function(){
    if(!window.confirm||!window.confirm('Delete this unsent token draft? This cannot be undone.'))return;
    try{await call('/api/token-launch/'+row.id+'/delete-draft',{});status('Draft deleted.');await loadMine()}
    catch(e){status(e.message,true)}
  });
  if(row.status==='prepared'||row.status==='submitted')action('Check transaction',function(){checkKnown(row,'create')});
  if(row.status==='pending_shares')action(cfg.enabled?'Finalize shares':'Finalize after preflight',function(){launchStage(row,'finalize')});
  if(row.status==='pending_shares'&&!cfg.enabled)actions.lastElementChild.disabled=true;
  if(row.status==='finalize_prepared'||row.status==='finalize_submitted')action('Check fee split',function(){checkKnown(row,'finalize')});
  if(row.status==='live'&&row.reward_mode!=='holder'){
    action(cfg.enabled?'Claim creator fees':'Claims in preflight',function(){claimRewards(row)});
    if(!cfg.enabled)actions.lastElementChild.disabled=true;
    action('Claim history',function(){showClaims(row)});
  }
  if(row.status==='live'&&row.reward_mode==='holder'){
    el.appendChild(dom('p','tl-helper','Pump distributes Holder Rewards; there is no separate creator claim for this mode.'));
  }
  if(row.mint){
    var url='https://pump.fun/coin/'+encodeURIComponent(row.mint);
    var a=dom('a','','View on Pump ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';actions.appendChild(a);
  }
  el.appendChild(actions);wrap.appendChild(el)
 });
}
async function loadMine(){
 try{var r=await call('/api/token-launch/mine');mine=r.launches||[];drawMine()}
 catch(e){text('tl-mine','Could not load your launch history.')}
}
function loadImage(file){
 return new Promise(function(resolve,reject){
  if(!file||file.size>1000000){reject(Error('Upload a PNG, JPG or WebP smaller than 1 MB.'));return}
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)){reject(Error('Invalid image type'));return}
  var fr=new FileReader();fr.onerror=function(){reject(Error('Unable to read image'))};
  fr.onload=function(){resolve(fr.result)};fr.readAsDataURL(file);
 });
}
async function saveDraft(){
 if(busy)return;
 var ack=$('tl-ack');if(!ack.checked){status('Confirm you understand the trading costs and rewards.',true);return}
 var bps=toBps($('tl-community-share').value),mode=choice('tl-mode');
 if(mode==='community'&&!bps){status('Choose a community share between 0.01% and 99.99%.',true);return}
 busy=true;$('tl-save').disabled=true;
 try{
  var icon=readerData||await loadImage($('tl-image').files[0]);
  var nonce='';
  if(window.crypto&&crypto.randomUUID)nonce=crypto.randomUUID().replaceAll('-','');
  else throw Error('Secure browser randomness unavailable');
  var req={client_nonce:nonce,
   name:$('tl-name').value.trim(),symbol:$('tl-symbol').value.trim(),
   description:$('tl-description').value.trim(),image_data:icon,
   quote_asset:choice('tl-asset'),reward_mode:mode,
   community_wallet:mode==='community'?$('tl-community-wallet').value.trim():'',
   community_bps:mode==='community'?bps:0};
  var data=await call('/api/token-launch/draft',req);
  status('Draft saved. '+(cfg.enabled?'Review it in Your launches and approve with Phantom.':'Mainnet signing is disabled during preflight.'));
  await loadMine();
  $('tl-mine').scrollIntoView({behavior:'smooth',block:'nearest'});
 }catch(e){status(e.message||'Draft could not be saved',true)}
 finally{busy=false;$('tl-save').disabled=false}
}
['tl-name','tl-symbol','tl-community-share','tl-community-wallet'].forEach(function(id){$(id).addEventListener('input',renderPreview)});
document.querySelectorAll('input[name="tl-asset"],input[name="tl-mode"]').forEach(function(i){i.addEventListener('change',renderPreview)});
$('tl-image').addEventListener('change',async function(){
 try{
  readerData=await loadImage(this.files[0]);
  var root=$('tl-preview-logo');root.replaceChildren();
  var img=document.createElement('img');img.src=readerData;img.alt='Token icon preview';root.appendChild(img);
 }catch(e){readerData='';status(e.message,true)}
});
$('tl-save').addEventListener('click',saveDraft);
renderPreview();loadMine();
})();
