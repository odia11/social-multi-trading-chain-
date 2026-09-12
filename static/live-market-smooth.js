/* UI-only smoothing for Calls charts. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/live-market')return;
function tune(){
  document.querySelectorAll('.pt-chart-wrap').forEach(function(w){
    if(w.dataset.oaSmooth==='1')return;
    w.dataset.oaSmooth='1';
    var svg=w.querySelector('.pt-chart-svg');
    if(svg){svg.style.willChange='contents';svg.style.transform='translateZ(0)';}
    var pill=w.querySelector('.pt-price-pill');
    if(pill){pill.style.willChange='transform,top';}
  });
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',tune);else tune();
new MutationObserver(tune).observe(document.documentElement,{childList:true,subtree:true});
})();
