/* Light mode (white with gold): the runtime half. See theme_light.py.

   The server already ships a light companion for every stylesheet and
   <style> block, and sets data-theme on <html> from the oa_theme cookie, so
   pages are light from their first paint. What only exists at runtime is
   handled here, while light mode is on:
   - inline style attributes and SVG fill/stroke written by JavaScript
     (charts, chips, buttons built on the fly), mapped with the same rules;
   - <style> elements and stylesheets JavaScript adds later, read through the
     CSSOM and given a companion like the server's.
   Everything is reversible: the original values are kept and restored when
   light mode is switched off, without a reload.

   window.OrcTheme = {get(), set('light'|'dark'), toggle()} for the switches. */
(function(){
'use strict';
if(window.OrcTheme) return;
var root=document.documentElement;
var ATTR='html[data-theme="light"]';

/* ── colour mapping: a port of theme_light.map_rgba ── */
var NAMED={white:[255,255,255],black:[0,0,0],red:[255,0,0],green:[0,128,0],blue:[0,0,255],
  yellow:[255,255,0],orange:[255,165,0],gold:[255,215,0],gray:[128,128,128],grey:[128,128,128],silver:[192,192,192]};
var COLOR_RE=/#[0-9a-fA-F]{3,8}\b|rgba?\([^()]*\)|hsla?\([^()]*\)|\b(?:white|black|red|green|blue|yellow|orange|gold|gray|grey|silver)\b/gi;
function hue2rgb(p,q,t){if(t<0)t+=1;if(t>1)t-=1;if(t<1/6)return p+(q-p)*6*t;if(t<1/2)return q;if(t<2/3)return p+(q-p)*(2/3-t)*6;return p}
function hslToRgb(h,s,l){l=Math.max(0,Math.min(1,l));s=Math.max(0,Math.min(1,s));if(!s)return [l*255,l*255,l*255];
  var q=l<0.5?l*(1+s):l+s-l*s,p=2*l-q;return [hue2rgb(p,q,h+1/3)*255,hue2rgb(p,q,h)*255,hue2rgb(p,q,h-1/3)*255]}
function rgbToHsl(r,g,b){r/=255;g/=255;b/=255;var mx=Math.max(r,g,b),mn=Math.min(r,g,b),l=(mx+mn)/2,h=0,s=0;
  if(mx!==mn){var d=mx-mn;s=l>0.5?d/(2-mx-mn):d/(mx+mn);
    h=mx===r?((g-b)/d+(g<b?6:0)):mx===g?((b-r)/d+2):((r-g)/d+4);h/=6}
  return [h,s,l]}
function parse(tok){
  var t=String(tok).trim().toLowerCase();
  if(NAMED[t])return NAMED[t].concat([1]);
  if(t.charAt(0)==='#'){var h=t.slice(1);if(h.length===3||h.length===4)h=h.split('').map(function(c){return c+c}).join('');
    if(h.length!==6&&h.length!==8)return null;
    var r=parseInt(h.slice(0,2),16),g=parseInt(h.slice(2,4),16),b=parseInt(h.slice(4,6),16),a=h.length===8?parseInt(h.slice(6,8),16)/255:1;
    return isNaN(r+g+b+a)?null:[r,g,b,a]}
  var m=/^(rgba?|hsla?)\(([^()]*)\)$/.exec(t);if(!m)return null;
  var parts=m[2].trim().split(/[\s,\/]+/).filter(Boolean);
  if(parts.length<3||/var|calc/.test(m[2]))return null;
  function num(p,scale){return /%$/.test(p)?parseFloat(p)*scale/100:parseFloat(p)}
  var a2=parts.length>3?num(parts[3],1):1,rgb;
  if(m[1].indexOf('rgb')===0)rgb=[num(parts[0],255),num(parts[1],255),num(parts[2],255)];
  else rgb=hslToRgb(((parseFloat(parts[0])/360)%1+1)%1,num(parts[1],1),num(parts[2],1));
  if(rgb.some(isNaN)||isNaN(a2))return null;
  return [Math.max(0,Math.min(255,rgb[0])),Math.max(0,Math.min(255,rgb[1])),Math.max(0,Math.min(255,rgb[2])),Math.max(0,Math.min(1,a2))]}
function lum(r,g,b){function c(v){v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)}return 0.2126*c(r)+0.7152*c(g)+0.0722*c(b)}
function onWhite(r,g,b){return 1.05/(lum(r,g,b)+0.05)}
function vivid(c){var hsl=rgbToHsl(c[0],c[1],c[2]);return hsl[1]*(1-Math.abs(2*hsl[2]-1))>=0.12}
function warm(l){return l>0.8?[42/360,Math.min(0.32,0.32*(l-0.8)/0.2)]:[220/360,0.08]}
function fmt(c){var r=Math.round(c[0]),g=Math.round(c[1]),b=Math.round(c[2]),a=c[3];
  if(a>=0.999)return '#'+[r,g,b].map(function(v){v=Math.max(0,Math.min(255,v));return (v<16?'0':'')+v.toString(16)}).join('');
  return 'rgba('+r+','+g+','+b+','+(+a.toFixed(3))+')'}
function mapRgba(c,role){
  var r=c[0],g=c[1],b=c[2],a=c[3];if(a<=0.001)return c;
  var hsl=rgbToHsl(r,g,b),h=hsl[0],s=hsl[1],l=hsl[2],nl,w,o;
  if(!vivid(c)){
    if(role==='shadow')return [0,0,0,+(a*(l<0.5?0.35:0.15)).toFixed(3)];
    if(role==='bg'&&l<0.03&&a<0.95)return [0,0,0,+(a*0.5).toFixed(3)];
    if((role==='bg'||role==='border')&&l>=0.98&&a>=0.9)return c;
    if(role==='var')role=l<0.5?'bg':'text';
    if(role==='text'){nl=l>=0.5?Math.min(1-l,0.58):l>=0.2?0.62-(0.5-l)*0.3:0.96}
    else if(l>0.5)nl=Math.max(0.08,1-l);
    else if(role==='border')nl=1-l*0.75;
    else if(l<=0.065)nl=0.962;
    else if(l<=0.14)nl=1-(l-0.065)*0.35;
    else nl=1-l*0.75;
    w=warm(nl);o=hslToRgb(w[0],w[1],nl);return [o[0],o[1],o[2],a]}
  if(role==='shadow')return [r,g,b,+(a*0.6).toFixed(3)];
  if(role==='bg'||role==='border'||role==='var'){
    if(l<0.22&&a>0.5){o=hslToRgb(h,Math.min(s,0.55),0.93+(0.22-l)*0.2);return [o[0],o[1],o[2],a]}
    if(a>=0.5&&l>0.55&&onWhite(r,g,b)<2.4)return darken(h,s,l,a,2.4,0.8);
    return c}
  if(l<0.22){o=hslToRgb(h,s,1-l);return [o[0],o[1],o[2],a]}
  if(onWhite(r,g,b)>=3.0)return c;
  return darken(h,s,l,a,3.0,0.7)}
function darken(h,s,l,a,target,goldSat){
  if(h>=25/360&&h<=60/360)s*=goldSat;
  var nl=l,o=hslToRgb(h,s,nl);
  while(onWhite(o[0],o[1],o[2])<target&&nl>0.22){nl-=0.01;o=hslToRgb(h,s,nl)}
  return [o[0],o[1],o[2],a]}
function mapToken(tok,role){
  if(/^(transparent|currentcolor|inherit|initial|unset|none)$/i.test(tok))return tok;
  var c=parse(tok);return c?fmt(mapRgba(c,role)):tok}
var TEXT={'color':1,'fill':1,'stroke':1,'caret-color':1,'accent-color':1,'-webkit-text-fill-color':1,
  'text-decoration-color':1,'stop-color':1,'-webkit-text-stroke-color':1,'scrollbar-color':1};
var BG={'background':1,'background-color':1,'background-image':1};
var SHADOW={'box-shadow':1,'text-shadow':1,'filter':1};
function roleOf(p){p=p.trim().toLowerCase();if(p.slice(0,2)==='--')return 'var';if(TEXT[p])return 'text';if(BG[p])return 'bg';
  if(SHADOW[p])return 'shadow';if(/^(border|outline|column-rule)/.test(p)&&!/radius|width|style|collapse|spacing|image|offset/.test(p))return 'border';return null}
function mapValue(v,role){return String(v).replace(COLOR_RE,function(t){return mapToken(t,role)})}
function keepText(style){
  var bg=String(style.getPropertyValue('background-color')||style.getPropertyValue('background')||'');
  var m=bg.match(COLOR_RE);
  if(!m){var v=/var\(\s*(--[\w-]+)/.exec(bg);if(v){var res=getComputedStyle(root).getPropertyValue(v[1]);m=res&&res.match(COLOR_RE)}}
  var c=m&&parse(m[0]);if(!c||c[3]<0.6)return false;
  var l=rgbToHsl(c[0],c[1],c[2])[2];
  if(!vivid(c))return l>=0.98&&c[3]>=0.9;
  return l>=0.3&&l<=0.85}
window.OrcThemeMap={mapToken:mapToken,mapValue:mapValue};

/* ── stylesheets added at runtime ── */
function prefix(sel){
  var out=[];var parts=sel.split(/,(?![^(]*\))/);
  for(var i=0;i<parts.length;i++){var s=parts[i].trim();if(!s)continue;if(s.slice(0,2)==='::')return '';
    if(/^:root/i.test(s))out.push(ATTR+s.slice(5));else if(/^html(?![\w-])/i.test(s))out.push(ATTR+s.slice(4));else out.push(ATTR+' '+s)}
  return out.join(',')}
function ruleText(rule){
  if(rule.cssRules&&rule.conditionText!==undefined){
    var inner=rulesText(rule.cssRules);return inner?('@'+(rule.type===4?'media ':'supports ')+rule.conditionText+'{'+inner+'}'):''}
  if(!rule.selectorText||!rule.style||/logo-(?:mark|tile|shape)|desk-logo|oa-brand-mark/i.test(rule.selectorText))return '';
  var st=rule.style,keep=keepText(st),decl=[];
  for(var i=0;i<st.length;i++){var p=st[i],v=st.getPropertyValue(p);if(!v)continue;
    var role=roleOf(p);if(!role)continue;
    if(role==='var'){var isColor=COLOR_RE.test(v);COLOR_RE.lastIndex=0;if(!isColor)continue}
    // restated even when unchanged, so the cascade between companions holds
    var mv=(keep&&role==='text')?v:mapValue(v,role);decl.push(p+':'+mv+(st.getPropertyPriority(p)?'!important':''))}
  var sel=decl.length?prefix(rule.selectorText):'';
  return sel?sel+'{'+decl.join(';')+'}':''}
function rulesText(rules){var out=[];for(var i=0;i<rules.length;i++){var t='';try{t=ruleText(rules[i])}catch(_){}if(t)out.push(t)}return out.join('\n')}
var companions=new WeakMap();
function sheetCompanion(node){
  if(companions.has(node))return;
  if(node.hasAttribute('data-oa-lt')||node.hasAttribute('data-oa-light'))return;
  if(node.tagName==='LINK'){
    var href=node.getAttribute('href')||'',m=/\/static\/([\w.\/-]+\.css)/.exec(href);
    if(!m||document.querySelector('link[data-oa-light-for="'+m[1]+'"]'))return;
    var sib=document.createElement('link');sib.rel='stylesheet';sib.href='/theme-light/'+m[1]+'?v='+encodeURIComponent(version());
    sib.setAttribute('data-oa-light-for',m[1]);if(node.media&&node.media!=='all')sib.media=node.media;
    companions.set(node,sib);node.parentNode&&node.parentNode.insertBefore(sib,node.nextSibling);return}
  var sheet=node.sheet;if(!sheet)return;
  var text='';try{text=rulesText(sheet.cssRules)}catch(_){return}
  var st=document.createElement('style');st.setAttribute('data-oa-light','1');st.textContent=text;
  companions.set(node,st);node.parentNode&&node.parentNode.insertBefore(st,node.nextSibling)}
function version(){var m=document.querySelector('meta[name="oa-app-version"]');return (m&&m.content)||'1'}

/* ── inline styles and SVG colours ── */
var ORIG='data-oa-dark-style',done=new WeakMap();
// [data-oa-keep]: colours that must not change with the theme (QR codes).
function kept(el){return !!(el.closest&&el.closest('[data-oa-keep]'))}
function mapInline(el){
  var cur=el.getAttribute('style');if(!cur||done.get(el)===cur||kept(el))return;
  if(!COLOR_RE.test(cur)){COLOR_RE.lastIndex=0;return}COLOR_RE.lastIndex=0;
  el.setAttribute(ORIG,cur);
  var st=el.style,keep=keepText(st);
  for(var i=0;i<st.length;i++){var p=st[i],v=st.getPropertyValue(p),role=roleOf(p);
    if(!role||(keep&&role==='text')||!v)continue;var mv=mapValue(v,role);if(mv!==v)st.setProperty(p,mv,st.getPropertyPriority(p))}
  done.set(el,el.getAttribute('style'))}
var SVG_ATTRS=['fill','stroke','stop-color'];
function mapSvg(el){
  if(kept(el))return;
  for(var i=0;i<SVG_ATTRS.length;i++){var a=SVG_ATTRS[i],v=el.getAttribute(a);if(!v)continue;
    var key='data-oa-dark-'+a;if(el.getAttribute(key+'-m')===v)continue;
    var mv=mapToken(v,'text');if(mv===v)continue;el.setAttribute(key,v);el.setAttribute(a,mv);el.setAttribute(key+'-m',mv)}}
function visit(node){
  if(node.nodeType!==1)return;
  if(node.tagName==='STYLE'||(node.tagName==='LINK'&&/stylesheet/i.test(node.rel))){
    if(node.tagName==='STYLE'&&!node.sheet)setTimeout(function(){sheetCompanion(node)},0);else sheetCompanion(node);return}
  if(node.hasAttribute('style'))mapInline(node);
  if(node instanceof SVGElement)mapSvg(node);
  var all=node.querySelectorAll('[style],[fill],[stroke],[stop-color],style,link[rel~="stylesheet"]');
  for(var i=0;i<all.length;i++)visit1(all[i])}
function visit1(n){
  if(n.tagName==='STYLE'||n.tagName==='LINK'){sheetCompanion(n);return}
  if(n.hasAttribute('style'))mapInline(n);if(n instanceof SVGElement)mapSvg(n)}
function restoreAll(){
  var els=document.querySelectorAll('['+ORIG+']');
  for(var i=0;i<els.length;i++){els[i].setAttribute('style',els[i].getAttribute(ORIG));els[i].removeAttribute(ORIG);done.delete(els[i])}
  SVG_ATTRS.forEach(function(a){var key='data-oa-dark-'+a,list=document.querySelectorAll('['+key+']');
    for(var j=0;j<list.length;j++){list[j].setAttribute(a,list[j].getAttribute(key));list[j].removeAttribute(key);list[j].removeAttribute(key+'-m')}})}
var observer=null;
function startRuntime(){
  if(observer)return;
  observer=new MutationObserver(function(muts){
    for(var i=0;i<muts.length;i++){var m=muts[i];
      if(m.type==='attributes'){var t=m.target;
        if(m.attributeName==='style')mapInline(t);else if(t instanceof SVGElement)mapSvg(t)}
      else for(var j=0;j<m.addedNodes.length;j++)visit(m.addedNodes[j])}});
  observer.observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:['style','fill','stroke','stop-color']});
  if(document.body)visit(document.body);
  var heads=document.head?document.head.querySelectorAll('style,link[rel~="stylesheet"]'):[];
  for(var i=0;i<heads.length;i++)sheetCompanion(heads[i])}
