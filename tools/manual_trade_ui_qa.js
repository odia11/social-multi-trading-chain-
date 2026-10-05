// Isolated QA only: run app_entry on localhost:5097 with a disposable DATA_DIR. All API calls are mocked; external requests are blocked.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('assert');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));
 const tokens=[0,1].map(i=>({mint:(i?'N':'M')+'1'.repeat(39),symbol:'CATE',name:i?'Other Cate':'Cate QA',chain:'solana',pair_address:'pair'+i,price_usd:.0013,market_cap:1300000,liquidity_usd:90000,volume_24h:200000,price_change_24h:18.5,buys_24h:50,sells_24h:20,score:4}));
 await page.route('**/*',async r=>{const u=new URL(r.request().url());if(u.origin!=='http://127.0.0.1:5097')return r.abort();if(u.pathname==='/live-market'){const response=await r.fetch();const html=(await response.text()).replace(/(<script[^>]*id="pt-initial-feed"[^>]*>)[\s\S]*?(<\/script>)/,(_,a,b)=>a+JSON.stringify({tokens,counts:{}})+b);return r.fulfill({response,body:html})}if(!u.pathname.startsWith('/api/'))return r.continue();let d={ok:true};if(u.pathname==='/api/market/scanner')d={ok:true,counts:{},tokens};else if(u.pathname==='/api/wallet/trading-balance')d={ok:true,available_sol:.02,sol_price_usd:150};else if(u.pathname==='/api/trade/holding')d={ok:true,amount:8000,price_usd:.0013,sol_price_usd:150,value_sol:10.4/150};else if(u.pathname==='/api/instant-trade'){requests.push(r.request().postDataJSON());d={error:'QA simulated refusal; no transaction sent'};return r.fulfill({status:400,json:d})}else if(u.pathname==='/api/watchlist')d={ok:true,tokens:[]};else if(u.pathname==='/api/leaderboard')d=[];else if(u.pathname==='/api/market/tape')d={ok:true,trades:[]};else if(u.pathname==='/api/market/surges')d={ok:true,tokens:[]};else if(u.pathname==='/api/token-launches')d={ok:true,tokens:[],launches:[]};else if(u.pathname.includes('chart'))d={ok:true,candles:[]};return r.fulfill({json:d});});
 await page.goto('http://127.0.0.1:5097/live-market',{waitUntil:'domcontentloaded'});
 await page.waitForSelector('.pt-card[data-mint="'+tokens[1].mint+'"] [data-action="buy-open"]');
 await page.locator('.pt-card[data-mint="'+tokens[1].mint+'"] [data-action="buy-open"]').click();
 await page.waitForSelector('#pt-sheet.open');
 await page.locator('#pt-sheet [data-mode="sell"]').click();
 await page.waitForFunction(()=>document.querySelector('#pt-sheet').classList.contains('sell-mode'));
 await page.waitForFunction(()=>document.querySelector('#pt-sheet-avail').textContent.includes('held'));
 assert.equal(await page.locator('#pt-sheet [data-mode="sell"]').getAttribute('aria-pressed'),'true');
 await page.locator('.pt-pct[data-spct="50"]').click();
 await page.screenshot({path:'/tmp/orca-trade-sell-preview.png'});
 async function slide(){const b=await page.locator('#pt-slide-knob').boundingBox(),t=await page.locator('#pt-slide').boundingBox();await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();await page.mouse.move(t.x+t.width-20,b.y+b.height/2,{steps:15});await page.mouse.up();await page.waitForTimeout(300)}
 await slide();assert.equal(requests.length,1);assert.equal(requests[0].token_address,tokens[1].mint);assert.equal(requests[0].side,'sell');
 await page.locator('#pt-sheet [data-mode="buy"]').click();
 await page.waitForFunction(()=>document.querySelector('#pt-sheet-avail').textContent.includes('available'));
 await page.locator('.pt-pct[data-pct="50"]').click();
 await page.screenshot({path:'/tmp/orca-trade-buy-preview.png'});
 await slide();assert.equal(requests.length,2);assert.equal(requests[1].token_address,tokens[1].mint);assert.equal(requests[1].protect,false);assert.equal(requests[1].side,'buy');assert.equal(requests[1].amount_sol,.01);
 await page.locator('#pt-fees summary').click();
 await page.locator('#pt-slide').scrollIntoViewIfNeeded();
 for(const viewport of [{width:390,height:844},{width:375,height:667},{width:1440,height:900}]){await page.setViewportSize(viewport);const geo=await page.evaluate(()=>{let selectors=['.pt-sheet-hd','.oa-swipe-mode','.pt-sheet-mid','.pt-sheet-pcts','#pt-keys','.pt-sheet-ft'];return selectors.map(s=>{let b=document.querySelector(s).getBoundingClientRect();return{selector:s,y:b.y,bottom:b.bottom,width:b.width}})});for(let i=1;i<geo.length;i++)assert(geo[i].y>=geo[i-1].bottom-2,JSON.stringify(geo));assert(await page.locator('.pt-trade-close').isVisible());}
 assert.equal(await page.locator('#pt-protect').count(),0);assert.equal(await page.locator('#oa-swap-modern').count(),0);
 console.log(JSON.stringify({pass:true,requests,errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
