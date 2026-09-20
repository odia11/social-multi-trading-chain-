"""Verify discontinued Face ID / passkey and screen lock cannot relaunch."""
import ast
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1]
SERVER = (BASE / 'dashboard.py').read_text()
JS = (BASE / 'static/dashboard.js').read_text()
HTML = (BASE / 'dashboard.html').read_text()
INFO = (BASE / 'templates/info.html').read_text()

class RetiredFeature(unittest.TestCase):
    def test_login_screen_and_settings_no_longer_offer_biometrics(self):
        for obsolete in ('ob-bio-btn', 'pk-banner', 's-faceid-prompt',
                         'st-passkey-settings', 'st-app-lock-row',
                         'oa-app-lock', 'Unlock OrcAgent'):
            self.assertNotIn(obsolete, HTML)
        self.assertIn('id="ob-wallet-btns"', HTML)
        self.assertIn('id="phantom-ob-btn"', HTML)
        self.assertIn('id="solflare-ob-btn"', HTML)

    def test_no_biometrics_or_reopen_lock_in_javascript(self):
        for obsolete in ('navigator.credentials.get(', 'navigator.credentials.create(',
                         '_webAuthnLogin(', '_maybePromptPasskey(',
                         '_appLockShow(', '_appLockLoad(', '_appLockTryAutomatic(',
                         '/api/auth/webauthn/', 'orca_app_lock_'):
            self.assertNotIn(obsolete, JS)
        self.assertIn('_resumeFromDeviceToken()', JS)
        self.assertIn("fetch('/api/session'", JS)
        self.assertIn('function disconnectWallet()', JS)

    def test_authentication_routes_retired_with_legacy_lock_off(self):
        routes=[]
        for node in ast.parse(SERVER).body:
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if (isinstance(decorator,ast.Call)
                        and isinstance(decorator.func,ast.Attribute)
                        and decorator.func.attr=='route' and decorator.args
                        and isinstance(decorator.args[0],ast.Constant)):
                        routes.append(decorator.args[0].value)
        for retired in ('/api/auth/webauthn/login',
                        '/api/auth/webauthn/login/options',
                        '/api/auth/webauthn/register',
                        '/api/auth/webauthn/register/options',
                        '/api/auth/app-lock/unlock'):
            self.assertNotIn(retired,routes)
        self.assertIn('/api/auth/app-lock',routes)
        self.assertIn("'enabled': False, 'has_passkey': False",SERVER)
        self.assertIn('/api/session/remember',SERVER)
        self.assertNotIn('Optional Face ID / WebAuthn login',INFO)

if __name__ == '__main__':
    unittest.main()
