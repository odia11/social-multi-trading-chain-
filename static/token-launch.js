/* USDC-first launch; only user's wallet signs. Never writes an invented reward. */
(function(){
'use strict';
var cfg=window.ORC_TOKEN_LAUNCH||{};
var mine=[];
var readerData='';
var busy=false;
var autoVerified=Object.create(null);
var draftNonce='';
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
 var mode=choice('tl-mode')||'creator';
 var bps=toBps($('tl-community-share').value);
 text('tl-preview-name',name);text('tl-preview-symbol',symbol+' / '+asset);
 text('tl-review-pair',asset);
 text('tl-review-mode',{creator:'Creator',community:'Creator + Community',holder:'Holder'}[mode]);
 text('tl-review-creator',mode==='holder'?'Holder rewards':mode==='creator'?'100.00%':money((10000-bps)/100));
 text('tl-review-community',mode==='community'?money(bps/100):'—');
 $('tl-community-fields').hidden=mode!=='community';
 text('tl-reward-summary',mode==='holder'?'Rewards: token holders':mode==='community'?'Rewards: creator + community':'Rewards: 100% creator');
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
function dialog(title,details,onApprove,options){
 return new Promise(function(resolve){
  var root=$('tl-dialog');
  text('tl-dialog-title',title);text('tl-dialog-details',details);
  text('tl-dialog-status','');root.classList.add('open');
  var okay=$('tl-dialog-confirm'),cancel=$('tl-dialog-cancel');
  okay.disabled=false;cancel.disabled=false;cancel.textContent='Cancel';
  okay.textContent='Approve in Phantom';
  function cleanup(){root.classList.remove('open');okay.onclick=null;cancel.onclick=null}
  cancel.onclick=function(){cleanup();resolve(false)};
  okay.onclick=async function(){
    okay.disabled=true;cancel.disabled=true;
    text('tl-dialog-status','Preparing wallet approval…');
    try{var result=await onApprove();cleanup();resolve(result)}
    catch(e){
      var message=e.message||'Wallet approval failed';
      text('tl-dialog-status',message);
      var needsFunding=/Insufficient SOL/i.test(message);
      var blocked=needsFunding||/SOL budget|transaction simulation failed/i.test(message);
      okay.disabled=blocked;
      okay.textContent=blocked?'Approval unavailable':'Approve in Phantom';
      cancel.disabled=false;
      if(needsFunding&&options&&options.fundId){
        cancel.textContent='See funding options';
        cancel.onclick=function(){
          cleanup();resolve(false);
          var section=$('tl-fund-'+options.fundId);
          if(section)section.scrollIntoView({behavior:'smooth',block:'center'});
        };
      }
    }
  };
 });
}
function confirmStage(id,stage,sig){
 return call('/api/token-launch/'+id+'/confirm',{stage:stage,signature:sig});
}
async function signGaslessSwap(tx_b64){
 var provider=selectedWallet();
 if(!provider.publicKey&&typeof provider.connect==='function')await provider.connect();
 if(!provider.publicKey||provider.publicKey.toString()!==cfg.wallet)
   throw Error('Phantom wallet does not match your OrcAgent account.');
 if(typeof provider.signTransaction!=='function')
   throw Error('Your Phantom version cannot sign a gasless Jupiter swap. Update Phantom first.');
 if(!window.OrcAgentSolana||!window.OrcAgentSolana.VersionedTransaction)
   throw Error('Solana gasless swap library unavailable. Reload OrcAgent.');
 var bytes=Uint8Array.from(atob(tx_b64),function(c){return c.charCodeAt(0)});
 var tx=window.OrcAgentSolana.VersionedTransaction.deserialize(bytes);
 // Do NOT signAndSend: Jupiter co-signs and lands the gasless order via /execute.
 var signed=await provider.signTransaction(tx);
 if(!signed||typeof signed.serialize!=='function')
   throw Error('Phantom did not return the signed USDC swap. No swap was sent.');
 var out=signed.serialize(),chars='';
 for(var i=0;i<out.length;i++)chars+=String.fromCharCode(out[i]);
 return btoa(chars);
}
async function fundLaunchWithUsdc(row,amount,notice){
 if(busy)return;
 busy=true;
 try{
   notice.textContent='Finding a gasless USDC → SOL quote…';
   var quote=await call('/api/token-launch/'+row.id+'/fund/quote',{max_usdc:amount});
   var disclosure='Swap up to '+quote.amount_usdc+' USDC for approximately '+quote.expected_sol+' SOL in YOUR Phantom wallet. This is a separate Jupiter gasless swap. Your launch reserve target is '+quote.target_sol+' SOL. Jupiter swap fees and price movement affect your received SOL. After this confirmation you must separately approve the token launch. No token is created by this swap.';
   var result=await dialog('Fund token launch with USDC',disclosure,async function(){
     text('tl-dialog-status','Sign the gasless USDC → SOL swap in Phantom…');
     var signed=await signGaslessSwap(quote.transaction_b64);
     text('tl-dialog-status','Sending the approved swap to Jupiter; do not approve a second swap…');
     return call('/api/token-launch/'+row.id+'/fund/execute',
          {quote_id:quote.quote_id,signed_transaction_b64:signed});
   });
   if(!result){notice.textContent='Funding quote saved. No USDC swap was submitted.';return}
   notice.textContent=result.message||'Swap submitted. Check your SOL balance before launching.';
   var statusResult=await call('/api/token-launch/'+row.id+'/fund/status');
   notice.textContent+=(statusResult.ready
       ?' Your wallet now has the SOL reserve. You may approve the SAME token launch.'
       :' SOL reserve not yet confirmed. Use Check funding and do not approve another USDC swap.');
   status(notice.textContent,!statusResult.ready);
 }catch(e){notice.textContent=e.message||'USDC funding unavailable';status(notice.textContent,true)}
 finally{busy=false}
}
async function checkFunding(row,notice){
 if(busy)return;
 busy=true;
 try{
   var found=await call('/api/token-launch/'+row.id+'/fund/status');
   notice.textContent=found.ready
      ?'Ready: '+found.balance_sol+' SOL in your Phantom wallet. Approve this saved token launch.'
      :'SOL balance '+found.balance_sol+' / '+found.target_sol+' reserve. '+
       (found.funding&&found.funding.status==='submitted'
       ?'Earlier swap confirmation is uncertain; inspect Phantom/Jupiter history before swapping again.'
       :'Fund with USDC or add SOL to this wallet.');
   status(notice.textContent,!found.ready);
 }catch(e){notice.textContent=e.message||'Unable to check SOL balance';status(notice.textContent,true)}
 finally{busy=false}
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
     text('tl-dialog-status',create?'Preparing your orc token address; this can take up to 90 seconds…':'Building the Pump transaction…');
     var path='/api/token-launch/'+row.id+'/'+(create?'prepare':'prepare-finalize');
     var prepared=await call(path,{});
     if(cfg.pilotCreatorOnly){
       var max=prepared.pilot_estimated_max_sol_lamports;
       if(!Number.isSafeInteger(max)||max<=0||max>25000000)
         throw Error('The 0.025 SOL launch reserve check failed. No transaction was sent.');
       text('tl-dialog-status','Read-only Solana simulation: estimated maximum launch charge '+
         (max/1e9).toFixed(6)+' SOL (includes a conservative fee allowance). Your separate test trade must be 2 USDC or less. Review this amount again in Phantom.');
     }else{
       var publicCost=prepared.pilot_estimated_max_sol_lamports;
       if(!Number.isSafeInteger(publicCost)||publicCost<=0||publicCost>50000000)
         throw Error('The public 0.05 SOL launch safety check failed. Nothing was sent.');
       text('tl-dialog-status','Estimated maximum network and rent cost: '+
         (publicCost/1e9).toFixed(6)+' SOL. Confirm the final amount in Phantom.');
     }
     // Safari/Chrome/PWA on mobile are not injected with Phantom's provider.
     // Use Phantom's encrypted Connect -> signTransaction Universal Links;
     // return to this SAME saved launch without signing in again or browsing
     // OrcAgent inside Phantom. The original browser session stays intact.
     var injected=(window.phantom&&window.phantom.solana&&window.phantom.solana.isPhantom
        &&window.phantom.solana)||
        (window.solana&&window.solana.isPhantom&&window.solana)||window.solflare;
     if((!injected||typeof injected.signAndSendTransaction!=='function') &&
         (/iPhone|iPad|iPod|Android/i.test(navigator.userAgent) ||
          (/Macintosh/i.test(navigator.userAgent)&&navigator.maxTouchPoints>1))){
       text('tl-dialog-status','Opening Phantom to approve your saved token launch…');
       var handoff=await call('/api/token-launch/'+row.id+'/phantom/start',{stage:stage,
         return_to_pwa:!!(navigator.standalone===true ||
           (window.matchMedia&&window.matchMedia('(display-mode: standalone)').matches))});
       window.location.assign(handoff.url);
       return {handoff:true};
     }
     var sig=await signWithWallet(prepared.transaction_b64);
     // Store transaction ID only for recovery if Safari suspends the web app.
     try{sessionStorage.setItem('orca-token-launch:'+row.id+':'+stage,sig)}catch(e){}
     text('tl-dialog-status','Verifying the transaction on Solana…');
     var confirmed=await confirmStage(row.id,stage,sig);
     return {sig:sig,result:confirmed};
   },{fundId:row.id});
   if(!result||result.handoff)return;
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
       if(cfg.pilotCreatorOnly){
         var claimCost=ready.pilot_estimated_max_sol_lamports;
         if(!Number.isSafeInteger(claimCost)||claimCost<=0||claimCost>5000000)
           throw Error('Pilot creator-fee claim exceeds the 0.005 SOL follow-up reserve.');
         text('tl-dialog-status','Creator fee claim simulation: up to '+
           (claimCost/1e9).toFixed(6)+' SOL. Review the actual cost and quote asset in Phantom.');
       }
       var sig=await signWithWallet(ready.transaction_b64);
       try{sessionStorage.setItem('orca-token-claim:'+ready.claim_id,sig)}catch(e){}
       text('tl-dialog-status','Verifying reward transaction on Solana…');
       var confirmed=await call('/api/token-launch/'+row.id+'/claim/confirm',
                    {claim_id:ready.claim_id,signature:sig});
       return confirmed;
     });
   if(result){
     var actual=(result.received_raw!==undefined&&result.received_raw!==''
       ?(BigInt(result.received_raw)/1000000n).toString()+'.'+
         (BigInt(result.received_raw)%1000000n).toString().padStart(6,'0')+' USDC'
       :'');
     status(result.confirmed
       ?(result.status==='confirmed_no_payout'?'Transaction confirmed, but no new USDC was received. Network costs may still have been charged.':
         actual?'Creator-fee claim confirmed. Actual USDC received in your wallet: '+actual+' (wallet-wide creator rewards).':'Creator-fee claim confirmed on-chain.')
       :'Claim submitted; check your wallet and claim history before retrying.');
     await loadMine();
   }
 }catch(e){status(e.message||'Claim could not be prepared',true)}
 finally{busy=false}
}

