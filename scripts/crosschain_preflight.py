#!/usr/bin/env python3
"""Everything that can be checked before a signature. Nothing that needs one.

This is the gate between "the code looks right" and "we are willing to put
real money through it". It asks 0x for a live quote and then runs that answer
through every check the engine would run before signing -- the parser, the
spender rules, the calldata, the gas requirement, the cost ceiling and the
route policy -- and prints a line per stage.

WHAT IT CANNOT DO, BY CONSTRUCTION
It does not sign, send, approve, or move anything. It does not read, decrypt
or touch a private key: there is no key handling in this file at all. The only
credential it uses is ZEROX_API_KEY, and it never prints it.

    python3 scripts/crosschain_preflight.py --amount 10
    python3 scripts/crosschain_preflight.py --amount 10 --wallet <session wallet>

Without --wallet it quotes for 0x's own published example addresses and skips
the two checks that need a real balance (gas, and the source USDC). With
--wallet it uses that account's real addresses and balances, still read-only.

Exit code 0 means every check passed and the route is ready for ONE controlled
live test. Anything else means read the output -- it says which stage failed
and why.
"""
import argparse
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXAMPLE_EVM = '0xABf40AADf960e20B4283dc5A06387A429Ba02456'
EXAMPLE_SVM = '9FzTJNUfMVSPPNEsUDfUHuE1gSE7uDBamcGHq1CseUUZ'

PASS, FAIL, SKIP = 'PASS', 'FAIL', 'SKIP'
_results = []


def verdict() -> int:
    """Print the one line an operator is actually looking for, and exit.

    Called from EVERY exit path, including the early ones. An earlier version
    returned straight out of the no-liquidity branch, so a run that could not
    get a quote printed a FAIL and then simply stopped -- no verdict at all,
    at exactly the moment somebody is deciding whether to spend real money.
    """
    failed = [s for s, st in _results if st == FAIL]
    skipped = [s for s, st in _results if st == SKIP]
    print()
    print('=' * 68)
    if failed:
        print(f'  READY FOR CONTROLLED LIVE TEST: NO   (failed: {", ".join(failed)})')
    elif skipped:
        print('  READY FOR CONTROLLED LIVE TEST: NOT PROVEN')
        print(f'  ({", ".join(skipped)} skipped — re-run with --wallet to check '
              f'a real balance)')
    else:
        print('  READY FOR CONTROLLED LIVE TEST: YES')
    print('=' * 68)
    print('  Nothing was signed, sent, approved or spent.')
    print()
    return 0 if not failed and not skipped else 1


