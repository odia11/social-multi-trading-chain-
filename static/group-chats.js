/* Group chats in Messages, WhatsApp-style (group_chats.py).

   - "New group" next to compose: pick people who follow you or whom you
     follow (search by @username), name the group, done.
   - Groups are listed above your chats, with unread counts.
   - The chat opens full screen: text and photos, the sender's name over
     their messages, small grey lines for joins, leaves and renames.
   - Group info: whoever started the group owns it -- they choose admins and
     can delete the group. Admins rename it, change its photo and add or
     remove members; anyone can leave.
   - /messages?group=<id> (what a notification opens) opens the group. */
(function(){
'use strict';
if(window.__oaGroupChats)return;
window.__oaGroupChats=true;

var chats=[], open=null, pollTimer=null, listTimer=null, sending=0, pendingSeq=0;

function csrf(){return window._csrfToken||((document.querySelector('meta[name="csrf-token"]')||{}).content)||'';}
function api(path,opts){
  opts=opts||{};
  var init={method:opts.method||'GET',credentials:'same-origin',cache:'no-store',headers:{}};
  if(opts.body!==undefined){init.headers['Content-Type']='application/json';init.body=JSON.stringify(opts.body);}
  if(init.method!=='GET')init.headers['X-CSRF-Token']=csrf();
  return fetch(path,init).then(function(r){return r.json().catch(function(){return {ok:false,msg:'Something went wrong'};});})
    .catch(function(){return {ok:false,msg:'No connection. Try again.'};});
}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function safeImg(u){
  u=String(u||'');
  if(/^data:image\/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+$/i.test(u))return u;
  if(/^https:\/\//i.test(u)||/^\/(?!\/)/.test(u))return u;
  return '';
}
function initial(name){return (String(name||'?').replace(/^@/,'').charAt(0)||'?').toUpperCase();}
function color(seed){
  if(typeof window._avatarColor==='function')return window._avatarColor(String(seed||''));
  return '#6366f1';
}
function parseTs(ts){return new Date(String(ts||'').indexOf('T')<0?String(ts).replace(' ','T')+'Z':ts);}
function ago(ts){
  if(typeof window._timeAgo==='function')return window._timeAgo(ts);
  return '';
}
function clock(ts){var d=parseTs(ts);return isNaN(d)?'':d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}
function dayLabel(ts){
  var d=parseTs(ts);if(isNaN(d))return '';
  var today=new Date();today.setHours(0,0,0,0);
  var day=new Date(d);day.setHours(0,0,0,0);
  var diff=Math.round((today-day)/86400000);
  if(diff===0)return 'Today';
  if(diff===1)return 'Yesterday';
  return d.toLocaleDateString([], {day:'numeric',month:'short',year:day.getFullYear()===today.getFullYear()?undefined:'numeric'});
}
function every(fn,ms){
  var L=window.OrcPageLifecycle;
  return L&&L.setInterval?L.setInterval(fn,ms):window.setInterval(fn,ms);
}
function toast(msg){
  if(typeof window._toast==='function')return window._toast(msg);
  var t=document.createElement('div');t.className='gc-toast';t.textContent=msg;document.body.appendChild(t);
  setTimeout(function(){t.remove();},2600);
}

var ICON={
  group:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  groupAdd:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6"/><path d="M22 11h-6"/></svg>',
  back:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
  info:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
  photo:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>',
  send:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/></svg>',
  check:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg>',
  camera:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
  smile:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01"/><path d="M15 9h.01"/></svg>',
  more:'<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  close:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>'
};
// The same set as the emoji panel in direct messages.
var EMOJI=['😀','😂','🤣','😍','🥰','😎','🤔','😅','😉','😢','😭','😡','😱','😴','🥳','🤯','🙌','👏','👍','👎','🙏','🤝','💪','👀','🔥','💯','✅','❌','🚀','📈','📉','💰','💎','❤️','🎉'];
var VERIFIED='<svg class="conv-verified" viewBox="0 0 24 24" aria-label="Verified"><circle cx="12" cy="12" r="12" fill="#f7b955"/><path d="M7 12.5l3.2 3.2L17 9" stroke="#0a0b0e" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function avatarHtml(cls,name,seed,url){
  var img=safeImg(url);
  return '<span class="'+cls+'" style="--oa-av:'+esc(color(seed))+'">'+esc(initial(name))
    +(img?'<img src="'+esc(img)+'" alt="" loading="lazy" onerror="this.remove()">':'')+'</span>';
}

/* ── the list ─────────────────────────────────────────────────────────── */
function section(){
  var s=document.getElementById('gc-section');
  if(s)return s;
  var list=document.getElementById('conv-list');
  if(!list)return null;
  s=document.createElement('div');s.id='gc-section';s.className='gc-section';
  list.parentNode.insertBefore(s,list);
  return s;
}
function previewOf(c){
  var l=c.last;if(!l)return 'No messages yet';
  if(l.kind==='system')return esc(l.text);
  var who=l.mine?'You: ':(l.sender?esc(l.sender)+': ':'');
  return who+(l.kind==='image'?'📷 Photo':esc(l.text));
}
function setListHtml(s,html){
  if(typeof window._reconcileInbox==='function') window._reconcileInbox(s,html,'data-gc');
  else if(s.innerHTML!==html) s.innerHTML=html;
}
function renderList(){
  var s=section();if(!s)return;
  var filter=window._convFilter==='unread';
  var q=((document.getElementById('msgs-search')||{}).value||'').trim().toLowerCase();
  var shown=chats.filter(function(c){
    if(filter&&!c.unread)return false;
    if(q&&c.name.toLowerCase().indexOf(q)<0)return false;
    return true;
  });
  if(!q&&!filter)setTimeout(remember,0);
  var chips=document.getElementById('oa-inbox-filters');
  if(chips&&chats.length)chips.hidden=false;
  if(!chats.length){
    setListHtml(s,q||filter?'':'<button type="button" class="gc-cta" data-gc-new>'
      +'<span class="gc-cta-ico">'+ICON.groupAdd+'</span>'
      +'<span class="gc-cta-copy"><b>New group</b><small>Chat with your followers, together</small></span></button>');
    return;
  }
  if(!shown.length){setListHtml(s,'');return;}
  setListHtml(s,'<div class="oa-active-title gc-title">Groups</div>'+shown.map(function(c){
    var unread=c.unread>0;
    return '<div class="conv-row-wrap gc-row-wrap'+(unread?' is-unread':'')+'" data-gc="'+c.id+'">'
      +'<div class="conv-row" role="button" tabindex="0" aria-label="Open group '+esc(c.name)+'">'
      +'<div class="conv-avatar-wrap">'+avatarHtml('conv-avatar gc-avatar',c.name,'g'+c.id,c.photo)
      +'<span class="gc-people-badge" aria-hidden="true">'+ICON.group+'</span></div>'
      +'<div class="conv-info"><div class="conv-top"><div class="conv-name">'+esc(c.name)+'</div>'
      +'<span class="conv-time">'+esc(c.last?ago(c.last.created_at):'')+'</span></div>'
      +'<div class="conv-bottom"><div class="conv-preview'+(unread?' unread':'')+'">'+previewOf(c)+'</div>'
      +(unread?'<span class="conv-badge" aria-label="'+c.unread+' unread">'+(c.unread>99?'99+':c.unread)+'</span>':'')
      +'</div></div></div></div>';
  }).join(''));
}
// What the list looked like, for the next visit to paint before the chats.
function remember(){
  var s=document.getElementById('gc-section');
  if(s)try{sessionStorage.setItem('oa_gc_html',JSON.stringify({w:window._myWallet||'',h:s.innerHTML}));}catch(_){}
}
// The last list seen this session is painted at once, so the chats below
// do not jump down when the groups arrive.
function cacheKey(){return 'oa_gc_list:'+(window._myWallet||'');}
function loadList(first){
  var req=first&&window.__gcFirst?window.__gcFirst.then(function(d){return d||api('/api/group-chats');}):api('/api/group-chats');
  return req.then(function(d){
    if(!d||!d.ok)return;
    chats=d.chats||[];renderList();
    try{sessionStorage.setItem(cacheKey(),JSON.stringify(chats.slice(0,30)));}catch(_){}
  });
}
function restoreList(){
  try{var c=JSON.parse(sessionStorage.getItem(cacheKey())||'null');if(Array.isArray(c)){chats=c;renderList();}}catch(_){}
}

/* ── the chat ─────────────────────────────────────────────────────────── */
function threadEl(){
  var t=document.getElementById('gc-thread');
  if(t)return t;
  t=document.createElement('div');t.id='gc-thread';t.className='gc-thread';t.hidden=true;
  t.setAttribute('role','dialog');t.setAttribute('aria-modal','true');t.setAttribute('aria-label','Group chat');
  t.innerHTML='<header class="gc-th-hd">'
    +'<button type="button" class="gc-icon-btn" data-gc-close aria-label="Back">'+ICON.back+'</button>'
    +'<button type="button" class="gc-th-title" data-gc-info>'
    +'<span class="gc-th-av"></span><span class="gc-th-names"><b class="gc-th-name"></b><small class="gc-th-sub"></small></span></button>'
    +'<button type="button" class="gc-icon-btn" data-gc-info aria-label="Group info">'+ICON.info+'</button></header>'
    +'<div class="gc-th-body"><div class="gc-msgs" aria-live="polite"></div></div>'
    +'<form class="gc-composer" autocomplete="off">'
    +'<button type="button" class="gc-icon-btn gc-photo" aria-label="Send a photo">'+ICON.photo+'</button>'
    +'<input type="file" accept="image/jpeg,image/png,image/gif,image/webp" class="gc-file" hidden>'
    +'<button type="button" class="gc-icon-btn gc-emoji" aria-label="Emoji" aria-expanded="false">'+ICON.smile+'</button>'
    +'<div class="gc-emoji-panel" role="dialog" aria-label="Emoji" hidden>'+EMOJI.map(function(e){return '<button type="button" aria-label="'+e+'">'+e+'</button>';}).join('')+'</div>'
    +'<textarea class="gc-input" rows="1" maxlength="1000" placeholder="Message" aria-label="Message"></textarea>'
    +'<button type="submit" class="gc-send" aria-label="Send" disabled>'+ICON.send+'</button></form>';
  document.body.appendChild(t);
  var input=t.querySelector('.gc-input'),send=t.querySelector('.gc-send'),form=t.querySelector('.gc-composer');
  input.addEventListener('input',function(){
    send.disabled=!input.value.trim();
    input.style.height='auto';input.style.height=Math.min(input.scrollHeight,120)+'px';
  });
  input.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&!e.shiftKey&&!('ontouchstart' in window)){e.preventDefault();form.requestSubmit?form.requestSubmit():form.dispatchEvent(new Event('submit',{cancelable:true}));}
  });
  var bodyEl=t.querySelector('.gc-th-body');
  bodyEl.addEventListener('scroll',function(){atBottom=bodyEl.scrollHeight-bodyEl.scrollTop-bodyEl.clientHeight<80;},{passive:true});
  // iOS may still scroll the page to show the field; keep the chat on screen.
  input.addEventListener('focus',function(){setTimeout(fitViewport,50);setTimeout(fitViewport,350);});
  input.addEventListener('blur',function(){setTimeout(fitViewport,50);});
  form.addEventListener('submit',function(e){e.preventDefault();emojiPanel(false);sendText();});
  var smile=t.querySelector('.gc-emoji'),panel=t.querySelector('.gc-emoji-panel');
  smile.addEventListener('click',function(){emojiPanel(panel.hidden);});
  // pointerdown + preventDefault keeps the keyboard (and the cursor) where it is.
  panel.addEventListener('pointerdown',function(e){if(e.target.closest('button'))e.preventDefault();});
  panel.addEventListener('click',function(e){
    var b=e.target.closest('button');if(!b)return;
    var em=b.textContent,a=input.selectionStart,z=input.selectionEnd;
    if(typeof a!=='number'){a=z=input.value.length;}
    if((input.value.length+em.length)>1000)return;
    input.value=input.value.slice(0,a)+em+input.value.slice(z);
    input.selectionStart=input.selectionEnd=a+em.length;
    input.dispatchEvent(new Event('input'));
  });
  document.addEventListener('pointerdown',function(e){
    if(!panel.hidden&&!panel.contains(e.target)&&!smile.contains(e.target))emojiPanel(false);
  });
  t.querySelector('.gc-photo').addEventListener('click',function(){t.querySelector('.gc-file').click();});
  t.querySelector('.gc-file').addEventListener('change',function(){var f=this.files&&this.files[0];this.value='';if(f)sendPhoto(f);});
  return t;
}
function emojiPanel(show){
  var t=document.getElementById('gc-thread');if(!t)return;
  var panel=t.querySelector('.gc-emoji-panel');
  panel.hidden=!show;t.querySelector('.gc-emoji').setAttribute('aria-expanded',show?'true':'false');
}
function paintHeader(){
  var t=threadEl();if(!open)return;
  t.querySelector('.gc-th-av').outerHTML=avatarHtml('gc-th-av',open.name,'g'+open.id,open.photo);
  t.querySelector('.gc-th-name').textContent=open.name;
  var names=(open.members||[]).map(function(m){return m.username;});
  t.querySelector('.gc-th-sub').textContent=names.length?(names.length+' members · '+names.slice(0,4).join(', ')+(names.length>4?'…':'')):'';
}
function messageHtml(m,prev){
  var html='';
  var day=dayLabel(m.created_at);
  if(!prev||dayLabel(prev.created_at)!==day)html+='<div class="gc-day"><span>'+esc(day)+'</span></div>';
  if(m.kind==='system')return html+'<div class="gc-sys" data-mid="'+m.id+'"><span>'+esc(m.body)+'</span></div>';
  var runStart=!prev||prev.kind==='system'||prev.sender_id!==m.sender_id||dayLabel(prev.created_at)!==day;
  var body=m.kind==='image'
    ?(safeImg(m.body)?'<img class="gc-img" src="'+esc(safeImg(m.body))+'" alt="Photo" loading="lazy">':'')
    :esc(m.body).replace(/\n/g,'<br>');
  var cls='gc-msg'+(m.mine?' mine':'')+(runStart?' run-start':'')+(m.pending?' pending':'')+(m.failed?' failed':'')+(m.kind==='image'?' is-image':'');
  html+='<div class="'+cls+'" data-mid="'+esc(m.id)+'">';
  if(!m.mine){
    html+=runStart?avatarHtml('gc-msg-av',m.sender,m.sender_wallet,m.sender_avatar):'<span class="gc-msg-av gc-msg-av-space"></span>';
  }
  html+='<div class="gc-bubble">'
    +(!m.mine&&runStart?'<div class="gc-sender" style="--gc-name:'+esc(color(m.sender_wallet))+'">'+esc(m.sender)+'</div>':'')
    +'<div class="gc-text">'+body+'</div>'
    +'<span class="gc-time">'+(m.failed?'Not sent · tap to retry':(m.pending?'Sending…':esc(clock(m.created_at))))+'</span></div></div>';
  return html;
}
function renderMessages(stick){
  var t=threadEl(),box=t.querySelector('.gc-msgs'),body=t.querySelector('.gc-th-body');
  var near=body.scrollHeight-body.scrollTop-body.clientHeight<120;
  var ms=open.messages,html='';
  for(var i=0;i<ms.length;i++)html+=messageHtml(ms[i],ms[i-1]);
  box.innerHTML=html||'<div class="gc-empty">Say hi to the group 👋</div>';
  if(stick||near)body.scrollTop=body.scrollHeight;
}
function mergeMessages(list){
  var have={};open.messages.forEach(function(m){have[m.id]=1;});
  var added=false;
  list.forEach(function(m){if(!have[m.id]){open.messages.push(m);added=true;}});
  list.forEach(function(m){if(m.id>open.lastId)open.lastId=m.id;});
  return added;
}
function fetchNew(){
  if(!open||document.hidden)return;
  var id=open.id;
  api('/api/group-chats/'+id+'/messages?after='+open.lastId).then(function(d){
    if(!open||open.id!==id)return;
    if(!d.ok){
      // Deleted by its owner, or you were removed.
      if(/not found/i.test(d.msg||'')){chats=chats.filter(function(c){return c.id!==id;});toast('This group is no longer available');closeGroup();}
      return;
    }
    var news=(d.messages||[]).filter(function(m){return m.kind==='system';}).length;
    if(mergeMessages(d.messages||[]))renderMessages(false);
    // Someone renamed it, changed the photo, or changed who is in it.
    if(news)api('/api/group-chats/'+id).then(function(x){if(x.ok)adopt(x.chat);});
  });
}
function openGroup(id,push){
  id=Number(id);if(!id)return;
  var c=chats.find(function(x){return x.id===id;})||{id:id,name:'Group',members:0};
  open={id:id,name:c.name,role:c.role,photo:c.photo||'',members:[],messages:[],lastId:0};
  window.__oaOpenGroupId=id;
  var t=threadEl();t.hidden=false;atBottom=true;fitViewport();
  document.documentElement.classList.add('gc-lock');document.body.classList.add('gc-open');
  t.querySelector('.gc-msgs').innerHTML='<div class="gc-empty">Loading…</div>';
  paintHeader();
  if(push!==false){
    try{history.pushState({gc:id},'',location.pathname+'?group='+id);}catch(_){}
  }
  api('/api/group-chats/'+id).then(function(d){
    if(!open||open.id!==id)return;
    if(!d.ok){toast(d.msg||'Group not found');closeGroup();return;}
    adopt(d.chat);
  });
  api('/api/group-chats/'+id+'/messages').then(function(d){
    if(!open||open.id!==id||!d.ok)return;
    open.messages=[];mergeMessages(d.messages||[]);renderMessages(true);
    c.unread=0;renderList();
  });
  if(pollTimer)window.clearInterval(pollTimer);
  pollTimer=window.setInterval(fetchNew,3000);
  setTimeout(function(){var i=t.querySelector('.gc-input');if(i&&!('ontouchstart' in window))i.focus();},60);
}
// The group as the server sees it now: name, photo, members, my role.
function adopt(chat){
  if(!open||open.id!==chat.id)return;
  open.name=chat.name;open.role=chat.role;open.owner=!!chat.is_owner;open.photo=chat.photo||'';
  open.members=chat.members;open.createdBy=chat.created_by;
  var c=chats.find(function(x){return x.id===chat.id;});
  if(c){c.name=chat.name;c.photo=open.photo;c.role=chat.role;renderList();}
  paintHeader();
}
// On a phone the keyboard does not shrink the page: iOS slides the visible
// part up instead, so a chat pinned to the page showed what lies under it
// between the composer and the keyboard, and lost its header. The chat is
// sized to exactly what is visible, as direct messages do.
var atBottom=true;
function fitViewport(){
  var t=document.getElementById('gc-thread'),vv=window.visualViewport;
  if(!t||t.hidden||!vv||!open)return;
  if(window.innerWidth>=768&&!window.matchMedia('(pointer:coarse)').matches)return;
  t.style.top=Math.round(vv.offsetTop)+'px';
  t.style.height=Math.round(vv.height)+'px';
  t.style.bottom='auto';
  if(atBottom){var b=t.querySelector('.gc-th-body');b.scrollTop=b.scrollHeight;}
}
if(window.visualViewport){
  window.visualViewport.addEventListener('resize',fitViewport);
  window.visualViewport.addEventListener('scroll',fitViewport);
}
function closeGroup(fromPop){
  if(pollTimer){window.clearInterval(pollTimer);pollTimer=null;}
  open=null;window.__oaOpenGroupId=null;emojiPanel(false);
  var t=document.getElementById('gc-thread');
  if(t){t.hidden=true;t.style.removeProperty('top');t.style.removeProperty('height');t.style.removeProperty('bottom');}
  closeSheet();
  document.documentElement.classList.remove('gc-lock');document.body.classList.remove('gc-open');
  if(!fromPop&&/[?&]group=/.test(location.search)){
    try{if(history.state&&history.state.gc)history.back();else history.replaceState(null,'',location.pathname);}catch(_){}
  }
  loadList();
}
function sendText(){
  var t=threadEl(),input=t.querySelector('.gc-input'),text=input.value.trim();
  if(!text||!open)return;
  input.value='';input.style.height='auto';t.querySelector('.gc-send').disabled=true;
  postMessage({message:text},{kind:'text',body:text});
}
function postMessage(payload,local){
  var id=open.id,tmp='p'+(++pendingSeq);
  var msg={id:tmp,sender_id:0,kind:local.kind,body:local.body,created_at:new Date().toISOString().slice(0,19).replace('T',' '),
           mine:true,pending:true,sender:'You'};
  open.messages.push(msg);renderMessages(true);
  sending++;
  api('/api/group-chats/'+id+'/messages',{method:'POST',body:payload}).then(function(d){
    sending--;
    if(!open||open.id!==id)return;
    var i=open.messages.indexOf(msg);
    if(d.ok&&d.message){
      if(i>=0)open.messages.splice(i,1);
      mergeMessages([d.message]);
    }else{
      msg.pending=false;msg.failed=true;msg.retry=payload;
      toast(d.msg||'Message not sent');
    }
    open.messages.sort(function(a,b){return (typeof a.id==='number'?a.id:1e15)-(typeof b.id==='number'?b.id:1e15);});
    renderMessages(true);
  });
}
function retry(mid){
  if(!open)return;
  var m=open.messages.find(function(x){return String(x.id)===String(mid);});
  if(!m||!m.failed)return;
  open.messages.splice(open.messages.indexOf(m),1);
  postMessage(m.retry,{kind:m.kind,body:m.body});
}
function sendPhoto(file){
  if(!/^image\/(jpeg|png|gif|webp)$/.test(file.type)){toast('Choose a JPEG, PNG, GIF or WebP photo');return;}
  if(file.size>12*1024*1024){toast('That photo is too large');return;}
  var reader=new FileReader();
  reader.onload=function(){
    var src=String(reader.result||'');
    if(file.type==='image/gif'){postMessage({message:src,message_type:'image'},{kind:'image',body:src});return;}
    var img=new Image();
    img.onload=function(){
      var max=1600,w=img.naturalWidth,h=img.naturalHeight,k=Math.min(1,max/Math.max(w,h));
      var cv=document.createElement('canvas');cv.width=Math.round(w*k);cv.height=Math.round(h*k);
      cv.getContext('2d').drawImage(img,0,0,cv.width,cv.height);
      var out=cv.toDataURL('image/jpeg',0.85);
      postMessage({message:out,message_type:'image'},{kind:'image',body:out});
    };
    img.onerror=function(){toast('That photo could not be read');};
    img.src=src;
  };
  reader.readAsDataURL(file);
}

