"""Regression checks for the shared token/trade card in direct messages."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PY_SOURCE = (ROOT / "dashboard.py").read_text(encoding="utf-8")
JS_SOURCE = (ROOT / "static" / "dashboard.js").read_text(encoding="utf-8")


def _python_function(name):
    tree = ast.parse(PY_SOURCE)
    node = next(
        item for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name
    )
    return ast.get_source_segment(PY_SOURCE, node) or ""


def _js_function(name):
    start = JS_SOURCE.index("function " + name + "(")
    next_function = JS_SOURCE.find("\nfunction ", start + 10)
    return JS_SOURCE[start:next_function if next_function >= 0 else None]


def test_dm_uses_the_shared_home_trade_card_renderer():
    dm_renderer = _js_function("_dmBuildMessageEl")

    assert "_renderTradeTerminalCard({" in dm_renderer
    assert "dm-shared-token-card" in dm_renderer
    assert '<div class="dm-trade-card' not in dm_renderer
    assert "token_address:addr" in dm_renderer


def test_dm_card_keeps_the_token_click_route_and_copy_action():
    dm_renderer = _js_function("_dmBuildMessageEl")
    shared_renderer = _js_function("_renderTradeTerminalCard")

    assert "showTokenCard(" in shared_renderer
    assert "token_address:t.token_address" in shared_renderer
    assert "_dmCopyTrade(" in dm_renderer


def test_dm_cards_hydrate_the_same_token_banner_as_feed_cards():
    render_all = _js_function("_dmRenderMessages")
    append_one = _js_function("_dmAppendMessage")

    selector = ".dm-shared-token-card [data-mint]"
    assert selector in render_all and "_hydrateTradeBanner" in render_all
    assert selector in append_one and "_hydrateTradeBanner" in append_one


def test_new_dm_payload_contains_every_field_the_shared_card_needs():
    endpoint = _python_function("share_trade_dm")

    for key in (
        "side",
        "entry_price",
        "current_price",
        "exit_price",
        "pnl_pct",
        "pnl_sol",
        "pnl_currency",
        "amount",
        "token_address",
    ):
        assert f"'{key}':" in endpoint

    assert "get_token_data(token_address)" in endpoint
    assert "if pnl_pct is not None else None" in endpoint
