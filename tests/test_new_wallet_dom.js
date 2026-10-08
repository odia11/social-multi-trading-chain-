'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const nacl = require('../static/vendor/tweetnacl-1.0.3.min.js');
const root=path.resolve(__dirname,'..');
const alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function encode(bytes){let n=0n,s='',z=0;for(const b of bytes)n=n*256n+BigInt(b);while(n){s=alphabet[Number(n%58n)]+s;n/=58n;}while(z<bytes.length&&bytes[z]===0)z++;return '1'.repeat(z)+s;}
function decode(value){let n=0n,b=[],z=0;for(const c of value)n=n*58n+BigInt(alphabet.indexOf(c));while(n){b.unshift(Number(n%256n));n/=256n;}while(z<value.length&&value[z]==='1')z++;return Uint8Array.from([...Array(z).fill(0),...b]);}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const dom=new JSDOM('<button id="oa-guest-connect-btn">Connect</button>',{url:'https://orca.test/',runScripts:'outside-only'});
 const w=dom.window, requests=[];let late=false,resolveStart;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
 w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.TextEncoder=class{encode(text){return w.Uint8Array.from(Buffer.from(text));}};
 w.eval(fs.readFileSync(path.join(root,'static/vendor/tweetnacl-1.0.3.min.js'),'utf8'));
 const kp=nacl.sign.keyPair(),address=encode(kp.publicKey),privateKey=encode(kp.secretKey);
 w.fetch=async(url,options={})=>{
  if(url==='/api/csrf-token')return {ok:true,json:async()=>({token:'csrf-test'})};
  if(url==='/api/auth/nonce')return {ok:true,json:async()=>({nonce:'dom-nonce'})};
  const body=JSON.parse(options.body);requests.push({url,body});
  if(url==='/api/account/create-wallet/start'){
   if(late)await new Promise(resolve=>resolveStart=resolve);
   return {ok:true,json:async()=>({ok:true,address,private_key:privateKey,token:'token'})};
  }
  // Prevent navigation; inspect the request and exercise the retry/wipe path.
  return {ok:false,json:async()=>({error:'test response'})};
 };
 w.eval(fs.readFileSync(path.join(root,'static/new-wallet.js'),'utf8'));
 const click=s=>w.document.querySelector(s).click();
 click('#oa-guest-connect-btn');assert(w.document.querySelector('dialog').open);
 click('[data-create]');await tick();
 assert.equal(w.document.querySelector('#nw-key').type,'password');
 assert.equal(w.document.querySelector('#nw-key').value,privateKey);
 const form=w.document.querySelector('#nw-confirm');
 form.elements.username.value='dom_user';form.elements.password.value='long-enough-password';
 form.dispatchEvent(new w.Event('input'));
 assert(w.document.querySelector('[data-activate]').disabled);
 form.elements.backup.checked=true;form.dispatchEvent(new w.Event('input'));
 assert(!w.document.querySelector('[data-activate]').disabled);
 form.dispatchEvent(new w.Event('submit',{cancelable:true}));await tick();
 const activation=requests.find(r=>r.url==='/api/account/create-wallet/confirm').body;
 assert.deepEqual(Object.keys(activation).sort(),['confirmed_backup','password','token','username']);
 assert(!JSON.stringify(activation).includes(privateKey));assert.equal(w.document.querySelector('#nw-key'),null);
 click('[data-back]');click('[data-import]');
 const imported=w.document.querySelector('form');imported.elements.key.value=privateKey;
 imported.dispatchEvent(new w.Event('submit',{cancelable:true}));await tick();
 const login=requests.find(r=>r.url==='/api/wallet/set').body;
 assert.deepEqual(Object.keys(login).sort(),['address','nonce','signature']);assert.equal(login.address,address);
 assert(nacl.sign.detached.verify(Buffer.from('OrcAgent verification\n\nCode: dom-nonce'),decode(login.signature),kp.publicKey));
 assert.equal(imported.elements.key.value,'');assert(!JSON.stringify(login).includes(privateKey));
 assert.equal(w.localStorage.length,0);assert.equal(w.sessionStorage.length,0);
 click('[data-back]');late=true;click('[data-create]');await tick();click('.nw-close');resolveStart();await tick();
 assert(!w.document.querySelector('dialog').open);assert.equal(w.document.querySelector('#nw-key'),null);
 dom.window.close();console.log('PASS backup gate, credential payload, key wiping, local import signature, no secret storage, cancellation');
})().catch(error=>{console.error(error.message);process.exit(1);});
