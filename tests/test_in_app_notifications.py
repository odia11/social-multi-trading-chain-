from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
nav = (ROOT / 'static' / 'navbar.js').read_text(encoding='utf-8')
js = (ROOT / 'static' / 'in-app-notifications.js').read_text(encoding='utf-8')
css = (ROOT / 'static' / 'in-app-notifications.css').read_text(encoding='utf-8')
backend = (ROOT / 'dashboard.py').read_text(encoding='utf-8')

checks = {
    'shared navbar loads foreground notification controller':
        'in-app-notifications.js?v=1' in nav and 'in-app-notifications.css?v=1' in nav,
    'polls the personal notification source while visible: every 6 s, easing to 15 s when quiet':
        'var POLL_MS=6000,POLL_MAX_MS=15000' in js and '/api/notifications/mine?category=all&limit=' in js
        and 'pollDelay=Math.min(POLL_MAX_MS,Math.round(pollDelay*1.5))' in js and 'pollDelay=POLL_MS;' in js,
    'uses incremental after_id queries instead of repeatedly downloading the inbox':
        '&after_id=' in js and "after_id = max(0, int(request.args.get('after_id', 0) or 0))" in backend,
    'first page load baselines existing notifications instead of replaying old alerts':
        "var baseline=!primed;" in js and "if(baseline){" in js,
    'new events are shown while the app is visible and checked immediately on resume':
        "visibilitychange" in js and "if(!document.hidden){syncTop();pollDelay=POLL_MS;poll(false);schedule()}" in js,
    'banner auto-dismisses and all close/open paths share one cleanup flow':
        'var AUTO_DISMISS_MS=4200;' in js
        and 'timer=window.setTimeout(finishCard,AUTO_DISMISS_MS);' in js
        and 'function finishCard(){' in js
        and 'finishCard();' in js,
    'same-page navigation cannot strand a notification after its timer is cleared':
        'Always dismiss first. Same-page feed navigation used to clear the timer' in js
        and "if(typeof window._openFeedNotification==='function' && window._openFeedNotification(target,n.type))return;" in js,
    'dismiss button marks the notification read before closing it':
        "close.addEventListener('click',function(e){" in js
        and 'markRead(Number(n.id)||0);' in js
        and 'finishCard();' in js,
    'tap opens the event destination and marks only that notification read with CSRF':
        "/api/notifications/mine/mark_read_batch" in js
        and "body:JSON.stringify({ids:[id]})" in js
        and "'X-CSRF-Token':token" in js
        and "keepalive:true" in js,
    'notification body is inserted with textContent rather than unsanitized HTML':
        "body.textContent=String(n.content||'');" in js and "copy.innerHTML" not in js,
    'avatar URLs are protocol checked':
        "u.protocol==='http:'||u.protocol==='https:'" in js,
    'banner is a fixed non-blocking overlay above the app chrome':
        '#oa-live-notification-root{' in css and 'z-index:6200' in css and 'pointer-events:none' in css,
    'mobile banner stays compact and readable':
        '@media(max-width:600px)' in css and '-webkit-line-clamp:2' in css,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(('PASS ' if ok else 'FAIL ') + name)
raise SystemExit(1 if failed else 0)
