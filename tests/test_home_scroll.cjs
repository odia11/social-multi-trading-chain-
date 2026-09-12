const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const rootDir = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(rootDir, 'static/dashboard.js'), 'utf8');
const start = source.indexOf('var _bottomHoldLastCheck = 0;');
const end = source.indexOf('\nfunction showToken(symbol)', start);
const pagination = source.slice(start, end);
let pages = 0, refreshes = 0;
const events = {main: {}, window: {}};
const root = {scrollTop: 0, scrollHeight: 10000, clientHeight: 800};
const main = {scrollTop: 0, scrollHeight: 10000, clientHeight: 10000,
  overflowY: 'visible', addEventListener(n,f){events.main[n]=f}};
const feed = {offsetParent: main, addEventListener(){throw Error('Feed must not capture touch gestures')}};
const ctx = {Date: {now:()=>Date.now()+1000*pages}, document: {
  scrollingElement: root, documentElement: root,
  getElementById:id=>id==='main-content'?main:feed},
  window: {addEventListener(n,f){events.window[n]=f}},
  getComputedStyle:el=>({overflowY:el.overflowY}),
  _homeFeedNextCursor: 'next', _homeFeedLoadingMore:false,
  loadMoreHomeFeed:()=>pages++, loadHomeFeed:()=>refreshes++,
  setTimeout(){throw Error('Scrolling must not schedule refresh')}
};
vm.runInNewContext(pagination,ctx);
function scroll(target){ctx._bottomHoldLastCheck=0;events[target].scroll()}
scroll('window');assert.equal(pages,0,'mobile wrapper is not the scroll position');
root.scrollTop=9000;scroll('window');assert.equal(pages,1,'mobile bottom appends next page');
ctx._homeFeedNextCursor=null;scroll('window');assert.equal(refreshes,0,'last page does not refresh');
ctx._homeFeedNextCursor='next';main.overflowY='auto';main.clientHeight=800;main.scrollTop=9000;
scroll('main');assert.equal(pages,2,'desktop bottom appends next page');
ctx._homeFeedLoadingMore=true;scroll('main');assert.equal(pages,2,'no duplicate in-flight pagination');
assert.equal(source.includes('_ptrEnsureIndicator'),false,'legacy Home swipe-refresh removed');
let css='',insertions=0;
const guardContext={document:{getElementById:()=>insertions?{}:null,createElement:()=>({}),head:{appendChild(s){css=s.textContent;insertions++}},addEventListener(){throw Error('Global guard must not capture touch gestures')}}};
const guard=fs.readFileSync(path.join(rootDir,'static/mobile-overscroll-guard.js'),'utf8');
vm.runInNewContext(guard,guardContext);vm.runInNewContext(guard,guardContext);
assert.equal(insertions,1);assert.match(css,/overscroll-behavior-y:none/);
console.log('PASS: mobile/desktop pagination, no bottom refresh, no duplicate pagination, no touch capture, CSS overscroll');