/* ── sheets: new group, add people, group info ───────────────────────── */
function sheet(html,cls){
  closeSheet();
  var back=document.createElement('div');back.className='gc-sheet-back';back.id='gc-sheet';
  back.innerHTML='<div class="gc-sheet '+(cls||'')+'" role="dialog" aria-modal="true"><div class="gc-sheet-handle"></div>'+html+'</div>';
  back.addEventListener('click',function(e){if(e.target===back)closeSheet();});
  document.body.appendChild(back);
  document.documentElement.classList.add('gc-lock');
  requestAnimationFrame(function(){back.classList.add('on');});
  return back.querySelector('.gc-sheet');
}
function closeSheet(){
  var s=document.getElementById('gc-sheet');if(s)s.remove();
  if(!open)document.documentElement.classList.remove('gc-lock');
}
function personRow(p,selected){
  return '<button type="button" class="gc-person'+(selected?' on':'')+'" data-uid="'+p.user_id+'">'
    +avatarHtml('gc-person-av',p.username,p.wallet,p.avatar)
    +'<span class="gc-person-copy"><b>'+esc(p.username)+(p.verified?VERIFIED:'')+'</b>'
    +'<small>'+(p.follows_you?'Follows you':'You follow')+'</small></span>'
    +'<span class="gc-check">'+ICON.check+'</span></button>';
}
function picker(opts){
  var picked={},people=[],seq=0;
  var el=sheet('<div class="gc-sheet-hd"><button type="button" class="gc-icon-btn" data-sheet-close aria-label="Close">'+ICON.close+'</button>'
    +'<h3>'+esc(opts.title)+'</h3><span class="gc-sheet-count"></span></div>'
    +'<div class="gc-step gc-step-pick">'
    +'<div class="gc-search"><input type="search" placeholder="Search your followers by @username" aria-label="Search by username" autocomplete="off"></div>'
    +'<div class="gc-chips"></div><div class="gc-people" aria-live="polite"><div class="gc-hint">Loading…</div></div>'
    +'<div class="gc-sheet-foot"><button type="button" class="gc-primary gc-next" disabled>'+esc(opts.next)+'</button></div></div>'
    +(opts.create?'<div class="gc-step gc-step-name" hidden>'
      +'<label class="gc-label" for="gc-name">Group name</label>'
      +'<input id="gc-name" class="gc-name-input" maxlength="40" placeholder="e.g. Moon crew" autocomplete="off">'
      +'<div class="gc-chips gc-chips-static"></div>'
      +'<div class="gc-sheet-foot"><button type="button" class="gc-ghost gc-prev">Back</button>'
      +'<button type="button" class="gc-primary gc-create" disabled>Create group</button></div></div>':''),'gc-sheet-picker');
  var input=el.querySelector('.gc-search input'),list=el.querySelector('.gc-people'),chipsEl=el.querySelector('.gc-chips'),
      next=el.querySelector('.gc-next'),count=el.querySelector('.gc-sheet-count');
  el.querySelector('[data-sheet-close]').onclick=closeSheet;
  function chosen(){return Object.keys(picked).map(function(k){return picked[k];});}
  function paintChips(target){
    var ch=chosen();
    (target||chipsEl).innerHTML=ch.map(function(p){
      return '<button type="button" class="gc-chip" data-uid="'+p.user_id+'">'+avatarHtml('gc-chip-av',p.username,p.wallet,p.avatar)
        +'<span>'+esc(p.username)+'</span>'+(target?'':'<i aria-hidden="true">'+ICON.close+'</i>')+'</button>';
    }).join('');
    count.textContent=ch.length?ch.length+' selected':'';
    next.disabled=!ch.length;
  }
  function paintPeople(){
    if(!people.length){
      list.innerHTML='<div class="gc-hint">'+(input.value.trim()
        ?'No follower or followed account matches “'+esc(input.value.trim())+'”.'
        :'Nobody to add yet. You can add people who follow you or whom you follow.')+'</div>';
      return;
    }
    list.innerHTML=people.map(function(p){return personRow(p,!!picked[p.user_id]);}).join('');
  }
  function search(){
    var my=++seq,q=input.value.trim();
    api('/api/group-chats/candidates?q='+encodeURIComponent(q)+(opts.chatId?'&chat_id='+opts.chatId:'')).then(function(d){
      if(my!==seq)return;
      people=d.ok?(d.people||[]):[];paintPeople();
    });
  }
  var timer=null;
  input.addEventListener('input',function(){clearTimeout(timer);timer=setTimeout(search,180);});
  list.addEventListener('click',function(e){
    var b=e.target.closest('.gc-person');if(!b)return;
    var uid=Number(b.dataset.uid),p=people.find(function(x){return x.user_id===uid;});
    if(picked[uid])delete picked[uid];else if(p)picked[uid]=p;
    b.classList.toggle('on',!!picked[uid]);paintChips();
  });
  chipsEl.addEventListener('click',function(e){
    var b=e.target.closest('.gc-chip');if(!b)return;
    delete picked[b.dataset.uid];paintChips();paintPeople();
  });
  next.addEventListener('click',function(){
    if(!opts.create){next.disabled=true;opts.done(chosen().map(function(p){return p.user_id;}),function(){next.disabled=false;});return;}
    el.querySelector('.gc-step-pick').hidden=true;el.querySelector('.gc-step-name').hidden=false;
    paintChips(el.querySelector('.gc-chips-static'));
    var name=el.querySelector('#gc-name');setTimeout(function(){name.focus();},40);
  });
  if(opts.create){
    var name=el.querySelector('#gc-name'),create=el.querySelector('.gc-create');
    name.addEventListener('input',function(){create.disabled=!name.value.trim();});
    name.addEventListener('keydown',function(e){if(e.key==='Enter'&&!create.disabled){e.preventDefault();create.click();}});
    el.querySelector('.gc-prev').onclick=function(){el.querySelector('.gc-step-name').hidden=true;el.querySelector('.gc-step-pick').hidden=false;};
    create.addEventListener('click',function(){
      create.disabled=true;create.textContent='Creating…';
      opts.done({name:name.value.trim(),user_ids:chosen().map(function(p){return p.user_id;})},function(){create.disabled=false;create.textContent='Create group';});
    });
  }
  search();
  setTimeout(function(){if(!('ontouchstart' in window))input.focus();},60);
}
function newGroup(){
  picker({title:'New group',next:'Next',create:true,done:function(body,reset){
    api('/api/group-chats',{method:'POST',body:body}).then(function(d){
      if(!d.ok){reset();toast(d.msg||'Could not create the group');return;}
      closeSheet();
      chats.unshift({id:d.chat.id,name:d.chat.name,role:'admin',members:d.chat.members.length,unread:0,last:null});
      renderList();openGroup(d.chat.id);
    });
  }});
}
function addPeople(){
  if(!open)return;
  var id=open.id;
  picker({title:'Add people',next:'Add',chatId:id,done:function(ids,reset){
    api('/api/group-chats/'+id+'/members',{method:'POST',body:{user_ids:ids}}).then(function(d){
      if(!d.ok){reset();toast(d.msg||'Could not add them');return;}
      adopt(d.chat);fetchNew();
      showInfo();
    });
  }});
}
function roleLabel(m){
  return m.owner?'<small class="gc-admin">Group owner</small>'
    :m.role==='admin'?'<small class="gc-admin">Group admin</small>':'<small>Member</small>';
}
function showInfo(){
  if(!open)return;
  var admin=open.role==='admin',owner=!!open.owner;
  var el=sheet('<div class="gc-sheet-hd"><button type="button" class="gc-icon-btn" data-sheet-close aria-label="Close">'+ICON.close+'</button><h3>Group info</h3><span></span></div>'
    +'<div class="gc-info-top">'
    +(admin?'<button type="button" class="gc-info-photo" aria-label="Change group photo">'+avatarHtml('gc-info-av',open.name,'g'+open.id,open.photo)
           +'<span class="gc-info-cam">'+ICON.camera+'</span></button>'
           +'<input type="file" accept="image/jpeg,image/png,image/gif,image/webp" class="gc-photo-file" hidden>'
           +(open.photo?'<button type="button" class="gc-link gc-photo-remove">Remove photo</button>':'')
           :avatarHtml('gc-info-av',open.name,'g'+open.id,open.photo))
    +(admin?'<div class="gc-rename"><input class="gc-name-input" maxlength="40" value="'+esc(open.name)+'" aria-label="Group name"><button type="button" class="gc-ghost gc-save" disabled>Save</button></div>'
           :'<div class="gc-info-name">'+esc(open.name)+'</div>')
    +'<small>'+open.members.length+' members</small></div>'
    +(admin?'<button type="button" class="gc-add-row">'+'<span class="gc-cta-ico">'+ICON.groupAdd+'</span><b>Add people</b></button>':'')
    +'<div class="gc-members">'+open.members.map(function(m){
      // The owner manages everyone; an admin manages members only.
      var manage=!isMe(m)&&!m.owner&&(owner||(admin&&m.role!=='admin'));
      return '<div class="gc-member">'+avatarHtml('gc-person-av',m.username,m.wallet,m.avatar)
        +'<a class="gc-person-copy" href="/profile/'+encodeURIComponent(m.wallet)+'"><b>'+esc(isMe(m)?'You':m.username)+(m.verified?VERIFIED:'')+'</b>'
        +roleLabel(m)+'</a>'
        +(manage?'<button type="button" class="gc-more" data-uid="'+m.user_id+'" aria-label="Options for '+esc(m.username)+'">'+ICON.more+'</button>':'')
        +'</div>';
    }).join('')+'</div>'
    +'<div class="gc-info-foot"><button type="button" class="gc-leave">Leave group</button>'
    +(owner?'<button type="button" class="gc-leave gc-delete">Delete group</button>':'')+'</div>','gc-sheet-info');
  el.querySelector('[data-sheet-close]').onclick=closeSheet;
  var add=el.querySelector('.gc-add-row');if(add)add.onclick=addPeople;
  var rename=el.querySelector('.gc-rename input'),save=el.querySelector('.gc-save');
  if(rename){
    rename.addEventListener('input',function(){save.disabled=!rename.value.trim()||rename.value.trim()===open.name;});
    save.onclick=function(){
      var id=open.id;save.disabled=true;
      api('/api/group-chats/'+id,{method:'PUT',body:{name:rename.value.trim()}}).then(function(d){
        if(!d.ok){toast(d.msg||'Could not rename');save.disabled=false;return;}
        adopt(d.chat);fetchNew();
        toast('Group renamed');
      });
    };
  }
  var pick=el.querySelector('.gc-info-photo'),file=el.querySelector('.gc-photo-file');
  if(pick){
    pick.onclick=function(){file.click();};
    file.addEventListener('change',function(){var f=this.files&&this.files[0];this.value='';if(f)setPhoto(f);});
  }
  var drop=el.querySelector('.gc-photo-remove');
  if(drop)drop.onclick=function(){
    var id=open.id;drop.disabled=true;
    api('/api/group-chats/'+id+'/photo',{method:'DELETE'}).then(function(d){
      if(!d.ok){toast(d.msg||'Could not remove the photo');drop.disabled=false;return;}
      adopt(d.chat);fetchNew();showInfo();
    });
  };
  el.querySelectorAll('.gc-more').forEach(function(b){
    b.onclick=function(){
      var m=open.members.find(function(x){return x.user_id===Number(b.dataset.uid);});
      if(m)memberMenu(m);
    };
  });
  el.querySelector('.gc-leave:not(.gc-delete)').onclick=function(){
    var id=open.id;
    confirmThen(owner&&open.members.length>1
      ?'Leave “'+open.name+'”? You own this group, so an admin (or the longest-standing member) takes over.'
      :'Leave “'+open.name+'”? You will stop getting its messages.',function(){
      api('/api/group-chats/'+id+'/leave',{method:'POST',body:{}}).then(function(d){
        if(!d.ok){toast(d.msg||'Could not leave');return;}
        chats=chats.filter(function(c){return c.id!==id;});
        closeSheet();closeGroup();toast('You left the group');
      });
    });
  };
  var del=el.querySelector('.gc-delete');
  if(del)del.onclick=function(){
    var id=open.id;
    confirmThen('Delete “'+open.name+'” for everyone? All messages and photos in it are removed. This cannot be undone.',function(){
      api('/api/group-chats/'+id,{method:'DELETE'}).then(function(d){
        if(!d.ok){toast(d.msg||'Could not delete the group');return;}
        chats=chats.filter(function(c){return c.id!==id;});
        closeSheet();closeGroup();toast('Group deleted');
      });
    });
  };
}
function confirmThen(text,yes){
  var ask=typeof window.openConfirmModal==='function'
    ?window.openConfirmModal({text:text,danger:true})
    :Promise.resolve(window.confirm(text));
  Promise.resolve(ask).then(function(ok){if(ok)yes();});
}
// What the owner (or an admin) can do with one member.
function memberMenu(m){
  var id=open.id,owner=!!open.owner;
  var el=sheet('<div class="gc-menu-who">'+avatarHtml('gc-person-av',m.username,m.wallet,m.avatar)
    +'<span class="gc-person-copy"><b>'+esc(m.username)+(m.verified?VERIFIED:'')+'</b>'+roleLabel(m)+'</span></div>'
    +'<div class="gc-menu">'
    +(owner?(m.role==='admin'
      ?'<button type="button" data-act="member">Dismiss as admin<small>They can no longer change the group or its members</small></button>'
      :'<button type="button" data-act="admin">Make group admin<small>Can rename the group, change its photo and add or remove members</small></button>'):'')
    +'<a href="/profile/'+encodeURIComponent(m.wallet)+'">View profile</a>'
    +'<button type="button" data-act="remove" class="gc-menu-danger">Remove from group</button>'
    +'<button type="button" data-act="back">Cancel</button></div>','gc-sheet-menu');
  el.addEventListener('click',function(e){
    var b=e.target.closest('[data-act]');if(!b)return;
    var act=b.dataset.act;
    if(act==='back'){showInfo();return;}
    b.disabled=true;
    var req=act==='remove'
      ?api('/api/group-chats/'+id+'/members/'+m.user_id,{method:'DELETE'})
      :api('/api/group-chats/'+id+'/members/'+m.user_id,{method:'PUT',body:{role:act}});
    req.then(function(d){
      if(!d.ok){toast(d.msg||'That did not work');b.disabled=false;return;}
      adopt(d.chat);fetchNew();showInfo();
      toast(act==='remove'?m.username+' removed':act==='admin'?m.username+' is now an admin':m.username+' is no longer an admin');
    });
  });
}
function setPhoto(file){
  if(!open)return;
  if(!/^image\/(jpeg|png|gif|webp)$/.test(file.type)){toast('Choose a JPEG, PNG, GIF or WebP photo');return;}
  if(file.size>12*1024*1024){toast('That photo is too large');return;}
  var id=open.id,reader=new FileReader();
  reader.onload=function(){
    var img=new Image();
    img.onload=function(){
      // Square, centred, 512 px: what an avatar needs.
      var side=Math.min(img.naturalWidth,img.naturalHeight),out=Math.min(512,side);
      var cv=document.createElement('canvas');cv.width=cv.height=out;
      cv.getContext('2d').drawImage(img,(img.naturalWidth-side)/2,(img.naturalHeight-side)/2,side,side,0,0,out,out);
      toast('Updating photo…');
      api('/api/group-chats/'+id+'/photo',{method:'PUT',body:{photo:cv.toDataURL('image/jpeg',0.86)}}).then(function(d){
        if(!d.ok){toast(d.msg||'Could not change the photo');return;}
        adopt(d.chat);fetchNew();
        if(document.querySelector('.gc-sheet-info'))showInfo();
        toast('Group photo updated');
      });
    };
    img.onerror=function(){toast('That photo could not be read');};
    img.src=String(reader.result||'');
  };
  reader.readAsDataURL(file);
}
function isMe(m){return !!(window._myWallet&&m.wallet===window._myWallet);}

