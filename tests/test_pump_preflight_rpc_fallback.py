"""Deploy preflight: a busy Solana RPC (429) must not block a whole deploy.

The read-only Pump preflight reads one account (Pump's global config) from a
single RPC. The public endpoint answered "429 Too Many Requests" and the
deploy stopped: "PREFLIGHT BLOCKED ... No app restart". It now tries the
trusted RPC, then independent public read endpoints, each with a short
backoff, and still fails closed when none answers. RPC URLs (which can carry
an API key) are never printed.
"""
import os, subprocess, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
ADAPTER = os.path.join(ROOT, 'pump_adapter')
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
src = open(os.path.join(ADAPTER, 'read-only-preflight.cjs'), encoding='utf-8').read()

check('the preflight reads Pump config through the fallback helper',
      'const global=await fetchGlobalFromAnyRpc();' in src and 'sdk.fetchGlobal()' in src)
check('trusted RPC first, then PublicNode, then the official public endpoint',
      "[...new Set([trusted,...FALLBACK_RPCS].filter(Boolean))]" in src
      and "FALLBACK_RPCS=['https://solana-rpc.publicnode.com','https://api.mainnet-beta.solana.com']" in src)
check('busy endpoints are retried with backoff; other errors move on; still fails closed',
      '429|too many requests' in src and 'await sleep(2000*(attempt+1))' in src
      and "throw last||Error('No Solana RPC endpoint answered')" in src)
check('endpoint URLs are never printed', "console.log('RPC '+(index+1)+'/'+endpoints.length" in src
      and 'console.log(url' not in src and "+url+" not in src)

# Run it for real when the pinned Pump runtime is installed: every RPC busy
# must still block (fail closed) without leaking the trusted URL's key.
node = '/opt/orcagent-runtime/node-v%s/bin/node' % open(os.path.join(ADAPTER, '.node-version')).read().strip()
if os.path.exists(node) and os.path.isdir(os.path.join(ADAPTER, 'node_modules')):
    stub = os.path.join(ADAPTER, '_test_preflight_stub.cjs')
    with open(stub, 'w') as f:
        f.write("const sdk=require('@pump-fun/pump-sdk');"
                "sdk.OnlinePumpSdk.prototype.fetchGlobal=async function(){"
                "throw Error('failed to get info about account x: Error: 429 Too Many Requests')};"
                "require('./read-only-preflight.cjs');")
    try:
        env = dict(os.environ, ORCA_LAUNCH_RPC='https://trusted.invalid/?api-key=SECRETKEY123')
        r = subprocess.run(['/bin/bash', os.path.join(ADAPTER, 'run-node.sh'), stub],
                           capture_output=True, text=True, timeout=120, env=env, cwd=ADAPTER)
        out = r.stdout + r.stderr
        check('with every RPC busy it tries all three, then blocks (fail closed)',
              r.returncode != 0 and 'RPC 3/3 busy' in out and 'PREFLIGHT BLOCKED' in out)
        check('the trusted RPC key never appears in the output', 'SECRETKEY123' not in out)
    finally:
        os.remove(stub)
else:
    print('SKIP live run: pinned Pump runtime not installed here')
raise SystemExit(0 if all(checks) else 1)
