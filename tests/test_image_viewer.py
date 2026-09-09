"""Tapping a posted photo should show the photo.

THE BUG
The DM page had a full-size viewer. The feed did not — its post images opened
#avatar-lightbox, which caps at 360px because it was built to display a
profile picture. So tapping a photo someone had posted gave you a thumbnail
of a thumbnail, and there was no way to actually look at it.

The two pages had each written out their own copy of the viewer's markup and
styles, and those copies had already drifted apart. That is why the fix is
one source rather than a third copy: dashboard.html is not rendered through
Jinja, so a shared template partial cannot serve both — the same reason
_navbar_html exists as a Python function.

The avatar viewer stays, for avatars. Enlarging a small round crop past its
own resolution only shows you the blur.

AND THE COMPOSER PREVIEW
Its wrapper was full width while the image inside it was not, so the remove
button — positioned against the wrapper's right edge — floated in empty space
well clear of the photo it was meant to remove.
"""
import ast
import re
import sys
from html.parser import HTMLParser

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
JS = open(REPO + '/static/dashboard.js').read()
PAGE = open(REPO + '/dashboard.html').read()
MSGS = open(REPO + '/templates/messages.html').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# Render the real thing.
ns = {'Markup': str}
node = next(n for n in ast.walk(ast.parse(SRC))
            if isinstance(n, ast.FunctionDef) and n.name == '_image_lightbox_html')
exec(ast.get_source_segment(SRC, node), ns)
VIEW = ns['_image_lightbox_html']()

# ── one source, two pages ─────────────────────────────────────────────────
check('the viewer is built in one place', 'def _image_lightbox_html(' in SRC)
check('...spliced into the feed page, which is not rendered through Jinja',
      '__IMAGE_LIGHTBOX__' in PAGE
      and "html.replace('__IMAGE_LIGHTBOX__'" in SRC)
check('...and reached from Jinja pages through the same context processor the '
      'navbar uses', "'image_lightbox_html': _image_lightbox_html" in SRC
      and 'image_lightbox_html()' in MSGS)
check('the DM page no longer carries its own copy of the styles — that copy is '
      'how the two drifted in the first place',
      '#img-lightbox img{' not in MSGS and '#img-lightbox-close{' not in MSGS)
check('...nor its own copy of the markup',
      '<div id="img-lightbox"' not in MSGS)

# ── what it renders has to survive a browser ──────────────────────────────
VOID = {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'area'}
class P(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.bad = []
    def handle_starttag(self, tag, attrs):
        if tag not in VOID: self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.bad.append(tag)
        else: self.stack.pop()
p = P(); p.feed(VIEW)
check(f'every tag it emits is closed{"" if not p.stack else ": " + ", ".join(p.stack)}',
      not p.stack and not p.bad)
css = re.search(r'<style>(.*?)</style>', VIEW, re.S).group(1)
check('the styles have balanced braces — one stray brace drops every rule '
      'after it', css.count('{') == css.count('}'))

# ── the thing that was actually wrong ─────────────────────────────────────
check('the image is bounded by the VIEWPORT, not by a pixel count — being able '
      'to see it large is the whole point',
      'max-width:94vw' in css and 'max-height:88vh' in css)
check('...and no 360px cap survives anywhere in it', '360px' not in VIEW)
check('object-fit is contain, so a tall photo is shown whole rather than '
      'cropped to fit', 'object-fit:contain' in css)
check('the close button clears the notch on a phone, where it would otherwise '
      'sit under the status bar', 'env(safe-area-inset-top)' in css)

# ── how it is opened and closed ───────────────────────────────────────────
check('feed posts open the full-size viewer', '_openImgLightbox(' in JS)
check('...and no longer the avatar one, which is what made them thumbnails',
      "_showAvatarLightbox('+esc(JSON.stringify(e.image_url))" not in JS)
check('avatars still use the avatar viewer, because enlarging a small round '
      'crop past its own resolution only shows the blur',
      '_showAvatarLightbox(' in JS and 'avatar_url' in JS)
check('a page without the viewer falls back to opening the file rather than '
      'doing nothing when someone taps', "window.open(url, '_blank')" in JS)
check('the page behind it cannot scroll while it is open',
      "document.body.style.overflow = 'hidden'" in JS)
check('...and that is undone on close, or the page would stay frozen',
      "document.body.style.overflow = ''" in JS)
check('Escape closes it', "e.key === 'Escape'" in JS and '_closeImgLightbox()' in JS)
check('clicking the image itself does not close it — only the backdrop and the '
      'button do', 'onclick="event.stopPropagation()"' in VIEW)

# ── the composer preview ──────────────────────────────────────────────────
# From the wrapper's own tag to the end of the image inside it. Slicing
# backwards from the id landed in the markup above it.
_start = PAGE.index('<div id="composer-image-preview"')
prev = PAGE[_start:PAGE.index('</div>', _start) + 6]
check('the preview wrapper shrinks to its image, so the remove button lands on '
      'the photo instead of floating in empty space beside it',
      'width:fit-content' in prev)
check('...while still never exceeding the column', 'max-width:100%' in prev)
check('the preview shows the whole picture rather than a centre crop — it is '
      'the last look before posting', 'object-fit:contain' in prev)
check('the remove button says what it does, for anyone not seeing the glyph',
      'aria-label="Remove image"' in prev)

# ── the photo in the feed itself ──────────────────────────────────────────
# It was forced into a 16/9 box and cropped to fill it, so a square or
# portrait picture lost both its sides. On a shared card that cut the first
# word off every line.
import re as _re
_feed = _re.search(r'\.fc-post-image\{([^}]*)\}', PAGE).group(1)
check('a posted photo keeps its own shape instead of being forced into a '
      '16/9 box', 'aspect-ratio' not in _feed)
check('...and is fitted, not cropped, so nothing is cut off the sides',
      'object-fit:contain' in _feed and 'object-fit:cover' not in _feed)
check('...with its height following the picture rather than the box',
      _re.search(r'(?:^|;)height:\s*auto', _feed))
check('...and a cap that only bites on something extremely tall, which would '
      'otherwise push the rest of the feed off the screen',
      _re.search(r'max-height:\s*([0-9]+)px', _feed)
      and int(_re.search(r'max-height:\s*([0-9]+)px', _feed).group(1)) >= 500)
_wrap = _re.search(r'\.fc-post-image-wrap\{([^}]*)\}', PAGE).group(1)
check('the wrapper has a background, since contain can leave bands beside a '
      'tall image and a transparent band reads as a bug', 'background:' in _wrap)
check('avatars still crop, which is what a round crop is for',
      '.feed-composer-avatar img' in PAGE and 'object-fit:cover' in PAGE)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
