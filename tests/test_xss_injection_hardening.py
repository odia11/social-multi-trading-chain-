"""Security regression coverage for authenticated CSRF, XSS sinks and injection guards."""
from pathlib import Path
from types import SimpleNamespace
from flask import Flask
import authenticated_csrf_hardening
import injection_hardening

ROOT = Path(__file__).resolve().parents[1]
def _read(path): return (ROOT / path).read_text(encoding="utf-8")

def test_authenticated_legacy_mutations_fail_closed_without_csrf():
    app=Flask(__name__); app.secret_key="security-test-only"
    d=SimpleNamespace(app=app,_authenticated_wallet=lambda:"wallet-one",_validate_csrf=lambda token:token=="good-token")
    authenticated_csrf_hardening.install(d)
    paths=("/api/instant-trade","/api/copy-trade/toggle","/api/push/subscribe","/api/push/unsubscribe","/api/settings/save","/api/settings/trading-profile","/api/follow/toggle","/api/invite/respond","/api/post/7/edit","/api/post/7/delete")
    for i,path in enumerate(paths): app.add_url_rule(path,"e"+str(i),lambda:("ok",200),methods=["POST"])
    client=app.test_client()
    for path in paths:
        assert client.post(path,json={}).status_code==403
        assert client.post(path,json={},headers={"X-CSRF-Token":"good-token"}).status_code==200

def test_login_bootstrap_routes_are_not_broken_by_extra_guard():
    app=Flask(__name__); app.secret_key="security-test-only"
    d=SimpleNamespace(app=app,_authenticated_wallet=lambda:"wallet-one",_validate_csrf=lambda token:False)
    authenticated_csrf_hardening.install(d)
    app.add_url_rule("/api/session/resume","resume",lambda:("ok",200),methods=["POST"])
    assert app.test_client().post("/api/session/resume",json={}).status_code==200

def test_dynamic_group_sql_identifier_is_allowlisted():
    app=Flask(__name__); d=SimpleNamespace(app=app); calls=[]
    def original(group_id,field,data):
        calls.append((group_id,field,data)); return "safe"
    d._group_image_upload=original; injection_hardening.install(d)
    with app.app_context():
        assert d._group_image_upload(1,"avatar_url","x")=="safe"
        assert d._group_image_upload(1,"banner_url","x")=="safe"
        blocked=d._group_image_upload(1,"avatar_url = NULL; DROP TABLE groups; --","x")
        assert isinstance(blocked,tuple) and blocked[1]==400
    assert [x[1] for x in calls]==["avatar_url","banner_url"]

def test_money_and_social_clients_send_csrf_tokens():
    profile=_read("templates/profile.html"); wallet=_read("templates/wallet.html")
    push=_read("static/push-subscribe.js"); notif=_read("static/notif-poll.js")
    follow=profile.split("fetch('/api/follow/toggle'",1)[1].split("})",1)[0]
    assert "X-CSRF-Token" in follow and "credentials: 'include'" in follow
    quick=wallet.split("fetch('/api/instant-trade'",1)[1].split("})",1)[0]
    assert "X-CSRF-Token" in quick
    assert "_pushCsrfToken" in push and push.count("X-CSRF-Token")>=2
    assert "_notifCsrfToken" in notif and "X-CSRF-Token" in notif

def test_high_risk_dom_sinks_escape_or_avoid_untrusted_html():
    js=_read("static/dashboard.js"); traders=_read("templates/traders.html")
    profile=_read("templates/profile.html"); live=_read("static/live-market-pro.js")
    messages=_read("templates/messages.html")
    assert "function safeImageUrl(value)" in js
    assert 'onclick="selectUserTag' not in js
    assert "data-username=" in js
    assert "${_esc(_dmInitials(name))}" in js
    assert "Feed render error: '+esc(" in js
    assert "Request failed: ${esc(" in js
    assert "logoImg.src=safeLogo" in js and "logoEl.replaceChildren(logoImg)" in js
    assert "esc(username)" in traders
    assert "esc(u.avatar_url)" in profile and "esc(ini)+img" in profile
    assert ".replace(/'/g,'&#39;')" in messages
    assert "var side = String(r.side||'').toLowerCase()==='sell' ? 'sell' : 'buy';" in live

def test_shell_command_injection_primitives_are_not_used():
    for path in ROOT.glob("*.py"):
        source=path.read_text(encoding="utf-8",errors="ignore")
        assert "shell=True" not in source, path.name
        assert "os.system(" not in source, path.name

def test_security_modules_are_installed_at_app_entry():
    entry=_read("app_entry.py")
    assert "_install_authenticated_csrf_hardening(_dashboard)" in entry
    assert "_install_injection_hardening(_dashboard)" in entry
    security=_read("security_hardening.py")
    assert "Cross-Origin-Resource-Policy" in security

if __name__=="__main__":
    for name in sorted(k for k in globals() if k.startswith("test_")):
        globals()[name](); print("PASS",name)
    print("ALL XSS/INJECTION/CSRF HARDENING REGRESSIONS PASSED")
