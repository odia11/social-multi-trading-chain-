/* The Home composer's attachment buttons must sit in ONE tidy row on a
   phone. Adding "+ Video" made the wrapping flex row push Video and the
   emoji onto a ragged second line. Now: a 5-column grid (4 equal buttons,
   icon above a short label, + a square emoji button), POST full width below.
   home-mobile-polish.css sets display:flex on this row with
   `body.oa-home-mobile #feed-composer ...` and is injected at runtime, so the
   grid rule must be MORE specific or whichever file loads last wins. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const css=fs.readFileSync('static/home-composer-mobile.css','utf8');
const html=fs.readFileSync('dashboard.html','utf8');
assert(/body\.oa-home-mobile #feed-composer\.feed-composer \.feed-composer-actions\{[^}]*display:grid!important;[^}]*grid-template-columns:repeat\(4,minmax\(0,1fr\)\) 46px!important/.test(css),
  'the actions row is a 4+1 column grid, with a selector that outranks home-mobile-polish.css');
assert(/#feed-composer\.feed-composer \.feed-composer-pill,[\s\S]*?flex-direction:column!important/.test(css),'icon above label, so full words fit on a 360px phone');
assert(/#feed-composer\.feed-composer \.feed-composer-post\{[^}]*grid-column:1\/-1!important/.test(css),'POST spans the full row below');
for(const [id,label] of [['chart-pill-btn','Chart'],['trade-pill-btn','Trade'],['image-pill-btn','Image'],['video-pill-btn','Video']]){
  assert(new RegExp('id="'+id+'"[^>]*>[\\s\\S]*?<svg[\\s\\S]*?</svg>\\s*<span class="feed-pill-label">'+label+'</span>').test(html),id+' has an icon + short label');
}
for(const f of ['static/app-ux.js','static/mobile-bottom-nav.js','app_performance.py'])
  assert(fs.readFileSync(f,'utf8').includes('home-composer-mobile.css?v=5'),f+' must cache-bust the composer CSS');
console.log('PASS Home composer: attachment buttons in one tidy row on every phone width');
