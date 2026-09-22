/* OrcAgent Tips: real chain-backed receipts, Portfolio history and profile stats.
   No direct signing, sending or user-supplied recipient routing. */
(function(){
'use strict';
function $(id){return document.getElementById(id)}
function money(value){
  var v=Number(value||0);
  return (isFinite(v)?v:0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:6});
}
function json(url){return fetch(url,{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.json()})}
function stateLabel(s){
  return s==='confirmed'?'Confirmed':s==='failed'?'Failed':'Submitted';
}
function when(date){
  var d=new Date(String(date||'').replace(' ','T')+'Z');
  return isNaN(d.getTime())?'':d.toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
}
function refreshStats(){
  var box=$('oa-tip-stats');
  if(!box)return;
  json('/api/profile/'+encodeURIComponent(box.dataset.userId)+'/tip-stats').then(function(d){
    if(!d.ok)return;
    if($('oa-tip-received'))$('oa-tip-received').textContent=money(d.received_usdc)+' USDC';
    if($('oa-tip-supporters'))$('oa-tip-supporters').textContent=String(d.supporters);
    if($('oa-tip-sent')&&d.sent_usdc!==undefined)$('oa-tip-sent').textContent=money(d.sent_usdc)+' USDC';
  }).catch(function(){});
}
function refreshProfileBalance(){
  var card=$('oa-profile-balance');
  if(!card)return;
  var userId=String(card.dataset.userId||'');
  if(!/^\d+$/.test(userId))return;
  fetch('/api/profile/'+encodeURIComponent(userId)+'/portfolio-balance',{
    credentials:'same-origin',cache:'no-store'
  }).then(function(r){
    if(!r.ok)throw new Error('Balance unavailable');
    return r.json();
  }).then(function(d){
    if(!d.ok||Number(d.user_id)!==Number(userId))throw new Error('Balance unavailable');
    var value=Number(d.portfolio_value_usdc_approx);
    var available=Number(d.available_usdc);
    if(!Number.isFinite(value)||value<0||!Number.isFinite(available)||available<0)
      throw new Error('Balance unavailable');
    $('oa-profile-balance-value').textContent='≈ '+money(value)+' USDC';
    $('oa-profile-balance-available').textContent=money(available)+' USDC';
    $('oa-profile-balance-state').textContent=d.stale?'Last available portfolio snapshot':'';
  }).catch(function(){
    if(!$('oa-profile-balance-value'))return;
    $('oa-profile-balance-value').textContent='Unavailable';
    $('oa-profile-balance-available').textContent='—';
    $('oa-profile-balance-state').textContent='Balance temporarily unavailable';
  });
}
window.OrcAgentRefreshProfileBalance=refreshProfileBalance;

window.OrcAgentRefreshTipStats=refreshStats;
var receiptTimer=null,receiptId=null,noteCallback=null,noteDelivered=false,receiptAttempts=0;
var receiptVisible=false;
function cancelReceiptTimer(){if(receiptTimer){clearTimeout(receiptTimer);receiptTimer=null}}
function renderReceipt(tip){
  var card=$('oa-tip-receipt'),sheet=card&&card.closest('.tip-sheet');
  if(!card||!sheet)return;
  if(tip.status==='confirmed'&&!noteDelivered&&typeof noteCallback==='function'){
    noteDelivered=true;noteCallback();refreshStats();
  }
  if(!receiptVisible)return;
  card.hidden=false;sheet.classList.add('oa-tip-result');
  var state=tip.status||'submitted';
  $('oa-tip-receipt-title').textContent=state==='confirmed'?'Tip delivered!':state==='failed'?'Tip failed':'Tip submitted';
  $('oa-tip-receipt-amount').textContent=money(tip.amount)+' USDC';
  $('oa-tip-receipt-peer').textContent=(state==='confirmed'?'Delivered to ':'To ')+(tip.recipient_username?'@'+tip.recipient_username.replace(/^@/,''):'OrcAgent member');
  $('oa-tip-receipt-network').textContent=(tip.chain||'Solana').replace(/^./,function(x){return x.toUpperCase()});
  var badge=$('oa-tip-receipt-status');
  badge.textContent=stateLabel(state);badge.className='oa-tip-pill '+state;
  var explorer=$('oa-tip-receipt-explorer');
  var href=tip.explorer_url||tip.explorer||'';
  explorer.hidden=!/^https:\/\/(solscan\.io|bscscan\.com|basescan\.org|arbiscan\.io|polygonscan\.com|explorer\.testnet\.chain\.robinhood\.com)\//.test(href);
  if(!explorer.hidden)explorer.href=href;
  $('oa-tip-receipt-info').textContent=state==='confirmed'
    ? 'Confirmed on-chain. Both users can see this tip in Portfolio → History.'
    :state==='failed'?(tip.failure_reason||'The blockchain rejected this transfer.')
    :'Your transaction has been submitted. OrcAgent is checking the blockchain for confirmation.';
}
function pollReceipt(){
  if(!receiptId)return;
  json('/api/tips/'+encodeURIComponent(receiptId)).then(function(d){
    if(!d.ok||!d.tip)return;
    renderReceipt(d.tip);
    if(d.tip.status==='submitted'&&receiptAttempts++<180){
      receiptTimer=setTimeout(pollReceipt,receiptAttempts<30?4000:10000);
    }
  }).catch(function(){
    if(receiptAttempts++<180)receiptTimer=setTimeout(pollReceipt,10000);
  });
}
window.OrcAgentTipReceipt=function(reply,amount,onConfirmed){
  cancelReceiptTimer();
  receiptId=reply.tip_id||null;receiptAttempts=0;receiptVisible=true;
  noteCallback=onConfirmed;noteDelivered=false;
  renderReceipt({
    amount:reply.amount_sent||amount,
    chain:reply.chain,
    status:reply.status||'submitted',
    explorer_url:reply.explorer,
    recipient_username:(($('tip-back')&&$('tip-back').querySelector('.tip-user-handle')||{}).textContent||'').trim().replace(/^@/,'')
  });
  if(receiptId)receiptTimer=setTimeout(pollReceipt,2200);
};
window._tipFinish=function(){
  receiptVisible=false;
  var backdrop=$('tip-back');
  if(backdrop)backdrop.classList.remove('open');
};
if(typeof window._openTip==='function'){
  var open=window._openTip;
  window._openTip=function(){
    receiptVisible=false;
    cancelReceiptTimer();
    var card=$('oa-tip-receipt');
    if(card){card.hidden=true;card.closest('.tip-sheet').classList.remove('oa-tip-result')}
    open.apply(this,arguments);
  };
}

function make(tag,className,text){
  var n=document.createElement(tag);
  if(className)n.className=className;
  if(text!==undefined)n.textContent=text;
  return n;
}
function validExplorer(url){
  return /^https:\/\/(solscan\.io|bscscan\.com|basescan\.org|arbiscan\.io|polygonscan\.com|explorer\.testnet\.chain\.robinhood\.com)\//.test(url||'');
}
function renderHistory(tips){
  var target=$('oa-tip-history');
  if(!target)return;
  target.replaceChildren();
  if(!tips.length){target.appendChild(make('div','oa-tip-empty','No tips yet. Tips you send or receive will appear here.'));return}
  var requested=new URLSearchParams(location.search).get('tip');
  tips.forEach(function(t){
    var sent=t.direction==='sent';
    var row=make('article','oa-tip-row'+(String(t.id)===requested?' oa-tip-highlight':''));
    row.id='oa-tip-'+t.id;
    var icon=make('div','oa-tip-row-icon '+(sent?'sent':'received'),sent?'↗':'↙');
    var content=make('div','oa-tip-row-main');
    content.appendChild(make('strong','',sent?'Tip sent':'Tip received'));
    var peer=make('a','oa-tip-peer',(sent?'To @':'From @')+(sent?t.recipient_username:t.sender_username));
    peer.href=sent?t.recipient_profile:t.sender_profile;
    content.appendChild(peer);
    content.appendChild(make('small','',when(t.created_at)+' · '+(t.chain||'').replace(/^./,function(x){return x.toUpperCase()})));
    var right=make('div','oa-tip-row-right');
    right.appendChild(make('strong',sent?'oa-tip-negative':'oa-tip-positive',(sent?'−':'+')+money(t.amount)+' USDC'));
    right.appendChild(make('span','oa-tip-pill '+t.status,stateLabel(t.status)));
    var detail=make('div','oa-tip-row-detail');
    detail.appendChild(make('span','',t.status==='confirmed'?'On-chain confirmed':t.status==='submitted'?'Awaiting on-chain confirmation':(t.failure_reason||'Transaction failed')));
    if(validExplorer(t.explorer_url)){
      var link=make('a','','View transaction ↗');
      link.href=t.explorer_url;link.rel='noopener noreferrer';link.target='_blank';
      detail.appendChild(link);
    }
    row.append(icon,content,right,detail);
    target.appendChild(row);
  });
  if(requested){
    var active=$('oa-tip-'+requested);
    if(active)setTimeout(function(){active.scrollIntoView({behavior:'smooth',block:'center'})},140);
  }
}
var historyTimer=null;
function loadHistory(){
  if(!$('oa-tip-history'))return;
  json('/api/tips/mine?limit=100').then(function(d){
    if(!d.ok)return;
    var tips=d.tips||[];
    renderHistory(tips);
    clearTimeout(historyTimer);
    if(tips.some(function(t){return t.status==='submitted'})){
      historyTimer=setTimeout(function(){if(!document.hidden)loadHistory()},10000);
    }
  }).catch(function(){
    if($('oa-tip-history'))$('oa-tip-history').textContent='Tip history is temporarily unavailable.';
  });
}
window.OrcAgentRefreshTipHistory=loadHistory;
function boot(){
  refreshStats();
  refreshProfileBalance();
  if($('oa-tip-history')){
    loadHistory();
    var btn=$('oa-tip-history-refresh');
    if(btn)btn.addEventListener('click',loadHistory);
    document.querySelectorAll('[data-portfolio-tab="history"]').forEach(function(btn){
      btn.addEventListener('click',function(){loadHistory()});
    });
  }
  if($('oa-tip-stats'))setInterval(function(){if(!document.hidden)refreshStats()},30000);
  if($('oa-profile-balance'))setInterval(function(){if(!document.hidden)refreshProfileBalance()},45000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
else boot();
})();
