#!/usr/bin/env python3
"""Deploy only the tested source-account fix, preserving other live code.

Run without arguments to validate; use --apply as root to install and restart.
Restores the original module if restart/health verification fails.
"""
import ast
import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

repo = Path(__file__).resolve().parents[1]
live = Path('/opt/orcagent/portfolio_token_withdraw.py')
source = (repo / 'portfolio_token_withdraw.py').read_text()
helper_node = next(n for n in ast.parse(source).body
                   if isinstance(n, ast.FunctionDef) and n.name == '_solana_source_accounts')
helper = ast.get_source_segment(source, helper_node)
original = live.read_text()
if 'def _solana_source_accounts(' in original:
    raise SystemExit('Source discovery has already changed in production; inspect before redeploying.')
anchor = 'def _solana_transfer(d, wallet, token_address, to_address, amount):'
old = """    result, url = _rpc_call_any(d, 'getTokenAccountsByOwner', [
        owner_text, {'mint': token_address}, {'encoding':'jsonParsed'}
    ], require_nonempty=True)
    result = result or {}
    accounts = result.get('value') or []
"""
if original.count(anchor) != 1 or original.count(old) != 1:
    raise SystemExit('Production code differs from the reviewed version; no changes made.')
updated = original.replace(anchor, helper + '\n\n\n' + anchor, 1).replace(
    old, '    accounts = _solana_source_accounts(d, owner_text, token_address)\n', 1)
compile(updated, str(live), 'exec')
print('Validated: only source-account discovery will change.', flush=True)
if '--apply' not in sys.argv:
    raise SystemExit(0)
if os.geteuid() != 0:
    raise SystemExit('Deployment requires sudo to update the service-owned file and restart OrcAgent.')
backup_dir = live.parent / 'backups'
backup_dir.mkdir(exist_ok=True)
backup = backup_dir / ('portfolio_token_withdraw.before-source-fix.' +
                       datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.py')
shutil.copy2(live, backup)
metadata = live.stat()
fd, temporary = tempfile.mkstemp(prefix='.tip-source-', suffix='.py', dir=live.parent)
try:
    with os.fdopen(fd, 'w') as stream:
        stream.write(updated)
    os.chmod(temporary, metadata.st_mode & 0o777)
    os.chown(temporary, metadata.st_uid, metadata.st_gid)
    if live.read_text() != original:
        raise RuntimeError('Production changed during deployment; refusing to overwrite it.')
    os.replace(temporary, live)
except Exception:
    if os.path.exists(temporary):
        os.unlink(temporary)
    raise
try:
    subprocess.run(['systemctl', 'restart', 'orcagent'], check=True, timeout=45)
    healthy = False
    for _ in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2) as response:
                healthy = response.status == 200
        except Exception:
            pass
        if healthy:
            break
        time.sleep(1)
    if not healthy:
        raise RuntimeError('Health check did not return HTTP 200')
    subprocess.run(['systemctl', 'is-active', '--quiet', 'orcagent'], check=True)
except Exception:
    shutil.copy2(backup, live)
    os.chown(live, metadata.st_uid, metadata.st_gid)
    subprocess.run(['systemctl', 'restart', 'orcagent'], timeout=45)
    raise
print('DEPLOYED: source-account discovery fixed; service active; health HTTP 200.')
print('Backup:', backup)
