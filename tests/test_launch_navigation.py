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
    assert 'id="orca-launch-back" class="tl-back" href="/launches"' in html
    assert '/static/launch-back.js' in html
    assert 'href="/">Home</a>' in html
    print('PASS Token Launch back fallback to /launches, directory back fallback to /')
    tmp.cleanup()

if __name__=='__main__':test_back_links()
