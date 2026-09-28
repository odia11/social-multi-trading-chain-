'use strict';
require('./runtime-check.cjs');
const {OnlinePumpSdk}=require('@pump-fun/pump-sdk');
const {Connection,PublicKey}=require('@solana/web3.js');
const USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const SOL='So11111111111111111111111111111111111111112';
async function main(){
 const mint=new PublicKey(process.argv[2]);
 const endpoint=process.env.ORCA_LAUNCH_RPC||process.env.SOLANA_RPC_URL||'https://api.mainnet-beta.solana.com';
 if(!/^https:\/\//.test(endpoint))throw Error('HTTPS RPC required');
 const curve=await new OnlinePumpSdk(new Connection(endpoint,{commitment:'confirmed'})).fetchBondingCurve(mint);
 const quote=curve.quoteMint.toBase58();
 if(quote!==USDC&&quote!==SOL&&quote!=='11111111111111111111111111111111')throw Error('Unexpected quote mint');
 const token=Number(curve.virtualTokenReserves.toString())/1e6;
 const quoteAmount=Number(curve.virtualQuoteReserves.toString())/(quote===USDC?1e6:1e9);
 const supply=Number(curve.tokenTotalSupply.toString())/1e6;
 if(!(token>0&&quoteAmount>0&&supply>0))throw Error('Invalid curve reserves');
 console.log(JSON.stringify({quote_asset:quote===USDC?'USDC':'SOL',price_quote:quoteAmount/token,market_cap_quote:quoteAmount/token*supply,complete:curve.complete}));
}
main().catch(()=>{console.error('Curve unavailable');process.exitCode=1});
