'use strict';
require('./runtime-check.cjs');
const {OnlinePumpSdk}=require('@pump-fun/pump-sdk');
const {Connection,PublicKey}=require('@solana/web3.js');
const USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const SOL='So11111111111111111111111111111111111111112';
async function main(){
 const mint=new PublicKey(process.argv[2]);
 // Market reads use independent public RPCs: the launch RPC may be a
 // restricted provider configured for transaction preflight only.
 let curve;
 for(const endpoint of ['https://solana-rpc.publicnode.com','https://api.mainnet-beta.solana.com']){
  try{curve=await new OnlinePumpSdk(new Connection(endpoint,{commitment:'confirmed'})).fetchBondingCurve(mint);break;}
  catch(_){ /* try the second read-only source */ }
 }
 if(!curve)throw Error('Curve unavailable');
 const quote=curve.quoteMint.toBase58();
 if(quote!==USDC&&quote!==SOL&&quote!=='11111111111111111111111111111111')throw Error('Unexpected quote mint');
 const token=Number(curve.virtualTokenReserves.toString())/1e6;
 const quoteAmount=Number(curve.virtualQuoteReserves.toString())/(quote===USDC?1e6:1e9);
 const supply=Number(curve.tokenTotalSupply.toString())/1e6;
 if(!(token>0&&quoteAmount>0&&supply>0))throw Error('Invalid curve reserves');
 console.log(JSON.stringify({quote_asset:quote===USDC?'USDC':'SOL',price_quote:quoteAmount/token,market_cap_quote:quoteAmount/token*supply,complete:curve.complete}));
}
main().catch(()=>{console.error('Curve unavailable');process.exitCode=1});
