'use strict';
// Verification only. Reads a supplied chain account; no private keys, signing
// or RPC URLs are accepted from the browser.
const {PUMP_SDK,feeSharingConfigPda,PUMP_FEE_PROGRAM_ID}=require('@pump-fun/pump-sdk');
const {PublicKey}=require('@solana/web3.js');
async function run(){
 let raw='';for await(const chunk of process.stdin){raw+=chunk;if(raw.length>5000)throw Error('Input too large')}
 const data=JSON.parse(raw);const mint=new PublicKey(data.mint);
 const address=feeSharingConfigPda(mint).toBase58();
 if(data.action==='address'){process.stdout.write(JSON.stringify({address,program:PUMP_FEE_PROGRAM_ID.toBase58()})+'\n');return}
 if(data.action!=='verify'||!data.data_b64)throw Error('Invalid share verification request');
 const config=PUMP_SDK.decodeSharingConfig({
  data:Buffer.from(data.data_b64,'base64'),
  executable:false,lamports:1,owner:PUMP_FEE_PROGRAM_ID,rentEpoch:0
 });
 process.stdout.write(JSON.stringify({address,
  mint:config.mint.toBase58(),admin_revoked:config.adminRevoked,
  shares:config.shareholders.map(s=>({wallet:s.address.toBase58(),bps:s.shareBps}))})+'\n');
}
run().catch(e=>{process.stderr.write('Sharing config unavailable\n');process.exitCode=1});
