(function(){
'use strict';
/* app-ux.js owns intent prefetching. This file only shows navigation progress. */
if(!document.getElementById('oa-app-ux-css')){var c=document.createElement('link');c.id='oa-app-ux-css';c.rel='stylesheet';c.href='/static/app-ux.css?v=4';document.head.appendChild(c)}
if(!document.getElementById('oa-app-ux-js')){var j=document.createElement('script');j.id='oa-app-ux-js';j.src='/static/app-ux.js?v=4';j.defer=true;document.head.appendChild(j)}
var b=document.getElementById('pgl-bar');
if(!b){b=document.createElement('div');b.id='pgl-bar';b.style.cssText='position:fixed;top:0;left:0;height:2px;width:0;background:#f7b955;z-index:99999;transition:width .18s ease,opacity .22s ease;box-shadow:0 0 8px rgba(247,185,85,.35);pointer-events:none';document.documentElement.appendChild(b)}
var p=0,t=null,running=false;
function start(){if(running)return;running=true;p=12;b.style.transition='none';b.style.width=p+'%';b.style.opacity='1';requestAnimationFrame(function(){b.style.transition='width .18s ease,opacity .22s ease'});clearInterval(t);t=setInterval(function(){p+=(88-p)*.11;b.style.width=p+'%'},120)}
function finish(){running=false;clearInterval(t);t=null;b.style.width='100%';b.style.opacity='0';setTimeout(function(){if(!running)b.style.width='0'},260)}
function localNavigation(a){if(!a||!a.href||a.hasAttribute('download')||(a.target&&a.target!=='_self')||a.hasAttribute('data-no-instant-nav')||/^javascript:/i.test(a.getAttribute('href')||''))return false;try{var u=new URL(a.href,location.href);if(u.origin!==location.origin||u.pathname.indexOf('/api/')===0)return false;return u.pathname!==location.pathname||u.search!==location.search}catch(e){return false}}
document.addEventListener('click',function(e){if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;if(localNavigation(a))start()},true);
addEventListener('beforeunload',start);
addEventListener('pageshow',function(e){finish();if(e.persisted)document.dispatchEvent(new CustomEvent('oa:bfcache-restore'))},true);
})();
