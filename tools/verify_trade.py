#!/usr/bin/env python3
"""Did the trade cost what the screen said it would?

Read-only. Signs nothing, sends nothing, prints no key.

    venv/bin/python tools/verify_trade.py [trade_id]

Nothing in this codebase has ever answered that question. Prices are checked
against live routes and the arithmetic has tests, but no execution has ever
been laid next to the chain it happened on. A decimals mistake, a fee charged
twice, a purchase sized from the wrong figure -- none of those would show up
anywhere until a user noticed their money was wrong.

Three columns, from three independent places:

  QUOTED    what the user was shown, out of trade_quotes.breakdown_json
  RECORDED  what the app believes happened, out of trade_executions
  ON-CHAIN  what actually moved, read back from the transaction itself

The third is the one that matters. The first two can agree with each other
and both be wrong; only the chain is a fact.

EVM only for now. A Solana swap needs pre/post token balances parsed out of a
versioned transaction, which is a different job -- for those this prints what
the app recorded and the explorer link, and says plainly that the comparison
was not made rather than implying it passed.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, BAD, WARN = '\033[32m✓\033[0m', '\033[31m✗\033[0m', '\033[33m•\033[0m'

# keccak("Transfer(address,address,uint256)")
TRANSFER_TOPIC = ('0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef')


def _fmt(x, places=6):
    return f'{x:,.{places}f}'.rstrip('0').rstrip('.') if isinstance(x, float) else str(x)


def main():
    import sqlite3
    import dashboard as d
    from trade_engine import ledger as L

    trade_id = (sys.argv[1] if len(sys.argv) > 1 else '').strip()

    conn = sqlite3.connect(d.DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        if not trade_id:
            row = conn.execute(
                'SELECT trade_id FROM trade_executions ORDER BY created_at DESC LIMIT 1'
            ).fetchone()
            if not row:
                print('No trades have been executed through the engine yet.')
                print('Make one, then run this again — that is the whole point.')
                return 2
            trade_id = row['trade_id']

        trade = L.get_trade(conn, trade_id)
        if not trade:
            print(f'{BAD} no trade {trade_id!r} in the ledger')
            return 1
        quote = L.load_quote(conn, trade['quote_id'])
        drift = L.cost_drift(conn, trade_id)
    finally:
        conn.close()

    print(f'Trade {trade_id}')
    print('=' * 68)
    print(f"state {trade['state']}  ·  mode {trade['mode']}  ·  "
          f"wallet {trade['wallet'][:6]}…{trade['wallet'][-4:]}")

    breakdown = {}
    if quote:
        try:
            breakdown = json.loads(quote['breakdown_json'])
        except Exception:
            breakdown = {}

    # ── 1. what the user was shown ──
    print('\n── QUOTED (what the screen said) ──')
    if not breakdown:
        print(f'{WARN} the quote breakdown could not be read')
    else:
        print(f"   maximum spend   {breakdown.get('max_spend_usd', '?')}")
        print(f"   token purchase  {breakdown.get('token_purchase_usd', '?')}")
        for kind, usd in (breakdown.get('costs_by_kind') or {}).items():
            print(f"   {kind:<15} {usd}")
        print(f"   user pays total {breakdown.get('total_user_spend_usd', '?')}")
        if breakdown.get('orcagent_subsidy_usd', '0') not in ('0', '', None):
            print(f"   fronted by us   {breakdown['orcagent_subsidy_usd']}")

    # ── 2. what the app believes ──
    print('\n── RECORDED (what the app stored) ──')
    print(f"   actual spend    {trade.get('actual_spend_usd') or '(not settled)'}")
    if trade.get('actual_subsidy_usd'):
        print(f"   fronted         {trade['actual_subsidy_usd']}")
    if drift:
        for kind, v in sorted(drift.items()):
            mark = OK if abs(v['drift']) < 0.005 else WARN
            print(f"   {mark} {kind:<13} quoted {_fmt(v['quoted'], 4)} · "
                  f"actual {_fmt(v['actual'], 4)} · drift {_fmt(v['drift'], 4)}")
    tx = (trade.get('source_tx_hash') or '').strip()
    if not tx:
        print(f'{WARN} no transaction hash recorded — nothing to compare against')
        print('    A trade with no hash never reached the chain, or the hash was '
              'not written back. Both are worth knowing.')
        return 1
    print(f'   tx              {tx}')

    # ── 3. what the chain says ──
    print('\n── ON-CHAIN (what actually moved) ──')
    if not tx.startswith('0x'):
        print(f'{WARN} this looks like a Solana signature, and the on-chain '
              f'comparison is not automated for Solana yet.')
        print(f'    Check it by hand: https://solscan.io/tx/{tx}')
        print(f'    What to compare: the USDC that left the wallet against the '
              f'"token purchase" figure above.')
        return 0

    # Which chain actually has this transaction? Ask, rather than assume.
    found = None
    for name in d.EVM_CHAINS:
        try:
            w3 = d._get_web3(name)
            rcpt = w3.eth.get_transaction_receipt(tx)
            if rcpt is not None:
                found = (name, w3, rcpt)
                break
        except Exception:
            continue
    if not found:
        print(f'{BAD} that transaction is on none of the configured chains.')
        print(f'    Either the hash is wrong, or the RPCs cannot see it.')
        return 1
    name, w3, rcpt = found
    print(f'   chain           {d.SURGE_ALERT_CHAIN_NAMES.get(name, name)}')
    print(f"   status          {'success' if rcpt.status == 1 else 'REVERTED'}")
    if rcpt.status != 1:
        print(f'{BAD} the transaction reverted. Whatever the app recorded, no '
              f'swap happened — and gas was still paid.')

    gas_native = (rcpt.gasUsed * rcpt.get('effectiveGasPrice',
                                          w3.eth.gas_price)) / 1e18
    sym = d.EVM_CHAINS[name]['native_symbol']
    print(f'   gas paid        {_fmt(gas_native, 8)} {sym}')

    wallet_cs = w3.to_checksum_address(trade['wallet']) if trade['wallet'].startswith('0x') else None
    try:
        tx_data = w3.eth.get_transaction(tx)
        sender = w3.to_checksum_address(tx_data['from'])
    except Exception:
        sender = wallet_cs
    stable = w3.to_checksum_address(d.EVM_CHAINS[name]['usdc'])

    out_stable, in_token = 0.0, {}
    for log in rcpt.logs:
        try:
            if not log.topics or log.topics[0].hex().lower().lstrip('0x') not in (
                    TRANSFER_TOPIC.lstrip('0x'),):
                continue
            frm = w3.to_checksum_address('0x' + log.topics[1].hex()[-40:])
            to  = w3.to_checksum_address('0x' + log.topics[2].hex()[-40:])
            raw = int(log.data.hex(), 16) if hasattr(log.data, 'hex') else int(log.data, 16)
            token = w3.to_checksum_address(log.address)
            if frm == sender and token == stable:
                out_stable += raw
            elif to == sender and token != stable:
                in_token[token] = in_token.get(token, 0) + raw
        except Exception:
            continue

    # Decimals read from the contract, never assumed -- assuming 6 or 18 is
    # exactly the class of mistake this tool exists to catch.
    try:
        dec = w3.eth.contract(address=stable, abi=d._ERC20_FULL_ABI
                              ).functions.decimals().call()
    except Exception:
        dec = None
    label = d.user_currency_label(name)
    if dec is None:
        print(f'{WARN} could not read the stablecoin decimals — raw units only')
        print(f'   {label} out        {out_stable} (raw)')
        spent = None
    else:
        spent = out_stable / (10 ** dec)
        print(f'   {label} out        {_fmt(spent, 6)}')
    for token, raw in in_token.items():
        try:
            td = w3.eth.contract(address=token, abi=d._ERC20_FULL_ABI
                                 ).functions.decimals().call()
            print(f'   token in        {_fmt(raw / (10 ** td), 6)}  ({token})')
        except Exception:
            print(f'   token in        {raw} raw  ({token})')

    # ── the verdict ──
    print('\n' + '=' * 68)
    if spent is None:
        print(f'{WARN} could not convert the on-chain amount — compare by hand')
        return 1
    quoted_purchase = None
    try:
        quoted_purchase = float(breakdown.get('token_purchase_usd'))
    except (TypeError, ValueError):
        pass
    if quoted_purchase is None:
        print(f'{WARN} no quoted purchase figure to compare against')
        return 1

    diff = spent - quoted_purchase
    pct = (abs(diff) / quoted_purchase * 100) if quoted_purchase else 0
    print(f'  screen said the purchase would be   {_fmt(quoted_purchase, 6)}')
    print(f'  the wallet actually spent           {_fmt(spent, 6)}')
    print(f'  difference                          {_fmt(diff, 6)}  ({pct:.2f}%)')
    if pct < 1:
        print(f'\n{OK} These agree. The swap sold what the quote said it would.')
        return 0
    print(f'\n{BAD} These do NOT agree. The screen and the chain disagree by '
          f'{pct:.2f}%.')
    print('  Something between the quote and the swap is using a different '
          'figure.\n  This is the failure the whole pricing rewrite was meant '
          'to make impossible.')
    return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        print('\nThis script only reads. Nothing was signed or sent.')
        sys.exit(1)
