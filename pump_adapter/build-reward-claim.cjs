'use strict';
require('./runtime-check.cjs');
// Permissionless creator-fee distribution or an owner's regular creator claim.
// Builds unsigned transactions only; this process never signs for any user.
const {OnlinePumpSdk,feeSharingConfigPda,creatorVaultPda}=require('@pump-fun/pump-sdk');
const {coinCreatorVaultAuthorityPda,coinCreatorVaultAtaPda}=require('@pump-fun/pump-swap-sdk');
const {PublicKey,Connection,Transaction}=require('@solana/web3.js');
const {TOKEN_PROGRAM_ID,NATIVE_MINT,getAssociatedTokenAddressSync,unpackAccount,
       createAssociatedTokenAccountIdempotentInstruction}=require('@solana/spl-token');
const USDC=new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
async function run(){
 let raw='';for await(const chunk of process.stdin){raw+=chunk;if(raw.length>4000)throw Error('Input too large')}
 const data=JSON.parse(raw);
 const wallet=new PublicKey(data.wallet);
 const mint=new PublicKey(data.mint);
 const quote=data.quote_asset==='USDC'?USDC:NATIVE_MINT;
 // A fee-sharing config (community split and/or OrcAgent's creator-fee share)
 // is paid out by a permissionless distribution to every shareholder.
 const sharing=data.reward_mode==='community'||data.fee_sharing===true;
 if(!['community','creator'].includes(data.reward_mode))throw Error('Holder fees are handled by Pump, not this wallet');
 const feeOwner=sharing?feeSharingConfigPda(mint):wallet;
 const rpc=process.env.ORCA_LAUNCH_RPC;
 if(!rpc || !/^https?:\/\//.test(rpc))throw Error('Configured Solana RPC unavailable');
 const connection=new Connection(rpc,'confirmed');
 const sdk=new OnlinePumpSdk(connection);
 let total;
 if(!sharing && data.quote_asset==='USDC'){
  // Some public Solana RPC providers reject getMultipleAccountsInfo and the
  // SDK's very broad getCreatorVaultQuoteBalances index scan with HTTP 403.
  // The claim is only for canonical USDC: read its two derived creator vault
  // ATAs directly instead. No account-enumeration or token-balance index.
  const creatorVault=creatorVaultPda(wallet);
  const ammAuthority=coinCreatorVaultAuthorityPda(wallet);
  const vault=getAssociatedTokenAddressSync(USDC,creatorVault,true);
  const ammVault=coinCreatorVaultAtaPda(
       ammAuthority,USDC,TOKEN_PROGRAM_ID);
  function validatedAmount(address,expectedOwner,info){
   if(!info)return 0n;
   if(!info.owner.equals(TOKEN_PROGRAM_ID))throw Error('Creator USDC vault program mismatch');
   const account=unpackAccount(address,info,TOKEN_PROGRAM_ID);
   if(!account.mint.equals(USDC)||!account.owner.equals(expectedOwner))
     throw Error('Creator USDC vault mint/authority mismatch');
   if(account.isFrozen)throw Error('Creator USDC vault is frozen');
   return BigInt(account.amount.toString());
  }
  const pumpInfo=await connection.getAccountInfo(vault,'confirmed');
  const ammInfo=await connection.getAccountInfo(ammVault,'confirmed');
  total=validatedAmount(vault,creatorVault,pumpInfo)+
        validatedAmount(ammVault,ammAuthority,ammInfo);
  // collectCoinCreatorFeeV2Instructions uses getMultipleAccountsInfo for two
  // precisely derived accounts. Replace ONLY this SDK connection's batch
  // reader with separate confirmed account reads, never fake missing data.
  connection.getMultipleAccountsInfo=async (keys)=>{
    if(!Array.isArray(keys)||keys.length!==2||
       !keys[0].equals(ammVault)||
       !keys[1].equals(getAssociatedTokenAddressSync(USDC,wallet,true)))
      throw Error('Unexpected claim account request');
    const answer=[];
    for(const key of keys)answer.push(await connection.getAccountInfo(key,'confirmed'));
    return answer;
  };
 }else{
  const vaults=await sdk.getCreatorVaultQuoteBalances(feeOwner);
  const current=vaults.find(x=>x.mint.equals(quote));
  total=current?BigInt(current.total.toString()):0n;
 }
 if(total<=0n)throw Error('No confirmed creator fees available for this quote asset');
 const ixs=[];
 if(sharing){
  const response=await sdk.buildDistributeCreatorFeesInstructions(mint,{
    quoteMint:quote,quoteTokenProgram:TOKEN_PROGRAM_ID,payer:wallet});
  ixs.push(...response.instructions);
 }else if(data.quote_asset==='USDC'){
  ixs.push(createAssociatedTokenAccountIdempotentInstruction(wallet,
       getAssociatedTokenAddressSync(USDC,wallet),wallet,USDC));
  ixs.push(...await sdk.collectCoinCreatorFeeV2Instructions(wallet,quote,TOKEN_PROGRAM_ID,wallet));
 }else ixs.push(...await sdk.collectCoinCreatorFeeInstructions(wallet,wallet));
 if(!ixs.length)throw Error('No creator fees to distribute');
 const tx=new Transaction({recentBlockhash:data.blockhash,feePayer:wallet});tx.add(...ixs);
 const bytes=tx.serialize({requireAllSignatures:false,verifySignatures:false});
 if(bytes.length>1232)throw Error('Claim too large; no wallet transaction prepared');
 process.stdout.write(JSON.stringify({mint:mint.toBase58(),transaction_b64:bytes.toString('base64'),
  transaction_bytes:bytes.length,quote_mint:quote.toBase58(),
  accrued_raw:total.toString(),
  accrued_scope:sharing?'token_sharing_config':'creator_wallet_all_tokens',
  quote_asset:data.quote_asset})+'\n');
}
run().catch(e=>{process.stderr.write(String(e&&e.message||'Claim unavailable').slice(0,220)+'\n');process.exitCode=1});
