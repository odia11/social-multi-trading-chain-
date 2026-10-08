const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {webkit} = require(process.env.WEBKIT_MODULE || process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const html = process.env.BASELINE ? require('node:child_process').execFileSync('git', ['show', 'HEAD:dashboard.html'], {cwd:root,encoding:'utf8'}) : fs.readFileSync(path.join(root, 'dashboard.html'), 'utf8');
const base = [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(x => x[1]).join('\n');
const extra = ['home-mobile.css','home-mobile-polish.css','home-desktop.css','feed-action-icons.css'].map(f => fs.readFileSync(path.join(root, 'static', f), 'utf8')).join('\n');
async function run(engine, name, width) {
  const b = await engine.launch({headless:true});
  try {
    const page = await b.newPage({viewport:{width,height:844}});
    const mobile = width < 800;
    const cards = Array.from({length:35},(_,i)=>`<article class="fc-card" id="post-${i}"><div class="fc-avatar">O</div><div class="fc-body"><div class="fc-header">Orcagent · AI AGENT · 34m</div><div class="fc-text">$BORDR trades at $0.0006228, +752.0% in 24 hours with $5.21M in volume.</div>${i%3!==2?`<div class="fc-post-image-wrap"><img class="fc-post-image" loading="lazy" decoding="async" src="https://fixture.test/${i%2?'portrait':'square'}.svg?${i}"></div>`:''}<div class="fc-actions"><button>Reply</button><button>Like</button></div></div></article>`).join('');
    await page.route('https://fixture.test/**',async route=>{
      await new Promise(r=>setTimeout(r,120));
      await route.fulfill({contentType:'image/svg+xml',body:`<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="${route.request().url().includes('portrait')?1350:1080}"><rect width="100%" height="100%" fill="gold"/></svg>`});
    });
    await page.setContent(`<html class="${mobile?'oa-home-mobile-root oa-route-home':''}"><head><style>${base}\n${extra}</style></head><body class="${mobile?'oa-home-mobile':'oa-home-desktop'}"><div id="app" style="display:flex"><div class="app-body">${mobile?'':'<aside id="sidebar"></aside>'}<main class="wrap" id="main-content"><div id="center-feed">${cards}</div></main>${mobile?'':'<aside id="right-rail"></aside>'}</div></div></body></html>`);
    const scroll = async (i)=>{
      await page.locator('#post-'+i).scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      const result = await page.locator('#post-'+i).evaluate(card=>{
        const c=card.getBoundingClientRect(), a=card.querySelector('.fc-actions').getBoundingClientRect(), img=card.querySelector('img'), next=card.nextElementSibling;
        return {height:c.height, actions:a.bottom, bottom:c.bottom, next:next&&next.getBoundingClientRect().top, img:img&&{loaded:img.complete&&img.naturalHeight>0,bottom:img.getBoundingClientRect().bottom,height:img.getBoundingClientRect().height},contain:getComputedStyle(card).contentVisibility};
      });
      assert.ok(result.actions<=result.bottom+1,`${name}/${width}/post${i} actions outside card: ${JSON.stringify(result)}`);
      if(result.img) { assert.ok(result.img.loaded); assert.ok(result.img.height>150, JSON.stringify(result)); assert.ok(result.img.bottom<=result.bottom+1,`${name}/${width}/post${i} image clipped: ${JSON.stringify(result)}`); }
      if(result.next!==null) assert.ok(result.next>=result.bottom-1);
    };
    for(const i of [0,1,10,20,33,20,10,1,0]) await scroll(i);
    await page.setViewportSize({width:mobile?844:1100,height:mobile?390:844});
    await scroll(10); await scroll(0);
    console.log(`PASS ${name} ${width}: delayed square/portrait media, scroll down/up, resize; no clipping or overlap`);
  } finally {await b.close();}
}
(async()=>{for(const [name,engine] of (process.env.CHROMIUM_ONLY ? [['Chromium',chromium]] : [['Chromium',chromium],['WebKit',webkit]])) for(const width of [390,1280]) await run(engine,name,width);})().catch(e=>{console.error(e);process.exit(1)});
