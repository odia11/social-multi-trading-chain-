const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const s=fs.readFileSync(path.resolve(__dirname,'../static/dashboard.js'),'utf8');
const code=s.slice(s.indexOf('var _mentionTarget = null;'),s.indexOf('function tagUser(){'));
const events={},pending=[];
let rect={left:80,top:330,bottom:420,width:285};
const input={id:'postText',isConnected:true,value:'@oj',selectionStart:3,classList:{contains:()=>false},getBoundingClientRect:()=>rect,
 focus(){ctx.document.activeElement=this},setSelectionRange(a){this.selectionStart=a},dispatchEvent(){}};
const box={style:{display:'none'},children:[],replaceChildren(){this.children=[]},appendChild(r){this.children.push(r)},contains(){return false},
 get scrollHeight(){return this.children.length*42},get offsetWidth(){return parseFloat(this.style.width)||240},
 get offsetHeight(){return Math.min(this.scrollHeight+2,parseFloat(this.style.maxHeight)||200)}};
const viewport={offsetTop:0,offsetLeft:0,width:390,height:460,addEventListener:(n,f)=>events['vv'+n]=f};
const ctx={document:{activeElement:input,getElementById:()=>box,addEventListener:(n,f)=>events[n]=f,
 createElement:()=>({style:{},addEventListener(){}})},window:{visualViewport:viewport,addEventListener:(n,f)=>events['win'+n]=f},
 fetch:()=>new Promise(resolve=>pending.push(resolve)),requestAnimationFrame:f=>{f();return 0},setTimeout:f=>f(),Event:class{}};
vm.createContext(ctx);vm.runInContext(code,ctx);
const settle=async(users)=>{pending.shift()({ok:true,json:async()=>({users})});for(let i=0;i<6;i++)await Promise.resolve()};
(async()=>{
 ctx._mentionCheck(input);await settle([{username:'OJ'}]);
 assert.equal(box.style.top,'280px','single row is six pixels above field');
 rect={...rect,top:260,bottom:350};events.winscroll();
 assert.equal(box.style.top,'356px','list follows field after scrolling, below when room exists');
 viewport.height=360;events.vvresize();assert.equal(box.style.top,'210px','keyboard opening keeps list beside field');
 viewport.offsetTop=100;rect={...rect,top:320,bottom:410};events.vvscroll();assert.equal(box.style.top,'270px');
 rect={...rect,top:500,bottom:590};events.winscroll();assert.equal(box.style.display,'none','offscreen input closes list');
 rect={...rect,top:200,bottom:290};viewport.offsetTop=0;viewport.height=460;
 ctx._mentionCheck(input);ctx._mentionHide();await settle([{username:'Late'}]);assert.equal(box.style.display,'none','late result does not reopen');
 input.value='@o';input.selectionStart=2;ctx._mentionCheck(input);
 input.value='@oj';input.selectionStart=3;ctx._mentionCheck(input);
 await settle([{username:'Older'}]);assert.equal(box.style.display,'none');
 await settle([{username:'OJ'}]);assert.equal(box.children[0].textContent,'@OJ');
 ctx._mentionSelect('OJ');assert.equal(input.value,'@OJ ');assert.equal(input.selectionStart,4);assert.equal(box.style.display,'none');
 console.log('PASS: measured height, page scroll, keyboard resize, visual viewport pan, offscreen dismissal, stale results and insertion');
})().catch(e=>{console.error(e);process.exitCode=1});
