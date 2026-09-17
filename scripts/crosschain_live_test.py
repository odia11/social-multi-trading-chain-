#!/usr/bin/env python3
"""One controlled, real-money cross-chain trade, driven step by step.

THIS SPENDS REAL MONEY. It is the test that has to happen before a route is
opened to anybody, and it is deliberately awkward to run by accident:

  * it refuses to start without --i-understand-this-spends-real-money
  * it refuses an amount above --max-usd (default 5)
  * it names the wallet it will spend from and waits for you to type yes
  * it enables the route IN THIS PROCESS ONLY, so nothing about the running
    site changes and no other user can reach the route because of it

WHAT IT DOES
Exactly what a user's Buy button does, with the same code: prices the route,
checks native gas, reserves the balance, broadcasts the origin transaction,
then follows the trade through the real recovery worker's own resume function
until it reaches a terminal state -- printing every state change as it
happens, with the transaction hashes.

    python3 scripts/crosschain_live_test.py \
        --wallet <the session wallet of your test account> \
        --token  <a Solana token mint> \
        --amount 2 \
        --i-understand-this-spends-real-money

Use a wallet you control and are willing to lose the amount from. Do not run
this against a real user's account.
"""
import argparse
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--wallet', required=True,
                    help='session wallet address of the CONTROLLED test account')
    ap.add_argument('--token', required=True, help='destination token address/mint')
    ap.add_argument('--source', default='base', help='source chain (default base)')
    ap.add_argument('--dest', default='solana', help='destination chain (default solana)')
    ap.add_argument('--amount', type=float, default=2.0, help='USDC to spend (default 2)')
    ap.add_argument('--max-usd', type=float, default=5.0,
                    help='hard ceiling; the script refuses above this (default 5)')
    ap.add_argument('--timeout', type=int, default=1800,
                    help='seconds to follow the trade before giving up watching '
                         '(the trade itself carries on; default 1800)')
    ap.add_argument('--i-understand-this-spends-real-money', dest='confirmed',
                    action='store_true')
    args = ap.parse_args()

    if not args.confirmed:
        print('Refusing to run: this spends real money and the flag saying you '
              'know that was not given.', file=sys.stderr)
        return 2
    if args.amount > args.max_usd:
        print(f'Refusing {args.amount}: above the {args.max_usd} ceiling. Raise '
              f'--max-usd deliberately if you really mean it.', file=sys.stderr)
        return 2
    if args.source == args.dest:
        print('Source and destination are the same chain — that is not a '
              'cross-chain test.', file=sys.stderr)
        return 2

    import dashboard as d
    from decimal import Decimal
    from trade_engine import ledger as te_ledger
    from trade_engine import execute as te_execute
    from trade_engine import crosschain as te_crosschain

    route_key = f'{args.source}->{args.dest}'
    # IN THIS PROCESS ONLY. The running site is untouched: nothing is written
    # to /etc/orcagent.env and no other process sees this.
    d.TRADE_ENGINE_CROSSCHAIN = True
    d.CROSSCHAIN_ENABLED_ROUTES = frozenset(
        set(d.CROSSCHAIN_ENABLED_ROUTES) | {route_key})

    conn = sqlite3.connect(d.DB_FILE)
    try:
        uid = d._get_uid(conn, args.wallet)
    finally:
        conn.close()
    if not uid:
        print(f'No such user: {args.wallet}', file=sys.stderr)
        return 2

    src_addr = d._cc_taker_address(args.wallet, args.source)
    dst_addr = d._cc_taker_address(args.wallet, args.dest)
    src_usdc = d._cc_usdc_balance(args.wallet, args.source)
    gas = d._cc_gas_requirement(args.wallet, args.source)

    print('=' * 70)
    print(f'  CONTROLLED LIVE TEST   {route_key}   ${args.amount}')
    print('=' * 70)
    print(f'  source wallet      {src_addr}')
    print(f'  destination wallet {dst_addr}')
    print(f'  source USDC        {src_usdc:.4f}')
    print(f'  native {gas["symbol"]:<12} {gas["have"]} '
          f'(estimated need {gas["estimated_native_gas"]}, '
          f'{gas["estimate_source"]})')
    print(f'  token              {args.token}')
    print('=' * 70)

    if src_usdc < args.amount:
        print(f'\nNot enough USDC on {args.source}. Nothing was sent.', file=sys.stderr)
        return 1

    reply = input('\nThis will spend real money from the wallet above. Type '
                  '"yes" to continue: ').strip().lower()
    if reply != 'yes':
        print('Stopped. Nothing was sent.')
        return 0

    # ── quote ──
    print('\n[1/4] pricing the route…')
    try:
        quote = d._te_build_and_store_quote(
            uid=uid, wallet=args.wallet, source_chain=args.source,
            dest_chain=args.dest, token_address=args.token,
            max_spend=Decimal(str(args.amount)),
            taker=(args.wallet if args.dest == 'solana' else dst_addr),
            mode='manual')
    except Exception as e:
        print(f'  could not price it: {type(e).__name__}: {e}', file=sys.stderr)
        return 1
    body = quote.to_dict()
    print(f'  quote_id      {quote.quote_id}')
    print(f'  route         {quote.route}')
    print(f'  spends max    {body["max_spend_usd"]}')
    print(f'  buys          {body["token_purchase_usd"]}')
    print(f'  costs         {body.get("costs_by_kind")}')
    print(f'  can execute   {body.get("can_execute")}')
    if not body.get('can_execute'):
        print(f'  refused: {body.get("reject_reason")}', file=sys.stderr)
        return 1

    route = d._cc_recall_route(f'quote:{quote.quote_id}')
    if route is None:
        print('  the priced route was not retained — cannot execute the quote '
              'that was shown', file=sys.stderr)
        return 1
    print(f'  bridge via    {route.bridge_provider or "?"}  '
          f'(quoteId={route.quote_id or "-"}, zid={route.zid or "-"})')
    print(f'  spender       {route.allowance_target or "none needed"}')

    # ── gas, re-checked against the priced route ──
    print('\n[2/4] checking native gas…')
    gas = d._cc_gas_requirement(args.wallet, args.source, route)
    if gas['required']:
        print(f'  NATIVE_GAS_REQUIRED: {gas["reason"]}', file=sys.stderr)
        return 1
    print(f'  ok — {gas["have"]} {gas["symbol"]} against an estimated '
          f'{gas["estimated_native_gas"]}')

    # ── execute ──
    print('\n[3/4] reserving, signing and broadcasting the origin transaction…')
    enc = None
    conn = sqlite3.connect(d.DB_FILE)
    try:
        row = conn.execute(
            'SELECT encrypted_private_key, encrypted_private_key_bsc FROM users '
            'WHERE id=?', (uid,)).fetchone()
    finally:
        conn.close()
    enc = (row[0] if args.source == 'solana' else row[1]) if row else None
    if not enc:
        print(f'  no {args.source} trading wallet on this account', file=sys.stderr)
        return 1

    started = time.time()
    try:
        result = d._te_run_crosschain_trade(
            quote_id=quote.quote_id,
            idem=f'{uid}:livetest:{quote.quote_id}',
            available=Decimal(str(src_usdc)), wallet=args.wallet, enc_blob=enc,
            source_chain=args.source, route=route, symbol='TEST',
            token_address=args.token, user_id=uid)
    except Exception as e:
        print(f'  execution error: {type(e).__name__}: {e}', file=sys.stderr)
        return 1

    trade_id = result.trade_id
    print(f'  trade_id      {trade_id}')
    print(f'  state         {result.state}')
    if result.source_tx_hash:
        print(f'  source tx     {result.source_tx_hash}')
    if result.state in (te_ledger.FAILED, te_ledger.CANCELLED):
        print(f'  failed: {result.failure_reason}', file=sys.stderr)
        return 1

    # ── follow it, through the real resume path ──
    print('\n[4/4] following the trade (the same resume function the worker '
          'uses)…')
    seen = result.state
    print(f'  {time.strftime("%H:%M:%S")}  {seen}')
    while time.time() - started < args.timeout:
        time.sleep(10)
        try:
            moved = d._crosschain_resume_once()
        except Exception as e:
            print(f'  resume pass error: {type(e).__name__}: {e}')
            moved = 0
        conn = sqlite3.connect(d.DB_FILE)
        try:
            trade = te_ledger.get_trade(conn, trade_id) or {}
            cc = te_ledger.get_crosschain(conn, trade_id) or {}
        finally:
            conn.close()
        state = trade.get('state', '?')
        if state != seen:
            seen = state
            print(f'  {time.strftime("%H:%M:%S")}  {state}'
                  + (f'   [{cc.get("provider_status")}]' if cc.get('provider_status') else ''))
            for label, key in (('source', 'source_tx_hash'),
                               ('destination', 'destination_tx_hash'),
                               ('swap', 'swap_tx_hash')):
                if cc.get(key):
                    print(f'             {label} tx {cc[key]}')
        if state in te_ledger.TERMINAL:
            print('\n' + '=' * 70)
            if state == te_ledger.COMPLETED:
                print('  RESULT: COMPLETED')
                print(f'  actually spent {trade.get("actual_spend_usd")}')
                print(f'  received raw   {cc.get("actual_out_raw")} '
                      f'(quoted {cc.get("quoted_out_raw")})')
                print('=' * 70)
                return 0
            print(f'  RESULT: {state}')
            print(f'  reason: {trade.get("failure_reason")}')
            print(f'  needs a person: {bool(trade.get("needs_investigation"))}')
            print('=' * 70)
            return 1

    print(f'\nStopped watching after {args.timeout}s. The trade is NOT '
          f'cancelled — the worker keeps going. Check:')
    print(f'  GET /api/trade/status/{trade_id}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
