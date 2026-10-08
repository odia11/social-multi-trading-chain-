'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const nacl = require('../static/vendor/tweetnacl-1.0.3.min.js');
const root = path.resolve(__dirname, '..');
const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function encode(bytes) { let n=0n,s='',z=0; for(const b of bytes)n=n*256n+BigInt(b); while(n){s=alphabet[Number(n%58n)]+s;n/=58n;} while(z<bytes.length&&bytes[z]===0)z++;return '1'.repeat(z)+s; }
function decode(value) {let n=0n,b=[],z=0;for(const c of value)n=n*58n+BigInt(alphabet.indexOf(c));while(n){b.unshift(Number(n%256n));n/=256n;}while(z<value.length&&value[z]==='1')z++;return Uint8Array.from([...Array(z).fill(0),...b]);}
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  for(const viewport of [{width:1280,height:900},{width:390,height:844}]){
   const context=await browser.newContext({viewport});const page=await context.newPage();
   const kp=nacl.sign.keyPair(), address=encode(kp.publicKey), privateKey=encode(kp.secretKey);
   const requests=[];let delayed=false,resolveStart;
   await page.route('https://orca.test/**',async route=>{
    const url=new URL(route.request().url()),p=url.pathname;
    if(p.startsWith('/static/'))return route.fulfill({body:fs.readFileSync(path.join(root,p.slice(1))),contentType:p.endsWith('.css')?'text/css':'text/javascript'});
    if(p==='/api/csrf-token')return route.fulfill({json:{token:'csrf-test'}});
    if(p==='/api/auth/nonce')return route.fulfill({json:{nonce:'local-signature-test'}});
    if(route.request().method()==='POST'){
     const body=route.request().postDataJSON();requests.push({p,body});
     if(p==='/api/account/create-wallet/start'){
      if(delayed)await new Promise(resolve=>resolveStart=resolve);
      return route.fulfill({json:{ok:true,address,private_key:privateKey,token:'one-time-token'}});
     }
     return route.fulfill({json:{ok:true,has_trading_key:true}});
    }
    return route.fulfill({body:'<!doctype html><button id="oa-guest-connect-btn">Connect</button><script src="/static/vendor/tweetnacl-1.0.3.min.js" defer></script><script src="/static/new-wallet.js" defer></script><link rel="stylesheet" href="/static/new-wallet.css">',contentType:'text/html'});
   });
   await page.goto('https://orca.test/');
   await page.click('#oa-guest-connect-btn');
   for(const text of ['Create new wallet','Connect Phantom','Enter address','Import key / sign in'])assert(await page.getByRole('button',{name:text,exact:true}).isVisible());
   await page.click('[data-create]');await page.waitForSelector('#nw-key');
   assert.equal(await page.locator('#nw-key').getAttribute('type'),'password');
   assert.equal(await page.locator('#nw-key').inputValue(),privateKey);
   await page.click('[data-show]');assert.equal(await page.locator('#nw-key').getAttribute('type'),'text');
   const box=await page.locator('#oa-new-wallet').boundingBox();assert(box.width<=viewport.width&&box.height<=viewport.height);
   await page.fill('[name=username]','browser_user');await page.fill('[name=password]','ten-characters');
   assert(await page.locator('[data-activate]').isDisabled());await page.check('[name=backup]');assert(await page.locator('[data-activate]').isEnabled());
   await page.click('[data-activate]');await page.waitForFunction(()=>!document.querySelector('dialog'));
   const confirmation=requests.find(r=>r.p==='/api/account/create-wallet/confirm').body;
   assert.deepEqual(Object.keys(confirmation).sort(),['confirmed_backup','password','token','username']);
   assert.equal(confirmation.confirmed_backup,true);assert(!JSON.stringify(confirmation).includes(privateKey));
   await page.click('#oa-guest-connect-btn');await page.click('[data-import]');await page.fill('[name=key]',privateKey);await page.click('button[type=submit]');
   await page.waitForFunction(()=>!document.querySelector('dialog'));
   const login=requests.find(r=>r.p==='/api/wallet/set').body;
   assert.deepEqual(Object.keys(login).sort(),['address','nonce','signature']);assert.equal(login.address,address);
   assert(nacl.sign.detached.verify(Buffer.from('OrcAgent verification\n\nCode: '+login.nonce),decode(login.signature),kp.publicKey));
   assert(!JSON.stringify(login).includes(privateKey));
   assert(await page.evaluate(()=>localStorage.length===0&&sessionStorage.length===0));
   await page.click('#oa-guest-connect-btn');await page.click('[data-address]');await page.fill('[name=address]',address);await page.click('button[type=submit]');
   await page.waitForFunction(()=>!document.querySelector('dialog'));
   assert.equal(requests.find(r=>r.p==='/api/wallet/connect-readonly').body.address,address);
   // A late creation response must never restore a key after the dialog closes.
   delayed=true;await page.click('#oa-guest-connect-btn');await page.click('[data-create]');
   await page.waitForFunction(()=>document.querySelector('#nw-title').textContent==='Creating your wallet');
   while(!resolveStart)await new Promise(resolve=>setTimeout(resolve,10));
   await page.keyboard.press('Escape');resolveStart();await page.waitForTimeout(100);
   assert.equal(await page.locator('#nw-key').count(),0);
   await context.close();
  }
  console.log('PASS desktop + mobile backup, activation, local import signatures, readonly and cancellation');
 } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exit(1);});
