"""Chains researched for a future EVM_CHAINS entry but NOT yet safe to ship.

This module is never imported by app_entry.py or dashboard.py. That is
deliberate: nothing here is live, nothing here is reachable from any route,
and it must stay that way until every "CONFIRM" below is replaced with a
value read from Circle's own docs (not a blog/aggregator summary) and the
providers this app actually depends on for EVM trading -- DexScreener
(token/pair discovery), GeckoTerminal (OHLCV chart history), 0x Protocol
(gasless swap quotes/execution) -- have confirmed support. Copying this
dict into EVM_CHAINS before then means either dead code (dex_chain unknown
to DexScreener returns nothing) or, if the USDC address is wrong, USDC sent
to a contract that silently isn't the real one. Circle's own materials at
launch explicitly listed only a TESTNET USDC address, with mainnet marked
not yet published -- this is why the field below is None rather than a
guess.

WHY THIS CHAIN DOESN'T JUST DROP INTO THE EXISTING SCHEMA
Every EVM_CHAINS entry assumes native gas is a DIFFERENT asset from USDC
(BNB, ETH, POL, ...) -- _ensure_evm_gas, _bootstrap_evm_gas_via_bridge and
the whole gas-sponsorship system exist specifically to keep that separate
token topped up. Arc's whole design point is that there is no separate gas
token: transaction fees are paid directly in USDC. That is a genuine
architectural difference, not a config value -- whoever activates this
should re-read _ensure_evm_gas's own module comment first and decide
whether "native_symbol": "USDC" (native balance == USDC balance) is
actually correct for Arc's RPC responses, or whether the gas-bootstrap
codepath needs to skip this chain entirely (probably the right call: a
chain that is never short of "gas" separately from USDC needs none of that
machinery). Do not assume; check Arc's own RPC eth_getBalance behavior
against a real funded address first.

RESEARCHED (2026-09-16, the day Arc mainnet launched) -- from web search
summaries only, NOT independently verified against developers.circle.com or
docs.arc.network (both were unreachable from this environment's egress
proxy at research time):
    chain_id: 5042            (testnet was reported as 5042002)
    rpc_url:  https://rpc.mainnet.arc.io
    explorer: unknown -- not found in the sources checked

STILL UNKNOWN / MUST CONFIRM BEFORE ACTIVATING:
    - the mainnet USDC contract address (see note above -- this is the one
      that actually matters and the one most likely to be wrong if guessed)
    - whether DexScreener has indexed any Arc pool yet (`dex_chain` below)
    - whether GeckoTerminal has an Arc network slug for chart history
    - whether 0x Protocol's Cross-Chain/swap API supports Arc
      (`zerox_chain_id` below)
    - the real block explorer URL
    - how "native gas" reads on this chain (see the architecture note above)

ACTIVATION STEPS, once every value above is confirmed from a primary source:
    1. Move this entry into dashboard.py's EVM_CHAINS dict.
    2. Resolve the gas-token question above -- do not skip it.
    3. Bump every cache-busted asset that renders a hardcoded chain list
       (grep templates/*.html and static/*.js for another chain's slug,
       e.g. 'robinhood', to find them all -- the six-chain badge/dropdown/
       filter lists are not generated from EVM_CHAINS everywhere).
    4. Add the new chain to test_all_chain_reverse_bridge_sources.py and
       any other test that currently hardcodes the chain list.
"""

ARC_PENDING = {
    'chain_id':      5042,   # CONFIRM against developers.circle.com -- reported, not verified
    'native_symbol': None,   # CONFIRM -- see the architecture note above before setting this to 'USDC'
    'usdc_symbol':   'USDC',
    'rpc_url':       'https://rpc.mainnet.arc.io',  # CONFIRM -- reported, not verified
    'usdc':          None,   # CONFIRM -- mainnet address was not published anywhere checked; do not guess
    'explorer':      None,   # CONFIRM
    'dex_chain':     None,   # CONFIRM DexScreener's slug for Arc once/if it indexes a pool
    'zerox_chain_id': None,  # CONFIRM 0x Protocol supports this chain at all before setting
}