def report(stage, status, detail=''):
    _results.append((stage, status))
    mark = {PASS: 'PASS', FAIL: 'FAIL', SKIP: 'SKIP'}[status]
    print(f'  {stage:<22} {mark}' + (f'   {detail}' if detail else ''))
    return status == PASS


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', default='base')
    ap.add_argument('--dest', default='solana')
    ap.add_argument('--amount', type=float, default=10.0,
                    help='USDC to quote for (nothing is spent)')
    ap.add_argument('--wallet', default='',
                    help='session wallet of a real account, for the balance '
                         'and gas checks. Omitted = example addresses, and '
                         'those two checks are skipped rather than faked.')
    ap.add_argument('--fixture', default='',
                    help='re-run every check against a SAVED capture instead '
                         'of calling the API. Makes no network request at all, '
                         'so a route can be re-examined after the fact and the '
                         'checks themselves can be tested.')
    args = ap.parse_args()

    if not args.fixture and not os.getenv('ZEROX_API_KEY'):
        print('ZEROX_API_KEY is not set. Nothing was sent.', file=sys.stderr)
        return 2

    import dashboard as d
    from trade_engine import crosschain as X
    from trade_engine import registry as R

    route_key = f'{args.source}->{args.dest}'
    # In this process only. The running site is untouched: this writes nothing
    # to /etc/orcagent.env and no other process sees it.
    d.TRADE_ENGINE_CROSSCHAIN = True
    d.CROSSCHAIN_ENABLED_ROUTES = frozenset(
        set(d.CROSSCHAIN_ENABLED_ROUTES) | {route_key})

    fixture = None
    if args.fixture:
        import json as _json
        with open(args.fixture) as fh:
            fixture = _json.load(fh)
        args.source, args.dest = (p.strip() for p in fixture['route'].split('->', 1))
        args.amount = float(fixture.get('amount_usd', args.amount))
        d._te_crosschain_provider = lambda: X.ZeroExCrossChain(
            lambda **kw: fixture['response'], lambda **kw: {})

    src = R.get_chain(args.source)
    dst = R.get_chain(args.dest)
    if args.wallet:
        origin = d._cc_taker_address(args.wallet, args.source)
        recipient = d._cc_taker_address(args.wallet, args.dest)
    elif fixture:
        origin = fixture.get('origin_address') or EXAMPLE_EVM
        recipient = fixture.get('destination_address') or EXAMPLE_SVM
    else:
        origin = EXAMPLE_SVM if src.kind == 'svm' else EXAMPLE_EVM
        recipient = EXAMPLE_SVM if dst.kind == 'svm' else EXAMPLE_EVM

    print('=' * 68)
    print(f'  PREFLIGHT   {route_key}   ${args.amount}   READ ONLY')
    print('=' * 68)
    print(f'  from {origin}')
    print(f'  to   {recipient}')
    print(f'  wallet mode: {"real account" if args.wallet else "example addresses"}')
    if fixture:
        print(f'  SAVED CAPTURE: {args.fixture} ({fixture.get("captured_at", "?")})')
        print('  no network request is made in this mode')
    print()

    amount_raw = int(args.amount * (10 ** src.stable.require_decimals()))
    provider = d._te_crosschain_provider()

    # ── 1. the live quote ──
    try:
        route = provider.get_quote(
            source_chain=args.source, destination_chain=args.dest,
            source_amount_raw=amount_raw, origin_address=origin,
            destination_address=recipient,
            extra_allowed_spenders=d.CROSSCHAIN_ALLOWED_SPENDERS,
            settler_lookup=d._cc_is_current_settler)
    except X.NoLiquidity as e:
        report('LIVE QUOTE', FAIL, f'{e.code} (zid {e.zid or "-"})')
        print()
        print(f'  The provider answered and cannot serve ${args.amount} on this')
        print('  route right now. That is a fact about the market, not a fault.')
        print('  Try a different size, or a different direction.')
        return verdict()
    except X.CrossChainError as e:
        report('LIVE QUOTE', FAIL, str(e)[:120])
        return verdict()
    report('LIVE QUOTE', PASS,
           f'{route.bridge_provider or "?"}, ~{route.estimated_seconds}s')
    report('PARSER', PASS,
           f'quoteId={route.quote_id[:14] or "-"}… zid={route.zid[:14] or "-"}…')

    # ── 2. the spender ──
    spender = (route.allowance_target or '').lower()
    canonical = spender in X.CANONICAL_ALLOWANCE_TARGETS
    pinned = spender in {a.lower() for a in d.CROSSCHAIN_ALLOWED_SPENDERS}
    if not route.needs_allowance and not spender:
        report('SPENDER', PASS, 'no allowance needed on this route')
    elif spender == X.ZEROX_SETTLER_REGISTRY:
        report('SPENDER', FAIL, 'the Settler registry — never approve this')
    elif canonical:
        report('SPENDER', PASS, f'{spender} (published 0x allowance contract)')
    elif pinned:
        report('SPENDER', PASS, f'{spender} (pinned by the operator)')
    else:
        report('SPENDER', FAIL, f'{spender} is not recognised or pinned')

    # ── 3. the calldata ──
    try:
        decoded = X.verify_source_calldata(route)
        if decoded.get('checked'):
            report('CALLDATA', PASS,
                   f'exec pulls {decoded["amount"]} of {decoded["token"][:10]}…')
        else:
            report('CALLDATA', SKIP, decoded.get('reason', ''))
    except X.CrossChainError as e:
        report('CALLDATA', FAIL, str(e)[:120])

    # ── 4. gas ──
    if args.wallet:
        gas = d._cc_gas_requirement(args.wallet, args.source, route)
        report('GAS', FAIL if gas['required'] else PASS,
               f'{gas["have"]} {gas["symbol"]} held, '
               f'~{gas["estimated_native_gas"]} needed ({gas["estimate_source"]})')
    else:
        est = d._cc_route_gas_estimate(args.source, route)
        report('GAS', SKIP,
               f'~{est:.8f} {src.native.symbol} estimated; pass --wallet to '
               f'check a real balance')

    # ── 5. the cost ceiling ──
    loss = route.loss_usd()
    pct = (loss / Decimal(str(args.amount))) * 100
    limit = Decimal(str(d.CROSSCHAIN_MAX_BRIDGE_COST_PCT))
    report('COST LIMIT', PASS if pct <= limit else FAIL,
           f'bridge {loss} = {pct.quantize(Decimal("0.01"))}% of '
           f'${args.amount} (limit {limit}%)')

    # ── 6. route policy ──
    report('ROUTE ENABLED', PASS if d._cc_route_enabled(args.source, args.dest) else FAIL,
           'in this process only; the site is untouched')

    # ── 7. the engine's own verdict ──
    try:
        provider.verify_route(route, expected_recipient=recipient,
                              expected_sender=origin,
                              extra_allowed_spenders=d.CROSSCHAIN_ALLOWED_SPENDERS,
                              settler_lookup=d._cc_is_current_settler)
        report('ENGINE ACCEPTS', PASS)
    except X.CrossChainError as e:
        report('ENGINE ACCEPTS', FAIL, str(e)[:120])

    return verdict()


if __name__ == '__main__':
    sys.exit(main())
