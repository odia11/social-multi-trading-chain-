const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements={};
for(const id of ['cv-amount','cv-quote','cv-quote-btn','cv-max','cv-balance','cv-chain','cv-direction'])elements[id]={value:'',innerHTML:'',textContent:'',disabled:false};
elements['cv-chain'].value='solana';elements['cv-direction'].value='stable_to_native';
let calls=[],resolveQuote;
const ctx={document:{getElementById:id=>elements[id],querySelectorAll:()=>[]},URLSearchParams,Date,Number,parseFloat,console,
_CONVERT_CHAINS:[{v:'solana',native:'SOL',stable:'USDC'}],esc:s=>s,_csrf:'test',
fetch:(url,options)=>{calls.push([url,options]);return new Promise(r=>{resolveQuote=r})}};
const path=require('path');
const template=fs.readFileSync(path.join(__dirname,'../templates/wallet.html'),'utf8');
vm.createContext(ctx);vm.runInContext(template.slice(template.indexOf('var _convertQuote'),template.indexOf('// ── bridge modal')),ctx);
ctx._convertMax='20.088712';ctx._convertUseMax();assert.equal(elements['cv-amount'].value,'20.088712');
ctx._convertGetQuote();assert(calls[0][0].startsWith('/api/wallet/sol-swap/quote?'));
ctx._convertInvalidate();
resolveQuote({json:async()=>({ok:true,quote_id:'old',out_amount:1})});
setImmediate(()=>{
 assert.equal(ctx._convertQuote,null,'stale quote must not become confirmable');
 ctx._convertQuote={quote_id:'q',expires_at:Date.now()+45000};ctx._convertConfirm();ctx._convertConfirm();
 assert.equal(calls.filter(c=>c[0]==='/api/wallet/sol-swap/execute').length,1);
 ctx._convertBusy=false;ctx._convertMax='0.118456789';ctx._convertUseMax();
 assert.equal(elements['cv-amount'].value,'0.118456789');
 console.log('PASS: exact Max precision, gasless route, stale quote rejected, double submit blocked');
});