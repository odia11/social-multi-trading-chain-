"""Every public share keeps a complete route back to its source."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PY_SOURCE = (ROOT / 'dashboard.py').read_text()
PROFILE_SOURCE = (ROOT / 'templates' / 'profile.html').read_text()
JS_SOURCE = (ROOT / 'static' / 'dashboard.js').read_text()


def _load_function(name):
    tree = ast.parse(PY_SOURCE)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'dashboard.py', 'exec'), namespace)
    return namespace[name]


def test_share_link_is_complete_and_inside_limit():
    attach = _load_function('_share_text_with_route')
    route = 'https://orcagent.fun/post/p123456'
    result = attach('x' * 400, route)

    assert len(result) <= 280
    assert result.endswith(route)
    assert result.count(route) == 1
    assert '… ' + route in result


def test_feed_share_always_uses_post_id_permalink():
    assert "location.origin+'/post/'+encodeURIComponent(postId)" in JS_SOURCE
    share_fn = ast.get_source_segment(
        PY_SOURCE,
        next(n for n in ast.parse(PY_SOURCE).body
             if isinstance(n, ast.FunctionDef) and n.name == 'share_feed_to_x'),
    )
    assert "'/post/' + post_id" in share_fn
    assert '_share_text_with_route(text, link_fallback)' in share_fn


def test_profile_share_uses_permanent_wallet_identifier():
    assert "window.location.origin + '/profile/'" in PROFILE_SOURCE
    assert 'encodeURIComponent({{ wallet|tojson }})' in PROFILE_SOURCE
    assert 'var url = window.location.href;' not in PROFILE_SOURCE


def test_automatic_shares_also_keep_a_source_route():
    assert "f'https://orcagent.fun/share/t{_trade_id}'" in PY_SOURCE
    assert "'https://orcagent.fun/profile/'" in PY_SOURCE
    assert PY_SOURCE.count('_share_text_with_route(') >= 4
