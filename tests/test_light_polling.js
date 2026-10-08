// Open tabs ask the server less, and a busy server is not hammered with retries.
//
// An idle tab used to send 54-81 requests a minute: the in-app notification
// check every 3 s, the header balance every 5 s, and on Home three hidden
// dashboard panels every 10-15 s. Worse, the fetch wrapper retried any 502,
// 503 or 504 nine times -- meant for a deploy restart, but a 504 is what a
// busy server answers, so every tab multiplied its load by ten exactly when
// the server had too much. This runs the real wrapper from navbar.js.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const read = f => fs.readFileSync(path.join(__dirname, '..', 'static', f), 'utf8');
const nav = read('navbar.js');
const start = nav.indexOf('(function(){\n  var DEFAULT_FETCH_TIMEOUT_MS');
const end = nav.indexOf('})();', start) + 5;
assert.ok(start > 0 && end > start, 'fetch wrapper found in navbar.js');

function run(status, contentType) {
  let calls = 0;
  const window = {
    location: { href: 'https://orcagent.fun/', origin: 'https://orcagent.fun' },
    fetch: async () => { calls++; return { status, headers: { get: () => contentType } }; },
  };
  const ctx = { window, URL, AbortController, Promise, Request: undefined, FormData: undefined, Math, Object, String,
                setTimeout: (fn) => { fn(); return 0; }, clearTimeout: () => {}, location: window.location };
  vm.createContext(ctx);
  vm.runInContext(nav.slice(start, end), ctx);
  return ctx.window.fetch('/api/portfolio/snapshot').then(() => calls);
}

(async () => {
  assert.equal(await run(502, 'text/html'), 10, 'a restart (502) is waited through');
  assert.equal(await run(503, 'text/html'), 10, "nginx's own 503 page is waited through");
  assert.equal(await run(503, 'application/json'), 1, 'an app that answered 503 is not asked nine more times');
  assert.equal(await run(504, 'text/html'), 2, 'a busy server (504) is asked once more, not nine times');
  assert.equal(await run(200, 'application/json'), 1, 'a normal answer is not repeated');
  assert.match(nav, /DEPLOY_RETRY_DELAYS\[n\]\*\(0\.7\+Math\.random\(\)\*0\.6\)/, 'retries are spread out');

  const inapp = read('in-app-notifications.js');
  assert.match(inapp, /var POLL_MS=6000,POLL_MAX_MS=15000/, 'notifications: every 6 s, easing to 15 s when quiet');
  assert.doesNotMatch(inapp, /setInterval\(function\(\)\{if\(!document\.hidden\)poll\(false\)\},POLL_MS\)/);
  assert.match(read('header-stable-balance.js'), /POLL_MS=20000/, 'header balance: every 20 s, and at once after a trade');
  assert.match(read('header-stable-balance.js'), /orca:trade-complete',function\(\)\{refresh\(true\)\}/);

  const dash = read('dashboard.js');
  assert.match(dash, /async function fetchMarketOnly\(\)\{\n  if\(!appVisible\(\)\) return;\n  if\(!_oaShown\('lm-tbody','ticker-track','token-count'\)\) return;/,
               'the hidden Home market table is not polled');
  assert.match(dash, /if\(!_oaShown\('bot-pnl-list','bot-pnl-total'\)\) return;/, 'the hidden bot P&L panel is not polled');
  console.log('PASS restart retried, app 503 not retried, 504 retried once, spread out; lighter notification, balance and Home polling');
})().catch(e => { console.error(e); process.exitCode = 1; });
