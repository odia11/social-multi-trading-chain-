"""Force X to re-crawl canonical OrcAgent post previews after metadata fixes.

X caches card metadata aggressively by URL. Older /post/<id> shares may still
show the previous generic OrcAgent card even after the page now serves the
correct token/trade Open Graph image. This adapter adds a harmless version query
to canonical post links immediately before they are sent to X.

It must be installed before share_canonical_routes so that adapter adds the
canonical link first and this wrapper then version-stamps the final text.
"""
from functools import wraps
import re

_INSTALLED = False
_POST_LINK_RE = re.compile(r'(https://orcagent\.fun/post/[pt]\d+)(?!\?[^\s]*)')
_PREVIEW_VERSION = '5'


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
