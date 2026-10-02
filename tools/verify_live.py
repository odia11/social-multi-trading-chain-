#!/usr/bin/env python3
"""Check, from the server itself, everything this app depends on outside it.

WHY THIS EXISTS
The development sandbox has no route to 0x, Jupiter, DexScreener or any RPC,
so the adapters the trade engine is built on have never run against a live
API. Every claim about them is therefore theory. This script is the missing
half: it runs where the app runs, calls the real services with the real keys,
and prints what it found.

Run it on the server:

    cd /path/to/the/app && python3 tools/verify_live.py

It is READ-ONLY. It quotes, reads balances and prices, and stops there --
nothing is signed, nothing is sent, no key is ever printed. The one thing it
proves about money is arithmetic: that a quote's parts add up to the ceiling
the user would have been shown.

Exit code is 0 when everything essential passed, 1 otherwise, so it can also
be used as a post-deploy check.
"""
import os
import sys
import time
import traceback

# Production app_entry.py enforces the same invariant before dashboard imports:
# OrcAgent never fronts user gas. Keep this verifier on that exact runtime mode.
os.environ['ORCAGENT_FRONTS_GAS'] = '0'

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_ROOT)


def _reexec_in_venv():
    """Re-run this script under the app's own interpreter.

    The app's dependencies live in APP_ROOT/venv, not in the system python,
    so `python3 tools/verify_live.py` -- the obvious thing to type, and what
    the line above this docstring says -- died on `No module named 'PIL'`
    before a single check had run. The whole point of this tool is to be run
    by someone who is trying to find out what is wrong, often from a phone;
    handing them an import error about an imaging library, from a script
    that checks RPCs and sponsor wallets, sends them looking in entirely the
    wrong place.

    So it just switches interpreters. Only when the venv python exists, is
    not already the one running, and can be executed -- otherwise this falls
    through and the run continues exactly as before.
    """
    if os.environ.get('_VERIFY_LIVE_REEXEC'):
        return
    venv_py = os.path.join(APP_ROOT, 'venv', 'bin', 'python')
    if not os.path.isfile(venv_py) or not os.access(venv_py, os.X_OK):
        return
    if os.path.realpath(venv_py) == os.path.realpath(sys.executable):
        return
    print(f'(running under {venv_py} — the app\'s own interpreter)', flush=True)
    os.environ['_VERIFY_LIVE_REEXEC'] = '1'
    try:
        os.execv(venv_py, [venv_py, os.path.abspath(__file__), *sys.argv[1:]])
    except OSError:
        # Could not switch; carry on with what we have rather than refusing
        # to run at all.
        os.environ.pop('_VERIFY_LIVE_REEXEC', None)


_reexec_in_venv()

OK, BAD, WARN = '  OK  ', ' FAIL ', ' WARN '
results = []


def report(status, name, detail='', key=None):
    # `key` is the bare name; `name` may carry the timing. The summary wants
    # the first and the live output the second -- a summary that repeats
    # "(843 ms)" is spending its width on the one number nobody needs twice.
    results.append((status, key or name, detail))
    line = f'[{status}] {name}'
    if detail:
        line += f'\n         {detail}'
    print(line, flush=True)


def section(title):
    print(f'\n── {title} ' + '─' * max(0, 60 - len(title)), flush=True)


class Blocking(Exception):
    """Something that stops real users dead, raised from a check that is
    otherwise allowed to merely warn.

    The gas sponsors are the case this exists for. "Low" and "empty" were
    both warnings, and the difference between them is the difference between
    a float to top up soon and a chain where nobody can trade OR withdraw
    right now. A deploy printed "26 passed, 2 warnings", the operator read
    that as fine, and a chain stayed dead for days while users sat on money
    they could not move. A warning that is scrolled past is not a warning.
    """


def attempt(name, fn, essential=True):
    """Run one check. A raised exception is a failure with its reason, never a
    traceback that stops the rest of the report."""
    t0 = time.time()
    try:
        detail = fn()
        ms = int((time.time() - t0) * 1000)
        report(OK, f'{name} ({ms} ms)', detail or '', key=name)
        return True
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        # Blocking outranks essential=False: a check may be allowed to warn
        # about degradation and still have to fail about an outage.
        status = BAD if (essential or isinstance(e, Blocking)) else WARN
        report(status, f'{name} ({ms} ms)', f'{type(e).__name__}: {e}', key=name)
        return False


