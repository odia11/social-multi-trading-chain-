"""Offline resource bounds and strict mint suffix tests. No chain writes."""
import base64
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import json
from solders.keypair import Keypair

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'pump_adapter/grind-mint.py'
def test_bounds():
    # Two creators may search at once (two slot locks); a third fails fast.
    locks=[]
    try:
        for slot in range(2):
            lock=(Path(tempfile.gettempdir())/('orcagent-mint-%d-%d.lock' % (os.getuid(), slot))).open('a')
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            locks.append(lock)
        r=subprocess.run([sys.executable,str(SCRIPT)],capture_output=True,text=True,timeout=3)
        assert r.returncode==1 and r.stdout==''
        assert 'retry shortly' in r.stderr
    finally:
        for lock in locks:
            lock.close()
    code="import runpy; m=runpy.run_path("+repr(str(SCRIPT))+"); m['generate'](timeout=0)"
    r=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=3)
    assert r.returncode!=0 and r.stdout=='' and 'took too long' in r.stderr
    key=Keypair()
    while str(key.pubkey()).endswith('orc'):key=Keypair()
    data={'wallet':str(Keypair().pubkey()),'quote_asset':'USDC',
          'mint_secret':base64.b64encode(bytes(key)).decode()}
    r=subprocess.run(['/bin/bash',str(ROOT/'pump_adapter/run-node.sh'),
        str(ROOT/'pump_adapter/build-launch.cjs')],input=json.dumps(data),
        capture_output=True,text=True,timeout=5)
    assert r.returncode!=0 and r.stdout=='' and 'Mint must end in orc' in r.stderr
    assert data['mint_secret'] not in r.stderr
    print('PASS concurrent grinding rejected, search deadline enforced, wrong suffix rejected, no secret in errors')

if __name__=='__main__':
    test_bounds()
