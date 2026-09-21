#!/usr/bin/env python3
"""Read-only tip diagnosis. No dashboard import, signing, sending or DB writes.

Defaults to the configured owner's account; --sender accepts a username or
session address. Prints the selected identity so the operator can verify it.
Private keys are used only locally to derive public addresses and never logged.
"""
import argparse
import base64
from contextlib import contextmanager
from decimal import Decimal
import hmac
import os
from pathlib import Path
import shlex
import sqlite3
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

APP = Path('/opt/orcagent')
sys.path.insert(0, str(APP))
import requests
from cryptography.fernet import Fernet
from solders.keypair import Keypair
import portfolio_token_withdraw as tip


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sender')
    parser.add_argument('--recipient', default='44aWybFqHA85RuixK1GYcyYvuPc76RMa7EQB8472zjyy')
    parser.add_argument('--amount', default='0.03')
    args = parser.parse_args()
    amount = Decimal(args.amount)
    if not amount.is_finite() or amount <= 0:
        raise ValueError('Invalid amount')
    env = {}
    for line in Path('/etc/orcagent.env').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        parsed = shlex.split(value, comments=True)
        env[name.removeprefix('export ').strip()] = ' '.join(parsed)
    selector = args.sender or env.get('OWNER_WALLET', '')
    db = Path(env.get('DATA_DIR') or '/data') / 'orcagent.db'
    connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
    connection.execute('PRAGMA query_only=ON')
    def user(value):
        return connection.execute(
            'SELECT id, username, wallet_address, encrypted_private_key '
            'FROM users WHERE wallet_address=? OR lower(username)=lower(?) LIMIT 1',
            (value, value)).fetchone()
    sender, recipient = user(selector), user(args.recipient)
    if not sender:
        print('Sender not found. Specify --sender YOUR_USERNAME; nothing was changed.')
        return 2
    if not recipient:
        print('Recipient account not found; nothing was changed.')
        return 2
    print('SENDER:', sender[0], sender[1], '(configured owner default)' if not args.sender else '')
    print('RECIPIENT:', recipient[0], recipient[1])
    print('SAME_USER:', sender[0] == recipient[0])
    encryption_key = env.get('ENCRYPTION_KEY', '')
    fernet = Fernet(encryption_key.encode())
    def address(row):
        if not row[3]:
            return ''
        blob = row[3]
        if blob.startswith('v2:'):
            derived = hmac.digest(encryption_key.encode(), row[2].encode(), 'sha256')
            blob_bytes = Fernet(base64.urlsafe_b64encode(derived)).decrypt(blob[3:].encode())
        else:
            blob_bytes = blob.encode()
        plaintext = fernet.decrypt(blob_bytes)
        key = Keypair.from_base58_string(plaintext.decode())
        public = str(key.pubkey())
        del key, plaintext, blob_bytes
        return public
    owner = address(sender)
    destination = address(recipient) or recipient[2]
    if not owner:
        print('BLOCKER: sender trading wallet is not configured')
        return 1
    print('SOURCE_PUBLIC_ADDRESS:', owner)
    print('DESTINATION_PUBLIC_ADDRESS:', destination)
    print('SAME_TRADING_ADDRESS:', owner == destination)
    urls = []
    for url in [env.get('SOLANA_RPC_URL'), env.get('HELIUS_RPC'),
                ('https://mainnet.helius-rpc.com/?api-key=' + env['HELIUS_API_KEY']) if env.get('HELIUS_API_KEY') else None,
                'https://api.mainnet-beta.solana.com']:
        if url and url not in urls:
            urls.append(url)
    d = SimpleNamespace(CLAIM_SOL_RPCS=urls, USDC_MINT='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
                        _get_trading_wallet_address=lambda _: owner)
    allowed = {'getTokenAccountsByOwner', 'getAccountInfo', 'getBalance',
               'getMinimumBalanceForRentExemption', 'getLatestBlockhash'}
    def readonly_rpc(url, method, params):
        if method not in allowed:
            raise RuntimeError('Blocked non-read RPC method')
        host = urlsplit(url).hostname or 'configured-provider'
        try:
            response = requests.post(url, json={
                'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, timeout=15)
        except requests.RequestException as exc:
            print('RPC', host, method, 'NETWORK_ERROR', type(exc).__name__, flush=True)
            raise RuntimeError('RPC network failure') from None
        print('RPC', host, method, 'HTTP', response.status_code, flush=True)
        if response.status_code != 200:
            raise RuntimeError('RPC HTTP ' + str(response.status_code))
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError('RPC invalid JSON') from None
        if body.get('error'):
            code = (body.get('error') or {}).get('code')
            print('RPC_ERROR_CODE', code if isinstance(code, int) else 'unspecified', flush=True)
            raise RuntimeError('RPC rejected read')
        if 'result' not in body:
            raise RuntimeError('RPC missing result')
        return body['result']
    tip._rpc_call = readonly_rpc
    def rpc(method, params):
        return tip._rpc_call_any(d, method, params)[0]
    print('Checking live source accounts...', flush=True)
    accounts = None
    try:
        accounts = tip._solana_source_accounts(d, owner, d.USDC_MINT)
    except Exception as exc:
        print('SOURCE_ACCOUNT_LOOKUP_FAILED:', type(exc).__name__, flush=True)
    balance = sum((Decimal(a['account']['data']['parsed']['info']['tokenAmount']['amount']) /
                   Decimal(10) ** int(a['account']['data']['parsed']['info']['tokenAmount']['decimals'])
                   for a in (accounts or [])), Decimal(0))
    native = int(rpc('getBalance', [owner, {'commitment':'confirmed'}])['value'])
    required = tip._tip_required_lamports(d, owner, destination)
    print('USDC_BALANCE:', balance if accounts is not None else 'UNKNOWN (RPC failure; not zero)')
    print('SOL_LAMPORTS:', native)
    print('REQUIRED_LAMPORTS_WITH_RECIPIENT_ACCOUNT:', required)
    print('SPARE_USDC_AFTER_TIP:', balance - amount if accounts is not None else 'UNKNOWN')
    print('JUPITER_API_KEY_CONFIGURED:', bool(env.get('JUPITER_API_KEY')))
    if accounts is None:
        print('BLOCKER: source token accounts could not be read; see RPC status codes above.')
        print('DONE: nothing signed or sent.')
        connection.close()
        return 1
    class PreflightReady(Exception):
        pass
    @contextmanager
    def refuse_signing(*unused):
        raise PreflightReady()
        yield  # Never reached: prevents any signing.
    d._use_key = refuse_signing
    tip._wallet_keys = lambda *_: ('diagnostic-placeholder', '', '')
    try:
        tip._solana_transfer(d, sender[2], d.USDC_MINT, destination, amount)
    except PreflightReady:
        print('TRANSFER_PRECHECK: PASSED; stopped before signing. No transaction sent.')
    except Exception as exc:
        known = ('This token is not available', 'Amount is higher', 'Not enough SOL',
                 'Destination is the same', 'Amount is too small', 'Invalid Solana')
        reason = str(exc)
        print('TRANSFER_PRECHECK:', reason if reason.startswith(known) else type(exc).__name__)
    api_key = env.get('JUPITER_API_KEY', '')
    print('JUPITER_API_KEY_CONFIGURED:', bool(api_key))
    spare = balance - amount
    if native < required and spare >= Decimal('0.20') and api_key:
        # GET /order is a quote only. No execute request or signature exists.
        sizes = sorted(set([min(Decimal('0.20'), spare), spare]))
        for size in sizes:
            response = requests.get('https://api.jup.ag/ultra/v1/order', params={
                'inputMint': d.USDC_MINT, 'outputMint': 'So11111111111111111111111111111111111111112',
                'amount': str(int(size * 1000000)), 'taker': owner},
                headers={'x-api-key': api_key}, timeout=20)
            print('GAS_QUOTE_USDC:', size, 'HTTP:', response.status_code)
            if response.ok:
                order = response.json()
                print('GASLESS:', bool(order.get('gasless')),
                      'TRANSACTION_AVAILABLE:', bool(order.get('transaction')),
                      'OUTPUT_LAMPORTS:', int(order.get('outAmount') or 0))
                print('ERROR_CODE:', order.get('errorCode'))
    connection.close()
    print('DONE: read-only; no signing, transfers, trades or database changes.')
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        # Provider URLs and secret values are deliberately never printed.
        print('DIAGNOSTIC_STOPPED:', type(exc).__name__, flush=True)
        sys.exit(1)
