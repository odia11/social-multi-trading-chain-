#!/usr/bin/env python3
"""Ask 0x for a real cross-chain quote. Read only. Never signs, never sends.

WHY THIS EXISTS
Every field name in OrcAgent's cross-chain integration was read from 0x's
published example code, because api.0x.org and docs.0x.org are unreachable
from the environment the integration was written in. That is a primary source
and it is current, but it is not the same as having called the API. This
script is how that gap gets closed from a machine that CAN reach it, before
any money moves.

WHAT IT WILL NOT DO
It does not sign anything. It does not broadcast anything. It does not send
an approval. It does not read, decrypt or touch any user's key. It makes GET
requests and prints what came back, with the secrets removed. The only
credential it uses is ZEROX_API_KEY, and it never prints it.

The addresses it quotes for are 0x's own published example addresses, not any
user's wallet -- a quote is priced FOR an address but moves nothing, so this
asks "what would a route look like" without involving anybody's funds.

    python3 scripts/test_0x_crosschain_quote.py
    python3 scripts/test_0x_crosschain_quote.py --amount 5 --json

Exit code 0 means every requested route answered and every answer survived
the same validation the engine applies. Non-zero means something needs
looking at before a route is enabled -- read the output, it says what.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests                                              # noqa: E402
from trade_engine import crosschain as X                     # noqa: E402
from trade_engine import registry as R                       # noqa: E402

API = 'https://api.0x.org'

# 0x's own example addresses (0x-examples, cross-chain-headless-example/src/
# config.ts DEFAULT_ADDRESSES). Used so this script never needs a real user's
# wallet: a quote is priced for an address but moves nothing.
EXAMPLE_EVM = '0xABf40AADf960e20B4283dc5A06387A429Ba02456'
EXAMPLE_SVM = '9FzTJNUfMVSPPNEsUDfUHuE1gSE7uDBamcGHq1CseUUZ'

SECRET_KEYS = ('apikey', 'api_key', 'privatekey', 'private_key', 'secret',
               'seed', 'mnemonic', 'signature', 'encryptionkey')


def redact(value, depth=0, truncate=True):
    """Strip anything that could be a secret, at any depth.

    `truncate` shortens long strings, which keeps the PRINTED output readable.
    It is turned off when saving a fixture: the longest string in a
    cross-chain quote is the calldata, which is not a secret and IS the thing
    a parser test most wants to see. The first captured fixture was saved
    with it on, so its calldata reads "0x2213bc0b...[2954 chars]" -- fine for
    checking that the response parses, useless for checking what the
    transaction would actually do.
    """
    if depth > 8:
        return '...'
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            flat = str(k).replace('_', '').replace('-', '').lower()
            out[k] = ('[redacted]' if flat in SECRET_KEYS
                      else redact(v, depth + 1, truncate))
        return out
    if isinstance(value, list):
        items = value[:5] if truncate else value
        return [redact(v, depth + 1, truncate) for v in items]
    if truncate and isinstance(value, str) and len(value) > 400:
        return value[:200] + f'... [{len(value)} chars]'
    return value


def build_quote_params(*, origin_chain, destination_chain, sell_token, buy_token,
                       sell_amount, origin_address, destination_address,
                       slippage_bps=100, gas_payer=None):
    """The same parameter set the app sends. Kept here rather than imported so
    this script can run without starting the Flask app, and checked against
    the app's builder by tests/test_crosschain_request_shape.py."""
    params = {
        'originChain':        origin_chain,
        'destinationChain':   destination_chain,
        'sellToken':          sell_token,
        'buyToken':           buy_token,
        'sellAmount':         str(sell_amount),
        'sortQuotesBy':       'price',
        'originAddress':      origin_address,
        'destinationAddress': destination_address,
        'slippageBps':        int(slippage_bps),
        'maxNumQuotes':       1,
    }
    if gas_payer:
        params['gasPayer'] = gas_payer
    return params


