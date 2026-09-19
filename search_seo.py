"""Search-engine metadata and discovery routes for OrcAgent.

The live app stays on the existing apex origin so installed-app and wallet
sessions are not broken. The www host already redirects here permanently.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import quote

from flask import Response, request


_INSTALLED = False
_BASE_URL = "https://orcagent.fun"
_LOGO_URL = _BASE_URL + "/static/icon-512.png"

_PAGE_META = {
    "/": (
        "OrcAgent — Multi-Chain Social Trading Platform",
        "Trade smarter together with OrcAgent. Discover live crypto markets, automate strategies, follow traders and share trades across multiple chains.",
    ),
    "/live-market": (
        "Live Crypto Market & Meme Coin Charts | OrcAgent",
        "Explore live crypto markets, meme coin charts and real-time token opportunities across the chains supported by OrcAgent.",
    ),
    "/auto-trading-bot": (
        "Automated Crypto Trading Bot | OrcAgent",
        "Configure OrcAgent's automated crypto trading bot with your own strategy, limits, take-profit and stop-loss settings.",
    ),
    "/groups": (
        "Crypto Trading Groups & Community | OrcAgent",
        "Join crypto trading groups, discuss market opportunities and share insights with the OrcAgent community.",
    ),
    "/info": (
        "About, Security & Privacy | OrcAgent",
        "Learn what OrcAgent is, how its multi-chain social trading platform works, how security and privacy are handled, current fees, contact details and terms.",
    ),
}
_SITEMAP_PATHS = tuple(_PAGE_META)
_PUBLIC_PREFIXES = ("/post/", "/profile/")
_PRIVATE_PREFIXES = (
    "/api/", "/admin", "/messages", "/notifications", "/wallet",
    "/settings", "/phantom", "/solflare", "/callback", "/logout",
)
_PUBLIC_PREVIEW_IMAGE_PREFIXES = ("/api/trade-card/", "/api/post-og-image/")
_TITLE_RE = re.compile(r"<title\b[^>]*>.*?</title>", re.I | re.S)
_DESCRIPTION_RE = re.compile(
    r"<meta\b(?=[^>]*\bname\s*=\s*[\"']description[\"'])[^>]*>\s*",
    re.I,
)
_ROBOTS_RE = re.compile(
    r"<meta\b(?=[^>]*\bname\s*=\s*[\"']robots[\"'])[^>]*>\s*",
    re.I,
)
_CANONICAL_RE = re.compile(
    r"<link\b(?=[^>]*\brel\s*=\s*[\"']canonical[\"'])[^>]*>\s*",
    re.I,
)


def _path() -> str:
    value = request.path.rstrip("/")
    return value or "/"


def _public_meta(path: str):
    if path in _PAGE_META:
        return _PAGE_META[path]
    if path.startswith("/post/"):
        return (
            "Crypto Trading Post | OrcAgent",
            "View this crypto trading post, token card and community discussion on OrcAgent.",
        )
    if path.startswith("/profile/"):
        return (
            "Crypto Trader Profile | OrcAgent",
            "View this trader's public profile, shared trades and social activity on OrcAgent.",
        )
    return None


def _canonical(path: str) -> str:
    return _BASE_URL + quote(path, safe="/:@-._~")


def _graph_json() -> str:
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": _BASE_URL + "/#organization",
                "name": "OrcAgent",
                "url": _BASE_URL + "/",
                "logo": {"@type": "ImageObject", "url": _LOGO_URL},
                "sameAs": ["https://x.com/orcagent"],
            },
            {
                "@type": "WebSite",
                "@id": _BASE_URL + "/#website",
                "name": "OrcAgent",
                "url": _BASE_URL + "/",
                "publisher": {"@id": _BASE_URL + "/#organization"},
            },
            {
                "@type": "WebApplication",
                "name": "OrcAgent",
                "url": _BASE_URL + "/",
                "applicationCategory": "FinanceApplication",
                "operatingSystem": "Web",
                "description": _PAGE_META["/"][1],
                "publisher": {"@id": _BASE_URL + "/#organization"},
            },
        ],
    }
    return json.dumps(graph, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _inject_before_head_close(body: str, markup: str) -> str:
    index = body.lower().find("</head>")
    if index < 0:
        return body
    return body[:index] + markup + "\n" + body[index:]


def _decorate_html(body: str, path: str) -> str:
    meta = _public_meta(path)
    body = _ROBOTS_RE.sub("", body)
    body = _DESCRIPTION_RE.sub("", body)
    body = _CANONICAL_RE.sub("", body)

    if not meta:
        return _inject_before_head_close(
            body, '<meta name="robots" content="noindex,nofollow,noarchive">'
        )

    title, description = meta
    safe_title = html.escape(title, quote=True)
    safe_description = html.escape(description, quote=True)
    canonical = html.escape(_canonical(path), quote=True)
    if _TITLE_RE.search(body):
        body = _TITLE_RE.sub("<title>" + safe_title + "</title>", body, count=1)
    else:
        body = _inject_before_head_close(body, "<title>" + safe_title + "</title>")

    tags = [
        '<meta name="description" content="' + safe_description + '">',
        '<meta name="robots" content="index,follow,max-image-preview:large">',
        '<link rel="canonical" href="' + canonical + '">',
    ]
    lower = body.lower()
    if 'property="og:title"' not in lower and "property='og:title'" not in lower:
        tags.extend([
            '<meta property="og:type" content="website">',
            '<meta property="og:site_name" content="OrcAgent">',
            '<meta property="og:title" content="' + safe_title + '">',
            '<meta property="og:description" content="' + safe_description + '">',
            '<meta property="og:url" content="' + canonical + '">',
            '<meta property="og:image" content="' + _LOGO_URL + '">',
            '<meta name="twitter:card" content="summary_large_image">',
        ])
    if path == "/":
        tags.append('<script type="application/ld+json">' + _graph_json() + "</script>")
    return _inject_before_head_close(body, "\n".join(tags))


_SITEMAP_XSL = """<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
  xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:sm="http://www.sitemaps.org/schemas/sitemap/0.9">
  <xsl:output method="html" encoding="UTF-8"/>
  <xsl:template match="/">
    <html lang="en">
      <head>
        <meta charset="UTF-8"/>
        <meta name="viewport" content="width=device-width,initial-scale=1"/>
        <title>OrcAgent Sitemap</title>
        <style>
          *{box-sizing:border-box}
          body{margin:0;background:#080d12;color:#eef1f5;font-family:system-ui,-apple-system,sans-serif}
          main{width:min(760px,calc(100% - 32px));margin:48px auto;padding:30px;background:#10161d;border:1px solid #27313d;border-radius:24px;box-shadow:0 24px 70px rgba(0,0,0,.35)}
          .brand{color:#f7b955;font-size:12px;font-weight:800;letter-spacing:.24em}
          h1{margin:10px 0 6px;font-size:clamp(28px,7vw,44px);letter-spacing:-.04em}
          p{margin:0 0 24px;color:#9ba6b3;line-height:1.6}
          .list{display:grid;gap:10px}
          a{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 18px;border:1px solid #27313d;border-radius:14px;color:#eef1f5;text-decoration:none;background:#0b1117;overflow:hidden}
          a:hover{border-color:#f7b955;background:#121922}
          .url{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
          .arrow{color:#f7b955;font-weight:800}
          .foot{margin-top:22px;padding-top:18px;border-top:1px solid #27313d;color:#697582;font-size:12px}
          @media(max-width:520px){main{margin:20px auto;padding:22px 16px;border-radius:20px}a{padding:14px}}
        </style>
      </head>
      <body>
        <main>
          <div class="brand">ORCAGENT</div>
          <h1>Public Sitemap</h1>
          <p><xsl:value-of select="count(sm:urlset/sm:url)"/> public pages available to search engines.</p>
          <div class="list">
            <xsl:for-each select="sm:urlset/sm:url">
              <a href="{sm:loc}">
                <span class="url"><xsl:value-of select="sm:loc"/></span>
                <span class="arrow">→</span>
              </a>
            </xsl:for-each>
          </div>
          <div class="foot">This sitemap is generated by OrcAgent and uses the canonical production URLs.</div>
        </main>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
"""

def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = dashboard_module.app

    @app.get("/robots.txt")
    def _orca_robots():
        text = "\n".join([
            "User-agent: *",
            # Put specific rules before broad ones for crawlers that match
            # the first applicable rule rather than the longest prefix.
            "Allow: /api/trade-card/",
            "Allow: /api/post-og-image/",
            "Disallow: /api/",
            "Disallow: /admin/",
            "Disallow: /phantom/",
            "Disallow: /solflare/",
            "Allow: /",
            "Sitemap: " + _BASE_URL + "/sitemap.xml",
            "",
        ])
        return Response(text, content_type="text/plain; charset=utf-8")

    @app.get("/sitemap.xsl")
    def _orca_sitemap_stylesheet():
        return Response(_SITEMAP_XSL, content_type="application/xml; charset=utf-8")

    @app.get("/sitemap.xml")
    def _orca_sitemap():
        urls = "\n".join(
            "\n".join([
                "  <url>",
                "    <loc>" + html.escape(_canonical(path)) + "</loc>",
                "  </url>",
            ])
            for path in _SITEMAP_PATHS
        )
        xml = "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<?xml-stylesheet type="text/xsl" href="/sitemap.xsl"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            urls,
            "</urlset>",
            "",
        ])
        return Response(xml, content_type="application/xml; charset=utf-8")

    @app.after_request
    def _orca_search_metadata(response):
        path = _path()
        is_private = any(path == prefix or path.startswith(prefix) for prefix in _PRIVATE_PREFIXES)
        is_public_preview_image = (
            response.status_code == 200
            and response.mimetype.startswith("image/")
            and any(path.startswith(prefix) for prefix in _PUBLIC_PREVIEW_IMAGE_PREFIXES)
        )
        if is_public_preview_image:
            # Public social-card PNGs must be crawlable; never open the rest
            # of /api/ to search engines or unfurl bots.
            response.headers.pop("X-Robots-Tag", None)
        elif is_private or (not _public_meta(path) and path not in ("/robots.txt", "/sitemap.xml")):
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        if (
            response.status_code == 200
            and response.mimetype == "text/html"
            and not response.headers.get("Content-Encoding")
        ):
            body = response.get_data(as_text=True)
            response.set_data(_decorate_html(body, path))
            response.content_length = len(response.get_data())
        return response