async function showClaims(row){
 try{
  var r=await call('/api/token-launch/'+row.id+'/claims');
  if(!r.claims.length){status('No creator-fee claims submitted for this token.');return}
  var lines=r.claims.slice(0,6).map(function(c){
    var received=(c.status==='confirmed'&&c.received_raw!==undefined&&c.received_raw!==''
      ?' · received '+((BigInt(c.received_raw)/1000000n).toString()+'.'+
           (BigInt(c.received_raw)%1000000n).toString().padStart(6,'0'))+' USDC'
      :'');
    var label=c.status==='confirmed_no_payout'?'confirmed · no USDC payout (network fee only)':c.status;
    return label+' · '+c.quote_asset+received+' · '+(c.signature?c.signature.slice(0,10)+'…':'awaiting wallet signature')+' · '+new Date(c.created_at*1000).toLocaleDateString();
  });
  status(lines.join(' | '));
  var pending=r.claims.find(function(c){return c.status==='submitted'||c.status==='prepared'});
  if(pending){
    var sig=pending.signature;
    if(!sig){try{sig=sessionStorage.getItem('orca-token-claim:'+pending.id)||''}catch(e){}}
    if(!sig)return;
    var confirmed=await call('/api/token-launch/'+row.id+'/claim/confirm',
       {claim_id:pending.id,signature:sig});
    if(confirmed.confirmed){
      var paid=confirmed.received_raw;
      status(paid!==undefined&&paid!==''
        ?'Creator-fee claim confirmed. Received '+((BigInt(paid)/1000000n).toString()+'.'+
          (BigInt(paid)%1000000n).toString().padStart(6,'0'))+' USDC in your wallet.'
        :'Creator-fee claim confirmed on-chain.');
    }
  }
 }catch(e){status(e.message||'Claim history unavailable',true)}
}

