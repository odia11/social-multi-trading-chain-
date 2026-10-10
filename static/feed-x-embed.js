/* Lazy native X previews. Original attribution and media are preserved;
 * engagement belongs to the OrcAgent post through its single action bar. */
(function(global){
  'use strict';
  var observer=null, scope=null;
  var allowedHosts={'x.com':1,'www.x.com':1,'twitter.com':1,
                    'www.twitter.com':1,'mobile.twitter.com':1};

  function statusFromText(text){
    var re=/(?:https?:\/\/|www\.)[^\s<>"'`]+|\b(?:x\.com|twitter\.com|mobile\.twitter\.com)\/[^\s<>"'`]+/gi, match;
    while((match=re.exec(String(text||'')))!==null){
      var matchedUrl=match[0].replace(/[),.!?;:\]]+$/g,'');
      var candidate=matchedUrl;
      if(!/^https?:\/\//i.test(candidate))candidate='https://'+candidate;
      var u;
      try{u=new URL(candidate);}catch(e){continue;}
      if(u.protocol!=='https:' || !allowedHosts[u.hostname.toLowerCase()] ||
         u.username || u.password || u.port)continue;
      var m=u.pathname.match(/^\/(?:[A-Za-z0-9_]{1,15}|i|i\/web)\/status\/([0-9]{5,20})\/?$/i);
      if(!m)continue;
      return {id:m[1],start:match.index,end:match.index+matchedUrl.length,url:'https://x.com/'+
        (/^\/i(?:\/web)?\/status\//i.test(u.pathname)?'i':''
          +u.pathname.split('/')[1])+'/status/'+m[1]};
    }
    return null;
  }

  function stripEmbeddedStatusUrl(text){
    var original=String(text==null?'':text);
    var tweet=statusFromText(original);
    if(!tweet)return original;
    // Remove only the URL shown by the X card; keep other links and the
    // author's own text. The stored post is never changed.
    var before=original.slice(0,tweet.start);
    var after=original.slice(tweet.end);
    // Joining both sides must not insert a blank line or two spaces where
    // the status URL used to be (especially for link-only lines on iPhone).
    if(/\n[ \t]*$/.test(before) && /^[ \t]*\n/.test(after))
      after=after.replace(/^[ \t]*\n/,'');
    else if(/[ \t]$/.test(before) && /^[ \t]/.test(after))
      after=after.replace(/^[ \t]+/,'');
    return (before+after)
      .replace(/[ \t]+\n/g,'\n')
      .replace(/\n[ \t]+/g,'\n')
      .trim();
  }

  function esc(value){
    return String(value==null?'':value).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function link(url,body,cls){
    return '<a class="'+(cls||'')+'" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer nofollow">'+body+'</a>';
  }
  function mediaUrl(raw){
    try{var u=new URL(raw);return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&
      /^(pbs|abs)\.twimg\.com$/.test(u.hostname)?u.href:'';}catch(e){return '';}
  }
  function card(text){
    var tweet=statusFromText(text);
    if(!tweet)return '';
    return '<div class="oa-x-post" data-x-post-id="'+tweet.id+'" data-x-post-url="'+tweet.url+'" role="group" aria-label="Post from X" onclick="event.stopPropagation()">'
      +'<div class="oa-x-post-slot" aria-live="polite"><span class="oa-x-post-loading">Loading post…</span>'
      +link(tweet.url,'𝕏','oa-x-source')+'</div></div>';
  }
  function renderTweet(t,quoted){
    var parsed=statusFromText(t.url);
    if(!parsed||parsed.id!==t.id)throw new Error('Invalid tweet');
    var avatar=mediaUrl(t.avatar),media='';
    (Array.isArray(t.media)?t.media:[]).slice(0,4).forEach(function(m){
      var src=mediaUrl(m.url);if(!src)return;
      var ratio=Number(m.width)>0&&Number(m.height)>0?' style="aspect-ratio:'+Number(m.width)+'/'+Number(m.height)+'"':'';
      media+=link(t.url,'<img src="'+esc(src)+'" alt="'+esc(m.alt||'Media from the original X post')+'" loading="lazy" decoding="async"'+ratio+'>'
        +(m.type==='video'?'<span class="oa-x-video-label">▶ Watch on X</span>':''),'oa-x-media-item');
    });
    var date=new Date(t.created_at),stamp=isNaN(date.getTime())?'':date.toLocaleString('en-US',{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit'});
    return '<div class="oa-x-native'+(quoted?' oa-x-quote':'')+'"><div class="oa-x-author">'
      +link(t.url,(avatar?'<img class="oa-x-avatar" src="'+esc(avatar)+'" alt="" loading="lazy" decoding="async">':'')
        +'<span class="oa-x-identity"><strong>'+esc(t.name)+(t.verified?'<span class="oa-x-verified" aria-label="Verified on X">✓</span>':'')+'</strong><span>@'+esc(t.username)+'</span></span>','oa-x-author-link')
      +link(t.url,'𝕏','oa-x-source')+'</div><div class="oa-x-text">'+esc(t.text)+'</div>'
      +(media?'<div class="oa-x-media'+(t.media.length>1?' oa-x-media-grid':'')+'">'+media+'</div>':'')
      +(!quoted&&t.quote?renderTweet(t.quote,true):'')
      +(stamp?link(t.url,'<time datetime="'+esc(t.created_at)+'">'+esc(stamp)+'</time>','oa-x-date'):'')+'</div>';
  }
  function fallback(root){
    if(!root.isConnected)return;
    root.dataset.xState='fallback';
    var slot=root.querySelector('.oa-x-post-slot');
    if(slot)slot.innerHTML='<span class="oa-x-post-loading">This post is unavailable.</span>'
      +link('https://x.com/i/status/'+root.dataset.xPostId,'View on X ↗','oa-x-fallback');
  }
  function load(root){
    if(!root.isConnected||root.dataset.xState)return;
    var id=root.dataset.xPostId;
    if(!/^[0-9]{5,20}$/.test(id)){fallback(root);return;}
    root.dataset.xState='loading';
    var slot=root.querySelector('.oa-x-post-slot');
    if(!slot)return;
    var controller=new AbortController();
    var timer=setTimeout(function(){controller.abort();},15000);
    global.fetch('/api/x-post/'+id,{signal:controller.signal,credentials:'same-origin'})
      .then(function(response){if(!response.ok)throw new Error('Unavailable');return response.json();})
      .then(function(data){
        if(!root.isConnected)return;
        if(!data.ok||!data.tweet||data.tweet.id!==id)throw new Error('Unavailable');
        slot.innerHTML=renderTweet(data.tweet,false);
        root.dataset.xState='ready';
      }).catch(function(){fallback(root);}).finally(function(){clearTimeout(timer);});
  }

  function observe(container){
    if(!container||!container.querySelectorAll)return;
    // Managed lifecycle scope disconnects and re-observes on iOS bfcache,
    // and clears the observer when Home is unmounted.
    if((!scope||!scope.isActive())&&global.OrcPageLifecycle){
      scope=global.OrcPageLifecycle.createScope('feed-x-embed',container);
      observer=null;
      scope.onCleanup(function(){observer=null;scope=null;});
    }
    if(!observer&&scope&&typeof scope.intersectionObserver==='function'){
      observer=scope.intersectionObserver(function(entries){
        entries.forEach(function(entry){
          if(!entry.isIntersecting)return;
          observer.unobserve(entry.target);load(entry.target);
        });
      },{rootMargin:'550px 0px'});
    }
    container.querySelectorAll('.oa-x-post:not([data-x-state])').forEach(function(root){
      if(observer)observer.observe(root);
      else load(root);
    });
  }
  function dispose(container){
    if(!observer||!container||!container.querySelectorAll)return;
    container.querySelectorAll('.oa-x-post').forEach(function(root){observer.unobserve(root);});
  }
  function reuse(oldCard,newCard){
    if(!oldCard||!newCard)return;
    var old=oldCard.querySelector('.oa-x-post'),next=newCard.querySelector('.oa-x-post');
    if(old&&next&&old.dataset.xPostId===next.dataset.xPostId)next.replaceWith(old);
  }
  global.OrcFeedXEmbed={statusFromText:statusFromText,stripEmbeddedStatusUrl:stripEmbeddedStatusUrl,
                        card:card,renderTweet:renderTweet,observe:observe,
                        dispose:dispose,reuse:reuse};
})(window);
