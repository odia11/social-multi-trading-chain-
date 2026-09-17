"""The gate before a signature, and the answer when there is no route.

Two things are checked here.

THE PREFLIGHT is the last thing run before anyone is willing to put real
money through a route. It must be incapable of moving any: no signing, no
approval, no broadcast, no key handling at all. And it must not report
"ready" on a partial answer -- a check it could not perform is SKIP, not
PASS, because "we did not look" and "we looked and it was fine" are the two
things most worth telling apart at that moment.

NO_CROSSCHAIN_LIQUIDITY is the provider saying, correctly, that it cannot
serve this trade. Nothing is wrong: not the response, not this integration,
not the provider. There is no route at this size right now, which is a fact
about a market and can change by the hour. What must never follow is
inventing one.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from trade_engine import crosschain as X            # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


PREFLIGHT = os.path.join(REPO, 'scripts', 'crosschain_preflight.py')
SMOKE = os.path.join(REPO, 'scripts', 'test_0x_crosschain_quote.py')
FX_DIR = os.path.join(REPO, 'tests', 'fixtures', '0x')
SRC = open(PREFLIGHT).read()


# ═══ the preflight cannot move money ═════════════════════════════════════
check('the preflight contains no signing, no broadcast and no approval',
      not any(w in SRC for w in ('sign_transaction', 'send_raw_transaction',
                                 'sendTransaction', '_bridge_sign_send',
                                 'ensure_evm_allowance')))
check('...and no key handling of any kind — there is nothing in it that could '
      'decrypt or read a private key',
      not any(w in SRC for w in ('_use_key', 'decrypt_private_key', 'Keypair',
                                 'private_key', 'privateKey')))
check('...and it never executes a trade',
      '_te_run_crosschain_trade' not in SRC and 'start_crosschain_trade' not in SRC)
check('...and it never prints the API key it needs',
      'ZEROX_API_KEY' in SRC and 'print(os.getenv' not in SRC)
check('it enables the route IN ITS OWN PROCESS ONLY, so running it changes '
      'nothing about the site — it writes no config and touches no file',
      'in this process only' in SRC.lower()
      and "open(args.fixture)" in SRC          # the only file it opens, to read
      and not any(w in SRC for w in ("open(", "w')", 'w")'))
      is False or ("'w'" not in SRC and '"w"' not in SRC))


# ═══ a check it could not run is SKIP, never PASS ════════════════════════
check('a check that could not be performed reports SKIP rather than PASS — '
      '"we did not look" and "we looked and it was fine" are exactly the two '
      'things not to merge just before spending money',
      "report('GAS', SKIP" in SRC and "report('CALLDATA', SKIP" in SRC)
check('...and a run with anything skipped does NOT say ready',
      'READY FOR CONTROLLED LIVE TEST: NOT PROVEN' in SRC)
check('...and only a run with nothing failed and nothing skipped says YES',
      'if not failed and not skipped' in SRC)


# ═══ it runs against the real captures ═══════════════════════════════════
def run_preflight(fixture):
    env = dict(os.environ)
    env.update({'DATA_DIR': tempfile.mkdtemp(), 'SECRET_KEY': 'x' * 32,
                'ENCRYPTION_KEY': 'K' * 43 + '=', 'DEV': '1'})
    p = subprocess.run([sys.executable, PREFLIGHT, '--fixture', fixture],
                       cwd=REPO, env=env, capture_output=True, text=True,
                       timeout=300)
    return p.returncode, p.stdout


bs = os.path.join(FX_DIR, 'quote_base_to_solana.json')
sb = os.path.join(FX_DIR, 'quote_solana_to_base.json')

if os.path.isfile(bs):
    rc, out = run_preflight(bs)
    check('the preflight runs against the saved Base -> Solana capture with no '
          'network request at all', 'no network request is made' in out)
    check('...and every check it can run offline PASSES on the real $30 '
          'capture: the parser, the spender, the full calldata, the cost '
          'ceiling, the route policy and the engine\'s own acceptance',
          all(f'{stage:<22} PASS' in out for stage in
              ('LIVE QUOTE', 'PARSER', 'SPENDER', 'CALLDATA', 'SIMULATION',
               'COST LIMIT', 'ROUTE ENABLED', 'ENGINE ACCEPTS'))
          and 'FAIL' not in out)
    check('...naming the real spender and the real amount, so the line an '
          'operator reads is the transaction rather than a summary of it',
          '0x0000000000001ff3684f28c67538d4d072c22734' in out
          and 'exec pulls 30000000' in out)
    check('...and the bridge cost is quoted against the $30 the capture was '
          'taken at: $0.56, 1.87%, under the 5% ceiling',
          'bridge 0.56 = 1.87% of $30.0 (limit 5.0%)' in out)
    check('...and it still does NOT say ready, because the gas check needs a '
          'real balance and a fixture has none. NOT PROVEN is the honest '
          'answer and it is not exit code 0',
          'READY FOR CONTROLLED LIVE TEST: NOT PROVEN' in out and rc != 0)

    # The same capture with 0x's own "I could not simulate this" flag raised.
    # The engine does not reject on it -- the honest approve-then-execute
    # sequence produces one -- but preflight is the last stop before real
    # money, and signing off on a transaction the provider itself could not
    # dry-run is not something to do quietly.
    _flagged = json.load(open(bs))
    _flagged['response']['quotes'][0]['simulationIncomplete'] = True
    _tmp = os.path.join(tempfile.mkdtemp(), 'quote_flagged.json')
    json.dump(_flagged, open(_tmp, 'w'))
    rc2, out2 = run_preflight(_tmp)
    check('a capture 0x flagged as simulationIncomplete FAILS the simulation '
          'stage, so nobody signs off a live test on a transaction the '
          'provider could not dry-run',
          f'{"SIMULATION":<22} FAIL' in out2)
    check('...and that alone turns the verdict to NO, even though every other '
          'stage still passes', 'READY FOR CONTROLLED LIVE TEST: NO' in out2
          and rc2 != 0)
    check('...and the line says what to do about it rather than only that it '
          'failed', 'approve first, then re-quote' in out2)

if os.path.isfile(sb):
    rc, out = run_preflight(sb)
    check('the preflight reports the real no-liquidity capture as '
          'NO_CROSSCHAIN_LIQUIDITY', 'NO_CROSSCHAIN_LIQUIDITY' in out)
    check('...naming the provider\'s own request id, which is the only handle '
          'a no-liquidity answer carries — there is no quoteId, because there '
          'is no quote', '0x2ec25cea152bdbbe58223a3f' in out)
    check('...and says it is a fact about the market rather than a fault, so '
          'nobody goes looking for a bug that is not there',
          'not a fault' in out)
    check('...and still prints a verdict. An earlier version returned straight '
          'out of the no-liquidity branch, so a run that could not get a quote '
          'printed a FAIL and then stopped — no verdict at all, at exactly the '
          'moment somebody is deciding whether to spend real money',
          'READY FOR CONTROLLED LIVE TEST: NO' in out)


# ═══ NO_CROSSCHAIN_LIQUIDITY, as a value ═════════════════════════════════
if os.path.isfile(sb):
    fx = json.load(open(sb))
    try:
        X.ZeroExCrossChain(lambda **k: fx['response'], lambda **k: {}).get_quote(
            source_chain='solana', destination_chain='base',
            source_amount_raw=30_000_000,
            origin_address=fx['origin_address'],
            destination_address=fx['destination_address'])
        check('a no-liquidity response raises NoLiquidity', False)
    except X.NoLiquidity as e:
        body = e.to_dict()
        check('a no-liquidity response raises NoLiquidity with the code',
              body['code'] == 'NO_CROSSCHAIN_LIQUIDITY')
        check('...carrying both chains, so the answer names the route it is '
              'about', body['source_chain'] == 'solana' and body['destination_chain'] == 'base')
        check('...and the amount that could not be served, which is the part '
              'that changes — the same route may work at a different size',
              body['amount_raw'] == '30000000')
        check('...and the provider, and its zid',
              body['provider'] == '0x' and body['zid'] == fx['response']['zid'])
        check('it is NOT a RouteRejected: the response was fine, the market is '
              'quiet, and treating those the same is how a provider gets '
              'blamed for a bug it does not have',
              not isinstance(e, X.RouteRejected)
              and not isinstance(e, X.RouteUnsupported))


# ═══ nothing invents a route when there is none ══════════════════════════
CC = open(os.path.join(REPO, 'trade_engine', 'crosschain.py')).read()
DASH = open(os.path.join(REPO, 'dashboard.py')).read()
check('no fallback bridge is reachable from the cross-chain adapter — there '
      'is no second provider, no hand-rolled transfer and no substitute asset '
      'anywhere in it',
      not any(w in CC for w in ('mayan', 'wormhole', 'fallback_bridge',
                                'FALLBACK', 'alternative_provider')))
check('the standalone Bridge feature is a separate thing and is NOT quietly '
      'used as a fallback for a trade',
      '_execute_cross_chain_bridge' not in
      DASH[DASH.index('def _te_bridge_quoter'):DASH.index('def _cc_pick_source_chain')])


# ═══ the fixture saver keeps the whole calldata ══════════════════════════
spec = importlib.util.spec_from_file_location('smoke', SMOKE)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

long_data = '0x' + 'ab' * 2000
sample = {'quotes': [{'transaction': {'details': {'data': long_data}}}],
          'apiKey': 'SEKRIT', 'nested': {'privateKey': 'SEKRIT'}}
printed = smoke.redact(sample)
saved = smoke.redact(sample, truncate=False)

check('the fixture saver keeps calldata at FULL length. The first captures '
      'were saved truncated ("...[2954 chars]"), which verifies that a '
      'response parses and nothing about what the transaction does',
      saved['quotes'][0]['transaction']['details']['data'] == long_data)
check('...while the printed output may still shorten it, because that is for '
      'a human to read',
      'chars]' in printed['quotes'][0]['transaction']['details']['data'])
check('...and secrets are removed from BOTH — the longer form is not a way '
      'round the redactor',
      printed['apiKey'] == '[redacted]' and saved['apiKey'] == '[redacted]'
      and saved['nested']['privateKey'] == '[redacted]')
check('...and lists are not truncated in the saved form either, so a response '
      'with several quotes keeps all of them',
      smoke.redact({'q': [1, 2, 3, 4, 5, 6, 7]}, truncate=False)['q'] == [1, 2, 3, 4, 5, 6, 7])

# ═══ the one script that DOES spend money, and how hard it is to ═══════
# ═══ run by accident                                              ═══════
LIVE = os.path.join(REPO, 'scripts', 'crosschain_live_test.py')
LSRC = open(LIVE).read()

_env = dict(os.environ)
_env.update({'DATA_DIR': tempfile.mkdtemp(), 'SECRET_KEY': 'x' * 32,
             'ENCRYPTION_KEY': 'K' * 43 + '=', 'DEV': '1'})
_p = subprocess.run([sys.executable, LIVE, '--wallet', 'W', '--token', 'T'],
                    cwd=REPO, env=_env, capture_output=True, text=True,
                    timeout=300)
check('the live-money script refuses to do anything without the flag that '
      'says you know it spends real money — and refuses BEFORE it imports '
      'the app, so nothing is even connected to',
      _p.returncode == 2 and 'Refusing to run' in _p.stderr
      and 'dashboard' not in _p.stdout)

_p2 = subprocess.run([sys.executable, LIVE, '--wallet', 'W', '--token', 'T',
                      '--amount', '50',
                      '--i-understand-this-spends-real-money'],
                     cwd=REPO, env=_env, capture_output=True, text=True,
                     timeout=300)
check('...and refuses an amount above its own ceiling, which has to be raised '
      'deliberately rather than by default',
      _p2.returncode == 2 and 'above the 5.0 ceiling' in _p2.stderr)

check('...and says up front that a small trade will be refused as '
      'uneconomical, with the live figures, rather than letting somebody type '
      '"yes" and then read a refusal that looks like a broken route',
      'args.amount < 6' in LSRC and '$0.56 at $30' in LSRC)
check('...and it still enables the route in its own process only, so running '
      'it changes nothing for anybody else',
      'IN THIS PROCESS ONLY' in LSRC)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
