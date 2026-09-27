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
async function main(){
 const rpc=process.env.ORCA_LAUNCH_RPC||'https://api.mainnet-beta.solana.com';
 if(!/^https:\/\//.test(rpc))throw Error('A trusted HTTPS RPC endpoint is required');
 const sdk=new OnlinePumpSdk(new Connection(rpc,'confirmed'));
 const global=await sdk.fetchGlobal();
 assert('Pump mainnet create_v2 is enabled',global.createV2Enabled===true);
 assert('Pump mainnet Holder Rewards are enabled',global.isHolderRewardEnabled===true);
 assert('Pump mainnet USDC quote is supported',global.whitelistedQuoteMints.some(x=>x.toBase58()===USDC));
 const wallet=Keypair.generate().publicKey.toBase58();
 const community=Keypair.generate().publicKey.toBase58();
 const blockhash=Keypair.generate().publicKey.toBase58();
 for(const asset of ['USDC','SOL'])for(const mode of ['creator','community','holder']){
  const args={wallet,community_wallet:community,community_bps:1500,
   name:'OrcAgent Preflight',symbol:'PREF',
   uri:'https://orcagent.fun/token-launch/metadata/0123456789abcdef0123456789abcdef',
   quote_asset:asset,reward_mode:mode,blockhash};
  const built=await build(args);
  const raw=Buffer.from(built.transaction_b64,'base64');
  const tx=Transaction.from(raw);
  assert(asset+'/'+mode+' unsigned wallet approval + signed ephemeral mint',
   raw.length<=1232&&tx.signatures.length===2&&
   tx.signatures[0].signature===null&&tx.signatures[1].signature!==null&&
   tx.instructions.some(i=>i.programId.equals(PUMP_PROGRAM_ID))&&
   built.holder_reward===(mode==='holder')&&
   built.needs_fee_share_finalization===(mode==='community'));
  if(mode==='community'){
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
