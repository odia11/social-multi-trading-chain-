const fs=require('fs'),path=require('path'),assert=require('assert');
const w=fs.readFileSync(path.join(__dirname,'../templates/wallet.html'),'utf8');

assert(w.includes('function _modalSolUsdcSwap()'));
assert(w.includes("fetch('/api/wallet/sol-swap/balance'"));
assert(w.includes('function _sxSeedPortfolioBalance()'));
assert(w.includes("_portfolioSnapshotData"));
assert(w.includes("cache:'no-store'"));
assert(w.includes('_sx.balanceAttempt<3'));
assert(w.includes("'/api/wallet/sol-swap/quote?"));
assert(w.includes("'/api/wallet/sol-swap/execute'"));
assert(w.includes("quote.quote_id?'/api/wallet/sol-swap/execute':'/api/wallet/convert'"));
assert(w.includes('if(_convertBusy) return'));
assert(w.includes("_sx={dir:'native_to_stable'"));
assert(w.includes("_sx.dir=_sx.dir==='native_to_stable'?'stable_to_native':'native_to_stable'"));
assert(w.includes("data-p=\"1\" id=\"cv-max\""));
assert(w.includes('Swaps run in your Solana trading wallet'));
console.log('PASS Portfolio SOL<->USDC UI uses live balance, quote, one-submit guard and current Solana routes');