/* ── wiring ───────────────────────────────────────────────────────────── */
function addHeaderButton(){
  var row=document.querySelector('.msgs-left-title-row'),compose=row&&row.querySelector('.msgs-new-btn');
  if(!row||!compose||row.querySelector('.gc-new-btn'))return;
  var b=document.createElement('button');
  b.type='button';b.className='gc-new-btn';b.title='New group';b.setAttribute('aria-label','New group');b.setAttribute('data-gc-new','');
  b.innerHTML=ICON.groupAdd;
  row.insertBefore(b,compose);
}
document.addEventListener('click',function(e){
  if(e.target.closest('[data-gc-new]')){e.preventDefault();newGroup();return;}
  var row=e.target.closest('.gc-row-wrap');
  if(row){openGroup(row.dataset.gc);return;}
  if(e.target.closest('[data-gc-close]')){closeGroup();return;}
  if(e.target.closest('[data-gc-info]')){showInfo();return;}
  var failed=e.target.closest('.gc-msg.failed');
  if(failed){retry(failed.dataset.mid);return;}
  var img=e.target.closest('.gc-img');
  if(img&&typeof window._showImgLightbox==='function'){window._showImgLightbox(img.src);}
});
document.addEventListener('keydown',function(e){
  if(e.key!=='Escape')return;
  if(document.getElementById('gc-sheet')){closeSheet();return;}
  var ep=document.querySelector('#gc-thread .gc-emoji-panel');
  if(ep&&!ep.hidden){emojiPanel(false);return;}
  if(open)closeGroup();
});
window.addEventListener('popstate',function(){
  var m=/[?&]group=(\d+)/.exec(location.search);
  if(m&&(!open||open.id!==Number(m[1])))openGroup(m[1],false);
  else if(!m&&open)closeGroup(true);
});
document.addEventListener('input',function(e){if(e.target&&e.target.id==='msgs-search')renderList();});
document.addEventListener('click',function(e){if(e.target.closest('.oa-inbox-chip'))setTimeout(renderList,0);});
document.addEventListener('visibilitychange',function(){if(!document.hidden){if(open)fetchNew();else loadList();}});

function boot(){
  if(!document.getElementById('conv-list'))return;
  addHeaderButton();
  restoreList();
  loadList(true).then(function(){
    var m=/[?&]group=(\d+)/.exec(location.search);
    if(m)openGroup(m[1],false);
  });
  listTimer=every(function(){if(!document.hidden&&!open)loadList();},12000);
}
window.OrcAgentGroupChats={open:openGroup,reload:loadList};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
