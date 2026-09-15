"""SEO output stays canonical, crawlable and privacy-safe."""
from pathlib import Path
from types import SimpleNamespace

from flask import Flask

import search_seo

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_HTML = (ROOT / "dashboard.html").read_text(encoding="utf-8")


def make_app():
    search_seo._INSTALLED = False
    app = Flask(__name__)

    @app.get("/")
    def home():
        return "<!doctype html><html><head><title>Old</title></head><body><h1>OrcAgent</h1></body></html>"

    @app.get("/live-market")
    def market():
        return "<html><head><title>Market</title></head><body></body></html>"

    @app.get("/messages")
    def messages():
        return "<html><head><title>Messages</title></head><body></body></html>"

    search_seo.install(SimpleNamespace(app=app))
    return app


def test_source_title_matches_multichain_product_positioning():
    assert "<title>OrcAgent — Multi-Chain Social Trading Platform</title>" in DASHBOARD_HTML
    assert "Solana Trading Terminal" not in DASHBOARD_HTML


def test_home_has_complete_search_metadata():
    body = make_app().test_client().get("/").get_data(as_text=True)
    assert "OrcAgent — Multi-Chain Social Trading Platform" in body
    assert '<link rel="canonical" href="https://orcagent.fun/">' in body
    assert 'name="description"' in body
    assert 'application/ld+json' in body
    assert '"Organization"' in body and '"WebSite"' in body


def test_public_pages_are_indexable_and_private_pages_are_not():
    client = make_app().test_client()
    market = client.get("/live-market")
    private = client.get("/messages")
    assert 'content="index,follow,max-image-preview:large"' in market.get_data(as_text=True)
    assert "X-Robots-Tag" not in market.headers
    assert private.headers["X-Robots-Tag"] == "noindex, nofollow, noarchive"
    assert 'content="noindex,nofollow,noarchive"' in private.get_data(as_text=True)


def test_sitemap_and_robots_point_to_canonical_site():
    client = make_app().test_client()
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    robots = client.get("/robots.txt").get_data(as_text=True)
    assert "<loc>https://orcagent.fun/</loc>" in sitemap
    assert "<loc>https://orcagent.fun/live-market</loc>" in sitemap
    assert '<?xml-stylesheet type="text/xsl" href="/sitemap.xsl"?>' in sitemap
    assert "\n  <url>\n    <loc>" in sitemap
    assert "Sitemap: https://orcagent.fun/sitemap.xml" in robots
    assert "Disallow: /api/" in robots


def test_sitemap_has_a_readable_professional_browser_view():
    client = make_app().test_client()
    stylesheet = client.get("/sitemap.xsl")
    body = stylesheet.get_data(as_text=True)
    assert stylesheet.status_code == 200
    assert "application/xml" in stylesheet.content_type
    assert "ORCAGENT" in body
    assert "Public Sitemap" in body
    assert 'href="{sm:loc}"' in body
