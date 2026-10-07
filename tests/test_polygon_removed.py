"""Polygon is no longer an OrcAgent chain (the owner's call: nobody trades it).

Its public RPC kept timing out / answering 529, which failed every deploy's
runtime check and could fail a real Polygon trade. The chain is removed from
trading, discovery, balances, deposits/withdrawals and the copy; labels and
explorer links stay so past Polygon trades still display. A Polygon position
left in the bot is skipped instead of retried every second: its tokens stay
in the user's own wallet (reachable with the revealed key).
"""
import os, sys
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()
from trade_engine.registry import CHAINS  # noqa: E402

src = read('dashboard.py')
evm = src[src.index('EVM_CHAINS = {'):src.index('EVM_CHAIN_FEE_WALLET')]
check('no Polygon entry in EVM_CHAINS, so the deploy check, bridge, balances and trade routes skip it',
      "'polygon'" not in evm and 'POLYGON_RPC_URL' not in src)
check('the trade engine registry has no Polygon chain', 'polygon' not in CHAINS)
# Since Polygon went, every EVM chain went (Solana-only): the lists below
# are now Solana alone / empty.
check('Live Market discovery, call lookups and GeckoTerminal charts skip Polygon',
      "_MARKET_LIVE_CHAINS = {'solana'}" in src
      and "_CALL_LOOKUP_EVM_CHAINS = ()" in src
      and "'polygon': 'polygon_pos'" not in src and "'polygon': 'polygon'," not in src)
check('header balance and pooled buying power no longer read Polygon',
      "_CHAINS = ()" in read('header_stable_balance.py')
      and "'polygon'" not in read('live_market_pooled_buy_balance.py'))
check('Live Market and the navbar no longer trade or list Polygon',
      'polygon:1' not in read('static', 'live-market-pro.js')
      and "'polygon'" not in read('static', 'navbar.js').split('_NB_LIVE_CHAINS=')[1].split(';')[0])
wallet = read('templates', 'wallet.html')
check('the wallet page offers no Polygon send, convert, bridge or filter option',
      'value="polygon"' not in wallet and "{v:'polygon'" not in wallet
      and 'Polygon' not in read('templates', 'info.html') and 'POLYGON' not in read('deploy', 'env.example'))
guard = src[src.index('def _chain_tradeable'):src.index('def _rpc_candidates')]
check('a chain outside ACTIVE_EVM_CHAINS is not tradeable', "chain == 'solana' or chain in ACTIVE_EVM_CHAINS" in guard)
exit_fn = src[src.index('def _bot_execute_exit'):]
exit_fn = exit_fn[:exit_fn.index('enc_blob = enc_blob_solana')]
check('the bot never tries to sell a leftover Polygon position (no retry every second)',
      'if not _chain_tradeable(chain):' in exit_fn
      and "continue  # chain removed from OrcAgent (Polygon) -- nothing to sell it through" in src
      and src.count("_chain_tradeable(p.get('chain', 'solana'))}") >= 2)
raise SystemExit(0 if all(checks) else 1)
