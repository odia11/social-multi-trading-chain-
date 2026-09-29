"""RPC API keys never reach the server log.

The [wallet-tokens] lines printed the full Helius URL, api-key included,
on every portfolio load and every RPC error. They now print the provider
label, and error text that quotes a URL has its api-key / token masked.
"""
import os, re, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0'})
import dashboard as d  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

src = open(os.path.join(os.path.dirname(__file__), '..', 'dashboard.py')).read()
check('no log line prints a raw RPC URL', not re.search(r"print\(f?['\"][^\n]*rpc=\{_rpc_url\}", src))
check('wallet-tokens logs the provider label', "rpc={_rpc_label(_rpc_url)}" in src)
check('Helius / Alchemy URLs become a label', d._rpc_label('https://mainnet.helius-rpc.com/?api-key=SECRET123') == 'Helius'
      and d._rpc_label('https://solana-mainnet.g.alchemy.com/v2/abc?token=SECRET') == 'Alchemy')
err = "HTTPSConnectionPool(host='mainnet.helius-rpc.com'): Max retries exceeded with url: /?api-key=612cf7a6-78cd&x=1 (Caused by ...)"
out = d._scrub_url_secrets(err)
check('an error quoting the URL has its api-key masked', '612cf7a6' not in out and 'api-key=***&x=1' in out)
check('token= values are masked too', d._scrub_url_secrets('https://x/?token=abc123') == 'https://x/?token=***')
raise SystemExit(0 if all(checks) else 1)
