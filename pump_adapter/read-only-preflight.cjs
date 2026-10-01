'use strict';
require('./runtime-check.cjs');
/** Mainnet preflight only: NO wallet key, network transaction, token creation or fee claim.
 * Run from pump_adapter with node read-only-preflight.cjs. Public RPC is the
 * fallback; the operator may supply ORCA_LAUNCH_RPC from the trusted host env.
 */
const {OnlinePumpSdk,PUMP_SDK,PUMP_PROGRAM_ID,PUMP_FEE_PROGRAM_ID}=require('@pump-fun/pump-sdk');
const {Connection,Keypair,Transaction,PublicKey}=require('@solana/web3.js');
const {build,finalize}=require('./build-launch.cjs');
const USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const errors=[];
function assert(label,condition){console.log((condition?'PASS ':'FAIL ')+label);if(!condition)errors.push(label)}
// Pump's global config is one read-only account. A busy public RPC answers
// 429 for it now and then, and that alone used to block a whole deploy. Try
// the operator's trusted RPC first, then independent public read endpoints,
// each with a short backoff; still fail closed when none of them answers.
// Endpoint URLs are never printed (a trusted one can carry an API key).
const FALLBACK_RPCS=['https://solana-rpc.publicnode.com','https://api.mainnet-beta.solana.com'];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function fetchGlobalFromAnyRpc(){
 const trusted=process.env.ORCA_LAUNCH_RPC||'';
 if(trusted&&!/^https:\/\//.test(trusted))throw Error('A trusted HTTPS RPC endpoint is required');
 const endpoints=[...new Set([trusted,...FALLBACK_RPCS].filter(Boolean))];
 let last;
 for(const [index,url] of endpoints.entries()){
  const sdk=new OnlinePumpSdk(new Connection(url,{commitment:'confirmed',disableRetryOnRateLimit:true}));
  for(let attempt=0;attempt<3;attempt++){
   try{return await sdk.fetchGlobal()}
   catch(e){
    last=e;
    const busy=/429|too many requests|rate.?limit|timed? ?out|fetch failed|ECONNRESET|503|502/i.test(String(e&&e.message||e));
    console.log('RPC '+(index+1)+'/'+endpoints.length+' '+(busy?'busy':'failed')+' reading Pump config (attempt '+(attempt+1)+'/3)');
    if(!busy)break;
    await sleep(2000*(attempt+1));
   }
  }
 }
 throw last||Error('No Solana RPC endpoint answered');
}
async function main(){
 const global=await fetchGlobalFromAnyRpc();
 assert('Pump mainnet create_v2 is enabled',global.createV2Enabled===true);
 assert('Pump mainnet USDC quote is supported',global.whitelistedQuoteMints.some(x=>x.toBase58()===USDC));
 const wallet=Keypair.generate().publicKey.toBase58();
 const community=Keypair.generate().publicKey.toBase58();
 const blockhash=Keypair.generate().publicKey.toBase58();
 // Holder Rewards is not offered (it could never carry OrcAgent's 20%):
 // the builder must refuse it.
 let holderRefused=false;
 try{await build({wallet,name:'OrcAgent Preflight',symbol:'PREF',quote_asset:'USDC',reward_mode:'holder',blockhash,
   uri:'https://orcagent.fun/token-launch/metadata/0123456789abcdef0123456789abcdef'})}
 catch(e){holderRefused=/Unsupported reward mode/.test(String(e&&e.message))}
 assert('Holder Rewards launches are refused',holderRefused);
 for(const asset of ['USDC','SOL'])for(const mode of ['creator','community']){
  // Every new launch carries OrcAgent's 20% creator-fee share.
  const orcBps=2000;
  const args={wallet,community_wallet:community,community_bps:1500,
   orcagent_bps:orcBps,orcagent_wallet:'HC5ahspSox3XRmDbzXjXVoAASuY89RCmGUKwp87FRJS5',
   name:'OrcAgent Preflight',symbol:'PREF',
   uri:'https://orcagent.fun/token-launch/metadata/0123456789abcdef0123456789abcdef',
   quote_asset:asset,reward_mode:mode,blockhash};
  const built=await build(args);
  assert(asset+'/'+mode+' OrcAgent mint suffix',built.mint.endsWith('orc')&&!('mint_secret' in built));
  const raw=Buffer.from(built.transaction_b64,'base64');
  const tx=Transaction.from(raw);
  assert(asset+'/'+mode+' unsigned wallet approval + signed ephemeral mint',
   raw.length<=1232&&tx.signatures.length===2&&
   tx.signatures[0].signature===null&&tx.signatures[1].signature!==null&&
   tx.instructions.some(i=>i.programId.equals(PUMP_PROGRAM_ID))&&
   built.holder_reward===false&&
   built.needs_fee_share_finalization===true);
  {
   assert(asset+'/'+mode+' sharing setup included',tx.instructions.some(i=>i.programId.equals(PUMP_FEE_PROGRAM_ID)));
   const shares=await finalize({...args,mint:built.mint,stage:'finalize'});
   const finalRaw=Buffer.from(shares.transaction_b64,'base64');
   const finalTx=Transaction.from(finalRaw);
   assert(asset+'/'+mode+' separate wallet-approved sharing finalization',
     finalRaw.length<=1232&&finalTx.signatures.length===1&&
     finalTx.signatures[0].signature===null&&
     finalTx.instructions.some(i=>i.programId.equals(PUMP_FEE_PROGRAM_ID)));
  }
 }
 console.log(errors.length?'PREFLIGHT FAILED: '+errors.join(', '):'READ-ONLY MAINNET PREFLIGHT PASSED; no transactions sent');
 if(errors.length)process.exitCode=1;
}
main().catch(e=>{console.error('PREFLIGHT BLOCKED: '+String(e.message||e).slice(0,250));process.exitCode=1});
