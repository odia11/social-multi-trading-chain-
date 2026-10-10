"""Bounded, cached public X syndication previews for the native feed card.

This is the same public syndication source used by native tweet renderers.
It is not a contractual API: missing/protected/deleted posts fail closed to
an attributed View on X link. Never accept an outbound URL from a client.
"""
from collections import OrderedDict
import json
import re
import threading
import time
from urllib.parse import urlsplit

import requests
from flask import jsonify

_ID = re.compile(r'^[0-9]{5,20}$')
_HANDLE = re.compile(r'^[A-Za-z0-9_]{1,15}$')
_CACHE = OrderedDict()
_LOCK = threading.Lock()
_FETCH_SLOTS = threading.BoundedSemaphore(3)
_INFLIGHT = {}


def _image(raw):
    if not isinstance(raw, str) or len(raw) > 2048:
        return ''
    try:
        u = urlsplit(raw)
        if (u.scheme == 'https' and u.hostname in {'pbs.twimg.com', 'abs.twimg.com'}
                and not u.username and not u.password and not u.port):
            return raw
    except ValueError:
        pass
    return ''


def _text(raw, limit):
    return raw[:limit] if isinstance(raw, str) else ''


def _normalize(raw, expected=None, quoted=False):
    if not isinstance(raw, dict) or raw.get('__typename') == 'TweetTombstone':
        return None
    tid = str(raw.get('id_str') or '')
    user = raw.get('user') or {}
    if not isinstance(user, dict):
        return None
    handle = user.get('screen_name', '')
    if not _ID.fullmatch(tid) or (expected and tid != expected) or not _HANDLE.fullmatch(str(handle)):
        return None
    text = _text(raw.get('text'), 25000)
    if not text:
        return None
    media = []
    details = raw.get('mediaDetails') or raw.get('photos') or []
    for m in details[:4] if isinstance(details, list) else []:
        if not isinstance(m, dict):
            continue
        url = _image(m.get('media_url_https') or m.get('url'))
        if not url:
            continue
        size = m.get('original_info') or {}
        if not isinstance(size, dict):
            size = {}
        def dimension(key):
            value = size.get(key, m.get(key, 0))
            return value if isinstance(value, int) and 0 < value <= 20000 else 0
        media.append({'url': url, 'type': 'video' if m.get('type') in {'video', 'animated_gif'} else 'photo',
                      'width': dimension('width'), 'height': dimension('height'),
                      'alt': _text(m.get('ext_alt_text'), 1000)})
    entities = raw.get('entities') or {}
    if isinstance(entities, dict):
        for m in entities.get('media', [])[:4]:
            if isinstance(m, dict) and isinstance(m.get('url'), str) and media:
                text = text.replace(m['url'], '')
        for item in entities.get('urls', [])[:30]:
            if isinstance(item, dict) and item.get('url') and item.get('display_url'):
                text = text.replace(_text(item['url'], 2048), _text(item['display_url'], 2048))
    card = raw.get('card') or {}
    if not media and isinstance(card, dict):
        bindings = card.get('binding_values') or {}
        if isinstance(bindings, dict):
            for key in ('photo_image_full_size_large', 'summary_photo_image_large', 'thumbnail_image_original'):
                value = bindings.get(key) or {}
                image = value.get('image_value') or {} if isinstance(value, dict) else {}
                url = _image(image.get('url')) if isinstance(image, dict) else ''
                if url:
                    media.append({'url': url, 'type': 'photo', 'width': 0, 'height': 0, 'alt': 'Linked preview from X'})
                    break
    result = {'id': tid, 'url': f'https://x.com/{handle}/status/{tid}',
              'name': _text(user.get('name'), 100), 'username': handle,
              'avatar': _image(user.get('profile_image_url_https')),
              'verified': bool(user.get('verified') or user.get('is_blue_verified') or user.get('verified_type')),
              'text': text.strip(), 'created_at': _text(raw.get('created_at'), 40), 'media': media}
    if not quoted:
        quote = _normalize(raw.get('quoted_tweet'), quoted=True)
        if quote:
            result['quote'] = quote
    return result


def _fetch(tid):
    with requests.get('https://cdn.syndication.twimg.com/tweet-result',
                      params={'id': tid, 'lang': 'en', 'token': '1'},
                      timeout=(5, 5), allow_redirects=False, stream=True) as response:
        if response.status_code != 200 or 'application/json' not in response.headers.get('Content-Type', ''):
            return None
        body = bytearray()
        deadline = time.monotonic() + 5
        for chunk in response.iter_content(16384):
            body.extend(chunk)
            if len(body) > 262144 or time.monotonic() > deadline:
                return None
        return _normalize(json.loads(body), expected=tid)


def _preview(tid):
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(tid)
        if hit and hit[0] > now:
            _CACHE.move_to_end(tid)
            return hit[1]
        pending = _INFLIGHT.get(tid)
        if not pending:
            if not _FETCH_SLOTS.acquire(blocking=False):
                return None
            _INFLIGHT[tid] = threading.Event()
    if pending:
        pending.wait(10)
        with _LOCK:
            hit = _CACHE.get(tid)
            return hit[1] if hit and hit[0] > time.monotonic() else None
    try:
        try:
            data = _fetch(tid)
        except (requests.RequestException, ValueError, TypeError, KeyError):
            data = None
        with _LOCK:
            _CACHE[tid] = (time.monotonic() + (300 if data else 30), data)
            _CACHE.move_to_end(tid)
            while len(_CACHE) > 256:
                _CACHE.popitem(last=False)
        return data
    finally:
        with _LOCK:
            event = _INFLIGHT.pop(tid, None)
            if event:
                event.set()
        _FETCH_SLOTS.release()


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_oa_x_feed_preview', False):
        return
    app._oa_x_feed_preview = True

    @app.get('/api/x-post/<tid>')
    def x_feed_post(tid):
        if not _ID.fullmatch(tid):
            return jsonify(ok=False), 400
        data = _preview(tid)
        response = jsonify(ok=bool(data), tweet=data)
        # Browser refreshes preserve the mounted card; new visits revalidate.
        response.headers['Cache-Control'] = 'private, max-age=30'
        return response, 200 if data else 503
