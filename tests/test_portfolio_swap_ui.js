/* Portfolio "Swap" (SOL <-> USDC) is a one-screen, wallet-app style swap:
   live quote while typing (no separate "Get Quote" step), 25/50/Max chips,
   a flip button, a Swap button that says what's missing, and a big amount
   field that a site-wide 16px!important input rule can't shrink. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('templates/wallet.html','utf8');
const script=[...html.matchAll(/<script(?![^>]*src)[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(b=>b.includes('function _modalSolUsdcSwap('));
assert(script,'swap script block not found');
function grab(name){const a=script.indexOf('function '+name+'(');assert(a>=0,name+' missing');return script.slice(a,script.indexOf('\n}',a)+2);}

const swap=grab('_modalSolUsdcSwap');
assert(!/Get Quote/.test(swap),'no separate Get Quote step');
for(const id of ['cv-amount','sx-flip','sx-out','sx-cta','cv-chain','cv-direction','cv-quote'])
  assert(swap.includes('id="'+id+'"'),id+' in the swap screen');
assert(/data-p="0\.25"[\s\S]*data-p="0\.5"[\s\S]*data-p="1"/.test(swap),'25/50/Max chips');
assert(/inputmode="decimal"/.test(swap));
assert(/setTimeout\(_sxQuote,450\)/.test(grab('_sxInput')),'quote is debounced while typing');
assert(/_sxSetCta\('Insufficient '\+_sxFrom\(\),false,true\)/.test(grab('_sxInput')));
assert(/_sxSetCta\('Enter an amount',false\)/.test(grab('_sxInput')));
assert(/!_sxOpen\(\)/.test(grab('_sxQuote')),'no quotes once the modal is closed');
assert(/_convertConfirm\(\)/.test(grab('_sxSwap')),'executes through the existing confirm path');
assert(/expires_at-3000/.test(grab('_sxSwap')),'refreshes a quote about to expire before swapping');

// Amount parsing accepts a Dutch decimal comma; formatting is sane.
const els={'cv-amount':{value:'0,0015'}};
const ctx={document:{getElementById:id=>els[id]},Number,parseFloat,Math,String};
vm.createContext(ctx);
vm.runInContext([grab('_sxEl'),grab('_sxAmount'),grab('_sxFmt')].join('\n'),ctx);
assert.equal(ctx._sxAmount(),0.0015);
assert.equal(ctx._sxFmt(1234.5,'USDC'),'1,234.50');
assert.equal(ctx._sxFmt(0.2134651,'USDC'),'0.213465');
assert.equal(ctx._sxFmt(0.04392141,'SOL'),'0.043921');

// The big amount survives the site-wide `font-size:16px!important` on inputs.
assert(/#w-modal input\.sx-amt\{font-size:34px!important/.test(html));
// _showModal clears the swap styling for every other modal.
assert(/box\.classList\.remove\('sx-box'\)/.test(html));
console.log('PASS Portfolio swap: one-screen SOL<->USDC swap with live quote');