async function checkKnown(row,stage,button,notice){
 if(busy)return;
 var key='orca-token-launch:'+row.id+':'+stage;
 var sig=stage==='create'?row.launch_signature:row.finalize_signature;
 if(!sig){try{sig=sessionStorage.getItem(key)||''}catch(e){}}
 if(!sig){sig=(window.prompt&&window.prompt('Paste your Solana transaction signature from Phantom history. Never paste your secret key.',''))||''}
 if(!sig){notice.textContent='No transaction signature saved. Check Phantom history and paste its transaction signature.';return}
 busy=true;button.disabled=true;button.textContent='Checking Solana…';
 try{
  notice.textContent='Verifying the exact transaction on Solana…';
  if(row.status==='submitted'||row.status==='finalize_submitted'){
    try{
      var relay=await call('/api/token-launch/'+row.id+'/phantom/retry-delivery',{});
      notice.textContent=relay.confirmed?'Confirmed on Solana.':
        relay.delivered?'Original signed transaction delivered. Checking confirmation…':relay.msg;
    }catch(e){
      // A pre-existing submission may have no saved signed bytes. Confirmation
      // still checks its recorded signature without preparing another launch.
      notice.textContent='Checking the original signature…';
    }
  }
  var result=await confirmStage(row.id,stage,sig.trim());
  notice.textContent=result.confirmed?'Confirmed on-chain. Updating launch…':'Transaction not yet available from Solana RPC. Do not launch the token again; retry later.';
  status(notice.textContent);
  await loadMine();
 }catch(e){
  notice.textContent=(e.message||'Unable to verify')+' The existing token was not changed. Do not create another token.';
  status(notice.textContent,true);
  button.disabled=false;button.textContent=stage==='create'?'Check transaction':'Check fee split';
 }finally{busy=false}
}
function renderRecent(){
 var panel=$('tl-recent-status'),target=$('tl-recent-items');if(!panel||!target)return;
 target.replaceChildren();var recent=mine.slice(0,4);panel.hidden=!recent.length;
 recent.forEach(function(row){
  var state=row.status==='live'?'confirmed':row.status==='draft'?'draft':
    row.status==='submitted'||row.status==='pending_shares'||row.status==='finalize_submitted'?'pending':
    row.status==='prepared'||row.status==='finalize_prepared'?'approval':'pending';
  var item=dom('div','tl-recent-item is-'+state);
  item.appendChild(dom('strong','',state));
  var age=Math.max(0,Math.floor(Date.now()/1000-Number(row.finalized_at||row.created_at||0)));
  item.appendChild(dom('small','',age<3600?Math.max(1,Math.floor(age/60))+'m ago':age<86400?Math.floor(age/3600)+'h ago':Math.floor(age/86400)+'d ago'));
  target.appendChild(item);
 });
}
function drawMine(){
 var wrap=$('tl-mine');wrap.replaceChildren();
 if(!mine.length){wrap.appendChild(dom('p','tl-helper','No saved tokens yet. Your first launch starts here.'));return}
 mine.forEach(function(row){
  var el=dom('article','tl-item');var top=dom('div','tl-item-top');
  var icon=dom('img','tl-item-icon');icon.src='/token-launch/icon/'+encodeURIComponent(row.id);icon.alt=row.name+' logo';icon.loading='lazy';top.appendChild(icon);
  var identity=dom('div','tl-item-identity');identity.appendChild(dom('strong','',row.symbol+' / '+row.quote_asset));
  identity.appendChild(dom('small','',row.name||''));
  var chips=dom('div','tl-item-chips');chips.appendChild(dom('span','tl-pair-chip',row.quote_asset+' Pair'));
  identity.appendChild(chips);top.appendChild(identity);
  top.appendChild(dom('span','tl-flag'+(row.status==='live'?' is-live':''),row.status.replaceAll('_',' ')));
  el.appendChild(top);
  el.appendChild(dom('p','tl-helper',row.reward_mode==='community'
    ? 'Community '+(row.community_bps/100).toFixed(2)+'% · Creator '+((10000-row.community_bps)/100).toFixed(2)+'%'
    :row.reward_mode==='holder'?'Creator fees belong to holders':'Creator fees belong to creator'));
  if(row.status==='live'&&row.mint){
    var live=dom('div','tl-live-note');live.appendChild(dom('span','tl-live-dot'));
    live.appendChild(dom('span','','Your token is live. Open Live Market to buy or sell.'));el.appendChild(live);
    var trade=dom('a','tl-buy-sell','Buy / Sell');trade.href='/live-market?mint='+encodeURIComponent(row.mint);el.appendChild(trade);
  }
  if(row.mint&&row.status!=='live')el.appendChild(dom('div','tl-mono',row.mint));
  var actions=dom('div','tl-actions');
  function action(label,fn){var b=dom('button','',label);b.type='button';b.onclick=fn;actions.appendChild(b);return b}
  if(cfg.enabled&&(row.status==='draft'||row.status==='prepared')){
    var fund=dom('div','tl-funding');fund.id='tl-fund-'+row.id;
    fund.appendChild(dom('p','tl-helper','Only have USDC in your connected Phantom wallet? OrcAgent estimates the SOL reserve from a live Jupiter quote and uses no more than your maximum USDC budget. Approve the gasless swap, then separately approve your token launch. No OrcAgent launch fee.'));
    var fundLabel=dom('label','tl-label','Maximum USDC budget');
    var fundAmount=dom('input','tl-input');fundAmount.type='number';fundAmount.min='5';fundAmount.max='250';fundAmount.step='0.01';fundAmount.value='25';fundAmount.setAttribute('aria-label','Maximum USDC to convert for launch SOL reserve');
    fundLabel.appendChild(fundAmount);fund.appendChild(fundLabel);
    var fundNotice=dom('p','tl-helper');fundNotice.setAttribute('role','status');
    var fundButton=dom('button','tl-btn secondary','Fund launch with USDC');fundButton.type='button';
    fundButton.disabled=!cfg.fundingAvailable;
    if(!cfg.fundingAvailable)fundNotice.textContent='USDC launch funding is not configured on the server yet.';
    fundButton.onclick=function(){fundLaunchWithUsdc(row,fundAmount.value,fundNotice)};
    var checkButton=dom('button','tl-btn secondary','Check funding');checkButton.type='button';
    checkButton.onclick=function(){checkFunding(row,fundNotice)};
    fund.appendChild(fundButton);fund.appendChild(checkButton);fund.appendChild(fundNotice);
    el.appendChild(fund);
  }
  if(row.status==='draft')action(cfg.enabled?'Approve launch':'Awaiting preflight',function(){launchStage(row,'create')});
  if(row.status==='draft'&&!cfg.enabled){actions.lastElementChild.disabled=true}
  if(row.status==='draft')action('Delete draft',async function(){
    if(!window.confirm||!window.confirm('Delete this unsent token draft? This cannot be undone.'))return;
    try{await call('/api/token-launch/'+row.id+'/delete-draft',{});status('Draft deleted.');await loadMine()}
    catch(e){status(e.message,true)}
  });
  if(row.status==='prepared')action(cfg.enabled?'Retry wallet approval':'Approval in preflight',function(){launchStage(row,'create')});
  if(row.status==='prepared'&&!cfg.enabled)actions.lastElementChild.disabled=true;
  var verification=dom('p','tl-helper');verification.setAttribute('role','status');
  if(row.status==='prepared'||row.status==='submitted'){
    var createCheck=action('Check transaction',function(){checkKnown(row,'create',createCheck,verification)});
  }
  if(row.status==='submitted'){
    el.appendChild(dom('p','tl-helper','Pending? Phantom may have signed the token without reaching Solana. Do not create a new token. Recovery checks the original signature, expired blockhash and mint on two RPCs before reusing this draft.'));
    action('Recover expired launch',async function(){
      if(busy)return;busy=true;
      try{
        verification.textContent='Checking the original token and signature on two Solana RPCs…';
        var result=await call('/api/token-launch/'+row.id+'/recover-submitted',{});
        verification.textContent=result.msg;
        status(result.msg);
        await loadMine();
      }catch(e){verification.textContent=e.message||'Recovery unavailable';status(verification.textContent,true)}
      finally{busy=false}
    });
  }
  if(row.status==='pending_shares')action(cfg.enabled?'Finalize shares':'Finalize after preflight',function(){launchStage(row,'finalize')});
  if(row.status==='pending_shares'&&!cfg.enabled)actions.lastElementChild.disabled=true;
  if(row.status==='finalize_prepared')action(cfg.enabled?'Retry wallet approval':'Approval in preflight',function(){launchStage(row,'finalize')});
  if(row.status==='finalize_prepared'&&!cfg.enabled)actions.lastElementChild.disabled=true;
  if(row.status==='finalize_prepared'||row.status==='finalize_submitted')var splitCheck=action('Check fee split',function(){checkKnown(row,'finalize',splitCheck,verification)});
  if(row.status==='live'&&row.reward_mode!=='holder'){
    if(row.reward_mode==='creator'&&row.quote_asset==='USDC'){
      action('Check USDC fees',async function(){
        try{
          verification.textContent='Reading Pump creator USDC vault…';
          var fees=await call('/api/token-launch/'+row.id+'/creator-fees');
          var n=BigInt(fees.pump_vault_raw);
          var value=(n/1000000n).toLocaleString('en-US')+'.'+(n%1000000n).toString().padStart(6,'0');
          verification.textContent='Unclaimed Pump USDC creator vault: '+value+' USDC (wallet-wide, across all your creator tokens; PumpSwap vault excluded). This is not a received payout. Claiming requires a separate Phantom approval.';
        }catch(e){verification.textContent=e.message||'Creator vault unavailable';status(verification.textContent,true)}
      });
    }
    action(cfg.enabled?'Claim creator fees':'Claims in preflight',function(){claimRewards(row)});
    if(!cfg.enabled)actions.lastElementChild.disabled=true;
    action('Claim history',function(){showClaims(row)});
  }
  if(row.status==='live'&&row.reward_mode==='holder'){
    el.appendChild(dom('p','tl-helper','Pump distributes Holder Rewards; there is no separate creator claim for this mode.'));
  }
  if(row.mint&&row.status==='pending_shares'){
    var a=dom('a','','Trade on OrcAgent →');
    a.href='/live-market?mint='+encodeURIComponent(row.mint);actions.appendChild(a);
  }
  if(row.launch_signature&&row.launch_signature.length>80){
    var explorer=dom('a','','View transaction ↗');
    explorer.href='https://solscan.io/tx/'+encodeURIComponent(row.launch_signature);
    explorer.target='_blank';explorer.rel='noopener noreferrer';actions.appendChild(explorer);
  }
  if(row.status==='live'){
    var details=dom('details','tl-item-details');var summary=dom('summary','');
    summary.appendChild(dom('span','tl-detail-icon','▥'));var heading=dom('span','tl-detail-heading');
    heading.appendChild(dom('strong','','Token details'));heading.appendChild(dom('small','','View contract, pair and links.'));
    summary.appendChild(heading);summary.appendChild(dom('span','tl-detail-chevron','⌄'));details.appendChild(summary);
    var body=dom('div','tl-detail-body');body.appendChild(dom('div','tl-mono',row.mint||''));
    body.appendChild(dom('p','tl-helper','Trading pair: '+row.quote_asset+' · '+(row.description||row.name)));
    if(row.mint){var chain=dom('a','','View contract on Solscan ↗');chain.href='https://solscan.io/token/'+encodeURIComponent(row.mint);chain.target='_blank';chain.rel='noopener noreferrer';body.appendChild(chain)}
    details.appendChild(body);el.appendChild(details);
    if(row.reward_mode!=='holder'){
      var fees=dom('details','tl-item-details tl-claim-details');fees.open=true;
      var feesSummary=dom('summary','');feesSummary.appendChild(dom('span','tl-detail-icon','▤'));
      var feesHeading=dom('span','tl-detail-heading');feesHeading.appendChild(dom('strong','','Manage creator fees'));
      feesSummary.appendChild(feesHeading);feesSummary.appendChild(dom('span','tl-detail-chevron','⌄'));fees.appendChild(feesSummary);
      var feeBody=dom('div','tl-detail-body');feeBody.appendChild(dom('p','tl-helper','Your token is live. Claiming trading fees is optional and requires a separate wallet approval.'));
      var feeActions=dom('div','tl-actions');
      ['Claim creator fees','Claims in preflight','Claim history','Check USDC fees'].forEach(function(label){
        Array.from(actions.children).forEach(function(button){
          if(button.textContent===label)feeActions.appendChild(button)
        });
      });feeBody.appendChild(feeActions);fees.appendChild(feeBody);el.appendChild(fees);
    }
  }
  if(actions.children.length)el.appendChild(actions);
  el.appendChild(verification);wrap.appendChild(el)
 });
}
async function loadMine(){
 try{
  var r=await call('/api/token-launch/mine');mine=r.launches||[];drawMine();renderRecent();
  // A creator may return from Phantom after a browser suspension. If their
  // signature is already durably recorded, retry chain verification ONCE
  // per page view without signing, spending, or creating another mint.
  var pending=mine.find(function(x){return x.status==='submitted'&&x.launch_signature&&!autoVerified[x.id]});
  if(pending){
   autoVerified[pending.id]=true;
   status('Checking your previously submitted token on Solana…');
   confirmStage(pending.id,'create',pending.launch_signature).then(function(result){
    if(result.confirmed){status('Token verified on Solana. Your launch is now live.');loadMine()}
    else status('Transaction not confirmed by Solana RPC yet. You can use Check transaction later.');
   }).catch(function(error){status((error.message||'Verification unavailable')+' Your submitted token is preserved; do not launch it again.',true)});
  }
 }catch(e){text('tl-mine','Could not load your launch history.')}
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
 var ack=$('tl-ack');if(!ack.checked){status('Confirm that you understand the network costs and creator rewards.',true);return}
 var bps=toBps($('tl-community-share').value),mode=choice('tl-mode');
 if(mode==='community'&&!bps){status('Choose a community share between 0.01% and 99.99%.',true);return}
 busy=true;$('tl-save').disabled=true;
 var readyToApprove=null,savedDraft=null;
 try{
  var icon=readerData||await loadImage($('tl-image').files[0]);
  if(!draftNonce){
    if(window.crypto&&crypto.randomUUID)draftNonce=crypto.randomUUID().replaceAll('-','');
    else throw Error('Secure browser randomness unavailable');
  }
  var nonce=draftNonce;
  var req={client_nonce:nonce,
   name:$('tl-name').value.trim(),symbol:$('tl-symbol').value.trim(),
   description:$('tl-description').value.trim(),image_data:icon,
   quote_asset:choice('tl-asset'),reward_mode:mode,
   community_wallet:mode==='community'?$('tl-community-wallet').value.trim():'',
   community_bps:mode==='community'?bps:0};
  var data=await call('/api/token-launch/draft',req);
  savedDraft=data.draft;draftNonce='';
  status('Draft saved. '+(cfg.enabled?'Preparing your Phantom approval…':'Mainnet signing is disabled during preflight.'));
  await loadMine();
  if(cfg.enabled){readyToApprove=data.draft}
  else $('tl-mine').scrollIntoView({behavior:'smooth',block:'nearest'});
 }catch(e){status(e.message||'Draft could not be saved',true)}
 finally{busy=false;$('tl-save').disabled=!!savedDraft}
 // One obvious action on the form: save the immutable draft first,
 // then offer explicit Phantom approval. No automatic signing/spending.
 if(readyToApprove){
   $('saved-launches').scrollIntoView({behavior:'smooth',block:'nearest'});
   await launchStage(readyToApprove,'create');
 }
}
['tl-name','tl-symbol','tl-description','tl-community-share','tl-community-wallet'].forEach(function(id){$(id).addEventListener('input',function(){renderPreview();$('tl-save').disabled=false})});
document.querySelectorAll('input[name="tl-asset"],input[name="tl-mode"]').forEach(function(i){i.addEventListener('change',function(){renderPreview();$('tl-save').disabled=false})});
$('tl-image').addEventListener('change',async function(){
 try{
  readerData=await loadImage(this.files[0]);$('tl-save').disabled=false;
  var root=$('tl-preview-logo');root.replaceChildren();
  var img=document.createElement('img');img.src=readerData;img.alt='Token icon preview';root.appendChild(img);
  text('tl-upload-label',this.files[0].name.length>28?this.files[0].name.slice(0,25)+'…':this.files[0].name);
 }catch(e){readerData='';text('tl-upload-label','Upload logo');status(e.message,true)}
});
$('tl-save').addEventListener('click',saveDraft);
renderPreview();loadMine();
// Phantom returns through the system browser on iOS. The original installed
// web app remains the source of truth and refreshes as soon as it is resumed.
var lastResumeCheck=0;
function refreshAfterPhantom(){
 if(document.hidden||Date.now()-lastResumeCheck<1200)return;
 lastResumeCheck=Date.now();
 // The PWA can remain alive for hours while Phantom and Safari handle the
 // callback. A prior pending check must not suppress the fresh chain check.
 autoVerified=Object.create(null);loadMine();
}
document.addEventListener('visibilitychange',refreshAfterPhantom);
window.addEventListener('pageshow',refreshAfterPhantom);
window.addEventListener('focus',refreshAfterPhantom);
})();
