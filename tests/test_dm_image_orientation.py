import base64
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({
    'DATA_DIR': tempfile.mkdtemp(),
    'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
    'ORCAGENT_FRONTS_GAS': '0',
})
import app_entry  # noqa: E402
from PIL import Image  # noqa: E402

d = app_entry._dashboard
ROOT = Path(__file__).resolve().parents[1]

checks = []
def check(name, cond):
    checks.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name, flush=True)

# Simulate an iPhone portrait JPEG: underlying pixels are landscape (80x40)
# and EXIF orientation 6 tells viewers to rotate 90 degrees clockwise.
img = Image.new('RGB', (80, 40), (240, 190, 80))
exif = Image.Exif()
exif[274] = 6
buf = io.BytesIO()
img.save(buf, format='JPEG', quality=90, exif=exif)
raw = buf.getvalue()
uri = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')

normalized_uri = d._shrink_image_data_uri(uri, max_edge=1600, target_kb=400)
out_raw = base64.b64decode(normalized_uri.split(',', 1)[1])
out = Image.open(io.BytesIO(out_raw))
check('EXIF portrait photo is physically normalized to portrait pixels',
      out.size == (40, 80))
check('normalized DM image no longer depends on a rotation EXIF flag',
      int((out.getexif() or {}).get(274, 1) or 1) in (0, 1))

out_bytes, out_ext = d._shrink_image_bytes(raw, 'jpg')
out2 = Image.open(io.BytesIO(out_bytes))
check('multipart DM upload route gets the same portrait normalization',
      out2.size == (40, 80) and out_ext == 'jpg')

messages = (ROOT / 'templates' / 'messages.html').read_text()
dashboard = (ROOT / 'dashboard.html').read_text()
check('Messages page preserves natural photo aspect ratio',
      '.msg-bubble.msg-image img{display:block;width:auto;height:auto;' in messages
      and 'object-fit:contain' in messages)
check('legacy/dashboard DM renderer also preserves natural photo aspect ratio',
      '.dm-bubble-img img{width:auto;height:auto;' in dashboard
      and 'object-fit:contain' in dashboard)

raise SystemExit(0 if all(checks) else 1)
