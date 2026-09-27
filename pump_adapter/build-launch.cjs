'use strict';
// Pump's published ESM 2.0.0 pulls an incompatible named-export from its
// agent-payments dependency in Node 22. The official CommonJS export loads.
// No user private keys ever enter this process; only an ephemeral new mint key.
const {PUMP_SDK} = require('@pump-fun/pump-sdk');
const {Keypair,PublicKey,Transaction} = require('@solana/web3.js');
const {TOKEN_PROGRAM_ID,NATIVE_MINT,createAssociatedTokenAccountIdempotentInstruction,getAssociatedTokenAddressSync} = require('@solana/spl-token');
const USDC = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
const MAX_BYTES=1232;
async function build(data){
  const wallet = new PublicKey(data.wallet);
  const quoteMint = data.quote_asset==='USDC' ? USDC : NATIVE_MINT;
  const mint = Keypair.generate();
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
  if(data.reward_mode==='community'){
    // A single legacy transaction with create_v2 + create_config + update
    // exceeds Solana's 1232-byte packet limit, even without ATA setup.
    // Create with the default 100% creator split, and REQUIRE a second,
    // user-approved finalization to install the requested community split.
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
    needs_fee_share_finalization:data.reward_mode==='community',
    // No private keys, no claim amounts or speculative rewards in response.
  };
}
async function finalize(data){
  const wallet=new PublicKey(data.wallet);
  const mint=new PublicKey(data.mint);
  const community=new PublicKey(data.community_wallet);
  const bps=Number(data.community_bps);
  if(!Number.isSafeInteger(bps)||bps<=0||bps>=10000||community.equals(wallet)){
    throw Error('Invalid community share');
  }
  const quoteMint=data.quote_asset==='USDC'?USDC:NATIVE_MINT;
  const ixs=[];
  if(data.quote_asset==='USDC'){
    ixs.push(createAssociatedTokenAccountIdempotentInstruction(
      wallet,getAssociatedTokenAddressSync(USDC,wallet),wallet,USDC));
  }
  ixs.push(await PUMP_SDK.updateFeeSharesV2({
    authority:wallet,mint,currentShareholders:[wallet],
    newShareholders:[
      {address:wallet,shareBps:10000-bps},
      {address:community,shareBps:bps},
    ],quoteMint,quoteTokenProgram:TOKEN_PROGRAM_ID,
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
