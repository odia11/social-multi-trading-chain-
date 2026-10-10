/* OrcAgent Home: safe, lazy X/Twitter status embeds. No data is fetched from X
 * until a post actually approaches the viewport. The embedded status URL is
 * hidden from the post text, but Open on X stays available as the fallback.
 * X controls whether public tweets are embeddable.
 */
(function(global){
  'use strict';
  var observer=null, scope=null, scriptPromise=null;
  var scriptUrl='https://platform.twitter.com/widgets.js';
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

  function card(text){
    var tweet=statusFromText(text);
    if(!tweet)return '';
    // Identifiers contain digits only and URLs contain an allowlisted X path.
    return '<div class="oa-x-post" data-x-post-id="'+tweet.id+'" role="group" aria-label="Tweet preview" onclick="event.stopPropagation()">'
      +'<div class="oa-x-post-head"><span class="oa-x-post-brand">𝕏 <span>Tweet</span></span>'
      +'<a href="'+tweet.url+'" target="_blank" rel="noopener noreferrer nofollow" onclick="event.stopPropagation()">Open on X ↗</a></div>'
      +'<div class="oa-x-post-slot" aria-live="polite"><span class="oa-x-post-loading">Tweet preview</span></div>'
      +'</div>';
  }

  function getWidgets(){
    if(global.twttr&&global.twttr.widgets&&typeof global.twttr.widgets.createTweet==='function')
      return Promise.resolve(global.twttr.widgets);
    if(scriptPromise)return scriptPromise;
    scriptPromise=new Promise(function(resolve,reject){
      var script=document.createElement('script'), finished=false;
      var timeout=setTimeout(function(){end(new Error('X widget timed out'));},12000);
      function end(err){
        if(finished)return;finished=true;clearTimeout(timeout);
        if(err){reject(err);return;}
        if(global.twttr&&typeof global.twttr.ready==='function'){
          global.twttr.ready(function(t){
            if(t&&t.widgets&&typeof t.widgets.createTweet==='function')resolve(t.widgets);
            else reject(new Error('X widgets unavailable'));
          });
        }else reject(new Error('X widgets unavailable'));
      }
      script.async=true;script.src=scriptUrl;
      script.onload=function(){end();};
      script.onerror=function(){end(new Error('X widget blocked'));};
      document.head.appendChild(script);
    });
    return scriptPromise;
  }

  function fallback(root){
    if(!root.isConnected)return;
    root.dataset.xState='fallback';
    var slot=root.querySelector('.oa-x-post-slot');
    if(slot){slot.textContent='Preview unavailable. Use Open on X to see this tweet.';}
  }

  function load(root){
    if(!root.isConnected||root.dataset.xState)return;
    var id=root.dataset.xPostId;
    if(!/^[0-9]{5,20}$/.test(id)){fallback(root);return;}
    root.dataset.xState='loading';
    var slot=root.querySelector('.oa-x-post-slot');
    if(!slot)return;
    slot.textContent='Loading tweet from X…';
    getWidgets().then(function(widgets){
      if(!root.isConnected)return null;
      slot.replaceChildren();
      return widgets.createTweet(id,slot,{theme:'dark',dnt:true,conversation:'none',cards:'visible',align:'center',lang:'en'});
    }).then(function(iframe){
      if(!root.isConnected)return;
      if(!iframe){fallback(root);return;}
      root.dataset.xState='ready';
    }).catch(function(){fallback(root);});
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
                        card:card,observe:observe,
                        dispose:dispose,reuse:reuse};
})(window);
