"""Executable boundary tests; no production import, credentials or network I/O."""
import io
from types import SimpleNamespace

import pytest
from flask import Flask
from PIL import Image
from werkzeug.datastructures import MultiDict

import security_hardening
import ssrf_hardening
import upload_hardening


def client_for(installer):
    app = Flask(__name__)
    app.config['TESTING'] = True
    installer(SimpleNamespace(app=app))
    app.add_url_rule('/api/change', 'change', lambda: ('ok', 200), methods=['POST'])
    return app.test_client()


@pytest.mark.parametrize('origin', [
    'http://orcagent.fun', 'https://orcagent.fun:8443', 'null',
    'https://evil.example', 'https://orcagent.fun.evil.example',
    'https://user@orcagent.fun', 'https://orcagent.fun/path',
    'https://orcagent.fun?x=1', 'https://orcagent.fun#x',
    'https://orcagent.fun:bad', 'https://orcagent.fun https://evil.example',
])
def test_cross_origin_mutations_fail_closed(origin):
    client = client_for(security_hardening.install)
    assert client.post('/api/change', base_url='https://orcagent.fun',
                       json={}, headers={'Origin': origin}).status_code == 403


@pytest.mark.parametrize('origin', [
    'https://orcagent.fun', 'https://www.orcagent.fun', 'https://orcagent.fun:443',
])
def test_public_https_origins_still_work(origin):
    client = client_for(security_hardening.install)
    assert client.post('/api/change', base_url='https://orcagent.fun',
                       json={}, headers={'Origin': origin}).status_code == 200


def test_untrusted_host_does_not_authorize_its_origin():
    client = client_for(security_hardening.install)
    assert client.post('/api/change', base_url='https://evil.example',
                       json={}, headers={'Origin': 'https://evil.example'}).status_code == 403


def test_loopback_smoke_tests_and_nonbrowser_requests_still_work():
    client = client_for(security_hardening.install)
    assert client.post('/api/change', base_url='http://127.0.0.1:5000',
                       json={}, headers={'Origin': 'http://127.0.0.1:5000'}).status_code == 200
    assert client.post('/api/change', base_url='https://orcagent.fun', json={}).status_code == 200


def png():
    output = io.BytesIO()
    Image.new('RGB', (1, 1)).save(output, format='PNG')
    return output.getvalue()


@pytest.mark.parametrize('invalid', [b'<svg onload="alert(1)"></svg>', b'not an image'])
def test_second_file_under_same_field_is_validated(monkeypatch, invalid):
    monkeypatch.setattr(upload_hardening, '_nsfw_check', lambda raw: None)
    client = client_for(upload_hardening.install)
    files = MultiDict([
        ('image', (io.BytesIO(png()), 'first.png', 'image/png')),
        ('image', (io.BytesIO(invalid), 'second.png', 'image/png')),
    ])
    assert client.post('/api/change', data=files).status_code == 400


def test_multiple_valid_images_still_work(monkeypatch):
    monkeypatch.setattr(upload_hardening, '_nsfw_check', lambda raw: None)
    client = client_for(upload_hardening.install)
    files = MultiDict([('image', (io.BytesIO(png()), name, 'image/png'))
                       for name in ('a.png', 'b.png')])
    assert client.post('/api/change', data=files).status_code == 200


def test_leading_whitespace_cannot_hide_active_data_uri():
    client = client_for(upload_hardening.install)
    assert client.post('/api/change', json={
        'attachments': ['  data:image/svg+xml;base64,PHN2Zz4=']
    }).status_code == 400


@pytest.mark.parametrize('address', ['100.64.0.1', '100.127.255.254', '::ffff:100.64.0.1'])
def test_shared_address_space_is_not_a_public_ssrf_destination(address):
    assert ssrf_hardening._is_forbidden_ip(address)


@pytest.mark.parametrize('address', ['1.1.1.1', '8.8.8.8', '2606:4700:4700::1111'])
def test_public_api_addresses_still_work(address):
    assert not ssrf_hardening._is_forbidden_ip(address)