def probe(source: str, dest: str, usd: float, api_key: str) -> dict:
    """One route, quoted and validated. Returns a sanitized report."""
    src, dst = R.get_chain(source), R.get_chain(dest)
    amount_raw = int(usd * (10 ** src.stable.require_decimals()))
    origin = EXAMPLE_SVM if src.kind == 'svm' else EXAMPLE_EVM
    recipient = EXAMPLE_SVM if dst.kind == 'svm' else EXAMPLE_EVM

    params = build_quote_params(
        origin_chain=X.chain_param(source), destination_chain=X.chain_param(dest),
        sell_token=src.stable.address, buy_token=dst.stable.address,
        sell_amount=amount_raw, origin_address=origin,
        destination_address=recipient)

    report = {'route': f'{source} -> {dest}', 'amount_usd': usd,
              'sent_params': {k: v for k, v in params.items()},
              'gasPayer_sent': 'gasPayer' in params}
    try:
        r = requests.get(f'{API}/cross-chain/quotes', params=params,
                         headers={'0x-api-key': api_key, '0x-version': 'v2'},
                         timeout=20)
    except Exception as e:
        report.update(ok=False, error=f'{type(e).__name__}: {e}')
        return report

    report['http_status'] = r.status_code
    if r.status_code != 200:
        report.update(ok=False, body=redact(r.text[:600]))
        return report
    try:
        data = r.json()
    except Exception as e:
        report.update(ok=False, error=f'unparseable: {e}')
        return report

    # The whole response, redacted, so a test can be built from what the live
    # API really returns rather than from what its example code suggests.
    report['raw_response'] = redact(data)                    # for printing
    report['raw_response_full'] = redact(data, truncate=False)   # for the fixture
    report['liquidityAvailable'] = data.get('liquidityAvailable')
    report['envelope_keys'] = sorted(data)
    # THE QUESTION THIS SCRIPT EXISTS FOR: which envelope does the live API
    # actually use? The integration accepts only the one it has verified.
    report['quote_list_key'] = next(
        (k for k in ('quotes', 'routes') if isinstance(data.get(k), list)), None)
    report['zid'] = data.get('zid')
    report['allowanceTarget'] = data.get('allowanceTarget')
    target = str(data.get('allowanceTarget') or '').lower()
    report['allowanceTarget_is_canonical'] = (
        target in X.CANONICAL_ALLOWANCE_TARGETS if target else None)
    report['allowanceTarget_is_settler_registry'] = (
        target == X.ZEROX_SETTLER_REGISTRY if target else None)

    quotes = data.get(report['quote_list_key'] or 'quotes') or []
    if quotes and isinstance(quotes[0], dict):
        q = quotes[0]
        tx = q.get('transaction') or {}
        details = tx.get('details') if isinstance(tx.get('details'), dict) else tx
        report.update({
            'quoteId': q.get('quoteId'),
            'quoteId_present': bool(q.get('quoteId')),
            'quoteId_equals_zid': bool(q.get('quoteId'))
                                  and q.get('quoteId') == data.get('zid'),
            'sellToken_echoed': q.get('sellToken'),
            'buyToken_echoed': q.get('buyToken'),
            'sellAmount': q.get('sellAmount'),
            'buyAmount': q.get('buyAmount'),
            'minBuyAmount': q.get('minBuyAmount'),
            'estimatedTimeSeconds': q.get('estimatedTimeSeconds'),
            'bridge_provider': next(
                (s.get('provider') for s in (q.get('steps') or [])
                 if isinstance(s, dict) and s.get('type') == 'bridge'), None),
            'transaction_keys': sorted(details) if isinstance(details, dict) else None,
            'transaction_chain_type': ('svm' if isinstance(details, dict)
                                       and details.get('serializedTransaction')
                                       else 'evm'),
            'gasCosts': redact(q.get('gasCosts')),
            'fees': redact(q.get('fees')),
            'issues': redact(q.get('issues')),
            'needs_allowance': bool((q.get('issues') or {}).get('allowance')),
        })
        # WHERE the ephemeral-signer answer came from, not only what it was.
        # A bare "required: true" is not actionable; the field it was found in
        # and the value it held are. An earlier version of the detector
        # answered true for a field merely being PRESENT and empty, which is
        # exactly the kind of thing this printout makes obvious.
        eph = X.ephemeral_signer_requirement(q, data)
        report.update({
            'ephemeral_signer_required': eph['required'],
            'ephemeral_signer_field': eph['path'],
            'ephemeral_signer_value': eph['value'],
            'ephemeral_signer_reason': eph['reason'],
        })

    # Finally: does this response survive the engine's own validation?
    try:
        route = X.ZeroExCrossChain(lambda **kw: data, lambda **kw: {}).get_quote(
            source_chain=source, destination_chain=dest,
            source_amount_raw=amount_raw, origin_address=origin,
            destination_address=recipient)
        report['engine_accepts'] = True
        report['engine_bridge_cost_usd'] = str(route.loss_usd())
    except X.CrossChainError as e:
        report['engine_accepts'] = False
        report['engine_refusal'] = f'{type(e).__name__}: {e}'
    report['ok'] = bool(report.get('engine_accepts'))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--amount', type=float, default=2.0,
                    help='quote size in USDC (default 2 — nothing is spent)')
    ap.add_argument('--route', action='append', default=[],
                    help='source->dest, repeatable. Default: base->solana and back')
    ap.add_argument('--json', action='store_true', help='machine-readable output')
    ap.add_argument('--save-fixture', metavar='DIR', default='',
                    help='write the sanitized live response to DIR as a test '
                         'fixture (tests/fixtures/0x is where the suite reads '
                         'them from). Addresses and amounts are kept, because '
                         'those are what the parser is tested against; nothing '
                         'secret is in a quote response, and it is run through '
                         'the same redactor as the printed output anyway.')
    args = ap.parse_args()

    api_key = os.getenv('ZEROX_API_KEY', '')
    if not api_key:
        print('ZEROX_API_KEY is not set. Nothing was sent.', file=sys.stderr)
        return 2

    routes = args.route or ['base->solana', 'solana->base']
    reports = []
    for spec in routes:
        if '->' not in spec:
            print(f'skipping {spec!r}: expected source->dest', file=sys.stderr)
            continue
        src, dst = (p.strip() for p in spec.split('->', 1))
        rep = probe(src, dst, args.amount, api_key)
        reports.append(rep)
        if args.save_fixture and rep.get('raw_response') is not None:
            os.makedirs(args.save_fixture, exist_ok=True)
            path = os.path.join(args.save_fixture,
                                f'quote_{src}_to_{dst}.json')
            with open(path, 'w') as fh:
                json.dump({'route': f'{src}->{dst}',
                           'captured_at': __import__('datetime').datetime
                                          .utcnow().isoformat() + 'Z',
                           'amount_usd': args.amount,
                           'origin_address': rep['sent_params'].get('originAddress'),
                           'destination_address': rep['sent_params'].get('destinationAddress'),
                           'response': rep.get('raw_response_full')
                                       or rep['raw_response']}, fh, indent=2)
            print(f'  fixture written: {path}', file=sys.stderr)

    if args.json:
        print(json.dumps(reports, indent=2, default=str))
    else:
        for rep in reports:
            print('\n' + '=' * 68)
            print(f'  {rep["route"]}   ${rep["amount_usd"]}   READ ONLY')
            print('=' * 68)
            for k in ('http_status', 'liquidityAvailable', 'quote_list_key',  # noqa
                      'envelope_keys', 'zid', 'quoteId', 'quoteId_present',
                      'quoteId_equals_zid', 'gasPayer_sent', 'allowanceTarget',
                      'allowanceTarget_is_canonical',
                      'allowanceTarget_is_settler_registry', 'needs_allowance',
                      'ephemeral_signer_required', 'ephemeral_signer_field',
                      'ephemeral_signer_value', 'ephemeral_signer_reason',
                      'bridge_provider',
                      'sellToken_echoed', 'buyToken_echoed', 'sellAmount',
                      'buyAmount', 'minBuyAmount', 'estimatedTimeSeconds',
                      'transaction_chain_type', 'transaction_keys', 'gasCosts',
                      'fees', 'issues', 'engine_accepts', 'engine_bridge_cost_usd',
                      'engine_refusal', 'error', 'body'):
                if k in rep:
                    print(f'  {k:38} {rep[k]}')

        print('\n' + '-' * 68)
        print('  WHAT TO DO WITH THIS')
        print('-' * 68)
        print('  quote_list_key must be "quotes". Anything else means the live')
        print('    envelope has changed and QUOTE_LIST_KEYS needs updating.')
        print('  quoteId_present false means status polling falls back to the')
        print('    two-parameter lookup for these routes.')
        print('  allowanceTarget_is_canonical false means the route wants a')
        print('    spender that is NOT Permit2 or AllowanceHolder. Find out what')
        print('    it is before adding it to CROSSCHAIN_ALLOWED_SPENDERS.')
        print('  ephemeral_signer_required true means this route needs a')
        print('    co-signer OrcAgent has no flow for; it will be refused.')
        print('    Check ephemeral_signer_field/value: if the value is null or')
        print('    empty the field is merely DECLARED, not required, and the')
        print('    detector now reads it that way.')
        print('  engine_accepts false is not necessarily bad — read the refusal.')
        print('\n' + '-' * 68)
        print('  FULL SANITIZED RESPONSE — paste this back if the fixture file')
        print('  does not reach the repository. It is the actual thing needed to')
        print('  finish the integration.')
        print('-' * 68)
        for rep in reports:
            print(f'\n### {rep["route"]}')
            print(json.dumps(rep.get('raw_response'), indent=2, default=str)[:12000])

        print('\n  Nothing was signed, sent, approved or spent.\n')

    return 0 if all(r.get('ok') for r in reports) else 1


if __name__ == '__main__':
    sys.exit(main())
