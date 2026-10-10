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
  if(opts.signal)init.signal=opts.signal;
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
  return '<span class="'+cls+'"'+(img&&cls==='gc-msg-av'?' role="button" tabindex="0" aria-label="View profile photo"':'')+' style="--oa-av:'+esc(color(seed))+'">'+esc(initial(name))
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
  if(l.kind==='tip')return '🎁 Group tip';
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
  var filter=(window._inboxTab==='groups'?window._convFilter:((window._inboxFilters||{}).groups))==='unread';
  var q=(window._inboxTab==='groups'?((document.getElementById('msgs-search')||{}).value||''):((window._inboxQueries||{}).groups||'')).trim().toLowerCase();
  window._groupInboxChats=chats;
  if(typeof window._renderInboxChrome==='function')window._renderInboxChrome();
  var shown=chats.filter(function(c){
    if(filter&&!c.unread)return false;
    if(q&&c.name.toLowerCase().indexOf(q)<0)return false;
    return true;
  });
  if(!q&&!filter)setTimeout(remember,0);
  if(!chats.length){
    setListHtml(s,q||filter?'':'<button type="button" class="gc-cta" data-gc-new>'
      +'<span class="gc-cta-ico">'+ICON.groupAdd+'</span>'
      +'<span class="gc-cta-copy"><b>New group</b><small>Chat with your followers, together</small></span></button>');
    return;
  }
  if(!shown.length){setListHtml(s,'<div class="msgs-left-empty">'+(q?'No groups found.':'No unread group chats.')+'</div>');return;}
  setListHtml(s,shown.map(function(c){
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
    +'<button type="button" class="gc-icon-btn gc-tip" aria-label="Tip the group">'+(window.OrcChatTip?window.OrcChatTip.gift:ICON.smile)+'</button>'
    +'<input type="file" accept="image/jpeg,image/png,image/gif,image/webp" class="gc-file" hidden>'
    +'<button type="button" class="gc-icon-btn gc-emoji" aria-label="Emoji" aria-expanded="false">'+ICON.smile+'</button>'
    +'<div class="gc-emoji-panel" role="dialog" aria-label="Emoji" hidden>'+EMOJI.map(function(e){return '<button type="button" aria-label="'+e+'">'+e+'</button>';}).join('')+'</div>'
    +'<textarea class="gc-input" rows="1" maxlength="1000" placeholder="Message" aria-label="Message"></textarea>'
    +'<button type="submit" class="gc-send" aria-label="Send" disabled>'+ICON.send+'</button></form>';
  document.body.appendChild(t);
  t.querySelector('.gc-tip').onclick=function(){if(open&&window.OrcChatTip)window.OrcChatTip.start({group:true,base:'/api/group-chats/'+open.id+'/tips',otherMemberCount:open.members&&open.members.length?Math.max(0,open.members.length-1):null,refresh:fetchNew});};
  var input=t.querySelector('.gc-input'),send=t.querySelector('.gc-send'),form=t.querySelector('.gc-composer');
  input.addEventListener('input',function(){
    send.disabled=!input.value.trim();
    input.style.height='auto';input.style.height=Math.min(input.scrollHeight,120)+'px';
  });
  input.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&!e.shiftKey&&!('ontouchstart' in window)){e.preventDefault();form.requestSubmit?form.requestSubmit():form.dispatchEvent(new Event('submit',{cancelable:true}));}
  });
  var bodyEl=t.querySelector('.gc-th-body');
  // Keep following the latest message through late photo/font layout changes.
  // Only user interaction releases the anchor; layout-generated scroll events
  // must not make a newly opened chat look like the user scrolled up.
  ['wheel','touchstart','pointerdown'].forEach(function(type){
    bodyEl.addEventListener(type,function(){atBottom=false;},{passive:true});
  });
  bodyEl.addEventListener('keydown',function(e){
    if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].indexOf(e.key)>=0)atBottom=false;
  });
  bodyEl.addEventListener('scroll',function(){
    if(!atBottom)atBottom=bodyEl.scrollHeight-bodyEl.scrollTop-bodyEl.clientHeight<80;
    if(bodyEl.scrollTop<60&&!atBottom)loadOlderMessages();
  },{passive:true});
  if(window.OrcPageLifecycle&&window.OrcPageLifecycle.resizeObserver&&window.ResizeObserver){
    var bottomObserver=window.OrcPageLifecycle.resizeObserver(function(){keepLatestVisible(t);});
    bottomObserver.observe(t.querySelector('.gc-msgs'));
    bottomObserver.observe(bodyEl);
  }
  bodyEl.addEventListener('load',function(){keepLatestVisible(t);},true);
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
  // Deleted tip cards disappear fully; versioned tombstones still sync to peers.
  if(m.kind==='deleted'&&m.body==='__tip_removed_from_chat__')return html;
  var runStart=!prev||prev.kind==='system'||prev.sender_id!==m.sender_id||dayLabel(prev.created_at)!==day;
  var body=m.kind==='image'
    ?(safeImg(m.body)?'<img class="gc-img" src="'+esc(safeImg(m.body))+'" alt="Photo" loading="lazy">':'')
    :esc(m.body).replace(/\n/g,'<br>');
  if(m.kind==='tip')body=window.OrcChatTip?window.OrcChatTip.card(m.body,true):'Group tip receipt';
  if(m.kind==='deleted')body='<span class="gc-deleted-text">Message deleted</span>';
  var cls='gc-msg'+(m.mine?' mine':'')+(runStart?' run-start':'')+(m.pending?' pending':'')+(m.failed?' failed':'')+(m.kind==='image'?' is-image':'');
  html+='<div class="'+cls+'" data-mid="'+esc(m.id)+'">';
  if(!m.mine){
    html+=runStart?avatarHtml('gc-msg-av',m.sender,m.sender_wallet,m.sender_avatar):'<span class="gc-msg-av gc-msg-av-space"></span>';
  }
  html+='<div class="gc-message-stack"><div class="gc-bubble">'
    +(!m.mine&&runStart?'<div class="gc-sender" style="--gc-name:'+esc(color(m.sender_wallet))+'">'+esc(m.sender)+'</div>':'')
    +'<div class="gc-text">'+body+'</div>'
    +(!m.pending&&!m.failed&&m.kind!=='deleted'&&(m.kind!=='tip'||m.mine)?'<button type="button" class="gc-message-more" data-message-menu="'+m.id+'" aria-label="Message options">'+ICON.more+'</button>':'')+'</div>'
    +(m.kind==='tip'?'':likeHtml(m))
    +'<span class="gc-time">'+(m.edited_at&&m.kind!=='deleted'?'Edited · ':'')+(m.failed?'Not sent · tap to retry':(m.pending?'Sending…':esc(clock(m.created_at))))+'</span></div></div>';
  return html;
}
function keepLatestVisible(t){
  if(!open||t.hidden||!atBottom)return;
  var body=t.querySelector('.gc-th-body');
  body.scrollTop=body.scrollHeight;
}
function renderMessages(stick){
  var t=threadEl(),box=t.querySelector('.gc-msgs'),body=t.querySelector('.gc-th-body');
  var near=body.scrollHeight-body.scrollTop-body.clientHeight<120;
  var ms=open.messages,html='';
  for(var i=0;i<ms.length;i++)html+=messageHtml(ms[i],ms[i-1]);
  var template=document.createElement('template');template.innerHTML=html||'<div class="gc-empty">Say hi to the group 👋</div>';
  var existing={};Array.from(box.children).forEach(function(el){if(el.dataset.mid)existing[el.dataset.mid]=el;});
  var cursor=box.firstElementChild;
  Array.from(template.content.children).forEach(function(next){
    var old=next.dataset.mid?existing[next.dataset.mid]:(cursor&&!cursor.dataset.mid&&cursor.outerHTML===next.outerHTML?cursor:null);
    var el=old&&old.outerHTML===next.outerHTML?old:next;
    if(el===cursor)cursor=cursor.nextElementSibling;
    else box.insertBefore(el,cursor);
  });
  while(cursor){var tail=cursor.nextElementSibling;cursor.remove();cursor=tail;}
  if(stick||near){atBottom=true;keepLatestVisible(t);}
}
function mergeMessages(list,updatesOnly){
  var have={};open.messages.forEach(function(m,i){have[m.id]=i;});
  var added=false;
  list.forEach(function(m){
    if(have[m.id]===undefined){if(!updatesOnly){have[m.id]=open.messages.length;open.messages.push(m);added=true;}}
    else{
      var previous=open.messages[have[m.id]];
      if(!previous._likePending&&(m.version||0)>=(previous.version||0)){
        var contentChanged=m.body!==previous.body||m.kind!==previous.kind||m.edited_at!==previous.edited_at;
        var likesChanged=!!m.liked!==!!previous.liked||JSON.stringify(m.likes||[])!==JSON.stringify(previous.likes||[]);
        open.messages[have[m.id]]=m;
        if(contentChanged)added=true;else if(likesChanged)paintLike(m);
      }
    }
    if(!updatesOnly&&m.id>open.lastId)open.lastId=m.id;
  });
  return added;
}
function loadOlderMessages(){
  if(!open||!open.hasMore||open.loadingOlder||!open.messages.length)return;
  var chat=open, before=chat.messages[0].id;
  chat.loadingOlder=true;
  api('/api/group-chats/'+chat.id+'/messages?before='+before).then(function(d){
    if(open!==chat||!d.ok)return;
    var body=threadEl().querySelector('.gc-th-body'),height=body.scrollHeight,top=body.scrollTop;
    mergeMessages(d.messages||[]);chat.messages.sort(function(a,b){return Number(a.id)-Number(b.id);});
    chat.hasMore=!!d.has_more;
    renderMessages(false);
    body.scrollTop=top+body.scrollHeight-height;
  }).finally(function(){chat.loadingOlder=false;});
}
function fetchNew(){
  if(!open||document.hidden||open.messages.some(function(m){return m._likePending;}))return;
  var id=open.id;
  return api('/api/group-chats/'+id+'/messages?after='+open.lastId+'&changes_since='+(open.changeVersion||0)).then(function(d){
    if(!open||open.id!==id)return;
    if(open.messages.some(function(m){return m._likePending;}))return;
    if(!d.ok){
      // Deleted by its owner, or you were removed.
      if(/not found/i.test(d.msg||'')){chats=chats.filter(function(c){return c.id!==id;});toast('This group is no longer available');closeGroup();}
      return;
    }
    var news=(d.messages||[]).filter(function(m){return m.kind==='system';}).length;
    var changed=mergeMessages(d.messages||[]);
    changed=mergeMessages(d.updates||[],true)||changed;
    open.changeVersion=Math.max(open.changeVersion||0,d.change_version||0);
    if(changed)renderMessages(false);
    // Someone renamed it, changed the photo, or changed who is in it.
    if(news)api('/api/group-chats/'+id).then(function(x){if(x.ok)adopt(x.chat);});
  });
}
function openGroup(id,push){
  if(window._setInboxTab)window._setInboxTab("groups");
  id=Number(id);if(!id)return;
  var c=chats.find(function(x){return x.id===id;})||{id:id,name:'Group',members:0};
  open={id:id,name:c.name,role:c.role,photo:c.photo||'',members:[],messages:[],lastId:0,changeVersion:0};
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
    open.messages=[];mergeMessages(d.messages||[]);open.changeVersion=d.change_version||0;open.hasMore=!!d.has_more;renderMessages(true);
    c.unread=0;renderList();
  });
  if(pollTimer)window.clearInterval(pollTimer);
  pollTimer=window.setInterval(fetchNew,3000);
  setTimeout(function(){var i=t.querySelector('.gc-input');if(i&&!('ontouchstart' in window))i.focus();},60);
}
// The group as the server sees it now: name, photo, members, my role.
function adopt(chat){
  if(!open||open.id!==chat.id)return;
  var ownerChanged=open.createdBy!==chat.created_by;
  open.name=chat.name;open.role=chat.role;open.owner=!!chat.is_owner;open.photo=chat.photo||'';
  open.members=chat.members;open.createdBy=chat.created_by;open.historyVisible=chat.history_visible!==false;
  var c=chats.find(function(x){return x.id===chat.id;});
  if(c){c.name=chat.name;c.photo=open.photo;c.role=chat.role;renderList();}
  paintHeader();
  if(ownerChanged&&document.querySelector('#gc-sheet .gc-sheet-info'))showInfo();
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
  if(window.OrcChatTip)window.OrcChatTip.close();
  closeReactionMenu();
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
    +(admin?'<label class="gc-history-setting"><span><b>Chat history for new members</b><small>Applies to people added from now on.</small></span><input type="checkbox" class="gc-history-toggle"'+(open.historyVisible?' checked':'')+' aria-label="Show chat history to new members"></label>':'')
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
  var historyToggle=el.querySelector('.gc-history-toggle');
  if(historyToggle)historyToggle.onchange=function(){
    var chat=open,visible=historyToggle.checked;historyToggle.disabled=true;
    api('/api/group-chats/'+chat.id+'/history',{method:'PUT',body:{visible:visible}}).then(function(d){
      if(open!==chat)return;
      if(!d.ok){historyToggle.checked=!visible;toast(d.msg||'Could not update history');return;}
      adopt(d.chat);toast(visible?'New members can see chat history':'New members see messages from when they join');
    }).finally(function(){historyToggle.disabled=false;});
  };
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
    +(owner?'<button type="button" data-act="owner">Make group owner<small>Transfer ownership; you remain a group admin</small></button>':'')
    +'<a href="/profile/'+encodeURIComponent(m.wallet)+'">View profile</a>'
    +'<button type="button" data-act="remove" class="gc-menu-danger">Remove from group</button>'
    +'<button type="button" data-act="back">Cancel</button></div>','gc-sheet-menu');
  el.addEventListener('click',function(e){
    var b=e.target.closest('[data-act]');if(!b)return;
    var act=b.dataset.act;
    if(act==='back'){showInfo();return;}
    if(act==='owner'){transferOwner(m,id);return;}
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
function transferOwner(m,id){
  var el=sheet('<h3>Transfer group ownership?</h3><p>'+esc(m.username)+' will become the group owner. You will remain an admin.</p><div class="gc-menu"><button type="button" class="gc-confirm-owner">Transfer ownership</button><button type="button" class="gc-cancel-owner">Cancel</button></div>','gc-sheet-menu');
  el.querySelector('.gc-cancel-owner').onclick=showInfo;
  el.querySelector('.gc-confirm-owner').onclick=function(){
    var button=this;button.disabled=true;
    api('/api/group-chats/'+id+'/owner',{method:'POST',body:{user_id:m.user_id}}).then(function(d){
      if(!open||open.id!==id){closeSheet();return;}
      if(!d.ok){toast(d.msg||'Could not transfer ownership');button.disabled=false;return;}
      adopt(d.chat);fetchNew();showInfo();toast(m.username+' is now the group owner');
    });
  };
}
function likeHtml(m){
  var likes=m.likes||[];if(m.pending||m.failed||m.kind==='deleted'||m.kind==='system')return '';
  if(!likes.length)return '<div class="gc-like-row"><button type="button" class="gc-like-pill gc-like-empty" data-message-like="'+m.id+'" data-emoji="❤️" aria-label="Like message" aria-pressed="false"><span aria-hidden="true">♡</span></button></div>';
  var grouped={};likes.forEach(function(l){var emoji=l.emoji||'❤️';if(!grouped[emoji])grouped[emoji]={count:0,mine:false};grouped[emoji].count++;grouped[emoji].mine=grouped[emoji].mine||l.mine;});
  return '<div class="gc-like-row">'+Object.keys(grouped).map(function(emoji){var g=grouped[emoji];return '<button type="button" class="gc-like-pill'+(g.mine?' liked':'')+'" data-message-like="'+m.id+'" data-emoji="'+esc(emoji)+'" aria-label="'+(g.mine?'Remove':'Add')+' '+esc(emoji)+' reaction" aria-pressed="'+!!g.mine+'">'+esc(emoji)+(g.count>1?' <span>'+g.count+'</span>':'')+'</button>';}).join('')+'<button type="button" class="gc-like-people" data-like-people="'+m.id+'" aria-label="See who reacted to this message">View reactions</button></div>';
}
// Patch only reaction controls, preserving mounted photos, messages and focus.
function paintLike(m){
  var box=document.querySelector('#gc-thread .gc-msgs');if(!box)return;
  var row=Array.from(box.children).find(function(el){return el.dataset.mid===String(m.id);});if(!row)return;
  var stack=row.querySelector('.gc-message-stack');if(!stack)return;
  var current=stack.querySelector('.gc-like-row'),template=document.createElement('template');template.innerHTML=likeHtml(m);
  var next=template.content.firstElementChild;
  if(!next){if(current)current.remove();return;}
  if(!current){current=next;stack.insertBefore(current,stack.querySelector('.gc-time'));}
  else{
    var buttons={};current.querySelectorAll('[data-emoji]').forEach(function(b){buttons[b.dataset.emoji]=b;});
    var keep=[];
    Array.from(next.children).forEach(function(n){
      var b=n.dataset.emoji?buttons[n.dataset.emoji]:current.querySelector('[data-like-people]');
      if(b){b.className=n.className;b.setAttribute('aria-label',n.getAttribute('aria-label'));if(n.hasAttribute('aria-pressed'))b.setAttribute('aria-pressed',n.getAttribute('aria-pressed'));if(b.innerHTML!==n.innerHTML)b.innerHTML=n.innerHTML;}
      else b=n;
      keep.push(b);
    });
    Array.from(current.children).forEach(function(b){if(keep.indexOf(b)<0)b.remove();});
    keep.forEach(function(b,i){if(current.children[i]!==b)current.insertBefore(b,current.children[i]||null);});
  }
  current.querySelectorAll('[data-message-like]').forEach(function(b){b.disabled=!!m._likePending;});
}
function toggleLike(mid,emoji){
  emoji=emoji||"❤️";
  if(!open)return;
  var thread=open,id=thread.id,m=thread.messages.find(function(x){return String(x.id)===String(mid);});
  if(!m||m._likePending||m.pending||m.failed||m.kind==='deleted'||m.kind==='system')return;
  var previous=(m.likes||[]).slice(),was=!!m.liked;
  var previousMine=previous.find(function(l){return l.mine;});
  var remove=previousMine&&(previousMine.emoji||'❤️')===emoji;
  var own=open.members.find(isMe)||{username:'You',wallet:window._myWallet||''};
  m.likes=previous.filter(function(l){return !l.mine;});m.liked=!remove;
  if(!remove)m.likes.push({user_id:own.user_id,username:own.username,wallet:own.wallet,avatar:own.avatar||'',mine:true,emoji:emoji});
  m._likePending=true;paintLike(m);
  var controller=new AbortController(),timeout=setTimeout(function(){controller.abort();},12000);
  api('/api/group-chats/'+id+'/messages/'+mid+'/likes',{method:'POST',body:{emoji:emoji},signal:controller.signal}).then(function(d){
    clearTimeout(timeout);m._likePending=false;if(open!==thread)return;
    if(d.ok){m.likes=d.likes;m.liked=d.liked;m.version=d.version;}
    else{m.likes=previous;m.liked=was;toast(d.msg||'Could not like message');}
    paintLike(m);fetchNew();
  });
}
function showLikes(mid){
  if(!open)return;var id=open.id;
  var el=sheet('<h3>Message reactions</h3><div class="gc-like-list">Loading…</div>','gc-sheet-menu');
  api('/api/group-chats/'+id+'/messages/'+mid+'/likes').then(function(d){
    if(!el.isConnected||!open||open.id!==id)return;
    var list=el.querySelector('.gc-like-list');
    if(!d.ok){list.textContent=d.msg||'Could not load likes';return;}
    list.innerHTML=d.likes.length?d.likes.map(function(l){return '<a class="gc-member" href="/profile/'+encodeURIComponent(l.wallet)+'">'+avatarHtml('gc-person-av',l.username,l.wallet,l.avatar)+'<span class="gc-person-copy"><b>'+esc(l.mine?'You':l.username)+'</b></span><span>'+esc(l.emoji||'❤️')+'</span></a>';}).join(''):'No reactions yet';
  });
}
function messageMenu(mid){
  if(!open)return;
  var m=open.messages.find(function(x){return String(x.id)===String(mid);});
  if(!m||m.pending||m.failed||m.kind==='system'||m.kind==='deleted'||(m.kind==='tip'&&!m.mine))return;
  var id=open.id;
  var isTip=m.kind==='tip';
  var el=sheet('<h3>'+(isTip?'Group tip options':'Message options')+'</h3><div class="gc-menu">'+(!isTip?'<button type="button" data-message-act="like">'+(m.liked?'Remove reaction':'❤️ Like message')+'</button>':'')+(m.mine&&m.kind==='text'?'<button type="button" data-message-act="edit">Edit message</button>':'')+(m.mine?'<button type="button" data-message-act="delete" class="gc-menu-danger">'+(isTip?'Delete tip from chat':'Delete for everyone')+'</button>':'')+'<button type="button" data-message-act="cancel">Cancel</button></div>','gc-sheet-menu');
  el.addEventListener('click',function(e){
    var button=e.target.closest('[data-message-act]');if(!button)return;
    if(button.dataset.messageAct==='cancel'){closeSheet();return;}
    if(button.dataset.messageAct==='like'){closeSheet();var current=open&&open.messages.find(function(x){return String(x.id)===String(mid);});var mine=current&&(current.likes||[]).find(function(l){return l.mine;});toggleLike(mid,mine?(mine.emoji||'❤️'):'❤️');return;}
    if(!m.mine)return;
    var editing=button.dataset.messageAct==='edit';
    var form=sheet('<h3>'+(editing?'Edit message':isTip?'Remove group tip?':'Delete message?')+'</h3>'+(editing?'<textarea class="gc-edit-input" maxlength="1000" aria-label="Edit message"></textarea>':'<p>'+(isTip?'The tip card will disappear for everyone in this group. This does not cancel or refund SOL transfers. Receipts remain in Portfolio history.':'This message will be deleted for everyone in the group.')+'</p>')+'<div class="gc-menu"><button type="button" class="gc-message-confirm'+(editing?'':' gc-menu-danger')+'">'+(editing?'Save changes':isTip?'Remove tip from chat':'Delete for everyone')+'</button><button type="button" class="gc-message-cancel">Cancel</button></div>','gc-sheet-menu');
    var input=form.querySelector('.gc-edit-input');if(input){input.value=m.body;input.focus();}
    form.querySelector('.gc-message-cancel').onclick=closeSheet;
    form.querySelector('.gc-message-confirm').onclick=function(){
      var save=this;if(editing&&!input.value.trim()){toast('Message cannot be empty');return;}
      save.disabled=true;
      api('/api/group-chats/'+id+'/messages/'+m.id,{method:editing?'PUT':'DELETE',body:editing?{message:input.value}:undefined}).then(function(d){
        if(!open||open.id!==id){closeSheet();return;}
        if(!d.ok){toast(d.msg||'Could not update message');save.disabled=false;return;}
        closeSheet();fetchNew();loadList();toast(editing?'Message edited':isTip?'Tip removed from group chat':'Message deleted for everyone');
      });
    };
  });
}
function setPhoto(file){
  if(!open)return;var id=open.id;
  OrcAgentEditPhoto(file,{title:'Position group photo',circle:true}).then(function(photo){
    if(!photo)return;toast('Updating photo…');
    return api('/api/group-chats/'+id+'/photo',{method:'PUT',body:{photo:photo}}).then(function(d){
      if(!d.ok){toast(d.msg||'Could not change the photo');return;}
      if(!open||open.id!==id)return;
      adopt(d.chat);fetchNew();if(document.querySelector('.gc-sheet-info'))showInfo();toast('Group photo updated');
    });
  }).catch(function(e){toast(e.message||'Could not change the photo');});
}

function isMe(m){return !!(window._myWallet&&m.wallet===window._myWallet);}

var REACTION_MAIN=['❤️','😂','😮','😢','😡','👍','🔥'];
var REACTION_MORE=['🙌','👏','🙏','💯','🚀','💰','🤑','📈','📉','💎','🐳','🤝','😍','🥳','😎','🤔','😅','😭','🤯','👀','✅','❌','💀','🫡'];
var reactionMenu=null,press=null,pressTimer=null,swallowUntil=0;
var reactionScope=window.OrcPageLifecycle?window.OrcPageLifecycle.createScope('group-reactions',document.getElementById('conv-list')):null;
function reactionListen(target,type,fn,opts){if(reactionScope)reactionScope.addEventListener(target,type,fn,opts);else target.addEventListener(type,fn,opts);}
if(reactionScope)reactionScope.onCleanup(closeReactionMenu);
function closeReactionMenu(){if(reactionMenu)reactionMenu.remove();reactionMenu=null;clearTimeout(pressTimer);press=null;}
function placeReactionMenu(menu,wrap,x,y){
  var rect=wrap.querySelector('.gc-bubble').getBoundingClientRect(),vv=window.visualViewport;
  var leftBound=vv?vv.offsetLeft:0,topBound=vv?vv.offsetTop:0,w=vv?vv.width:innerWidth,h=vv?vv.height:innerHeight;
  var mw=menu.offsetWidth,mh=menu.offsetHeight;
  menu.style.left=Math.max(leftBound+8,Math.min(x-mw/2,leftBound+w-mw-8))+'px';
  var top=rect.top-mh-10;
  if(top<topBound+8)top=rect.bottom+10;
  menu.style.top=Math.max(topBound+8,Math.min(top,topBound+h-mh-8))+'px';
}
function openReactionMenu(wrap,x,y){
  if(!open||!wrap)return;
  var mid=wrap.dataset.mid,m=open.messages.find(function(m){return String(m.id)===mid;});
  if(!m||m.pending||m.failed||m.kind==='deleted'||m.kind==='system')return;
  closeReactionMenu();
  var menu=document.createElement('div');menu.className='gc-reaction-menu';menu.setAttribute('role','dialog');menu.setAttribute('aria-label','React to message');
  var row=document.createElement('div');row.className='gc-reaction-choices';
  function emojiButton(emoji){
    var b=document.createElement('button');b.type='button';b.textContent=emoji;b.setAttribute('aria-label','React '+emoji);
    var committed=false;
    function choose(e){e.preventDefault();e.stopPropagation();if(committed)return;committed=true;toggleLike(mid,emoji);closeReactionMenu();}
    b.addEventListener('pointerup',choose);b.addEventListener('click',choose);return b;
  }
  REACTION_MAIN.forEach(function(e){row.appendChild(emojiButton(e));});
  var more=document.createElement('button');more.type='button';more.textContent='+';more.className='gc-reaction-more';more.setAttribute('aria-label','More reactions');
  more.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();if(menu.querySelector('.gc-reaction-grid'))return;more.hidden=true;var grid=document.createElement('div');grid.className='gc-reaction-grid';REACTION_MORE.forEach(function(emoji){grid.appendChild(emojiButton(emoji));});menu.appendChild(grid);placeReactionMenu(menu,wrap,x,y);});
  row.appendChild(more);menu.appendChild(row);
  if(m.kind==='text'){
    var copy=document.createElement('button');copy.type='button';copy.className='gc-reaction-copy';copy.textContent='Copy text';
    copy.addEventListener('click',function(){closeReactionMenu();try{navigator.clipboard.writeText(m.body).then(function(){toast('Copied');},function(){toast('Could not copy');});}catch(_){toast('Could not copy');}});menu.appendChild(copy);
  }
  document.body.appendChild(menu);reactionMenu=menu;placeReactionMenu(menu,wrap,x,y);
}
reactionListen(document,'contextmenu',function(e){var wrap=e.target.closest('#gc-thread .gc-msg');if(!wrap)return;e.preventDefault();openReactionMenu(wrap,e.clientX,e.clientY);});
reactionListen(document,'pointerdown',function(e){
  if(e.pointerType==='mouse'&&e.button!==0)return;
  var wrap=e.target.closest('#gc-thread .gc-msg');if(!wrap||e.target.closest('button,a,input,textarea'))return;
  clearTimeout(pressTimer);press={wrap:wrap,x:e.clientX,y:e.clientY};
  pressTimer=setTimeout(function(){if(!press)return;var p=press;try{var selection=window.getSelection();if(selection)selection.removeAllRanges();}catch(_){}openReactionMenu(p.wrap,p.x,p.y);swallowUntil=Date.now()+1500;press=null;},360);
},{passive:true});
reactionListen(document,'pointermove',function(e){if(press&&(Math.abs(press.x-e.clientX)>10||Math.abs(press.y-e.clientY)>10)){clearTimeout(pressTimer);press=null;}},{passive:true});
['pointerup','pointercancel'].forEach(function(t){reactionListen(document,t,function(){clearTimeout(pressTimer);press=null;},{passive:true});});
reactionListen(document,'selectstart',function(e){if(e.target.closest('#gc-thread .gc-bubble'))e.preventDefault();});
reactionListen(document,'click',function(e){
  if(reactionMenu&&reactionMenu.contains(e.target))return;
  if(Date.now()<swallowUntil){swallowUntil=0;e.preventDefault();e.stopImmediatePropagation();return;}
  if(reactionMenu)closeReactionMenu();
},true);

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
  var tip=e.target.closest('[data-chat-tip][data-tip-group="true"]');if(tip&&open){window.OrcChatTip.view({group:true,base:'/api/group-chats/'+open.id+'/tips',refresh:fetchNew},tip.dataset.chatTip);return;}
  var avatar=e.target.closest('.gc-msg-av img,.gc-th-av img');
  if(avatar){e.preventDefault();e.stopPropagation();OrcAgentViewPhoto(avatar.src);return;}
  var like=e.target.closest('[data-message-like]');if(like){toggleLike(like.dataset.messageLike,like.dataset.emoji);return;}
  var people=e.target.closest('[data-like-people]');if(people){showLikes(people.dataset.likePeople);return;}
  var options=e.target.closest('[data-message-menu]');if(options){messageMenu(options.dataset.messageMenu);return;}
  if(e.target.closest('[data-gc-new]')){e.preventDefault();if(window._setInboxTab)window._setInboxTab('groups');newGroup();return;}
  var row=e.target.closest('.gc-row-wrap');
  if(row){openGroup(row.dataset.gc);return;}
  if(e.target.closest('[data-gc-close]')){closeGroup();return;}
  if(e.target.closest('[data-gc-info]')){showInfo();return;}
  var failed=e.target.closest('.gc-msg.failed');
  if(failed){retry(failed.dataset.mid);return;}
  var img=e.target.closest('.gc-img');
  if(img&&typeof window._showImgLightbox==='function'){window._showImgLightbox(img.src);}
});
document.addEventListener('dblclick',function(e){
  if(e.target.closest('button,a,input,textarea,img'))return;
  var bubble=e.target.closest('#gc-thread .gc-bubble');if(!bubble)return;
  var message=bubble.closest('.gc-msg');if(message)toggleLike(message.dataset.mid);
});
document.addEventListener('keydown',function(e){
  if((e.key==='Enter'||e.key===' ')&&e.target.matches('.gc-msg-av[role="button"]')){e.preventDefault();var img=e.target.querySelector('img');if(img)OrcAgentViewPhoto(img.src);return;}
  if(e.key!=='Escape')return;
  if(reactionMenu){closeReactionMenu();return;}
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
document.addEventListener('oa-inbox-tabchange',renderList);
window.OrcAgentGroupChats={open:openGroup,reload:loadList};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
