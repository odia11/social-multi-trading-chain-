'use strict';
require('./runtime-check.cjs');
// Pump's published ESM 2.0.0 pulls an incompatible named-export from its
// agent-payments dependency in Node 22. The official CommonJS export loads.
// No user private keys ever enter this process; only an ephemeral new mint key.
const {PUMP_SDK} = require('@pump-fun/pump-sdk');
const {Keypair,PublicKey,Transaction} = require('@solana/web3.js');
const {TOKEN_PROGRAM_ID,NATIVE_MINT,createAssociatedTokenAccountIdempotentInstruction,getAssociatedTokenAddressSync} = require('@solana/spl-token');
const USDC = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
const MAX_BYTES=1232;
// OrcAgent's creator-fee share, if the saved launch carries one. Holder
// Rewards have no creator share to divide.
function orcShare(data){
  if(!['creator','community'].includes(data.reward_mode))return null;
  const bps=Number(data.orcagent_bps||0);
  if(!bps)return null;
  if(!Number.isSafeInteger(bps)||bps<0||bps>5000)throw Error('Invalid OrcAgent share');
  return {address:new PublicKey(data.orcagent_wallet),bps};
}
function needsShares(data){return data.reward_mode==='community'||!!orcShare(data);}
async function build(data){
  const wallet = new PublicKey(data.wallet);
  const quoteMint = data.quote_asset==='USDC' ? USDC : NATIVE_MINT;
  // Server-created ephemeral mint only; never a creator wallet key.
  let secret=data.mint_secret;
  if(!secret){
    const path=require('node:path');
    const child=require('node:child_process').spawnSync(
      path.resolve(__dirname,'../venv/bin/python'),[path.join(__dirname,'grind-mint.py')],
      {encoding:'utf8',timeout:96000,maxBuffer:4096});
    if(child.error||child.status!==0)throw Error('Orc mint address not ready; retry shortly');
    secret=child.stdout.trim();
  }
  const bytes=Buffer.from(secret,'base64');
  if(bytes.length!==64)throw Error('Invalid ephemeral mint');
  const mint=Keypair.fromSecretKey(Uint8Array.from(bytes));
  bytes.fill(0);
  if(!mint.publicKey.toBase58().endsWith('orc'))throw Error('Mint must end in orc');
  const holderReward = data.reward_mode==='holder';
  const create = await PUMP_SDK.createV2Instruction({
    mint: mint.publicKey,
    name: data.name,
    symbol: data.symbol,
    uri: data.uri,
    creator: wallet,
    user: wallet,
    mayhemMode: false,
    holderReward,
    quoteMint,
    quoteTokenProgram: TOKEN_PROGRAM_ID,
  });
  const ixs=[create];
  if(needsShares(data)){
    // A single legacy transaction with create_v2 + create_config + update
    // exceeds Solana's 1232-byte packet limit, even without ATA setup.
    // Create with the default 100% creator split, and REQUIRE a second,
    // user-approved finalization to install the agreed split (community
    // and/or OrcAgent's creator-fee share).
    ixs.push(await PUMP_SDK.createFeeSharingConfig({
      creator:wallet,mint:mint.publicKey,pool:null}));
  }
  const tx=new Transaction({feePayer:wallet,recentBlockhash:data.blockhash});
  tx.add(...ixs);
  tx.partialSign(mint);
  const raw=tx.serialize({requireAllSignatures:false,verifySignatures:false});
  if(raw.length>MAX_BYTES)throw Error('Launch with selected fee shares is too large; no transaction prepared');
  return {
    mint:mint.publicKey.toBase58(),
    transaction_b64:raw.toString('base64'),
    transaction_bytes:raw.length,
    instruction_count:ixs.length,
    quote_mint:quoteMint.toBase58(),
    holder_reward:holderReward,
    needs_fee_share_finalization:needsShares(data),
    // No private keys, no claim amounts or speculative rewards in response.
  };
}
async function finalize(data){
  const wallet=new PublicKey(data.wallet);
  const mint=new PublicKey(data.mint);
  const orc=orcShare(data);
  const orcBps=orc?orc.bps:0;
  const holders=[];
  if(data.reward_mode==='community'){
    const community=new PublicKey(data.community_wallet);
    const bps=Number(data.community_bps);
    if(!Number.isSafeInteger(bps)||bps<=0||bps+orcBps>=10000||community.equals(wallet)||
       (orc&&community.equals(orc.address))){
      throw Error('Invalid community share');
    }
    holders.push({address:community,shareBps:bps});
  }
  if(orc){
    if(orc.address.equals(wallet))throw Error('Invalid OrcAgent share');
    holders.push({address:orc.address,shareBps:orcBps});
  }
  if(!holders.length)throw Error('No fee split to finalize');
  const creatorBps=10000-holders.reduce((sum,h)=>sum+h.shareBps,0);
  if(creatorBps<1)throw Error('Invalid fee split');
  const quoteMint=data.quote_asset==='USDC'?USDC:NATIVE_MINT;
  const ixs=[];
  if(data.quote_asset==='USDC'){
    ixs.push(createAssociatedTokenAccountIdempotentInstruction(
      wallet,getAssociatedTokenAddressSync(USDC,wallet),wallet,USDC));
  }
  ixs.push(await PUMP_SDK.updateFeeSharesV2({
    authority:wallet,mint,currentShareholders:[wallet],
    newShareholders:[{address:wallet,shareBps:creatorBps},...holders],quoteMint,quoteTokenProgram:TOKEN_PROGRAM_ID,
  }));
  const tx=new Transaction({feePayer:wallet,recentBlockhash:data.blockhash});
  tx.add(...ixs);
  const raw=tx.serialize({requireAllSignatures:false,verifySignatures:false});
  if(raw.length>MAX_BYTES)throw Error('Fee-sharing transaction is too large');
  return {mint:mint.toBase58(),transaction_b64:raw.toString('base64'),
    transaction_bytes:raw.length,instruction_count:ixs.length,
    quote_mint:quoteMint.toBase58(),stage:'finalize'};
}

async function main(){
  let raw='';
  for await(const chunk of process.stdin){raw+=chunk;if(raw.length>65536)throw Error('Invalid launch input size')}
  const request=JSON.parse(raw);
  process.stdout.write(JSON.stringify(request.stage==='finalize'?await finalize(request):await build(request))+'\n');
}
if(require.main===module){main().catch(e=>{
  process.stderr.write(String(e&&e.message||'Could not build transaction').slice(0,300)+'\n');
  process.exitCode=1;
});}
module.exports={build,finalize};
