/* OrcAgent foreground notifications.
   Shows new personal notifications while the member is actively using the app.
   The notifications table is the single source of truth, so DMs, confirmed
   tips, follows, likes, replies, mentions, group events, trade/bridge events,
   support replies and future notification types all use the same surface. */
(function(){
'use strict';
if(window.__oaInAppNotificationsStarted)return;
window.__oaInAppNotificationsStarted=true;

// Every open tab asks the server; at every 3 s, a few hundred members with the
// app open were most of the server's traffic. Start at 6 s, slow down to 15 s
// while nothing new comes in, and ask at once when the tab comes back.
var POLL_MS=6000,POLL_MAX_MS=15000,pollDelay=POLL_MS,pollTimer=null;
var AUTO_DISMISS_MS=4200;
var MAX_BATCH=8;
var STORAGE_KEY='oa_live_notification_last_id_v1';
var lastId=readLastId();
var queue=[];
var showing=false;
var inFlight=false;
var root=null;
var csrfToken='';
var csrfPromise=null;

function readLastId(){
  try{return Math.max(0,parseInt(sessionStorage.getItem(STORAGE_KEY)||'0',10)||0)}
  catch(_){return 0}
}
function writeLastId(id){
  try{sessionStorage.setItem(STORAGE_KEY,String(id||0))}catch(_){}
}
function safeInternalLink(value){
  var raw=String(value||'').trim();
  if(!raw)return'/notifications';
  try{
    var u=new URL(raw,location.origin);
    if(u.origin!==location.origin)return'/notifications';
    return u.pathname+u.search+u.hash;
  }catch(_){return'/notifications'}
}
function safeAvatar(value){
  var raw=String(value||'').trim();
  if(!raw)return'';
  if(/^data:image\/(?:png|jpe?g|webp|gif);base64,/i.test(raw))return raw;
  try{
    var u=new URL(raw,location.origin);
    return (u.protocol==='http:'||u.protocol==='https:')?u.href:'';
  }catch(_){return''}
}
function labelFor(type){
  type=String(type||'').toLowerCase();
  if(type==='message')return'New message';
  if(type==='tip')return'Tip received';
  if(type==='follow')return'New follower';
  if(type==='follow_call')return'New token call';
  if(type==='follow_post')return'New post from a trader you follow';
  if(type==='mention')return'You were mentioned';
  if(type==='reply')return'New reply';
  if(type==='reply_like'||type==='like')return'New like';
  if(type==='reaction')return'New reaction';
  if(type==='repost')return'New repost';
  if(type==='group_post')return'Group update';
  if(type==='trade')return'Trade update';
  if(type==='price_alert')return'Your price alert';
  if(type==='bridge')return'Bridge update';
  if(type==='admin_invite')return'Account update';
  return'New notification';
}
function glyphFor(type){
  type=String(type||'').toLowerCase();
  if(type==='message')return'✉';
  if(type==='tip')return'$';
  if(type==='follow')return'+';
  if(type==='mention')return'@';
  if(type==='like'||type==='reply_like'||type==='reaction')return'♥';
  if(type==='reply'||type==='repost'||type==='group_post')return'↗';
  if(type==='trade')return'↗';
  if(type==='price_alert')return'🔔';
  if(type==='bridge')return'⇄';
  return'●';
}
function ensureRoot(){
  if(root&&document.documentElement.contains(root))return root;
  root=document.getElementById('oa-live-notification-root');
  if(!root){
    root=document.createElement('div');
    root.id='oa-live-notification-root';
    root.setAttribute('aria-live','polite');
    root.setAttribute('aria-atomic','false');
    document.body.appendChild(root);
  }
  syncTop();
  return root;
}
function syncTop(){
  if(!root)return;
  var top=10;
  var nav=document.querySelector('.pt-nb-topbar');
  if(nav){
    var r=nav.getBoundingClientRect();
    if(r.bottom>0&&r.top<window.innerHeight)top=Math.max(10,Math.round(r.bottom+8));
  }
  root.style.setProperty('--oa-live-notification-top',top+'px');
}
function primeCsrf(){
  if(csrfToken)return Promise.resolve(csrfToken);
  var meta=document.querySelector('meta[name="csrf-token"]');
  var known=(meta&&meta.content)||window._csrfToken||'';
  if(known){csrfToken=known;return Promise.resolve(csrfToken)}
  if(csrfPromise)return csrfPromise;
  csrfPromise=fetch('/api/csrf-token',{credentials:'include',cache:'no-store'})
    .then(function(r){return r.ok?r.json():null})
    .then(function(d){csrfToken=(d&&d.token)||'';return csrfToken})
    .catch(function(){return''});
  return csrfPromise;
}
function setBadge(ids,count){
  ids.forEach(function(id){
    var el=document.getElementById(id);
    if(!el)return;
    el.textContent=count>99?'99+':String(count||'');
    el.classList.toggle('show',count>0);
  });
}
function refreshBadges(){
  fetch('/api/notifications/mine/unread_count',{credentials:'include',cache:'no-store'})
    .then(function(r){return r.ok?r.json():null})
    .then(function(d){if(d&&d.ok)setBadge(['pt-nb-notif-badge','pt-nb-more-notif-badge'],Number(d.unread)||0)})
    .catch(function(){});
  fetch('/api/messages/unread_count',{credentials:'include',cache:'no-store'})
    .then(function(r){return r.ok?r.json():null})
    .then(function(d){if(d)setBadge(['pt-nb-msg-badge','pt-nb-more-msg-badge'],Number(d.count)||0)})
    .catch(function(){});
}
function markRead(id){
  if(!id)return;
  primeCsrf().then(function(token){
    if(!token)return;
    return fetch('/api/notifications/mine/mark_read_batch',{
      method:'POST',credentials:'include',keepalive:true,
      headers:{'Content-Type':'application/json','X-CSRF-Token':token},
      body:JSON.stringify({ids:[id]})
    });
  }).then(function(){refreshBadges()}).catch(function(){});
}
function actorNode(n){
  var avatar=safeAvatar(n.actor_avatar);
  if(avatar){
    var img=document.createElement('img');
    img.className='oa-live-notification-avatar';
    img.src=avatar;
    img.alt='';
    return img;
  }
  var fallback=document.createElement('div');
  fallback.className='oa-live-notification-avatar oa-live-notification-avatar-fallback';
  if(n.actor_username){
    fallback.textContent=String(n.actor_username).trim().charAt(0).toUpperCase()||'?';
  }else{
    fallback.textContent=glyphFor(n.type);
    fallback.classList.add('oa-live-notification-type-'+String(n.type||'system').toLowerCase().replace(/[^a-z0-9_-]/g,''));
  }
  return fallback;
}
function dismiss(card,done){
  if(!card)return;
  card.classList.remove('is-visible');
  card.classList.add('is-leaving');
  window.setTimeout(function(){
    if(card.parentNode)card.parentNode.removeChild(card);
    if(done)done();
  },180);
}
function inView(el){
  if(!el)return false;
  var r=el.getBoundingClientRect();
  if(!r.width&&!r.height)return false;
  return r.bottom>0&&r.top<(window.innerHeight||document.documentElement.clientHeight);
}
/* The member is already looking at what this notification is about: the
   reply (or the open replies of that post) is on screen, or the DM thread
   with the sender is open. A banner then only covers the very thing it
   announces, so it is marked read without showing one. */
function alreadyOnScreen(n){
  var link=safeInternalLink(n.link),u;
  try{u=new URL(link,location.origin)}catch(_){return false}
  var post=/^#post-([pt]\d+)(?:-reply-(\d+))?$/.exec(u.hash||'');
  if(post&&u.pathname===location.pathname){
    if(post[2]&&inView(document.querySelector('.fc-reply-item[data-reply-id="'+post[2]+'"]')))return true;
    var box=document.getElementById('rbox-'+post[1]);
    if(box&&getComputedStyle(box).display!=='none'&&inView(box))return true;
    return false;
  }
  var dm=/^\/messages\/([^/?#]+)/.exec(u.pathname);
  if(dm&&!document.hidden){
    var peer=decodeURIComponent(dm[1]);
    if(location.pathname==='/messages/'+dm[1])return true;
    var active=window._activePeer;
    if(location.pathname.indexOf('/messages')===0&&active&&active.wallet===peer)return true;
  }
  return false;
}
function showNext(){
  if(showing||document.hidden||!queue.length)return;
  var n=queue.shift();
  if(alreadyOnScreen(n)){markRead(Number(n.id)||0);refreshBadges();showNext();return}
  showing=true;
  var host=ensureRoot();
  var card=document.createElement('div');
  card.className='oa-live-notification';
  card.setAttribute('role','button');
  card.setAttribute('tabindex','0');
  card.setAttribute('aria-label',labelFor(n.type)+'. '+String(n.content||''));
  card.appendChild(actorNode(n));

  var copy=document.createElement('div');
  copy.className='oa-live-notification-copy';
  var title=document.createElement('div');
  title.className='oa-live-notification-title';
  title.textContent=labelFor(n.type);
  var body=document.createElement('div');
  body.className='oa-live-notification-body';
  body.textContent=String(n.content||'');
  copy.appendChild(title);copy.appendChild(body);card.appendChild(copy);

  var close=document.createElement('button');
  close.type='button';
  close.className='oa-live-notification-close';
  close.setAttribute('aria-label','Dismiss notification');
  close.textContent='×';
  card.appendChild(close);

  var dot=document.createElement('span');
  dot.className='oa-live-notification-dot';
  dot.setAttribute('aria-hidden','true');
  card.appendChild(dot);

  var finished=false;
  var timer=null;
  function finishCard(){
    if(finished)return;
    finished=true;
    if(timer!==null)window.clearTimeout(timer);
    dismiss(card,function(){showing=false;showNext()});
  }
  timer=window.setTimeout(finishCard,AUTO_DISMISS_MS);
  function open(){
    markRead(Number(n.id)||0);
    var target=safeInternalLink(n.link);
    try{sessionStorage.setItem('_notifJumpType',n.type||'')}catch(_){}
    // Always dismiss first. Same-page feed navigation used to clear the timer
    // and return without removing the banner, leaving it stuck indefinitely.
    finishCard();
    if(typeof window._openFeedNotification==='function' && window._openFeedNotification(target,n.type))return;
    location.href=target;
  }
  card.addEventListener('click',function(e){
    if(e.target===close||close.contains(e.target))return;
    open();
  });
  card.addEventListener('keydown',function(e){
    if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}
  });
  close.addEventListener('click',function(e){
    e.preventDefault();e.stopPropagation();
    markRead(Number(n.id)||0);
    finishCard();
  });
  host.appendChild(card);
  requestAnimationFrame(function(){requestAnimationFrame(function(){card.classList.add('is-visible')})});
}
function enqueue(items){
  items.sort(function(a,b){return Number(a.id)-Number(b.id)});
  items.forEach(function(n){queue.push(n)});
  refreshBadges();
  showNext();
}
function poll(initial){
  if(inFlight||document.hidden&&!initial)return;
  inFlight=true;
  var baseline=(lastId===0);
  var url='/api/notifications/mine?category=all&limit='+(baseline?'1':String(MAX_BATCH));
  if(!baseline)url+='&after_id='+encodeURIComponent(lastId);
  fetch(url,{credentials:'include',cache:'no-store'})
    .then(function(r){
      if(r.status===401)return null;
      return r.ok?r.json():null;
    })
    .then(function(d){
      if(!d||!d.ok||!Array.isArray(d.notifications))return;
      var items=d.notifications.filter(function(n){return n&&Number(n.id)>0});
      if(baseline){
        if(items.length){
          lastId=Math.max.apply(null,items.map(function(n){return Number(n.id)||0}));
          writeLastId(lastId);
        }
        return;
      }
      var fresh=items.filter(function(n){return Number(n.id)>lastId});
      if(!fresh.length){pollDelay=Math.min(POLL_MAX_MS,Math.round(pollDelay*1.5));return;}
      pollDelay=POLL_MS;
      lastId=Math.max(lastId,Math.max.apply(null,fresh.map(function(n){return Number(n.id)||0})));
      writeLastId(lastId);
      enqueue(fresh);
    })
    .catch(function(){})
    .finally(function(){inFlight=false});
}

function schedule(){
  if(pollTimer)window.clearTimeout(pollTimer);
  pollTimer=window.setTimeout(function(){
    pollTimer=null;
    if(!document.hidden)poll(false);
    schedule();
  },pollDelay);
}

function boot(){
  ensureRoot();
  primeCsrf();
  poll(true);
  schedule();
  document.addEventListener('visibilitychange',function(){if(!document.hidden){syncTop();pollDelay=POLL_MS;poll(false);schedule()}});
  window.addEventListener('focus',function(){pollDelay=POLL_MS;poll(false);schedule()});
  window.addEventListener('online',function(){poll(false)});
  window.addEventListener('resize',syncTop,{passive:true});
  window.addEventListener('orientationchange',function(){window.setTimeout(syncTop,100)},{passive:true});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
else boot();
})();
