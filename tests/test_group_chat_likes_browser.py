"""Run with Python + Playwright; regression for mobile group-like DOM churn.

The production group-chat script runs against a deterministic API fixture.
A mounted image has a runtime attribute, as loaded/secured images do in-app.
Both local reactions and polled reactions must preserve every message/image.
"""
import asyncio
import json
import os
from pathlib import Path

async def main():
    from playwright.async_api import async_playwright
    root = Path(__file__).resolve().parents[1]
    image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII='
    messages = [dict(id=i, sender_id=2, sender='Bob', sender_wallet='bob', sender_avatar='',
                     kind='image' if i % 2 else 'text', body=image if i % 2 else f'Message {i}',
                     mine=False, created_at='2026-10-09 07:00:00', version=0, likes=[], liked=False)
                for i in range(1, 82)]
    chat = dict(id=1, name='Test group', members=[dict(user_id=1, username='Alice', wallet='alice')],
                role='member', created_by=2, is_owner=False)
    state = dict(version=0, fail=False, delay=0, posts=0, incoming=False)
    async with async_playwright() as pw:
        kwargs = dict(args=['--no-sandbox', '--disable-dev-shm-usage'])
        if os.getenv('ORCAGENT_CHROMIUM'): kwargs['executable_path'] = os.environ['ORCAGENT_CHROMIUM']
        browser = await pw.chromium.launch(**kwargs)
        page = await browser.new_page(viewport=dict(width=390, height=844), is_mobile=True, has_touch=True)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        async def route(r):
            path = r.request.url.split('http://group.test')[-1]
            if path == '/':
                await r.fulfill(content_type='text/html', body='<div id="gc-section"></div><div id="conv-list"></div><script>window._myWallet="alice";</script>')
                return
            if path.endswith('/likes'):
                state['posts'] += 1
                if state['delay']: await asyncio.sleep(state['delay'])
                if state['fail']:
                    await r.abort(); return
                m = messages[int(path.split('/')[-2])-1]
                emoji=json.loads(r.request.post_data or '{}').get('emoji','❤️')
                mine=next((l for l in m['likes'] if l['mine']),None)
                m['liked']=not(mine and mine.get('emoji','❤️')==emoji)
                m['likes']=[l for l in m['likes'] if not l['mine']]
                if m['liked']: m['likes'].append(dict(user_id=1, username='Alice', wallet='alice', mine=True, emoji=emoji))
                state['version'] += 1; m['version'] = state['version']
                data = dict(ok=True, likes=m['likes'], liked=m['liked'], version=m['version'])
            elif '/messages?' in path:
                data = dict(ok=True, messages=[], updates=[messages[-1]] if state['incoming'] else [], change_version=state['version'])
            elif path.endswith('/messages'):
                data = dict(ok=True, messages=messages, change_version=state['version'])
            elif path == '/api/group-chats/1': data = dict(ok=True, chat=chat)
            else: data = dict(ok=True, chats=[dict(id=1, name='Test group', members=2, unread=0)])
            await r.fulfill(content_type='application/json', body=json.dumps(data))
        await page.route('http://group.test/**', route)
        await page.goto('http://group.test/')
        await page.add_style_tag(content=(root/'static/group-chats.css').read_text())
        await page.add_script_tag(content=(root/'static/group-chats.js').read_text())
        await page.evaluate('OrcAgentGroupChats.open(1,false)')
        await page.wait_for_selector('.gc-like-empty')
        await page.evaluate('''() => {
          window.rows=[...document.querySelectorAll('.gc-msg')];window.photos=[...document.querySelectorAll('.gc-img')];
          photos.forEach(img=>img.dataset.loaded='1');
          window.button=rows[rows.length-1].querySelector('[data-message-like]');
          window.changes=0;window.ob=new MutationObserver(ms=>changes+=ms.reduce((n,m)=>n+m.addedNodes.length+m.removedNodes.length,0));
          ob.observe(document.querySelector('.gc-msgs'),{childList:true,subtree:true});
        }''')
        for i in range(20):
            await page.evaluate('button.click()')
            await page.wait_for_function('!button.disabled')
            assert await page.evaluate('button.classList.contains("liked")') == (i % 2 == 0)
        state['delay'] = .3
        before = state['posts']
        await page.evaluate('for(let i=0;i<15;i++)button.click()')
        await page.wait_for_function('!button.disabled')
        assert state['posts'] == before+1, 'Rapid taps sent duplicate toggles'
        state['delay'] = 0; state['fail'] = True
        await page.evaluate('button.click()')
        await page.wait_for_function('!button.disabled')
        assert await page.evaluate('button.classList.contains("liked")'), 'Failed request did not roll back'
        state['fail'] = False
        messages[-1]['likes'] = [dict(user_id=2, username='Bob', wallet='bob', mine=False)]
        messages[-1]['liked'] = False; state['version'] += 1; messages[-1]['version'] = state['version']; state['incoming'] = True
        await page.wait_for_function('button.getAttribute("aria-pressed")==="false"')
        assert await page.evaluate('rows.every(e=>e.isConnected)&&photos.every(e=>e.isConnected)&&button.isConnected'), 'Like replaced mounted messages/photos'
        assert await page.evaluate('changes') < 200, 'Like caused chat-wide mutation churn'
        await page.locator('.gc-msg').last.dispatch_event('contextmenu', dict(clientX=180,clientY=400))
        await page.get_by_role('button',name='React 😂',exact=True).click()
        await page.wait_for_selector('.gc-like-pill.liked[data-emoji="😂"]')
        await page.locator('.gc-msg').last.dispatch_event('contextmenu', dict(clientX=180,clientY=400))
        await page.get_by_role('button',name='More reactions',exact=True).click()
        await page.get_by_role('button',name='React 💎',exact=True).click()
        await page.wait_for_selector('.gc-like-pill.liked[data-emoji="💎"]')
        assert not await page.locator('.gc-like-pill[data-emoji="😂"]').count(), 'Emoji switch retained old reaction'
        assert await page.evaluate('rows.every(e=>e.isConnected)&&photos.every(e=>e.isConnected)'), 'Emoji picker replaced photos'
        await page.locator('.gc-msg').last.locator('.gc-message-more').click()
        await page.get_by_role('button',name='Remove reaction',exact=True).click()
        await page.wait_for_selector('.gc-like-pill[data-emoji="💎"]',state='detached')
        assert not errors, errors
        print('PASS: 81 messages with photos, repeated likes/unlikes, rapid taps, rollback, incoming likes, stable message/image/button DOM, no JS errors')
        await browser.close()

if __name__ == '__main__': asyncio.run(main())
