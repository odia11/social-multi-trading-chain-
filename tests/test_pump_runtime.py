"""Runtime regression tests; offline, never signs a wallet or submits RPC."""
import json
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ADAPTER=ROOT/'pump_adapter'
ENV=dict(os.environ,PATH='/usr/bin:/bin',
         NODE_OPTIONS='--this-option-must-be-removed',NODE_PATH='/nonexistent')
NODE=os.environ.get('ORCAGENT_PUMP_NODE','/opt/orcagent-runtime/node-v22.23.2/bin/node')
ENV['ORCAGENT_PUMP_NODE']=NODE

def run(*args, data=None, env=None):
    return subprocess.run(['/bin/bash',str(ADAPTER/'run-node.sh'),*args],
        input=json.dumps(data) if data is not None else None,
        cwd=ADAPTER,env=env or ENV,text=True,capture_output=True,timeout=20)

def test_runtime():
    r=run('-p','process.versions.node')
    assert r.returncode==0,r.stderr
    assert r.stdout.strip()=='22.23.2'
    r=run('npm','--version')
    assert r.returncode==0,r.stderr
    assert r.stdout.strip()=='10.9.8'
    r=run('-e',"const s=require('@pump-fun/pump-sdk');if(!s.PUMP_SDK)process.exit(1)")
    assert r.returncode==0,r.stderr
    r=run('--version',env=dict(ENV,ORCAGENT_PUMP_NODE='/missing/node'))
    assert r.returncode!=0 and 'runtime missing' in r.stderr
    print('PASS Node/npm/SDK ignore old PATH and injected NODE_OPTIONS; missing runtime fails closed')
    mint='11111111111111111111111111111111'
    r=run('check-sharing.cjs',data={'action':'address','mint':mint})
    assert r.returncode==0,r.stderr
    assert json.loads(r.stdout)['address']
    # Invalid public wallet is rejected after the REAL SDK loads, before any RPC.
    r=run('build-reward-claim.cjs',data={'wallet':'invalid'})
    assert r.returncode!=0 and ('Invalid public key' in r.stderr or 'Non-base58 character' in r.stderr),r.stderr
    print('PASS sharing and reward entrypoints load the real SDK on pinned runtime')
    old=Path('/usr/bin/node')
    if old.exists():
        version=subprocess.check_output([str(old),'--version'],text=True).strip()
        if version!='v22.23.2':
            for name in ['build-launch.cjs','build-reward-claim.cjs','check-sharing.cjs','read-only-preflight.cjs']:
                r=subprocess.run([str(old),str(ADAPTER/name)],input='{}',
                    text=True,capture_output=True,timeout=10)
                assert r.returncode!=0 and 'Pump requires pinned Node' in r.stderr,(name,r.stderr)
                assert 'ERR_REQUIRE_ESM' not in r.stderr
            print('PASS incompatible system Node rejected before SDK loading for every entrypoint')

if __name__=='__main__':
    test_runtime()
