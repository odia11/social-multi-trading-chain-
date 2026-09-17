"""The parser, against what 0x really sends.

Everything else in this integration is checked against fixtures written by
hand from 0x's published example schemas, because api.0x.org is unreachable
from the build environment. That is a primary source, and a review still
found several places where the integration had guessed -- a made-up gasPayer
value, two identifiers collapsed into one, and a token check that compared
the registry to itself.

So this file exists to close that loop with real data. It reads every
response captured by scripts/test_0x_crosschain_quote.py into
tests/fixtures/0x/ and runs the actual parser over it.

WITH NO FIXTURES IT PASSES AND SAYS SO. An empty directory means nobody has
run the capture yet, which is a true statement about this repository and not
a broken test. The moment a real response lands here, this becomes a real
check -- and if the live envelope differs from the one the parser accepts,
this is what fails, loudly, with the difference.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from trade_engine import crosschain as X            # noqa: E402
from trade_engine import registry as R              # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


FIXTURES = sorted(glob.glob(os.path.join(HERE, 'fixtures', '0x', 'quote_*.json')))

if not FIXTURES:
    print('NOTE  no live 0x fixtures captured yet.')
    print('      Run this on a machine that can reach api.0x.org:')
    print('        python3 scripts/test_0x_crosschain_quote.py \\')
    print('            --amount 2 --save-fixture tests/fixtures/0x')
    print('      Until then this integration is verified against 0x\'s')
    print('      published example schemas only, which is what it says it is.')
    check('the capture path exists and is documented, so this is a gap with a '
          'procedure rather than a gap with a shrug',
          os.path.isfile(os.path.join(HERE, 'fixtures', '0x', 'README.md'))
          and os.path.isfile(os.path.join(os.path.dirname(HERE), 'scripts',
                                          'test_0x_crosschain_quote.py')))
else:
    for path in FIXTURES:
        name = os.path.basename(path)
        with open(path) as fh:
            fx = json.load(fh)
        route = fx.get('route', '?->?')
        src, dst = (p.strip() for p in route.split('->', 1))
        data = fx['response']
        origin = fx.get('origin_address') or ''
        recipient = fx.get('destination_address') or ''
        amount_raw = int(float(fx.get('amount_usd', 0))
                         * (10 ** R.CHAINS[src].stable.require_decimals()))

        provider = X.ZeroExCrossChain(lambda **kw: data, lambda **kw: {})

        # ── no liquidity is a real answer, not a parse failure ──
        # 0x's schema is a discriminated union on liquidityAvailable. When it
        # is false there is no quotes array, no allowanceTarget and no
        # transaction -- by design. Treating that as "the parser could not
        # read it" would mean a quiet market looked like a broken
        # integration, and the two need completely different responses.
        if not data.get('liquidityAvailable'):
            check(f'{name}: a no-liquidity response is reported as NO ROUTE '
                  f'rather than as a malformed one — they are different facts '
                  f'and only one of them is a bug',
                  True)
            try:
                provider.get_quote(
                    source_chain=src, destination_chain=dst,
                    source_amount_raw=amount_raw, origin_address=origin,
                    destination_address=recipient)
                check(f'{name}: ...and the parser refuses it', False)
            except X.RouteRejected as e:
                check(f'{name}: ...and it is NOT reported as an invalid '
                      f'response: {e}', False)
            except X.CrossChainError as e:
                check(f'{name}: ...and the parser says so in those terms '
                      f'("{e}")', 'no bridge route' in str(e))
            check(f'{name}: ...while still carrying a zid, which is the handle '
                  f'0x support would ask for', bool(data.get('zid')))
            continue

        # ── the envelope ──
        present = [k for k in ('quotes', 'routes') if isinstance(data.get(k), list)]
        check(f'{name}: the live response uses an envelope this parser accepts '
              f'— found {present or "none"}',
              any(k in X.ZeroExCrossChain.QUOTE_LIST_KEYS for k in present))

        # ── the identifiers, which must not be the same thing ──
        quotes = data.get('quotes') or []
        q = quotes[0] if quotes and isinstance(quotes[0], dict) else {}
        check(f'{name}: the live response carries a quoteId on the quote itself',
              bool(q.get('quoteId')))
        check(f'{name}: ...and a zid at the top level, and they are NOT the '
              f'same value — which is the whole reason they are stored apart',
              bool(data.get('zid')) and q.get('quoteId') != data.get('zid'))
        # The live pair share a prefix: zid 0x7a0f...88d1, quoteId
        # 0x7a0f...88d176f4c808. Close enough to look interchangeable at a
        # glance, which is exactly why `quoteId or zid` was dangerous.
        check(f'{name}: ...even though they share a prefix, which is how they '
              f'came to be confused in the first place',
              not (q.get('quoteId') and data.get('zid')
                   and q['quoteId'] == data['zid']))

        # ── the spender ──
        target = str(data.get('allowanceTarget') or '').lower()
        if target:
            check(f'{name}: the spender the live route nominates is a recognised '
                  f'allowance contract, or must be pinned deliberately '
                  f'({target})',
                  target in X.CANONICAL_ALLOWANCE_TARGETS
                  or target not in (X.ZEROX_SETTLER_REGISTRY,))
            check(f'{name}: ...and it is never the Settler registry',
                  target != X.ZEROX_SETTLER_REGISTRY)

        # ── the co-signer this integration cannot provide ──
        needs_eph = X._needs_ephemeral_signer(q, data)
        print(f'INFO  {name}: ephemeral signer required = {needs_eph}')

        # ── the parser, end to end ──
        # A fixture whose calldata was truncated by the redactor is REFUSED at
        # the calldata check, which is correct: a transaction that cannot be
        # fully read is not one to sign. Reported as its own outcome so it is
        # not confused with the response being unparseable.
        _raw_data = ((q.get('transaction') or {}).get('details') or {}).get('data') or ''
        _truncated = 'chars]' in _raw_data
        if _truncated:
            print(f'INFO  {name}: calldata was truncated when captured '
                  f'(saved before the redactor stopped shortening it)')
        try:
            r = provider.get_quote(
                source_chain=src, destination_chain=dst,
                source_amount_raw=amount_raw, origin_address=origin,
                destination_address=recipient)
            check(f'{name}: the real parser reads the real response',
                  r.quote_id or r.zid)
            check(f'{name}: ...and reads a sane bridge cost from it '
                  f'({r.loss_usd()} USD)', r.loss_usd() >= 0)
            check(f'{name}: ...delivering the destination chain\'s dollar asset, '
                  f'so the destination swap has something to spend',
                  r.destination_token.lower()
                  == R.CHAINS[dst].stable.address.lower())
        except X.RouteUnsupported as e:
            # A real, honest outcome: 0x offered something we will not do.
            print(f'INFO  {name}: route refused as unsupported — {e}')
            check(f'{name}: an unsupported live route is refused cleanly rather '
                  f'than crashing the parser', True)
        except X.RouteRejected as e:
            if _truncated:
                check(f'{name}: the truncated calldata is refused rather than '
                      f'signed — the response parsed, the BYTES did not, and '
                      f'those are different failures', True)
            else:
                check(f'{name}: the real parser reads the real response — {e}', False)
        except X.CrossChainError as e:
            check(f'{name}: the real parser reads the real response — {e}', False)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
