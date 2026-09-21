#!/usr/bin/env python3
"""Configure user-supplied provider credentials and deploy reviewed tip fixes.
Only balance reads validate providers. No keys are displayed or transactions sent.
"""
import datetime
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import requests
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
ENV = Path('/etc/orcagent.env')
DASH = Path('/opt/orcagent/dashboard.py')


def save(path, text, uid, gid, mode):
    fd, tmp = tempfile.mkstemp(prefix='.orca-config-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo; no changes made.')
    subprocess.run([sys.executable, str(ROOT/'deploy/fix-tip-readiness.py')], check=True)
    helius = getpass.getpass('Helius API key (hidden): ').strip()
    jupiter = getpass.getpass('Jupiter API key (hidden): ').strip()
    for key in (helius, jupiter):
        if not key or any(c.isspace() for c in key) or any(c in key for c in '\"\\'):
            raise RuntimeError('Invalid key format; nothing changed.')
    rpc = 'https://mainnet.helius-rpc.com/?' + urlencode({'api-key': helius})
    # Validate the exact RPC operation that currently fails, without writing.
    owner = 'HC5ahspSox3XRmDbzXjXVoAASuY89RcmGUKwp87FRJS5'
    response = requests.post(rpc, json={'jsonrpc':'2.0','id':1,
        'method':'getTokenAccountsByOwner', 'params':[owner,
        {'mint':'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'},
        {'encoding':'jsonParsed','commitment':'confirmed'}]}, timeout=20)
    if response.status_code != 200 or not isinstance(response.json().get('result', {}).get('value'), list):
        raise RuntimeError('Helius token-account check failed; nothing changed.')
    response = requests.get('https://api.jup.ag/ultra/v1/holdings/' + owner,
                            headers={'x-api-key':jupiter}, timeout=20)
    if response.status_code != 200:
        raise RuntimeError('Jupiter API check failed; nothing changed.')
    print('Both provider checks passed. No transaction sent.', flush=True)
    original = ENV.read_text()
    info = ENV.stat()
    values = {'SOLANA_RPC_URL':rpc, 'HELIUS_API_KEY':helius,
              'JUPITER_API_KEY':jupiter, 'ORCAGENT_FRONTS_GAS':'0'}
    lines = [line for line in original.splitlines()
             if line.strip().removeprefix('export ').split('=',1)[0].strip() not in values]
    lines += [name + '=' + value for name,value in values.items()]
    updated = '\n'.join(lines) + '\n'
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ENV.with_name('orcagent.env.before-tip-providers.' + stamp)
    save(backup, original, 0, 0, 0o600)
    original_dash = DASH.read_text()
    dashinfo = DASH.stat()
    old = "print(f'[rpc] PROXY_RPCS: {_PROXY_RPCS}', flush=True)"
    new = "print('[rpc] PROXY_RPCS: ' + ', '.join(_rpc_label(u) for u in _PROXY_RPCS), flush=True)"
    updated_dash = original_dash.replace(old, new)
    try:
        save(ENV, updated, info.st_uid, info.st_gid, info.st_mode & 0o777)
        save(DASH, updated_dash, dashinfo.st_uid, dashinfo.st_gid, dashinfo.st_mode & 0o777)
        subprocess.run([sys.executable, str(ROOT/'deploy/fix-tip-readiness.py'), '--apply'], check=True)
    except Exception:
        save(ENV, original, info.st_uid, info.st_gid, info.st_mode & 0o777)
        save(DASH, original_dash, dashinfo.st_uid, dashinfo.st_gid, dashinfo.st_mode & 0o777)
        subprocess.run(['systemctl','restart','orcagent'], timeout=45)
        raise
    print('Provider configuration saved. Platform gas sponsorship remains OFF.')
    print('Run the read-only tip diagnosis next to check available gas quotes.')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never output exception details containing credential-bearing URLs.
        print('Setup stopped:', type(exc).__name__, 'No credentials displayed.')
        sys.exit(1)
