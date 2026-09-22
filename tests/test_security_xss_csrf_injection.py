"""Regression checks for OrcAgent XSS, CSRF and injection boundaries."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
DASH = (ROOT / 'dashboard.py').read_text(encoding='utf-8')
DASH_JS = (ROOT / 'static/dashboard.js').read_text(encoding='utf-8')
PUSH = (ROOT / 'static/push-subscribe.js').read_text(encoding='utf-8')
NOTIF = (ROOT / 'static/notif-poll.js').read_text(encoding='utf-8')
TRADERS = (ROOT / 'templates/traders.html').read_text(encoding='utf-8')
MESSAGES = (ROOT / 'templates/messages.html').read_text(encoding='utf-8')
PROFILE = (ROOT / 'templates/profile.html').read_text(encoding='utf-8')
SETTINGS = (ROOT / 'templates/settings.html').read_text(encoding='utf-8')
TREE = ast.parse(DASH)

def decorators(name):
    fn = next(n for n in ast.walk(TREE)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return [ast.unparse(x) for x in fn.decorator_list]

def test_authenticated_mutations_require_csrf():
    guarded = (
        'api_copy_trade_toggle', 'push_subscribe', 'push_unsubscribe',
        'settings_save', 'api_trading_profile', 'feed_post_edit',
        'feed_post_delete_v2', 'follow_toggle_by_wallet', 'invite_respond',
    )
    for name in guarded:
        assert 'csrf_exempt' not in ' '.join(decorators(name)), name

def test_auth_bootstrap_remains_csrf_exempt():
    for name in ('api_phantom_sign_init', 'api_phantom_decrypt_signature',
                 'api_pair_start', 'api_pair_claim', 'api_session_resume'):
        assert 'csrf_exempt' in ' '.join(decorators(name)), name

def test_push_mutations_send_csrf():
    assert '_pushCsrfHeaders' in PUSH
    assert "'X-CSRF-Token':token" in PUSH
    assert '_notifCsrfHeaders' in NOTIF
    assert "'X-CSRF-Token':token" in NOTIF

def test_usernames_never_enter_inline_script_or_raw_modal_html():
    assert 'onclick="selectUserTag(' not in DASH_JS
    assert "label.textContent='@'+u.username" in DASH_JS
    assert "strong.textContent=String(username||'')" in TRADERS
    assert "strong2.textContent=String(username||'')" in TRADERS
    assert "'Stop copying <strong>'+username" not in TRADERS
    assert "'When <strong>'+username" not in TRADERS
    assert 'onclick="document.getElementById(\\\'newMsgBar' not in MESSAGES
    assert "_openThread(Number(u.user_id)||0" in MESSAGES
    assert 'class="flm-row" onclick=' not in PROFILE
    assert 'class="rr-trader-row" onclick=' not in DASH_JS

def test_clients_send_tokens_before_newly_guarded_mutations():
    assert "return Promise.resolve(_csrfReady).then(send)" in DASH_JS
    assert "'X-CSRF-Token':_csrfToken" in TRADERS
    assert "'X-CSRF-Token': _csrfToken" in MESSAGES
    assert "'X-CSRF-Token': _csrf" in PROFILE
    assert "'X-CSRF-Token':_csrf" in SETTINGS

def test_dynamic_group_sql_identifier_is_allowlisted():
    assert "if field not in {'avatar_url', 'banner_url'}:" in DASH
    assert "conn.execute(f'UPDATE groups SET {field}=? WHERE id=?'" in DASH

def test_origin_specific_cors_is_cache_safe():
    assert "resp.headers.add('Vary', 'Origin')" in DASH

def test_subprocesses_never_enable_shell_true():
    for path in ROOT.glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8', errors='ignore'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == 'shell' and isinstance(kw.value, ast.Constant):
                    assert kw.value.value is not True, f'shell=True in {path}:{node.lineno}'

def test_api_error_text_is_escaped_before_inner_html():
    assert "Request failed: ${esc(String(e.message||e))}" in DASH_JS
    assert "Feed render error: '+esc(String(e.message||e))" in DASH_JS

if __name__ == '__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL XSS/CSRF/INJECTION REGRESSIONS PASSED')
