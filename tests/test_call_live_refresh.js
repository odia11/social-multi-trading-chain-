'use strict';
const assert = require('node:assert/strict');
let tick, scheduled, requests = [], quote, fail = false, hidden = false;
global.window = global;
window.innerHeight = 900;
window.addEventListener = function(){};
global.setTimeout = fn => {scheduled = fn; return 1;};
global.clearTimeout = () => {};
global.setInterval = fn => {tick = fn; return 1;};
const attrs = {'data-mint':'A'.repeat(32), 'data-chain':'solana', 'data-entry':'1', 'data-now':'1', 'data-called':'2026-01-01 00:00:00'};
const svg = {getAttribute:k=>attrs[k], setAttribute:(k,v)=>{attrs[k]=v;}, removeAttribute:k=>{delete attrs[k];},classList:{add(){},remove(){}},innerHTML:''};
const stats = [{textContent:'$100'},{textContent:'$100'},{textContent:'$100'}];
const multi = {}, status = {};
const card = {isConnected:true,getAttribute:k=>k==='data-call-id'?'1':attrs['data-mint'],getBoundingClientRect:()=>({top:10,bottom:400}),
  querySelectorAll:()=>stats,querySelector:s=>s==='.fcall-multi b'?multi:s==='.fcall-live-status'?status:svg};
const feed = {querySelectorAll:()=>attrs['data-watched']?[]:[svg]};
global.document = {readyState:'complete',get hidden(){return hidden;},getElementById:id=>id==='center-feed'?feed:null,
  querySelectorAll:()=>[card], addEventListener(){}};
global.OrcPageLifecycle = {mutationObserver:()=>({observe(){}})};
global.fetch = (url,options) => {
  requests.push({url,options});
  if(url.startsWith('/api/chart/')) return Promise.resolve({ok:true,json:()=>Promise.resolve({candles:[{t:1,c:999},{t:1767225601,c:1.5}]})});
  if(fail) return Promise.reject(new Error('offline'));
  return Promise.resolve({ok:true,json:()=>Promise.resolve({ok:true,calls:[quote]})});
};
const base = {id:1,mint:attrs['data-mint'],price_at_call:1,mcap_at_call:100,last_price:2,peak_price:3,mcap_now:220,mcap_peak:330,multiplier:3,now_multiplier:2,quote_at:Date.now()/1000,stale:false};
quote = {...base};
require('../static/feed-calls.js');
const settle = () => new Promise(resolve=>setImmediate(resolve));
(async()=>{
  scheduled();await settle();
  assert.equal(stats[0].textContent,'$100');
  assert.equal(stats[1].textContent,'$220.00');
  assert.equal(multi.textContent,'3.0x');
  assert.match(status.textContent,/Updated/);
  assert.equal(attrs['data-now'],'2');
  assert.equal(requests.find(r=>r.url.startsWith('/api/calls/live')).options.cache,'no-store');
  assert.ok(svg.innerHTML.includes('fcall-spark-line'));
  const firstCard = card;
  quote = {...base,last_price:.5,mcap_now:55,now_multiplier:.5};tick();await settle();
  assert.equal(stats[1].textContent,'$55.00');assert.equal(stats[1].className,'down');
  assert.equal(stats[2].textContent,'$3.00');assert.equal(card,firstCard);
  quote = {...base,mint:'B'.repeat(32)};tick();await settle();
  assert.equal(stats[1].textContent,'$55.00');
  const count=requests.length;hidden=true;tick();await settle();assert.equal(requests.length,count);
  hidden=false;fail=true;tick();await settle();assert.equal(stats[1].textContent,'$55.00');assert.match(status.textContent,/unavailable/);
  console.log('PASS: initial refresh, interval, immutable entry, peak retention, exact mint, hidden-page pause, no-store, chart, failure retention, stable DOM');
})().catch(e=>{console.error(e);process.exitCode=1;});
