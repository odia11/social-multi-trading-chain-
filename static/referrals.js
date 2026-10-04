(function(){
'use strict';
var config=JSON.parse(document.getElementById('referral-config').textContent),toast=null,toastTimer=null,sharing=false;
window._refCode=config.code||'';
var link=config.link||'',text='Join me on OrcAgent — explore calls, trade on Solana and grow your community.';
function notify(message,ok){
if(!toast){toast=document.createElement('div');toast.className='w-toast';toast.setAttribute('role','status');toast.setAttribute('aria-live','polite');document.body.appendChild(toast);}
clearTimeout(toastTimer);toast.textContent=message;toast.style.background=ok?'#173229':'#3a1d23';toast.style.color=ok?'#6fe5b4':'#ffb5b5';toast.hidden=false;
toastTimer=setTimeout(function(){toast.hidden=true;},2200);
}
window._copyReferralText=function(value,message){
if(!value)return Promise.resolve(false);
function fallback(){
var focus=document.activeElement,node=document.createElement('textarea');node.value=value;node.readOnly=true;node.style.cssText='position:fixed;left:-9999px;top:0';document.body.appendChild(node);node.select();
var ok=false;try{ok=document.execCommand('copy');}catch(e){}
node.remove();if(focus&&focus.focus)focus.focus({preventScroll:true});notify(ok?message:'Could not copy. Select and copy the link.',ok);return ok;
}
if(navigator.clipboard&&navigator.clipboard.writeText)return navigator.clipboard.writeText(value).then(function(){notify(message,true);return true;}).catch(fallback);
return Promise.resolve(fallback());
};
window._copyRefLink=function(){return window._copyReferralText(link,'Invitation link copied');};
window._shareReferral=function(){
if(!link||sharing)return Promise.resolve(false);
if(!navigator.share)return window._copyRefLink();
sharing=true;
return navigator.share({title:'OrcAgent',text:text,url:link}).catch(function(error){if(error&&error.name!=='AbortError')return window._copyRefLink();}).finally(function(){sharing=false;});
};
document.getElementById('share-x').href='https://x.com/intent/post?text='+encodeURIComponent(text+' '+link);
document.getElementById('share-telegram').href='https://t.me/share/url?url='+encodeURIComponent(link)+'&text='+encodeURIComponent(text);
document.getElementById('share-email').href='mailto:?subject='+encodeURIComponent('Join me on OrcAgent')+'&body='+encodeURIComponent(text+'\n\n'+link);
var tabs=Array.from(document.querySelectorAll('.tab'));
function activate(button){
tabs.forEach(function(tab){var active=tab===button;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;document.getElementById('tab-'+tab.dataset.tab).classList.toggle('active',active);});
}
tabs.forEach(function(button,index){
button.addEventListener('click',function(){activate(button);});
button.addEventListener('keydown',function(e){var next;if(e.key==='ArrowRight')next=tabs[(index+1)%tabs.length];if(e.key==='ArrowLeft')next=tabs[(index+tabs.length-1)%tabs.length];if(e.key==='Home')next=tabs[0];if(e.key==='End')next=tabs[tabs.length-1];if(next){e.preventDefault();activate(next);next.focus();}});
});
})();
