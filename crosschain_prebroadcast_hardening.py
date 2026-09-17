"""Close the cross-chain broadcast/hash crash window.

The transaction identity is deterministic once signed. Persist it before the
network send so a process death can never leave OrcAgent unable to identify a
possibly-broadcast origin transaction. A crash before the send can leave a
prepared-but-never-broadcast hash; that is safe: recovery watches it and
ultimately asks for manual review rather than ever sending a second bridge.
"""
from __future__ import annotations

import base64
import sqlite3
import threading
import time

_ctx = threading.local()


def _norm_hash(value) -> str:
    s = str(value or '').strip()
    return s.lower() if s.startswith('0x') else s


def _persist_prebroadcast_hash(d, tx_hash: str) -> None:
    route = getattr(_ctx, 'route', None)
    wallet = getattr(_ctx, 'wallet', '')
    source_chain = getattr(_ctx, 'source_chain', '')
    if route is None or not wallet or not source_chain:
        raise RuntimeError('cross-chain pre-broadcast context is missing')
    tx_hash = str(tx_hash or '').strip()
    if not tx_hash:
        raise RuntimeError('cannot persist an empty pre-broadcast transaction hash')

    conn = sqlite3.connect(d.DB_FILE)
    try:
        rows = conn.execute(
            "SELECT c.trade_id FROM trade_crosschain c "
            "JOIN trade_executions e ON e.trade_id=c.trade_id "
            "WHERE e.wallet=? AND e.state=? AND c.source_chain=? "
            "AND c.source_amount_raw=? AND c.provider_quote_id=? "
            "AND COALESCE(c.source_tx_hash,'')='' "
            "ORDER BY e.created_at DESC LIMIT 2",
            (wallet, d.te_ledger.AWAITING_SOURCE, source_chain,
             str(route.source_amount_raw), str(route.quote_id or '')),
        ).fetchall()
        if len(rows) != 1:
            raise RuntimeError(
                f'expected exactly one awaiting cross-chain leg before broadcast; found {len(rows)}')
        trade_id = rows[0][0]
        now = time.time()
        conn.execute(
            "UPDATE trade_crosschain SET source_tx_hash=?, source_sent_at=?, "
            "provider_status='origin_tx_prepared', updated_at=? WHERE trade_id=?",
            (tx_hash, now, now, trade_id),
        )
        conn.commit()
    finally:
        conn.close()


def install(d):
    original_factory = d._te_cc_source_sender

    def source_sender_factory(enc_blob: str, wallet: str, source_chain: str):
        original_sender = original_factory(enc_blob, wallet, source_chain)

        def send(route):
            _ctx.route = route
            _ctx.wallet = wallet
            _ctx.source_chain = source_chain
            try:
                return original_sender(route)
            finally:
                for name in ('route', 'wallet', 'source_chain'):
                    if hasattr(_ctx, name):
                        delattr(_ctx, name)
        return send

    def bridge_sign_send_evm(txn: dict, raw_quote: dict, private_key: str,
                             chain: str, origin_address: str,
                             origin_token: str) -> str:
        w3 = d._get_web3(chain)
        wallet_cs = w3.to_checksum_address(origin_address)
        allowance_issue = (raw_quote.get('issues') or {}).get('allowance')
        if allowance_issue:
            spender = allowance_issue.get('spender')
            sell_amount_raw = int(raw_quote.get('sellAmount') or 0)
            if spender and origin_token and sell_amount_raw:
                ok = d._ensure_evm_allowance(
                    w3, wallet_cs, private_key, origin_token,
                    spender, sell_amount_raw, chain)
                if not ok:
                    raise RuntimeError('origin allowance transaction did not confirm')

        details = txn.get('details') or {}
        tx = {
            'from': wallet_cs,
            'to': w3.to_checksum_address(details['to']),
            'data': details['data'],
            'value': int(details.get('value', '0')),
            'gas': int(details['gas']) if details.get('gas') else 400000,
            'gasPrice': int(details['gasPrice']) if details.get('gasPrice') else w3.eth.gas_price,
            'nonce': w3.eth.get_transaction_count(wallet_cs),
            'chainId': d.EVM_CHAINS[chain]['chain_id'],
        }
        acct = d._EvmAccount.from_key(private_key)
        signed = acct.sign_transaction(tx)
        prepared_hash = w3.keccak(signed.raw_transaction).hex()
        _persist_prebroadcast_hash(d, prepared_hash)

        sent = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
        if _norm_hash(sent) != _norm_hash(prepared_hash):
            raise RuntimeError(
                f'broadcast returned {sent}, but signed bytes hash to {prepared_hash}')
        return sent

    def bridge_sign_send_solana(txn, private_key: str) -> str:
        from solders.transaction import VersionedTransaction as VTx

        details = txn.get('details') or {} if isinstance(txn, dict) else {}
        tx_b64 = details.get('serializedTransaction')
        if not tx_b64:
            raise ValueError('no base64 transaction in quote response')
        keypair = d._sol_keypair_from_base58(private_key)
        vtx = VTx.from_bytes(base64.b64decode(tx_b64))
        signed_tx = VTx(vtx.message, [keypair])
        prepared_sig = str(signed_tx.signatures[0])
        _persist_prebroadcast_hash(d, prepared_sig)

        encoded = base64.b64encode(bytes(signed_tx)).decode()
        r = d.requests.post(d.SOLANA_RPC, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'sendTransaction',
            'params': [encoded, {
                'encoding': 'base64', 'skipPreflight': False, 'maxRetries': 3,
            }],
        }, timeout=30)
        data = r.json()
        if 'error' in data:
            raise RuntimeError(f'sendTransaction error: {data["error"]}')
        sent_sig = str(data.get('result') or '')
        if not sent_sig:
            raise RuntimeError(f'no signature in RPC response: {data}')
        if sent_sig != prepared_sig:
            raise RuntimeError(
                f'RPC returned {sent_sig}, but signed transaction is {prepared_sig}')
        return sent_sig

    d._te_cc_source_sender = source_sender_factory
    d._bridge_sign_send_evm = bridge_sign_send_evm
    d._bridge_sign_send_solana = bridge_sign_send_solana
