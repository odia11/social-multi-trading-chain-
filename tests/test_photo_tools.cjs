const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const root=path.resolve(__dirname,'..');
const group=fs.readFileSync(root+'/static/group-chats.js','utf8');
const clicks=group.slice(group.indexOf("document.addEventListener('click',function(e){\n  var avatar"),group.indexOf("document.addEventListener('dblclick'"));
const setPhoto=group.slice(group.indexOf('function setPhoto(file){'),group.indexOf('function isMe('));
(async()=>{
 const b=await chromium.launch({executablePath:process.env.ORCAGENT_CHROMIUM,args:['--no-sandbox']});
 try{for(const width of [390,1280]){
 const p=await b.newPage({viewport:{width,height:844},hasTouch:true});
 await p.setContent('<button id="before">Open</button>');await p.addScriptTag({content:fs.readFileSync(root+'/static/photo-tools.js','utf8')});
 await p.evaluate(()=>{
  const c=document.createElement('canvas');c.width=800;c.height=400;const x=c.getContext('2d');x.fillStyle='red';x.fillRect(0,0,400,400);x.fillStyle='blue';x.fillRect(400,0,400,400);
  window.file=new File([Uint8Array.from(atob(c.toDataURL().split(',')[1]),v=>v.charCodeAt(0))],'test.png',{type:'image/png'});
  window.openCrop=opts=>{window.result=undefined;OrcAgentEditPhoto(file,opts).then(v=>result=v);};openCrop({circle:true});
 });
 await p.locator('.oa-photo-stage').waitFor();
 if(width===390){
  const box=await p.locator('canvas').boundingBox(),cdp=await p.context().newCDPSession(p),cx=box.x+box.width/2,cy=box.y+box.height/2;
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:cx-20,y:cy,id:1},{x:cx+20,y:cy,id:2}]});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:cx-55,y:cy,id:1},{x:cx+55,y:cy,id:2}]});
  await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  assert.ok(Number(await p.getByRole('slider').inputValue())>1,'pinch zoom');
 }
 await p.getByRole('slider').fill('2');
 const box=await p.locator('canvas').boundingBox();await p.mouse.move(box.x+box.width/2,box.y+box.height/2);await p.mouse.down();await p.mouse.move(box.x+box.width*.85,box.y+box.height/2);await p.mouse.up();
 await p.getByRole('button',{name:'Use photo',exact:true}).click();await p.waitForFunction(()=>typeof result==='string');
 const sample=await p.evaluate(async()=>{const i=new Image();i.src=result;await i.decode();const c=document.createElement('canvas');c.width=i.width;c.height=i.height;const x=c.getContext('2d');x.drawImage(i,0,0);return {w:i.width,h:i.height,p:Array.from(x.getImageData(256,256,1,1).data)};});
 assert.equal(sample.w,512);assert.equal(sample.h,512);assert.ok(sample.p[0]>sample.p[2],JSON.stringify(sample));
 await p.evaluate(()=>openCrop({aspect:3,title:'Banner'}));await p.locator('.oa-photo-stage').waitFor();await p.getByRole('button',{name:'Reset',exact:true}).click();await p.getByRole('button',{name:'Use photo',exact:true}).click();await p.waitForFunction(()=>typeof result==='string');
 const size=await p.evaluate(async()=>{const i=new Image();i.src=result;await i.decode();return [i.width,i.height]});assert.deepEqual(size,[1500,500]);
 await p.evaluate(()=>openCrop({circle:true}));await p.locator('.oa-photo-stage').waitFor();await p.getByRole('button',{name:'Cancel',exact:true}).click();await p.waitForFunction(()=>result===null);
 await p.evaluate(()=>OrcAgentViewPhoto(URL.createObjectURL(file)));await p.locator('.oa-photo-view img').waitFor();assert.equal(await p.locator('dialog').evaluate(e=>e.open),true);await p.keyboard.press('Escape');await p.waitForFunction(()=>!document.querySelector('dialog'));assert.equal(await p.locator('dialog').count(),0);
 await p.evaluate(()=>openCrop({circle:true}));await p.locator('.oa-photo-stage').waitFor();await p.evaluate(()=>dispatchEvent(new Event('pagehide')));await p.waitForFunction(()=>result===null);
 await p.addScriptTag({content:clicks});
 await p.evaluate(()=>{document.body.insertAdjacentHTML('beforeend','<span class="gc-msg-av"><img id="group-avatar" alt="User photo"></span>');document.getElementById('group-avatar').src=URL.createObjectURL(file);});
 await p.locator('#group-avatar').click();await p.locator('.oa-photo-view img').waitFor();await p.keyboard.press('Escape');await p.waitForFunction(()=>!document.querySelector('dialog'));
 await p.evaluate(()=>{window.open={id:7};window.uploads=[];window.toast=()=>{};window.api=(url,opts)=>{uploads.push({url,opts});return Promise.resolve({ok:false,msg:'test'});};});
 await p.addScriptTag({content:setPhoto});await p.evaluate(()=>setPhoto(file));await p.locator('.oa-photo-stage').waitFor();await p.getByRole('button',{name:'Cancel',exact:true}).click();await p.waitForFunction(()=>!document.querySelector('dialog'));assert.equal(await p.evaluate(()=>uploads.length),0);
 await p.evaluate(()=>setPhoto(file));await p.locator('.oa-photo-stage').waitFor();await p.getByRole('button',{name:'Use photo',exact:true}).click();await p.waitForFunction(()=>uploads.length===1);assert.equal(await p.evaluate(()=>uploads[0].url),'/api/group-chats/7/photo');

 await p.close();console.log('PASS '+width+': drag/zoom exported original photo at selected position; banner 1500×500; cancel no result; full-size viewer and route cleanup');
 }}finally{await b.close()}
})().catch(e=>{console.error(e);process.exit(1)});
