"""Regression checks for the server-owned remembered-login cookie.

The JSON/localStorage token remains for old browsers, but it must not be the
only recovery path: Safari may evict that storage while retaining cookies.
"""
import ast
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, 'dashboard.py'), encoding='utf-8').read()
JS = open(os.path.join(REPO, 'static', 'dashboard.js'), encoding='utf-8').read()
TREE = ast.parse(SRC)


def fn(name):
    node = next(n for n in ast.walk(TREE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(SRC, node) or ''


def check(message, condition):
    assert condition, message
    print('PASS ' + message)


setter = fn('_set_device_cookie')
clearer = fn('_clear_device_cookie')
resume = fn('api_session_resume')
logout = fn('logout')

check('remembered-login cookie is HttpOnly', 'httponly=True' in setter)
check('remembered-login cookie is Secure in production', "SESSION_COOKIE_SECURE" in setter)
check('remembered-login cookie lasts as long as the 10-year device login',
      'DEVICE_TOKEN_DAYS * 86400' in setter)
check('resume accepts the cookie when localStorage has no token',
      'request.cookies.get(DEVICE_COOKIE_NAME' in resume)
check('successful resume refreshes the remembered-login cookie',
      '_set_device_cookie(response, new_token)' in resume)
check('explicit logout is the route that clears the cookie',
      '_clear_device_cookie(' in logout and 'session.clear()' in logout)
check('a missing localStorage token still makes the resume request',
      "async function _resumeFromDeviceToken(){\n  var t = _deviceToken();\n  if(!t) return '';" not in JS)
check('a cookie-only 401 cannot delete an unrelated localStorage credential',
      "if(t && res.status === 401" in JS)

print('\n8/8 checks passed')
