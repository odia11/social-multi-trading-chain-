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
_IMAGE_KEYS = {
    'image', 'image_data', 'image_url', 'avatar', 'avatar_url', 'banner', 'banner_url',
    'photo', 'picture', 'group_avatar', 'group_banner',
}


def _validate_image_bytes(raw: bytes) -> None:
    if not raw or len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError('Image payload is empty or too large')
    try:
        from PIL import Image, UnidentifiedImageError
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
            # verify() forces Pillow to parse enough structure to reject truncated/polyglot junk.
            im.verify()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Invalid image data') from exc


def _validate_data_uri(value: str) -> None:
    text = str(value or '')
    if not text.lower().startswith('data:image/'):
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


def _walk_images(obj, key=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_images(v, str(k).lower())
    elif isinstance(obj, list):
        for v in obj[:50]:
            yield from _walk_images(v, key)
    elif isinstance(obj, str):
        if obj.lower().startswith('data:image/') or key in _IMAGE_KEYS or key.endswith('_image'):
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
            # Validate multipart images by bytes, never by filename extension alone.
            for storage in request.files.values():
                mime = str(storage.mimetype or '').lower()
                if not mime.startswith('image/'):
                    continue
                if mime not in _ALLOWED_MIMES:
                    raise ValueError('Unsupported image MIME type')
                pos = storage.stream.tell()
                raw = storage.stream.read(_MAX_IMAGE_BYTES + 1)
                storage.stream.seek(pos)
                _validate_image_bytes(raw)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        return None
