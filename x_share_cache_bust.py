"""Keep OrcAgent X shares fresh and consistently branded.

Adds a cache-busting version to canonical /post/<id> links and ensures direct
X shares include the @orcagent tag in English copy.
"""
from functools import wraps
import re

_INSTALLED = False
_POST_LINK_RE = re.compile(r'(https://orcagent\.fun/post/[pt]\d+)(?!\?[^\s]*)')
_PREVIEW_VERSION = '9'


def _version_post_links(text):
    text = text or ''
    return _POST_LINK_RE.sub(lambda m: m.group(1) + '?xv=' + _PREVIEW_VERSION, text)


def _ensure_orcagent_tag(text):
    text = (text or '').strip()
    if '@orcagent' in text.lower():
        return text
    # Keep the mention before the canonical URL when one is present.
    match = re.search(r'\shttps://orcagent\.fun/post/', text)
    if match:
        pos = match.start()
        return text[:pos].rstrip() + ' @orcagent' + text[pos:]
    return (text + ' @orcagent').strip()


def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_post_to_x = dashboard_module._post_to_x

    @wraps(original_post_to_x)
    def _post_to_x_with_fresh_preview(wallet, text, media_ids=None):
        text = _ensure_orcagent_tag(text)
        text = _version_post_links(text)
        return original_post_to_x(wallet, text, media_ids=media_ids)

    dashboard_module._post_to_x = _post_to_x_with_fresh_preview
