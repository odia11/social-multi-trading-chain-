"""Launch navigation: no browser history required for a working back route."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup


def test_back_links():
    tmp,app,_=setup()
    client=app.test_client()
    dashboard=client.get('/launches')
    assert dashboard.status_code==200
    html=dashboard.get_data(as_text=True)
    assert 'id="orca-launch-back" class="back-btn" href="/"' in html
    assert '/static/launch-back.js' in html
    assert 'href="/token-launch"' in html
    with client.session_transaction() as sess:
        sess['wallet']='Emj2Uktv12QjDZXRrvhHwHibJtkAMHxUGhzBK2AjXSGd'
        sess['csrf_token']='test-csrf'
    page=client.get('/token-launch')
    assert page.status_code==200
    html=page.get_data(as_text=True)
    # The redesigned launch page carries the app's own navigation (top bar and
    # bottom nav), so it has no separate back link or its script.
    assert "{{ navbar_html('token-launch') }}" in (ROOT/'templates'/'token_launch.html').read_text()
    assert 'orca-launch-back' not in html and '/static/launch-back.js' not in html
    print('PASS Token Launch uses the app navigation, directory back fallback to /')
    tmp.cleanup()

if __name__=='__main__':test_back_links()
