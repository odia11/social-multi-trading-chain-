"""A swap is confirmed at 'confirmed'; its balance must be read there too.

The RPC's default commitment is 'finalized', ~13s behind 'confirmed'. Reading
the output balance at the default right after confirmation saw the pre-swap
amount, so a swap that had landed was reported as
"Swap confirmed but balance reconciliation failed (... baseline=0 now=0)".
"""
import unittest
from unittest.mock import patch

import orcagent_solana as eng


def fake_rpc(finalized_raw, confirmed_raw, calls):
    def rpc(payload, timeout=30):
        calls.append(payload)
        cfg = next((p for p in payload['params'] if isinstance(p, dict) and 'commitment' in p), {})
        raw = confirmed_raw if cfg.get('commitment') == 'confirmed' else finalized_raw
        if payload['method'] == 'getBalance':
            return {'result': {'value': raw}}
        return {'result': {'value': [{'account': {'data': {'parsed': {'info': {
            'tokenAmount': {'amount': str(raw), 'uiAmount': raw / 1e6}}}}}}]}}
    return rpc


class ReconcileCommitmentTests(unittest.TestCase):
    def test_landed_swap_reconciles_before_it_is_finalized(self):
        calls = []
        with patch.object(eng, '_rpc_post', fake_rpc(0, 20_190_000, calls)), \
             patch.object(eng.time, 'sleep'):
            raw, changed = eng._reconciled_token_balance(eng.USDC_MINT, 'increase', 0)
        self.assertTrue(changed)
        self.assertEqual(raw, 20_190_000)

    def test_balance_reads_ask_for_confirmed(self):
        calls = []
        with patch.object(eng, '_rpc_post', fake_rpc(0, 5, calls)):
            self.assertEqual(eng.get_token_balance_raw(eng.USDC_MINT)[1], 5)
            self.assertEqual(eng._get_sol_balance_raw('owner'), 5)
        self.assertEqual(len(calls), 2)

    def test_swap_that_never_moved_funds_still_fails(self):
        calls = []
        with patch.object(eng, '_rpc_post', fake_rpc(0, 0, calls)), \
             patch.object(eng.time, 'sleep') as sleep:
            raw, changed = eng._reconciled_token_balance(eng.USDC_MINT, 'increase', 0)
        self.assertFalse(changed)
        self.assertEqual(sleep.call_count, 7)


if __name__ == '__main__':
    unittest.main()
