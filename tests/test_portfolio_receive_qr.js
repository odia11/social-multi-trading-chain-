/* Portfolio "Receive" must show a REAL, scannable QR code of the wallet
   address. It used to draw a 7x7 decorative pattern hashed from the address
   (_qrPattern), which no wallet or exchange could scan. The code is encoded
   in the browser by the vendored qrcode-generator (MIT), so the address is
   never sent to a third-party QR service. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const crypto=require('node:crypto');
const html=fs.readFileSync('templates/wallet.html','utf8');
const libPath='static/vendor/qrcode-generator-1.4.4.js';
const lib=fs.readFileSync(libPath,'utf8');

// Vendored library: exact upstream file (npm qrcode-generator@1.4.4), MIT.
assert.equal(crypto.createHash('sha256').update(lib).digest('hex'),
  '18ae399f81182bc9de916e9c77b195df20cc58d6f2d55a62b085a299f1bf1780');
assert(/Licensed under the MIT license/.test(lib));
assert(html.includes('<script src="/static/vendor/qrcode-generator-1.4.4.js" defer></script>'));
assert(!/api\.qrserver\.com|chart\.googleapis/.test(html),'no third-party QR service');

// The fake pattern is gone everywhere on the page.
assert(!/_qrPattern/.test(html),'decorative fake QR removed');

const script=[...html.matchAll(/<script(?![^>]*src)[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(b=>b.includes('function _modalDeposit('));
function grab(name){const a=script.indexOf('function '+name+'(');assert(a>=0,name);return script.slice(a,script.indexOf('\n}',a)+2);}
const dep=grab('_modalDeposit');
assert(/_qrSvg\(addr,'H'\)/.test(dep),'receive QR uses error correction H (logo in the middle)');
assert(/el\.style\.display='none'; return   \/\/ never show a fake code/.test(dep));

// _qrSvg draws exactly the modules the encoder produced, with a quiet zone.
const ctx={String,Math};
vm.createContext(ctx);
vm.runInContext(lib+'\n'+grab('_qrSvg'),ctx);
const addr='Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9';
const svg=ctx._qrSvg(addr,'H');
const qr=ctx.qrcode(0,'H'); qr.addData(addr); qr.make();
const n=qr.getModuleCount(); let dark=0;
for(let r=0;r<n;r++) for(let c=0;c<n;c++) if(qr.isDark(r,c)) dark++;
assert.equal((svg.match(/h1v1h-1z/g)||[]).length,dark,'every dark module drawn');
assert(svg.includes(`viewBox="0 0 ${n+8} ${n+8}"`),'4-module quiet zone');
assert(/fill="#fff"/.test(svg)&&/fill="#0b0f14"/.test(svg),'dark on white for reliable scanning');
// Without the library: no QR at all rather than a fake one.
const ctx2={String,Math}; vm.createContext(ctx2); vm.runInContext(grab('_qrSvg'),ctx2);
assert.equal(ctx2._qrSvg(addr),'');
console.log('PASS Portfolio receive: real scannable QR code of the wallet address');
