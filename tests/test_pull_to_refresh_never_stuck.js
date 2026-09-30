/* Pull-to-refresh never gets stuck and never stutters.

   - An in-place refresh holds the spinner at most 3 s, even when a request
     never answers (a slow wallet/RPC call used to hold it -- and ignore every
     new pull -- for 15 s). The next pull works right after.
   - A full reload (pages without onRefresh) keeps spinning until the new
     page arrives.
   - touchstart does no style/layout work (every tap and scroll starts
     there); a touchmove never measures layout, and paints once per frame.
   - Home's spinner waits for the feed only, and a touch no longer starts
     the audio hardware for someone who has sound alerts off.
   Runs pull-to-refresh.js against a small fake DOM with fake timers. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const src = fs.readFileSync('static/pull-to-refresh.js', 'utf8');

function world() {
  let now = 0, timers = [], rafs = [], seq = 0;
  const counts = { style: 0, rect: 0 };
  const handlers = {};
  const el = () => {
    const cls = new Set();
    return {
      style: {}, nodeType: 1, parentElement: null, children: [],
      classList: { add: c => cls.add(c), remove: (...c) => c.forEach(x => cls.delete(x)),
        toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)), contains: c => cls.has(c) },
      setAttribute() {}, querySelector: () => null, appendChild(n) { this.children.push(n); },
      getBoundingClientRect() { counts.rect++; return { bottom: 56 }; },
      set innerHTML(_) {}, closest: () => null,
    };
  };
  const body = el(), head = el(), docEl = el();
  const target = el(); target.parentElement = body;
  const document = {
    body, head, documentElement: docEl, scrollingElement: { scrollTop: 0 },
    getElementById: id => (id === 'oa-ptr' ? body.children.find(c => c.id === 'oa-ptr') || null : null),
    createElement: () => el(),
    querySelector: sel => (sel === '.pt-nb-topbar' ? el() : null),
    addEventListener: (t, fn) => { (handlers[t] = handlers[t] || []).push(fn); },
  };
  const window = { pageYOffset: 0 };
  const g = {
    window, document, navigator: {},
    getComputedStyle: () => { counts.style++; return { position: 'static', overflowY: 'visible' }; },
    setTimeout: (fn, ms) => { timers.push({ at: now + ms, fn, id: ++seq }); return seq; },
    clearTimeout: () => {},
    requestAnimationFrame: fn => { rafs.push(fn); return rafs.length; },
    cancelAnimationFrame: () => {},
    location: { reload() { g.reloads = (g.reloads || 0) + 1; } },
    Promise, Date: { now: () => now }, Math, String,
  };
  new Function(...Object.keys(g), src)(...Object.values(g));
  const fire = (t, y) => (handlers[t] || []).forEach(fn =>
    fn({ target, touches: y == null ? [] : [{ clientX: 100, clientY: y }] }));
  const flushRaf = () => { const r = rafs; rafs = []; r.forEach(fn => fn(now)); };
  const tick = async ms => {
    const end = now + ms;
    for (;;) {
      await new Promise(r => setImmediate(r));
      timers.sort((a, b) => a.at - b.at);
      const t = timers[0];
      if (!t || t.at > end) break;
      timers.shift(); now = t.at; t.fn();
    }
    now = end; await new Promise(r => setImmediate(r));
  };
  const pull = () => { fire('touchstart', 100); for (let i = 1; i <= 20; i++) { fire('touchmove', 100 + i * 12); flushRaf(); } fire('touchend'); };
  const ind = () => body.children.find(c => c.id === 'oa-ptr');
  return { window, fire, flushRaf, tick, pull, ind, counts, g };
}

(async () => {
  // A refresh whose request never answers.
  let w = world(), calls = 0;
  w.window.initPullToRefresh({ onRefresh: () => { calls++; return new Promise(() => {}); } });
  w.pull();
  assert.equal(calls, 1, 'a full pull starts the refresh');
  assert.ok(w.ind().classList.contains('oa-ptr-spin'), 'the spinner shows');
  await w.tick(3000);
  assert.ok(!w.ind().classList.contains('oa-ptr-spin'), 'a hanging refresh releases the spinner within 3 s');
  w.pull();
  assert.equal(calls, 2, '...and the very next pull refreshes again');

  // A normal quick refresh.
  w = world(); calls = 0;
  w.window.initPullToRefresh({ onRefresh: () => { calls++; return Promise.resolve(); } });
  w.pull(); await w.tick(460);
  assert.ok(!w.ind().classList.contains('oa-ptr-spin'), 'a quick refresh is done in under half a second');

  // A page without onRefresh reloads and keeps spinning while the new page loads.
  w = world();
  w.window.initPullToRefresh();
  w.pull(); await w.tick(5000);
  assert.equal(w.g.reloads, 1, 'a page without onRefresh reloads');
  assert.ok(w.ind().classList.contains('oa-ptr-spin'), '...and keeps spinning until the new page replaces it');

  // Cheap gestures.
  w = world();
  w.window.initPullToRefresh({ onRefresh: () => Promise.resolve() });
  w.fire('touchstart', 100);
  assert.equal(w.counts.style, 0, 'touchstart does no style work');
  w.fire('touchmove', 90);                     // an upward first move = a scroll
  assert.equal(w.counts.style, 0, '...nor does a normal scroll');
  w.fire('touchend');
  w.fire('touchstart', 100);
  for (let i = 1; i <= 10; i++) w.fire('touchmove', 100 + i * 12);
  const rectsAfterMoves = w.counts.rect;
  assert.ok(rectsAfterMoves <= 1, 'the header is measured once per pull, not per touchmove');
  assert.ok(!w.ind().style.transform, 'moves are painted on the next frame, not inside touchmove');
  w.flushRaf();
  assert.ok(/translate3d/.test(w.ind().style.transform), '...once per frame');

  const dash = fs.readFileSync('static/dashboard.js', 'utf8');
  const home = dash.slice(dash.indexOf('// Pull down at the top of Home'));
  assert.ok(/window\.OrcAgentRefreshHome\(\); \}catch\(e\)\{\}\s*try\{ return loadHomeFeed\(\);/.test(home),
    "Home's spinner waits for the feed only; the cards refresh on their own");
  assert.ok(dash.includes("if(!_prefSoundAlerts || (_tradeSoundCtx && _tradeSoundCtx.state === 'running')) return;"),
    'a touch starts no audio hardware unless sound alerts are on');
  console.log('PASS pull-to-refresh: never stuck, one paint per frame, no work on plain taps and scrolls');
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
