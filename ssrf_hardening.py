"""Process-wide SSRF guard for outbound requests.

Every actual requests.Session.send call (including redirect follow-ups) validates the
resolved destination immediately before network I/O. Public HTTP(S) APIs continue to
work; loopback/private/link-local/metadata-style destinations are rejected fail-closed.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


def _is_forbidden_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split('%', 1)[0])
    except ValueError:
        return True
    # IPv4-mapped IPv6 must inherit the IPv4 decision.
    mapped = getattr(ip, 'ipv4_mapped', None)
    if mapped is not None:
        ip = mapped
    return bool(
        not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or
        ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def validate_outbound_url(url: str) -> None:
    try:
        parsed = urlsplit(str(url or ''))
    except Exception as exc:
        raise ValueError('Invalid outbound URL') from exc
    if parsed.scheme.lower() not in {'http', 'https'}:
        raise ValueError('Outbound URL scheme is not allowed')
    if parsed.username or parsed.password:
        raise ValueError('Credentials in outbound URLs are not allowed')
    host = (parsed.hostname or '').strip().lower().rstrip('.')
    if not host or host in {'localhost', 'localhost.localdomain'} or host.endswith('.localhost'):
        raise ValueError('Local network destinations are not allowed')
    try:
        # Numeric hosts need no DNS lookup.
        ipaddress.ip_address(host.split('%', 1)[0])
        addresses = {host}
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == 'https' else 80),
                                       type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError('Outbound hostname could not be resolved') from exc
        addresses = {item[4][0] for item in infos if item and item[4]}
    if not addresses or any(_is_forbidden_ip(addr) for addr in addresses):
        raise ValueError('Local or private network destinations are not allowed')


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_ssrf_hardening_installed', False):
        return
    app._orca_ssrf_hardening_installed = True

    try:
        import requests.sessions
    except Exception as exc:
        app.logger.warning('SSRF requests guard unavailable: %s', exc)
        return

    original_send = requests.sessions.Session.send
    if getattr(original_send, '_orca_ssrf_guard', False):
        return

    def guarded_send(self, request, **kwargs):
        try:
            validate_outbound_url(getattr(request, 'url', ''))
        except ValueError as exc:
            app.logger.warning('SSRF blocked outbound destination: %s', exc)
            raise requests.exceptions.InvalidURL(str(exc))
        return original_send(self, request, **kwargs)

    guarded_send._orca_ssrf_guard = True
    guarded_send._orca_original = original_send
    requests.sessions.Session.send = guarded_send
