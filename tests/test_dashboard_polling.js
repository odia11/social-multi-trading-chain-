// Exercise the production polling functions with controlled DOM/network state.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/dashboard.js'),'utf8');
const counters={};let hidden=false,onScreen=false,resolveFetch,requests=0;
let payload={tokens:[],positions_detail:[],log_lines:[],sol_price:100};
const node={style:{display:'block'},getClientRects:()=>onScreen?[{}]:[],getBoundingClientRect:()=>({top:0,bottom:100})};
const context={console,Promise,Set,JSON,window:{innerHeight:844},document:{get hidden(){return hidden},getElementById:()=>node,querySelector:()=>null},
 fetch:async()=>{requests++;if(resolveFetch)await new Promise(r=>resolveFetch=r);return {json:async()=>payload}},
 _solPrice:100,_lfPositions:[],_updateSolUsdc:()=>{},fmtSolToUsdc:()=>'',fmtNum:()=>'',esc:s=>s,
 setTimeout:()=>{},localStorage:{setItem:()=>{}},_authKey:'',traderOn:false,phantomKey:null};
for(const name of ['updateAuthBtns','updateBtns','checkForTrades','renderLog','renderMarket','_lfBuildMintMap','_checkClosedPositions','renderPositions','_lfCheckNewBuys','renderLiveFeed','_renderPnlcChart','_ensureLightweightCharts'])
 context[name]=()=>{counters[name]=(counters[name]||0)+1};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('let lastLogCount=0;'),source.indexOf('async function fetchMarketOnly(')),context);
vm.runInContext(source.slice(source.indexOf('let _pnlcChart='),source.indexOf('function _renderPnlcChart(')),context);
(async()=>{
 await context.fetchState();
 const rendered=counters.renderLiveFeed;
 await context.fetchState();
 assert.equal(counters.renderLiveFeed,rendered,'identical state must preserve the feed DOM');
 assert.equal(counters.renderMarket,1,'identical tokens must preserve market DOM');
 assert.equal(counters.renderLog,1,'identical logs must preserve log DOM');
 payload={...payload,sol_price:110};await context.fetchState();
 assert.equal(counters.renderPositions,2,'SOL valuation change must refresh positions');
 assert.equal(counters.renderLiveFeed,rendered+1,'SOL valuation change must refresh trade values');
 hidden=true;let before=requests;await context.fetchState();assert.equal(requests,before);
 let polls=0;const poll=context._oaPollTask(async()=>{polls++;await new Promise(r=>resolveFetch=r)});
 poll();await Promise.resolve();assert.equal(polls,0,'hidden polling pauses');
 hidden=false;const active=poll();await Promise.resolve();poll();assert.equal(polls,1,'overlapping poll is skipped');resolveFetch();await active;resolveFetch=null;
 before=requests;await context.fetchPnlChart();assert.equal(requests,before,'offscreen chart must not fetch');
 onScreen=true;payload={data:[]};await context.fetchPnlChart();assert.equal(requests,before+1,'visible chart fetches');
 console.log('PASS identical state, live valuation, hidden state, hidden polling, overlapping polling, offscreen/visible chart');
})().catch(e=>{console.error(e);process.exitCode=1});
