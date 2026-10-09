/* A hanging response must release the shared flight without losing balances. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(root,'templates/wallet.html'),'utf8');
const source=html.slice(html.indexOf('function _getPortfolioSnapshot(forceFresh)'),html.indexOf('window.OrcAgentGetPortfolioSnapshot='));
function fixture(cached=null){
  const nodes={'pf-performance':{textContent:''},'oa-pf-scope':{textContent:''}};
  let calls=0,signals=[],paints=[];
  const c={Promise,Error,AbortController,Date,Object,setTimeout,clearTimeout,
    _PORTFOLIO_REQUEST_TIMEOUT:25,_portfolioSnapshotData:cached,_portfolioSnapshotAt:0,
    _portfolioSnapshotPromise:null,_portfolioForcedPromise:null,
    document:{getElementById:id=>nodes[id]},
    _rememberPortfolioSnapshot:()=>{},_paintPortfolioSnapshotInstant:s=>paints.push(s),
    fetch:(url,opts)=>{calls++;signals.push(opts.signal);return c.read(url,opts)}};
  vm.createContext(c);vm.runInContext(source,c);
  return {c,nodes,signals,paints,calls:()=>calls};
}
(async()=>{
  // The transport ignores abort; Promise.race still releases the flight.
  let f=fixture({ok:true,total_usd:42,inventory_complete:true});
  let late;f.c.read=()=>new Promise(r=>late=r);
  const first=f.c._getPortfolioSnapshot(false);
  assert.equal(first,f.c._getPortfolioSnapshot(false));assert.equal(f.calls(),1);
  await assert.rejects(first,/timed out/);
  assert.equal(f.signals[0].aborted,true);assert.equal(f.c._portfolioSnapshotPromise,null);
  assert.equal(f.c._portfolioSnapshotData.total_usd,42);
  assert.match(f.nodes['pf-performance'].textContent,/Last confirmed balance/);
  f.c.read=()=>Promise.resolve({ok:true,json:()=>Promise.resolve({ok:true,total_usd:43,inventory_complete:true})});
  await f.c._getPortfolioSnapshot(false);assert.equal(f.c._portfolioSnapshotData.total_usd,43);
  late({ok:true,json:()=>Promise.resolve({ok:true,total_usd:999})});
  await new Promise(r=>setTimeout(r,5));assert.equal(f.c._portfolioSnapshotData.total_usd,43);
  assert.equal(f.paints.length,1);
  // A stalled JSON body is also bounded; a forced refresh recovers after it.
  f=fixture();f.c.read=()=>Promise.resolve({ok:true,json:()=>new Promise(()=>{})});
  const hung=f.c._getPortfolioSnapshot(false),forced=f.c._getPortfolioSnapshot(true);
  assert.equal(forced,f.c._getPortfolioSnapshot(true));
  await assert.rejects(hung,/timed out/);
  f.c.read=()=>Promise.resolve({ok:true,json:()=>Promise.resolve({ok:true,total_usd:0,inventory_complete:true})});
  await assert.rejects(forced,/timed out/);
  assert.equal(f.c._portfolioForcedPromise,null);
  await f.c._getPortfolioSnapshot(true);assert.equal(f.c._portfolioSnapshotData.total_usd,0);
  assert.equal(f.calls(),3);
  console.log('PASS stalled transport/body bounded, shared flight released, stale balances retained, late response ignored, forced retry recovered');
})().catch(e=>{console.error(e);process.exitCode=1});
