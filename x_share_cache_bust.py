"""Force X to re-crawl OrcAgent post previews after metadata fixes.

Adds a harmless version query to canonical /post/<id> links immediately before
they are sent to X. The matching preview adapter preserves the same version in
canonical/og:url and the card image URL, preventing X from normalizing the
request back onto an older cached generic preview.
"""
from functools import wraps
import re

_INSTALLED = False
_POST_LINK_RE = re.compile(r'(https://orcagent\.fun/post/[pt]\d+)(?!\?[^\s]*)')
_PREVIEW_VERSION = '6'


def _version_post_links(text):
    text = text or ''
    return _POST_LINK_RE.sub(lambda m: m.group(1) + '?xv=' + _PREVIEW_VERSION, text)


def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_post_to_x = dashboard_module._post_to_x

    @wraps(original_post_to_x)
    def _post_to_x_with_fresh_preview(wallet, text, media_ids=None):
        return original_post_to_x(
            wallet,
            _version_post_links(text),
            media_ids=media_ids,
        )

    dashboard_module._post_to_x = _post_to_x_with_fresh_preview
