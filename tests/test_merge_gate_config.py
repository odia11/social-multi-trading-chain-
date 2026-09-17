from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / '.github/workflows/security-scan.yml').read_text()
dashboard = (ROOT / 'dashboard.py').read_text()
env_example = (ROOT / 'deploy/env.example').read_text()

checks = []

def check(name, ok):
    checks.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name)

check('security workflow runs for pull requests targeting main',
      'pull_request:' in workflow and 'branches: [main, dev]' in workflow)
check('security workflow has an explicit timeout', 'timeout-minutes:' in workflow)
check('cross-chain engine is off by default in application code',
      "os.getenv('TRADE_ENGINE_CROSSCHAIN', '0')" in dashboard)
check('cross-chain route allowlist is empty by default in application code',
      "os.getenv('CROSSCHAIN_ROUTES', '')" in dashboard)
check('deployment example documents cross-chain as off by default',
      '# TRADE_ENGINE_CROSSCHAIN=0' in env_example)
check('deployment example documents an empty route allowlist by default',
      '# CROSSCHAIN_ROUTES=' in env_example)

raise SystemExit(0 if all(ok for _, ok in checks) else 1)
