# Runnable on its own, like every other test here: these import modules from
# the repository root, and `python3 tests/x.py` puts tests/ on the path and
# not the root. Without this the file fails with ModuleNotFoundError and
# reads as a broken test rather than a missing PYTHONPATH.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from ssrf_hardening import validate_outbound_url


def blocked(url):
    try:
        validate_outbound_url(url)
        return False
    except ValueError:
        return True

assert blocked('http://127.0.0.1/admin')
assert blocked('http://10.0.0.1/')
assert blocked('http://169.254.169.254/latest/meta-data/')
assert blocked('http://[::1]/')
assert blocked('http://user:pass@8.8.8.8/')
assert blocked('file:///etc/passwd')
validate_outbound_url('https://8.8.8.8/')
print('SSRF destination validation: PASS')
