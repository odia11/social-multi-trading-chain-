"""Source-level regression checks for the approved mobile Post route."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV = (ROOT / 'static' / 'mobile-bottom-nav.js').read_text(encoding='utf-8')
HOME = (ROOT / 'static' / 'home-mobile.js').read_text(encoding='utf-8')
CSS = (ROOT / 'static' / 'home-social-feed.css').read_text(encoding='utf-8')
PERF = (ROOT / 'app_performance.py').read_text(encoding='utf-8')


def check(msg, ok):
    assert ok, msg
    print('PASS ' + msg)


check('center mobile action is Post, not Trade',
      'aria-label="Create post"' in NAV and '<span>Post</span>' in NAV)
check('Post from another screen routes to the Home composer',
      "location.href='/?compose=1#feed-composer'" in NAV)
check('Home keeps the existing composer instead of creating a duplicate',
      "document.getElementById('feed-composer')" in HOME
      and "document.getElementById('postText')" in HOME)
check('approved four Home tabs are present',
      all(x in HOME for x in ('For You', 'Following', 'Groups', 'Live')))
check('existing composer features stay available',
      all(x in CSS for x in ('#chart-pill-btn', '#trade-pill-btn', '#image-pill-btn', '.feed-emoji-btn')))
check('Home is feed-first and old marketing blocks are removed',
      "removeOldHomeBlocks()" in HOME and 'oa-m-hero' in HOME)
check('composer is always expanded and direct-focusable',
      "c.classList.add('expanded'" in HOME and 'scrollIntoView' in HOME)
check('fresh Post navigation is cache-busted in HTML',
      'mobile-bottom-nav.js?v=5' in PERF)
check('fresh feed-first Home controller is cache-busted in HTML',
      'home-mobile.js?v=4' in PERF and 'home-social-feed.css?v=1' in PERF)

print('\n9/9 checks passed')
