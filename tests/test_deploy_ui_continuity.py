"""Deploy continuity contract: deployments must not visibly break the app shell."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERF = (ROOT / 'app_performance.py').read_text(encoding='utf-8')
NAV = (ROOT / 'static' / 'navbar.js').read_text(encoding='utf-8')
INSTALL = (ROOT / 'deploy' / 'install.sh').read_text(encoding='utf-8')
UPDATE = (ROOT / 'deploy' / 'update.sh').read_text(encoding='utf-8')
SERVICE = (ROOT / 'deploy' / 'orcagent.service').read_text(encoding='utf-8')
SMOKE = (ROOT / 'deploy' / 'security-smoke.sh').read_text(encoding='utf-8')

checks = {
    'HTML static assets are versioned by the current deploy hash':
        "oa-app-version" in PERF and "m.group(1) + '?v=' + version" in PERF,
    'avatar continuity uses a per-account non-identifying cache key':
        'oa-user-cache-key' in PERF and 'hashlib.sha256' in PERF,
    'navbar restores the last confirmed avatar before /api/me finishes':
        'restoreNavIdentity();' in NAV and 'rememberNavIdentity(d)' in NAV,
    'dynamic shell assets inherit the deploy version':
        'function deployAsset(url)' in NAV and "u.searchParams.set('v',_OA_ASSET_VERSION)" in NAV,
    'transient deploy errors retry only idempotent same-origin reads':
        "DEPLOY_RETRY_DELAYS" in NAV
        and "(method==='GET'||method==='HEAD')&&sameOrigin(input)" in NAV
        and "resp.status===502||resp.status===503||resp.status===504" in NAV,
    'active PWA navigation waits through the backend restart without caching HTML':
        "if(req.mode==='navigate')" in (ROOT / 'static' / 'sw.js').read_text(encoding='utf-8')
        and 'oaFetchThroughDeploy(req,0)' in (ROOT / 'static' / 'sw.js').read_text(encoding='utf-8'),
    'mutations are never replayed by the deploy retry shield':
        "method!=='GET'&&method!=='HEAD'" in NAV and 'TRANSACTION_FETCH_TIMEOUT_MS' in NAV,
    'slow install work preserves the currently served UI':
        "--exclude '/static'" in INSTALL
        and "--exclude '/templates'" in INSTALL
        and "--exclude '/dashboard.html'" in INSTALL,
    'web assets activate together only at the end of install':
        'Activating web assets for the restart' in INSTALL
        and 'rsync -a --delete-delay --delay-updates "$REPO_DIR/static/" "$APP_DIR/static/"' in INSTALL,
    'production service uses the proven loopback bind':
        '--bind 127.0.0.1:8080' in SERVICE and '--bind fd://3' not in SERVICE,
    'a stale handoff socket is retired before restart':
        'systemctl stop orcagent.socket' in UPDATE
        and 'systemctl restart orcagent' in UPDATE,
    'security smoke validates direct loopback binding':
        '--bind 127\\.0\\.0\\.1:8080' in SMOKE,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(('PASS ' if ok else 'FAIL ') + name)
raise SystemExit(1 if failed else 0)
