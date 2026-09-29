const assert=require('node:assert/strict');
const fs=require('node:fs');
const css=fs.readFileSync('static/mobile-bottom-nav.css','utf8');
const home=fs.readFileSync('dashboard.html','utf8');
const boot=fs.readFileSync('static/navbar.js','utf8');
const js=fs.readFileSync('static/mobile-bottom-nav.js','utf8');
const app=fs.readFileSync('static/app-ux.css','utf8');

assert.match(css,/\.oa-bottom-nav\{[^}]*position:fixed!important;[^}]*bottom:0!important;[^}]*transform:none!important;[^}]*visibility:visible!important;[^}]*box-sizing:border-box!important/);
assert(!css.includes('box-sizing:content-box'));
assert(home.includes('viewport-fit=cover'));
assert(boot.includes('mobile-bottom-nav.css?v=8'));
assert(boot.includes('mobile-bottom-nav.js?v=8'));
assert(!js.includes('visibleBottom-nav.getBoundingClientRect().bottom'),
       'do not manually translate fixed nav against visualViewport');
assert(!js.includes('Math.max(-360,Math.min(180,next))'),
       'large Safari toolbar offsets must not become page transforms');
assert(js.includes("document.documentElement.style.setProperty('--oa-nav-lift','0px')"),
       'new bundle must clear stale lift restored from bfcache');
assert(js.includes("nav.style.setProperty('transform','none','important')"),
       'new bundle must clear stale inline transform');
assert(!app.includes('var(--oa-nav-lift'),
       'document must never reserve a second dynamic navbar lift');
console.log('PASS mobile footer: CSS-fixed visible nav, no double Safari lift, stale bfcache geometry cleared');
