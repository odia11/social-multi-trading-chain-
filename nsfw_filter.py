"""Blocks pornographic / sexually explicit images and videos at upload time.

Model: Yahoo's open_nsfw (BSD 2-Clause, Copyright 2016 Yahoo Inc.), in the
ONNX conversion shipped by the MIT-licensed `opennsfw-standalone` package
(Sector Labs). deploy/install.sh extracts just that model file into
/opt/orcagent/models/ and checks its sha256 -- the package itself is not
installed, because it pins Pillow<9, which would downgrade the app's Pillow.
NudeNet was deliberately NOT used: its model ships under AGPL-3.0.

It runs locally on the CPU (onnxruntime, ~50-100 ms per image): no image
ever leaves the server, and there is nothing to pay for.

Scores are 0..1 ("how likely is this explicit"). Yahoo's guidance: < 0.2 is
very likely safe, > 0.8 very likely NSFW. Anything at or above
NSFW_BLOCK_THRESHOLD (default 0.75, env ORCAGENT_NSFW_THRESHOLD) is refused.

Fail-closed in production: if the model can't be loaded on the live server
(the /data volume exists), image and video uploads are refused with a
"temporarily unavailable" message rather than let unchecked media through.
Locally/in tests it fails open unless ORCAGENT_NSFW_REQUIRED=1.
"""
from __future__ import annotations

import io
import os
import threading

MODEL_SHA256 = '864bb37bf8863564b87eb330ab8c785a79a773f4e7c43cb96db52ed8611305fa'
BLOCKED_MSG = "This appears to contain explicit content, which isn't allowed on OrcAgent"
UNAVAILABLE_MSG = 'Uploads are temporarily unavailable — please try again later'

_lock = threading.Lock()
_state = {'session': None, 'tried': False, 'error': ''}


def threshold() -> float:
    try:
        return float(os.getenv('ORCAGENT_NSFW_THRESHOLD', '0.75'))
    except ValueError:
        return 0.75


def required() -> bool:
    flag = os.getenv('ORCAGENT_NSFW_REQUIRED')
    if flag is not None:
        return flag.strip() == '1'
    return os.path.isdir('/data')   # the production server


def _model_path() -> str:
    explicit = os.getenv('ORCAGENT_NSFW_MODEL', '').strip()
    if explicit:
        return explicit
    for path in ('/opt/orcagent/models/open-nsfw.onnx',
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'open-nsfw.onnx')):
        if os.path.exists(path):
            return path
    return ''


def _session():
    if _state['session'] is not None or _state['tried']:
        return _state['session']
    with _lock:
        if _state['session'] is not None or _state['tried']:
            return _state['session']
        _state['tried'] = True
        path = _model_path()
        if not path:
            _state['error'] = 'open-nsfw.onnx model not found'
            print(f'[nsfw] {_state["error"]} — uploads will be '
                  f'{"REFUSED" if required() else "allowed unchecked"}', flush=True)
            return None
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2    # never starve the trading loops
            opts.inter_op_num_threads = 1
            _state['session'] = ort.InferenceSession(path, sess_options=opts,
                                                     providers=['CPUExecutionProvider'])
            print(f'[nsfw] open_nsfw model loaded ({path})', flush=True)
        except Exception as e:
            _state['error'] = f'could not load model: {e}'
            print(f'[nsfw] {_state["error"]}', flush=True)
        return _state['session']


def available() -> bool:
    return _session() is not None


def _preprocess(img):
    """Yahoo open_nsfw's own preprocessing (classify_nsfw.py): 256x256
    bilinear, JPEG round-trip, centre 224 crop, RGB->BGR, mean subtraction."""
    import numpy as np
    from PIL import Image
    img = img.convert('RGB').resize((256, 256), resample=Image.BILINEAR)
    img = img.crop((16, 16, 240, 240))
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)
    arr = np.array(Image.open(buf), dtype=np.float32)[:, :, ::-1]
    arr = arr - np.array([104, 117, 123], dtype=np.float32)
    return np.expand_dims(arr, axis=0)


def score_pil(img):
    """NSFW probability 0..1 for a PIL image, or None if the model is unavailable."""
    sess = _session()
    if sess is None:
        return None
    x = _preprocess(img)
    out = sess.run(None, {sess.get_inputs()[0].name: x})
    return float(out[0][0][1])


def score_image_bytes(raw: bytes, max_frames: int = 6):
    """Highest NSFW score over an image (for an animated GIF/WebP, over up to
    `max_frames` evenly spread frames). None if the model is unavailable."""
    from PIL import Image, ImageSequence
    if _session() is None:
        return None
    with Image.open(io.BytesIO(raw)) as im:
        n = int(getattr(im, 'n_frames', 1) or 1)
        if n <= 1:
            return score_pil(im)
        step = max(1, n // max_frames)
        best = 0.0
        for i, frame in enumerate(ImageSequence.Iterator(im)):
            if i % step == 0:
                best = max(best, score_pil(frame.copy()))
                if best >= threshold():
                    break
        return best


def check_image_bytes(raw: bytes):
    """None if the image may be uploaded, else the user-facing reason."""
    score = score_image_bytes(raw)
    if score is None:
        return UNAVAILABLE_MSG if required() else None
    return BLOCKED_MSG if score >= threshold() else None


def check_frame_files(paths):
    """(reason_or_None, max_score) over extracted video frames (JPEG files)."""
    from PIL import Image
    if _session() is None:
        return (UNAVAILABLE_MSG if required() else None), None
    best = 0.0
    for p in paths:
        try:
            with Image.open(p) as im:
                best = max(best, score_pil(im))
        except Exception:
            continue
        if best >= threshold():
            return BLOCKED_MSG, best
    return None, best
