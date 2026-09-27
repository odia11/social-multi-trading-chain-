'use strict';
// Offline frontend route test: no wallet keys, no real network or Phantom app.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/dashboard.js', 'utf8');
const pick = (start, end) => {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a + start.length);
  assert(a >= 0 && b > a, `Expected function bounds for ${start}`);
  return source.slice(a, b);
};
const safe = pick('function _safeWalletReturnRoute(raw){', 'function _currentWalletReturnRoute(){');
const mobile = pick('function _phantomMobileV1Connect(returnRoute){', '// window.solana is a single global');
async function run(isStandalonePWA) {
  let pairStored = '', routeStored = '', referrer = '', link = '';
  const requests = [];
  const location = {
    origin:'https://orcagent.fun', pathname:'/live-market', search:'?tab=gainers', hash:'#top',
    get href(){ return link; }, set href(value){ link=value; }
  };
  const box = {
    URL, URLSearchParams, Promise, console:{log(){},error(){}},
    localStorage:{removeItem(){}}, document:{getElementById(){return null;}},
    window:{location}, isStandalonePWA,
    _currentWalletReturnRoute(){return '/live-market?tab=gainers#top';},
    _storePairReturnRoute(value){routeStored=value;},
    _storePairToken(value){pairStored=value;},
    fetch: async (path, opts) => {
      requests.push({path, opts});
      if(path==='/api/pair/start') return {json:async()=>({ok:true,pair:'offline-test-pair-token'})};
      if(path==='/api/phantom/init') return {json:async()=>({ok:true,dapp_pk:'mock-dapp-pubkey',token:'0123456789abcdef'})};
      throw Error('Unmocked endpoint '+path);
    },
  };
  vm.createContext(box);
  vm.runInContext(safe + mobile, box);
  box._phantomMobileV1Connect('/live-market?tab=gainers#top');
  for(let i=0; i<10 && !link; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 2);
  assert.equal(requests[0].path, '/api/pair/start');
  assert.equal(requests[1].path, '/api/phantom/init');
  assert.equal(JSON.parse(requests[1].opts.body).pair, 'offline-test-pair-token');
  assert.equal(pairStored, 'offline-test-pair-token');
  assert.equal(routeStored, '/live-market?tab=gainers#top');
  assert(link.startsWith('https://phantom.app/ul/v1/connect?'));
  assert(!link.includes('/ul/browse/'));
  const params = new URL(link).searchParams;
  const cb = new URL(params.get('redirect_link'));
  assert.equal(cb.hostname, 'orcagent.fun');
  assert.equal(cb.pathname, '/phantom-callback');
  assert.equal(cb.searchParams.get('return_to'), '/live-market?tab=gainers#top');
  assert.equal(cb.searchParams.get('source'), isStandalonePWA ? 'pwa' : 'browser');
  assert(!link.includes('offline-test-pair-token'));
  console.log('PASS '+(isStandalonePWA?'installed PWA':'ordinary Safari/Chrome')+' uses signed Phantom Connect, preserves OrcAgent return route and keeps pair token out of URL');
}
async function main(){
  await run(false);
  await run(true);
  const box={URL,window:{location:{origin:'https://orcagent.fun'}}};
  vm.createContext(box);
  vm.runInContext(safe,box);
  assert.equal(box._safeWalletReturnRoute('https://evil.invalid/fake'),'/');
  assert.equal(box._safeWalletReturnRoute('//evil.invalid/fake'),'/');
  assert.equal(box._safeWalletReturnRoute('/phantom-callback?token=secret'),'/');
  assert.equal(box._safeWalletReturnRoute('/live-market?tab=new#start'),'/live-market?tab=new#start');
  console.log('PASS cross-origin and recursive return routes are rejected while same-site deep links work');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
