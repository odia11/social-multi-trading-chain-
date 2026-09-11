/* OrcAgent Live Market v2 interaction layer.
   Presentation only: existing scanner + openBuySheet/openSellSheet + quote/trade engine remain authoritative. */
(function(){
'use strict';
var path=location.pathname.replace(/\/+$/,'')||'/';
if(path!=='/live-market') return;
document.documentElement.classList.add('oa-live-v2-root');
function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn);else fn();}

function activeSortKey(){
  try{return (window.ST&&ST.sort)||'trending';}catch(e){return 'trending';}
}
function clickExistingSort(key){
  var selectors=['[data-sort="'+key+'"]','[data-action="sort"][data-value="'+key+'"]','button[value="'+key+'"]'];
  for(var i=0;i<selectors.length;i++){
    var el=document.querySelector(selectors[i]);
    if(el){el.click();return true;}
  }
  try{
    if(window.ST){ST.sort=key;if(typeof loadFeed==='function')loadFeed(true);else if(typeof refreshFeed==='function')refreshFeed();return true;}
  }catch(e){}
  return false;
}
function injectQuickFilters(){
  if(document.getElementById('oa-lm-quick')) return;
  var anchor=document.querySelector('.pt-feed-hd')||document.querySelector('.pt-search-wrap')||document.querySelector('.pt-feed');
  if(!anchor) return;
  var row=document.createElement('div');row.id='oa-lm-quick';row.className='oa-lm-quick';
  [['trending','🔥 Trending'],['gainers','↗ Gainers'],['new','◉ New'],['volume','◌ Volume']].forEach(function(d){
    var b=document.createElement('button');b.type='button';b.dataset.sort=d[0];b.textContent=d[1];b.classList.toggle('active',activeSortKey()===d[0]);
    b.addEventListener('click',function(){if(clickExistingSort(d[0]))row.querySelectorAll('button').forEach(function(x){x.classList.toggle('active',x===b)});});
    row.appendChild(b);
  });
  if(anchor.nextSibling)anchor.parentNode.insertBefore(row,anchor.nextSibling);else anchor.parentNode.appendChild(row);
}

function switchMode(mode){
  try{
    if(typeof _sheetIdx==='undefined'||_sheetIdx==null) return;
    if(mode==='sell'&&typeof openSellSheet==='function')openSellSheet(_sheetIdx);
    if(mode==='buy'&&typeof openBuySheet==='function')openBuySheet(_sheetIdx);
  }catch(e){}
}
function syncSwipeText(sheet){
  var hint=sheet.querySelector('.oa-swipe-hint b');if(!hint)return;
  hint.textContent=sheet.classList.contains('sell-mode')?'Swipe left to buy':'Swipe right to sell';
}
function installSwipe(){
  var sheet=document.getElementById('pt-sheet');if(!sheet||sheet.dataset.oaSwipe==='1')return;
  sheet.dataset.oaSwipe='1';
  var sw=document.createElement('div');sw.className='oa-swipe-mode';sw.setAttribute('aria-label','Buy or sell');
  sw.innerHTML='<button type="button" data-mode="buy">Buy</button><button type="button" data-mode="sell">Sell</button>';
  var hint=document.createElement('div');hint.className='oa-swipe-hint';hint.innerHTML='↔ <b>Swipe right to sell</b> ↔';
  var hd=sheet.querySelector('.pt-sheet-hd');
  if(hd&&hd.nextSibling){hd.parentNode.insertBefore(sw,hd.nextSibling);hd.parentNode.insertBefore(hint,sw.nextSibling);}else{sheet.insertBefore(sw,sheet.firstChild);sheet.insertBefore(hint,sw.nextSibling);}
  sw.addEventListener('click',function(e){var b=e.target.closest('[data-mode]');if(b)switchMode(b.dataset.mode);});
  var sx=0,sy=0,tracking=false;
  sw.addEventListener('touchstart',function(e){if(e.touches.length!==1)return;sx=e.touches[0].clientX;sy=e.touches[0].clientY;tracking=true;},{passive:true});
  sw.addEventListener('touchend',function(e){if(!tracking)return;tracking=false;var t=e.changedTouches&&e.changedTouches[0];if(!t)return;var dx=t.clientX-sx,dy=t.clientY-sy;if(Math.abs(dx)<54||Math.abs(dx)<Math.abs(dy)*1.15)return;if(dx>0)switchMode('sell');else switchMode('buy');},{passive:true});
  if(window.MutationObserver)new MutationObserver(function(){syncSwipeText(sheet);}).observe(sheet,{attributes:true,attributeFilter:['class']});
  syncSwipeText(sheet);
}
ready(function(){document.body.classList.add('oa-live-v2');injectQuickFilters();installSwipe();setTimeout(function(){injectQuickFilters();installSwipe();},700);});
})();
