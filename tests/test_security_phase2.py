"""Static regression checks for the production security hardening adapters.

These checks intentionally avoid importing the full app so they can run in CI without
real chain credentials. They assert that the fail-closed boundaries stay installed.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding='utf-8')

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

entry = read('app_entry.py')
canonical = read('canonical_domain.py')
replay = read('auth_replay_hardening.py')
ssrf = read('ssrf_hardening.py')
upload = read('upload_hardening.py')
privacy = read('response_privacy_hardening.py')
audit = read('audit_hardening.py')
backup = read('backup_scheduler.py')
owner = read('owner_money_hardening.py')
rate = read('abuse_rate_hardening.py')
sec = read('security_hardening.py')
secret = read('secret_hygiene.py')
monitor = read('security_monitoring.py')

for module in ('canonical_domain','auth_replay_hardening','ssrf_hardening','secret_hygiene','owner_money_hardening',
               'abuse_rate_hardening','upload_hardening','response_privacy_hardening','audit_hardening',
               'security_monitoring','backup_scheduler'):
    check(f'{module} is installed by app_entry', f'from {module} import install' in entry)

check('untrusted Host headers are rejected',
      '_ALLOWED_HOSTS' in canonical and 'abort(400)' in canonical and 'request.host' in canonical)
check('canonical www host is redirected without changing mutation method',
      '_ALIAS_HOSTS' in canonical and 'code=308' in canonical)
check('loopback host remains allowed for server health checks',
      '127.0.0.1' in canonical and 'localhost' in canonical)
check('login nonce is single-use with an atomic unique claim',
      'BEGIN IMMEDIATE' in replay and 'auth_nonce_claims' in replay and 'IntegrityError' in replay)
check('login nonce expires quickly', '_NONCE_TTL_SECONDS = 600' in replay)
check('SSRF guard runs on every requests send, including redirects',
      'Session.send' in ssrf and 'getaddrinfo' in ssrf and 'is_private' in ssrf and 'is_link_local' in ssrf)
check('SSRF rejects embedded URL credentials', 'parsed.username or parsed.password' in ssrf)
check('image validation is bytes-based and rejects unsupported formats',
      '_validate_image_bytes' in upload and "{'JPEG', 'PNG', 'GIF', 'WEBP'}" in upload and 'im.verify()' in upload)
check('image dimensions/pixels/frames are bounded',
      '_MAX_PIXELS' in upload and '_MAX_EDGE' in upload and '_MAX_GIF_FRAMES' in upload)
check('upload JSON walk never silently skips tail items',
      'for v in obj:' in upload and 'obj[:50]' not in upload)
check('over-complex upload JSON is rejected fail-closed',
      '_MAX_WALK_NODES' in upload and '_MAX_NESTING' in upload and 'Upload payload is too complex' in upload)
check('API privacy filter strips private-key and token-hash fields',
      'encrypted_private_key' in privacy and 'token_hash' in privacy and '_clean(' in privacy)
check('API privacy filter covers mnemonic, API key and secret schema variants',
      "'mnemonic'" in privacy and "'api_key'" in privacy and "low.endswith('_secret')" in privacy)
check('API privacy filter fails closed on sanitizer error',
      '_replace_with_blocked' in privacy and 'Response blocked by privacy guard' in privacy
      and 'return _replace_with_blocked(response)' in privacy)
check('redacted API responses are non-cacheable', "response.headers['Cache-Control'] = 'no-store'" in privacy)
check('sensitive mutations are audit logged without raw bodies',
      'security_audit_log' in audit and 'request.get_json' in audit and 'private_key' not in audit)
check('audit IP is HMAC hashed rather than stored raw', 'hmac.new' in audit and 'ip_hash' in audit)
check('audit attribution validates the nginx-supplied client IP',
      '_trusted_client_ip' in audit and 'ipaddress.ip_address' in audit and 'X-Real-IP' in audit)
check('money-moving admin mutations require OWNER_WALLET',
      'OWNER_WALLET' in owner and 'collect-fees' in owner and 'Owner wallet required' in owner)
check('high-risk actions have category abuse ceilings',
      'sec:auth:' in rate and 'sec:withdraw:' in rate and 'sec:bridge:' in rate and 'sec:trade:' in rate)
check('abuse ceilings use validated trusted client IP',
      '_trusted_client_ip' in rate and 'ipaddress.ip_address' in rate and 'X-Real-IP' in rate)
check('production secrets are rejected when weak/default',
      '_bad_secret' in secret and 'len(raw) < minimum' in secret and 'RuntimeError' in secret)
check('daily backup is encrypted and restore-verified',
      'aes-256-cbc' in backup and 'integrity_check' in backup and 'restore verification' in backup)
check('daily backup is cross-worker locked and retained', 'flock' in backup and 'backups[14:]' in backup)
check('CSP script elements are nonce gated',
      'script-src-elem' in sec and "'nonce-{nonce}'" in sec and '_SCRIPT_TAG_RE' in sec)
check('legacy handlers are isolated to script-src-attr instead of all scripts',
      "script-src-attr 'unsafe-inline'" in sec and "script-src 'self' https://unpkg.com" in sec)
check('security anomalies are surfaced in logs', 'SECURITY_ANOMALY' in monitor and '401' in monitor and '429' in monitor)
check('security anomaly attribution uses validated trusted client IP',
      '_trusted_client_ip' in monitor and 'ipaddress.ip_address' in monitor and 'X-Real-IP' in monitor)
check('security anomaly log path strips control characters', "ch >= ' '" in monitor and "ch != '\\x7f'" in monitor)

passed = sum(ok for _, ok in checks)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
