"""Server-side image upload validation.

Client file type/size checks are UX only. This guard validates raster image bytes before
mutating API handlers see them, rejects SVG/HTML/polyglot data URIs, decompression bombs,
extreme dimensions and oversized payloads, while preserving JPEG/PNG/GIF/WEBP support.
"""
from __future__ import annotations

import base64
import binascii
import io

from flask import jsonify, request

_ALLOWED_FORMATS = {'JPEG', 'PNG', 'GIF', 'WEBP'}
_ALLOWED_MIMES = {'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_EDGE = 6000
_MAX_PIXELS = 24_000_000
_MAX_GIF_FRAMES = 180
_MAX_WALK_NODES = 5000
_MAX_NESTING = 32
_IMAGE_KEYS = {
    'image', 'image_data', 'image_url', 'avatar', 'avatar_url', 'banner', 'banner_url',
    'photo', 'picture', 'group_avatar', 'group_banner',
}


def _validate_image_bytes(raw: bytes) -> None:
    if not raw or len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError('Image payload is empty or too large')
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = _MAX_PIXELS
        with Image.open(io.BytesIO(raw)) as im:
            fmt = str(im.format or '').upper()
            if fmt not in _ALLOWED_FORMATS:
                raise ValueError('Unsupported image format')
            w, h = im.size
            if w < 1 or h < 1 or w > _MAX_EDGE or h > _MAX_EDGE or w * h > _MAX_PIXELS:
                raise ValueError('Image dimensions are not allowed')
            frames = int(getattr(im, 'n_frames', 1) or 1)
            if frames > _MAX_GIF_FRAMES:
                raise ValueError('Animated image has too many frames')
            im.verify()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Invalid image data') from exc
    # Pornographic / sexually explicit images are refused here, the one
    # place every image upload passes through (posts, avatars, banners,
    # group and chat images) -- see nsfw_filter.py.
    reason = _nsfw_check(raw)
    if reason:
        raise NsfwRejected(reason)


class NsfwRejected(ValueError):
    """An upload refused for explicit content (logged for moderators)."""


def _nsfw_check(raw: bytes):
    try:
        import nsfw_filter
    except Exception:
        return None
    return nsfw_filter.check_image_bytes(raw)


def _validate_data_uri(value: str) -> None:
    text = str(value or '').strip()
    low = text.lower()
    if low.startswith('data:') and not low.startswith('data:image/'):
        raise ValueError('Only raster image data URIs are allowed in image fields')
    if not low.startswith('data:image/'):
        return
    head, sep, payload = text.partition(',')
    if not sep or ';base64' not in head.lower():
        raise ValueError('Image data URI must be base64 encoded')
    mime = head[5:].split(';', 1)[0].strip().lower()
    if mime not in _ALLOWED_MIMES:
        raise ValueError('Unsupported image MIME type')
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('Invalid image base64') from exc
    _validate_image_bytes(raw)


def _walk_images(obj, key='', *, _state=None, _depth=0):
    # Never silently skip the tail of a list: that used to let an attacker put
    # a malicious image in item 51 and bypass validation. Instead bound the
    # total JSON structure and reject over-complex payloads fail-closed.
    if _state is None:
        _state = [0]
    _state[0] += 1
    if _state[0] > _MAX_WALK_NODES or _depth > _MAX_NESTING:
        raise ValueError('Upload payload is too complex')
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_images(v, str(k).lower(), _state=_state, _depth=_depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_images(v, key, _state=_state, _depth=_depth + 1)
    elif isinstance(obj, str):
        if obj.strip().lower().startswith('data:') or key in _IMAGE_KEYS or key.endswith('_image'):
            yield obj


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_upload_hardening_installed', False):
        return
    app._orca_upload_hardening_installed = True

    @app.before_request
    def _validate_uploaded_images():
        if request.method not in {'POST', 'PUT', 'PATCH'} or not request.path.startswith('/api/'):
            return None
        try:
            if request.is_json:
                body = request.get_json(silent=True)
                if body is not None:
                    for value in _walk_images(body):
                        _validate_data_uri(value)
            # MultiDict.values() only returns the first file for each field.
            # Handlers using getlist() must never receive unchecked siblings.
            for _field, storage in request.files.items(multi=True):
                mime = str(storage.mimetype or '').lower()
                if not mime.startswith('image/'):
                    continue
                if mime not in _ALLOWED_MIMES:
                    raise ValueError('Unsupported image MIME type')
                pos = storage.stream.tell()
                raw = storage.stream.read(_MAX_IMAGE_BYTES + 1)
                storage.stream.seek(pos)
                _validate_image_bytes(raw)
        except NsfwRejected as exc:
            try:
                wallet = dashboard_module._authenticated_wallet() or 'unknown'
                dashboard_module._log_security_event('nsfw_blocked', wallet,
                                                     f'explicit image refused on {request.path}')
            except Exception:
                pass
            return jsonify({'ok': False, 'error': str(exc), 'msg': str(exc)}), 400
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        return None
