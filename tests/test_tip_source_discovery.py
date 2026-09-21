"""Behavioral tests: balance scanner succeeds while mint lookup is empty.

RPC and signing keys are test fixtures; no live transaction is submitted.
"""
import copy
import sys
import unittest
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portfolio_token_withdraw as tip
from solders.keypair import Keypair
from solders.hash import Hash

PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'

class SourceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.key = Keypair()
        self.owner = str(self.key.pubkey())
        self.recipient = str(Keypair().pubkey())
        self.account = {
            'pubkey': str(Keypair().pubkey()),
            'account': {'owner': PROGRAM, 'data': {'parsed': {'info': {
                'mint': MINT, 'owner': self.owner, 'state': 'initialized',
                'tokenAmount': {'amount': '864500', 'decimals': 6}
            }}}}
        }
        self.d = SimpleNamespace(CLAIM_SOL_RPCS=['rpc-a', 'rpc-b'],
                                 _get_trading_wallet_address=lambda _: self.owner)

    def rpc(self, url, method, params):
        if method == 'getTokenAccountsByOwner':
            entries = [self.account] if params[1].get('programId') == PROGRAM else []
            return {'value': entries}
        if method == 'getAccountInfo':
            return {'value': {'owner': PROGRAM}}
        if method == 'getBalance':
            return {'value': 100000}
        if method == 'getLatestBlockhash':
            return {'value': {'blockhash': str(Hash.default())}}
        if method == 'sendTransaction':
            return 'simulated-signature'
        raise AssertionError(method)

    def test_empty_mint_query_falls_back_and_completes_transfer(self):
        @contextmanager
        def use_key(*args):
            yield str(self.key)
        self.d._use_key = use_key
        with patch.object(tip, '_rpc_call', side_effect=self.rpc) as rpc, patch.object(
                tip, '_wallet_keys', return_value=('test-encrypted-key', '', '')):
            signature, sent = tip._solana_transfer(
                self.d, 'session', MINT, self.recipient, Decimal('0.03'))
        self.assertEqual(signature, 'simulated-signature')
        self.assertEqual(sent, 0.03)
        self.assertEqual(sum(c.args[1] == 'sendTransaction' for c in rpc.call_args_list), 1)
        self.assertTrue(any(c.args[2][1] == {'programId': PROGRAM}
                            for c in rpc.call_args_list if c.args[1] == 'getTokenAccountsByOwner'))

    def test_unrelated_mint_owner_and_frozen_accounts_are_ignored(self):
        wrong_mint = copy.deepcopy(self.account)
        wrong_mint['account']['data']['parsed']['info']['mint'] = self.recipient
        wrong_owner = copy.deepcopy(self.account)
        wrong_owner['account']['data']['parsed']['info']['owner'] = self.recipient
        frozen = copy.deepcopy(self.account)
        frozen['account']['data']['parsed']['info']['state'] = 'frozen'
        with patch.object(tip, '_rpc_call', return_value={'value': [wrong_mint, wrong_owner, frozen]}):
            self.assertEqual(tip._solana_source_accounts(self.d, self.owner, MINT), [])

    def test_provider_failures_do_not_hide_program_fallback(self):
        def rpc(url, method, params):
            if url == 'rpc-a':
                raise RuntimeError('unavailable')
            return self.rpc(url, method, params)
        with patch.object(tip, '_rpc_call', side_effect=rpc):
            self.assertEqual(tip._solana_source_accounts(self.d, self.owner, MINT), [self.account])

    def test_healthy_mint_lookup_stays_fast(self):
        with patch.object(tip, '_rpc_call', return_value={'value': [self.account]}) as rpc:
            self.assertEqual(tip._solana_source_accounts(self.d, self.owner, MINT), [self.account])
            self.assertEqual(rpc.call_count, 1)

    def test_total_rpc_failure_is_not_reported_as_empty_balance(self):
        with patch.object(tip, '_rpc_call', side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                tip._solana_source_accounts(self.d, self.owner, MINT)

    def test_no_matching_source_never_sends(self):
        with patch.object(tip, '_rpc_call', return_value={'value': []}) as rpc:
            with self.assertRaisesRegex(ValueError, 'not available'):
                tip._solana_transfer(self.d, 'session', MINT, self.recipient, Decimal('0.03'))
            self.assertFalse(any(c.args[1] == 'sendTransaction' for c in rpc.call_args_list))

if __name__ == '__main__':
    unittest.main()
