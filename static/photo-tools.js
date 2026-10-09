/* Local-only photo positioning: upload only the user's confirmed crop. */
(function(){
'use strict';
var active=null;
function modal(title){
  if(active)active.close();
  var d=document.createElement('dialog');d.className='oa-photo-dialog';d.setAttribute('aria-label',title);
  d.innerHTML='<form method="dialog" class="oa-photo-panel"><header><h2></h2><button value="cancel" aria-label="Close">×</button></header><div class="oa-photo-content"></div></form>';
  d.querySelector('h2').textContent=title;document.body.appendChild(d);active=d;
  d.addEventListener('keydown',function(e){if(e.key==='Escape')e.stopPropagation();});
  d.addEventListener('click',function(e){if(e.target===d)d.close();});
  d.addEventListener('close',function(){if(active===d)active=null;d.remove();},{once:true});
  return d;
}
var style=document.createElement('style');style.textContent=`
.oa-photo-dialog{margin:auto;padding:0;border:1px solid #303944;border-radius:20px;background:#10161f;color:#eef1f5;width:min(94vw,560px);max-height:94dvh;overflow:auto;box-shadow:0 20px 90px #0009;font:15px system-ui}
.oa-photo-dialog::backdrop{background:rgba(0,0,0,.86)}
.oa-photo-panel{padding:20px}.oa-photo-panel header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.oa-photo-panel h2{font-size:20px;margin:0}.oa-photo-panel button{cursor:pointer;border:1px solid #3b424e;border-radius:12px;padding:10px 16px;color:#eee;background:#202833;font:inherit}.oa-photo-panel header button{font-size:24px;padding:3px 12px}
.oa-photo-stage{position:relative;width:100%;overflow:hidden;border-radius:14px;background:#05090e;touch-action:none;cursor:grab}.oa-photo-stage canvas{display:block;width:100%;height:auto}.oa-photo-stage[data-circle]::after{content:'';position:absolute;inset:0;border-radius:50%;box-shadow:0 0 0 120px #0008;pointer-events:none;border:1px solid #fffc}.oa-photo-hint{color:#9aa5b4;line-height:1.5;margin:14px 0}.oa-photo-zoom{display:flex;align-items:center;gap:12px;margin:16px 0}.oa-photo-zoom input{flex:1;accent-color:#f7b955;min-width:0}.oa-photo-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}.oa-photo-actions .oa-photo-save{background:#f7b955;color:#0a0b0e;border-color:#f7b955;font-weight:700}.oa-photo-view{width:min(94vw,1000px)}.oa-photo-view img{display:block;max-width:100%;max-height:78dvh;object-fit:contain;margin:auto}
`;document.head.appendChild(style);
window.OrcAgentViewPhoto=function(url){
  if(!url)return;var d=modal('Photo');d.classList.add('oa-photo-view');
  var img=document.createElement('img');img.alt='Full-size photo';img.src=url;
  d.querySelector('.oa-photo-content').appendChild(img);d.showModal();
};
window.OrcAgentEditPhoto=function(file,options){
  options=options||{};
  return new Promise(function(resolve,reject){
    if(!file||!/^image\/(jpeg|png|gif|webp)$/.test(file.type)||file.size>12*1024*1024){reject(new Error('Choose a JPEG, PNG, GIF or WebP photo up to 12 MB'));return;}
    var url=URL.createObjectURL(file),img=new Image();
    img.onerror=function(){URL.revokeObjectURL(url);reject(new Error('That photo could not be read'));};
    img.onload=function(){
      var d=modal(options.title||'Position your photo'),settled=false;
      var content=d.querySelector('.oa-photo-content');
      content.innerHTML='<div class="oa-photo-stage"><canvas aria-label="Photo crop preview" tabindex="0"></canvas></div><p class="oa-photo-hint">Drag to position. Pinch or use the slider to zoom. Arrow keys move the photo.</p><label class="oa-photo-zoom">Zoom <input aria-label="Photo zoom" type="range" min="1" max="5" step="0.01" value="1"></label><div class="oa-photo-actions"><button type="button" data-reset>Reset</button><button value="cancel">Cancel</button><button type="button" class="oa-photo-save">Use photo</button></div>';
      var stage=content.querySelector('.oa-photo-stage'),cv=content.querySelector('canvas'),slider=content.querySelector('input');
      var aspect=Number(options.aspect)||1;aspect=Math.max(1,Math.min(6,aspect));
      cv.width=360;cv.height=Math.round(360/aspect);if(options.circle)stage.setAttribute('data-circle','');
      var ctx=cv.getContext('2d'),base=Math.max(cv.width/img.naturalWidth,cv.height/img.naturalHeight),zoom=1,x=0,y=0;
      var pointers=new Map(),distance=0;
      function draw(){var w=img.naturalWidth*base*zoom,h=img.naturalHeight*base*zoom;x=Math.max(-(w-cv.width)/2,Math.min((w-cv.width)/2,x));y=Math.max(-(h-cv.height)/2,Math.min((h-cv.height)/2,y));ctx.clearRect(0,0,cv.width,cv.height);ctx.drawImage(img,(cv.width-w)/2+x,(cv.height-h)/2+y,w,h);slider.value=String(zoom);}
      function point(e){var r=cv.getBoundingClientRect();return {x:(e.clientX-r.left)*cv.width/r.width,y:(e.clientY-r.top)*cv.height/r.height};}
      function gap(){var a=Array.from(pointers.values());return a.length===2?Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y):0;}
      stage.onpointerdown=function(e){e.preventDefault();stage.setPointerCapture(e.pointerId);pointers.set(e.pointerId,point(e));distance=gap();};
      stage.onpointermove=function(e){if(!pointers.has(e.pointerId))return;var old=pointers.get(e.pointerId),next=point(e);pointers.set(e.pointerId,next);if(pointers.size===1){x+=next.x-old.x;y+=next.y-old.y;}else{var g=gap();if(distance>0)zoom=Math.max(1,Math.min(5,zoom*g/distance));distance=g;}draw();};
      function up(e){pointers.delete(e.pointerId);distance=gap();}
      stage.onpointerup=up;stage.onpointercancel=up;stage.onlostpointercapture=up;
      slider.oninput=function(){zoom=Number(slider.value);draw();};
      stage.onwheel=function(e){e.preventDefault();zoom=Math.max(1,Math.min(5,zoom-e.deltaY*.002));draw();};
      cv.onkeydown=function(e){var delta={ArrowLeft:[-10,0],ArrowRight:[10,0],ArrowUp:[0,-10],ArrowDown:[0,10]}[e.key];if(delta){e.preventDefault();x+=delta[0];y+=delta[1];draw();}};
      content.querySelector('[data-reset]').onclick=function(){zoom=1;x=y=0;draw();};
      content.querySelector('.oa-photo-save').onclick=function(){
        try{var out=document.createElement('canvas');out.width=options.circle?512:1500;out.height=Math.round(out.width/aspect);var c=out.getContext('2d');c.fillStyle='#10161f';c.fillRect(0,0,out.width,out.height);var factor=out.width/cv.width,w=img.naturalWidth*base*zoom,h=img.naturalHeight*base*zoom;c.drawImage(img,((cv.width-w)/2+x)*factor,((cv.height-h)/2+y)*factor,w*factor,h*factor);settled=true;resolve(out.toDataURL('image/jpeg',.9));d.close();}catch(e){settled=true;reject(e);d.close();}
      };
      d.addEventListener('close',function(){URL.revokeObjectURL(url);pointers.clear();if(!settled)resolve(null);},{once:true});
      draw();d.showModal();
    };img.src=url;
  });
};
window.addEventListener('pagehide',function(){if(active)active.close();});
})();