function stopRuntime(){if(observer){observer.disconnect();observer=null}restoreAll()}

/* ── the switch ── */
function readTheme(){
  try{var v=localStorage.getItem('oa_theme');if(v==='light'||v==='dark')return v}catch(_){}
  var m=/(?:^|;\s*)oa_theme=(light|dark)/.exec(document.cookie);return m?m[1]:'dark'}
function paintMeta(theme){
  var metas=document.querySelectorAll('meta[name="theme-color"]');
  for(var i=0;i<metas.length;i++){if(!metas[i].hasAttribute('data-oa-dark'))metas[i].setAttribute('data-oa-dark',metas[i].content);
    metas[i].content=theme==='light'?'#f7f6f2':metas[i].getAttribute('data-oa-dark')}}
function apply(theme){
  if(theme==='light')root.setAttribute('data-theme','light');else root.removeAttribute('data-theme');
  paintMeta(theme);
  if(theme==='light'){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',startRuntime,{once:true});else startRuntime()}
  else stopRuntime();
  var sw=document.querySelectorAll('[data-oa-theme-switch]');
  for(var i=0;i<sw.length;i++)sw[i].setAttribute('aria-checked',theme==='light'?'true':'false');
  var box=document.getElementById('pref-theme-light');if(box)box.checked=theme==='light'}
function set(theme){
  theme=theme==='light'?'light':'dark';
  try{localStorage.setItem('oa_theme',theme)}catch(_){}
  document.cookie='oa_theme='+theme+'; path=/; max-age=31536000; SameSite=Lax'+(location.protocol==='https:'?'; Secure':'');
  apply(theme);
  try{document.dispatchEvent(new CustomEvent('orca:theme',{detail:{theme:theme}}))}catch(_){}
  return theme}
window.OrcTheme={get:function(){return root.getAttribute('data-theme')==='light'?'light':'dark'},
  set:set,toggle:function(){return set(this.get()==='light'?'dark':'light')}};
// Clicks on any [data-oa-theme-switch] toggle it (menus are built in several places).
document.addEventListener('click',function(e){var b=e.target&&e.target.closest&&e.target.closest('[data-oa-theme-switch]');
  if(!b)return;e.preventDefault();window.OrcTheme.toggle()},true);
var initial=readTheme();
// The cookie is what the server reads; keep it in step with this device.
if(initial==='light'&&!/(?:^|;\s*)oa_theme=light/.test(document.cookie))set('light');else apply(initial);
document.addEventListener('DOMContentLoaded',function(){apply(window.OrcTheme.get())},{once:true});
new MutationObserver(function(muts){for(var i=0;i<muts.length;i++)for(var j=0;j<muts[i].addedNodes.length;j++){var n=muts[i].addedNodes[j];
  if(n.nodeType===1&&(n.hasAttribute('data-oa-theme-switch')||n.querySelector('[data-oa-theme-switch],#pref-theme-light'))){
    var on=window.OrcTheme.get()==='light';var list=n.hasAttribute('data-oa-theme-switch')?[n]:n.querySelectorAll('[data-oa-theme-switch]');
    for(var k=0;k<list.length;k++)list[k].setAttribute('aria-checked',on?'true':'false');
    var box=document.getElementById('pref-theme-light');if(box)box.checked=on}}}).observe(root,{childList:true,subtree:true});
})();