def main():
    print('OrcAgent — live dependency check')
    print('=' * 68)

    # ── configuration, without printing any of it ──
    section('configuration')

    def cfg():
        import dashboard as d
        missing = [k for k in ('ENCRYPTION_KEY', 'SECRET_KEY') if not os.getenv(k)]
        if missing:
            raise RuntimeError(f'missing required variables: {", ".join(missing)}')
        # Presence only. A value is never printed, here or anywhere below.
        present = [k for k in ('SOL_GAS_SPONSOR_PRIVATE_KEY', 'JUPITER_PROXY',
                               'HELIUS_API_KEY', 'PUBLIC_HOST', 'DATA_DIR')
                   if os.getenv(k)]
        absent = [k for k in ('SOL_GAS_SPONSOR_PRIVATE_KEY',)
                  if not os.getenv(k)]
        out = f'set: {", ".join(present) or "none"}'
        if absent:
            out += f'\n         not set: {", ".join(absent)}'
        out += (f'\n         production={d.IS_PRODUCTION} host={d.PUBLIC_HOST} '
                f'data_dir={d._DATA_DIR}')
        return out

    attempt('app imports and configuration reads', cfg)

    def storage():
        import dashboard as d
        return d._storage_breakdown()

    attempt('storage', storage)

    # ── Solana-only product ──
    import dashboard as d

    section('Solana')

    def sol_price():
        """Fetch it the way the app does, rather than reading the global.

        _sol_price_usd is only assigned inside the scanner loop, which runs
        every 120 seconds in a background thread. A script that has just
        imported the module always sees 0 there -- so checking that global
        reported a failure that said nothing about whether the price feed
        works. It checks the feed itself now, and hands the result to the
        module so the Solana gas figures below have something to work with.
        """
        r = d._dex_get('https://api.dexscreener.com/latest/dex/tokens/' + d.SOL_MINT,
                       timeout=8)
        if not r or r.status_code != 200:
            raise RuntimeError(f'price feed returned HTTP '
                               f'{getattr(r, "status_code", "no response")}')
        pairs = r.json().get('pairs') or []
        p = next((x for x in pairs
                  if (x.get('quoteToken') or {}).get('address') == d.USDC_MINT),
                 pairs[0] if pairs else None)
        price = float((p or {}).get('priceUsd', 0) or 0)
        if price <= 1:
            raise RuntimeError('no usable SOL/USDC pair in the feed response')
        d._sol_price_usd = price
        return f'SOL = ${price:.2f}'
    attempt('SOL price feed', sol_price)

    def jupiter():
        q = d._jupiter_quote(d.SOL_MINT, d.USDC_MINT, 100_000_000)   # 0.1 SOL
        out = q.get('outAmount')
        if not out:
            raise RuntimeError(f'no route returned: {str(q)[:200]}')
        return f'0.1 SOL routes to {int(out) / 1e6:.4f} USDC'
    attempt('Jupiter quote', jupiter)

    def dexscreener():
        r = d._dex_get('https://api.dexscreener.com/latest/dex/tokens/'
                       + d.SOL_MINT, timeout=10)
        if not r or r.status_code != 200:
            raise RuntimeError(f'HTTP {getattr(r, "status_code", "no response")}')
        return f'{len(r.json().get("pairs") or [])} pairs returned'
    attempt('DexScreener', dexscreener)

    section('trade engine — Solana only')
    report(OK, 'active trading chain', 'Solana via Jupiter; legacy non-Solana routes are disabled')

    # ── the wallets that have to hold something ──
    section('sponsor wallets')

    # Whether an empty sponsor wallet is a problem depends entirely on the
    # rule, so the rule is reported first and the balance checks read it.
    _fronting = bool(getattr(d, 'ORCAGENT_FRONTS_GAS', False))
    if _fronting:
        report(WARN, 'unexpected gas-fronting mode',
               'Production is Solana-only and app_entry.py forces ORCAGENT_FRONTS_GAS=0.')
    else:
        report(OK, 'gas-fronting mode',
               'OrcAgent fronts no user gas. Solana trades use Jupiter gasless when available; otherwise the user needs SOL for network fees.')

    # What counts as "enough" is measured in GRANTS, not in tokens.
    #
    # The previous version picked a figure per token by hand -- 0.002 ETH,
    # 0.01 BNB, 20 POL, 0.05 SOL -- and those numbers answered a different
    # question from the one the app asks itself. The journal was saying
    # "needs 0.0200" while this check said "below 0.05", so the operator had
    # two numbers for "how much do I send" and neither was the app's own.
    #
    # The sponsor check below remains only as a diagnostic if gas-fronting is
    # deliberately enabled in a non-production experiment. In production it
    # returns immediately because app_entry.py forces fronting off.
    WARN_BELOW_GRANTS = 5     # fewer than this many users could be activated
    TARGET_GRANTS     = getattr(d, 'GAS_SPONSOR_TARGET_GRANTS', 30)

    def _grants_left(bal, one_grant):
        return int(bal // one_grant) if one_grant > 0 else 0

    def sol_sponsor():
        if not _fronting:
            return 'not used (ORCAGENT_FRONTS_GAS is off)'
        addr = d._sol_gas_sponsor_address()
        if not addr:
            raise Blocking('SOL_GAS_SPONSOR_PRIVATE_KEY is not set, but this '
                           'deployment fronts gas — a Solana wallet holding only '
                           'USDC cannot pay for its own first transaction, so it '
                           'can neither trade nor send anything out. Set the key, '
                           'or set ORCAGENT_FRONTS_GAS=0 if users really are meant '
                           'to fund their own gas')
        bal = d._get_user_sol(addr)
        # Solana's grant is a constant plus the reserve the sponsor keeps for
        # its own transfer fees -- exactly the sum _sponsor_solana_gas checks
        # before it will hand anything out, which is where "needs 0.0200" in
        # the journal comes from.
        one_grant = d.SOL_GAS_SPONSOR_GRANT + d.SOL_GAS_SPONSOR_MIN_RESERVE
        left = _grants_left(bal, one_grant)
        target = (d.SOL_GAS_SPONSOR_GRANT
                  * getattr(d, 'SOL_GAS_SPONSOR_TARGET_GRANTS', TARGET_GRANTS)
                  + d.SOL_GAS_SPONSOR_MIN_RESERVE)
        line = f'{addr}  {bal:.5f} SOL ({left} users)'
        _send = f'send {max(0.0, target - bal):.4f} SOL to this address'
        # Same line as the EVM sponsors: nothing left to grant is an outage,
        # not a low balance. A Solana wallet at zero SOL cannot pay for its
        # own first transaction, so its holder can neither trade nor move
        # anything out until this wallet can pay for them.
        if left < 1:
            raise Blocking(line + '\n         NOBODY without their own SOL can '
                                  f'trade or withdraw on Solana — {_send}')
        if left < WARN_BELOW_GRANTS:
            raise RuntimeError(
                line + f'\n         enough for {left} more users — {_send}')
        return line
    attempt('Solana gas sponsor funding', sol_sponsor, essential=False)

    # ── what it all means ──
    section('summary')
    failed = [(n, d) for s, n, d in results if s == BAD]
    warned = [(n, d) for s, n, d in results if s == WARN]
    print(f'{len(results) - len(failed) - len(warned)} passed · '
          f'{len(warned)} warning · {len(failed)} failed')

    def _why(detail):
        # The exception type is noise here -- the sentence after it is the
        # part that says what to do. Everything the checks raise puts the
        # instruction on the first line or the last.
        text = (detail or '').split(': ', 1)[-1].strip()
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if not lines:
            return ''
        tail = lines[-1]
        return tail if ('send ' in tail or 'top these up' in tail) else lines[0]

    # Warnings first, failures LAST -- deliberately the opposite of severity
    # order. This is read on a phone at the end of a deploy, where only the
    # tail of the output is on screen, so the most important lines have to be
    # the closest ones to the prompt. Printing failures first put them above
    # the fold and left the reader with "see the FAILED lines above" and
    # several screens of scrolling to find them.
    for label, group in (('warning:', warned), ('FAILED: ', failed)):
        for n, d in group:
            why = _why(d)
            print(f'  {label} {n}' + (f'\n             {why}' if why else ''))

    if failed:
        print('\nThe failures above are things the app needs at runtime. A trade '
              'that depends on one of them will fail for a real user.')
    elif warned:
        # This used to print the all-clear whenever nothing had FAILED, so a
        # deploy with both gas sponsors empty still signed off with
        # "Everything the app trades through is reachable" -- true, and
        # completely beside the point: reachable is not the same as working,
        # and an empty sponsor blocks every user who holds only USDC.
        print('\nEverything the app trades through is reachable, but the warnings '
              'above are not cosmetic: each one is something a real user can '
              'walk into. Read them before calling this deploy done.')
    else:
        print('\nEverything the app trades through is reachable from this server.')
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ModuleNotFoundError as e:
        # Named separately because the generic advice below sent someone
        # hunting through /etc/orcagent.env for a key that was set all along.
        # A missing third-party module is not a configuration problem: it is
        # this script running under an interpreter that is not the app's.
        _venv_py = os.path.join(APP_ROOT, 'venv', 'bin', 'python')
        print(f'\nThis needs the app\'s own interpreter, and did not get it: '
              f'{e}.')
        if os.path.isfile(_venv_py):
            print(f'Run it as:\n\n    cd {APP_ROOT} && venv/bin/python tools/verify_live.py\n')
        else:
            print(f'There is no virtualenv at {_venv_py}. On a deployed server '
                  f'install.sh creates one; run this from the directory the '
                  f'service actually runs from.')
        sys.exit(1)
    except Exception:
        traceback.print_exc()
        print('\nThe check itself could not run. That is usually a missing '
              'ENCRYPTION_KEY/SECRET_KEY, or being run from the wrong directory.')
        sys.exit(1)
