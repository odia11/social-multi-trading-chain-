"""Execute the real swap pipeline against mocked providers; never broadcast."""
import contextlib
import io
import unittest
from unittest.mock import Mock, patch
from solders.keypair import Keypair
import orcagent_solana as eng

class FakeTx:
    message = object()
    def __init__(self, *args): pass
    @classmethod
    def from_bytes(cls, raw): return cls()
    def __bytes__(self): return b'fixture-only'

class NativeSwapTests(unittest.TestCase):
    def run_swap(self, input_mint, output_mint, token_values, native_values=(), failed=False):
        key = Keypair()
        token_reads = []
        values = iter(token_values)
        def token(mint):
            token_reads.append(mint)
            # Native SOL must never be looked up as an SPL token account.
            self.assertNotEqual(mint, eng.SOL_MINT)
            value = next(values)
            return value / 1e6, value
        quote = Mock(status_code=200)
        quote.json.return_value = {'outAmount':'43000000','priceImpactPct':'0'}
        build = Mock(status_code=200)
        build.json.return_value = {'swapTransaction':'Zml4dHVyZQ=='}
        native = Mock(side_effect=native_values)
        confirmation = {'status':'failed' if failed else 'confirmed',
                        'confirmed':not failed,'confirmation_time_s':1,'err':'fixture failure'}
        with patch.object(eng, 'get_token_balance_raw', side_effect=token), \
             patch.object(eng, '_get_sol_balance_raw', native), \
             patch.object(eng, 'VersionedTransaction', FakeTx), \
             patch.object(eng.requests, 'get', return_value=quote), \
             patch.object(eng.requests, 'post', return_value=build), \
             patch.object(eng, '_rpc_post', return_value={'result':'fixture-signature'}) as rpc, \
             patch.object(eng, '_confirm_transaction', return_value=confirmation), \
             patch.object(eng.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            result = eng._execute_swap_inner(input_mint,output_mint,5191906,
                       wallet_address=str(key.pubkey()),private_key=str(key))
        self.assertEqual(rpc.call_count,1)
        return result, token_reads, native.call_count

    def test_usdc_to_native_sol_uses_input_decrease_and_native_output(self):
        result, reads, native = self.run_swap(eng.USDC_MINT,eng.SOL_MINT,
                                               [5191906,0],[134016000,177000000])
        self.assertEqual(result,('fixture-signature','42984000'))
        self.assertEqual(reads,[eng.USDC_MINT,eng.USDC_MINT])
        self.assertEqual(native,2)

    def test_sol_to_usdc_still_reconciles_output_increase(self):
        result, reads, native = self.run_swap(eng.SOL_MINT,eng.USDC_MINT,[0,5191906])
        self.assertEqual(result,('fixture-signature','5191906'))
        self.assertEqual(reads,[eng.USDC_MINT,eng.USDC_MINT])
        self.assertEqual(native,0)

    def test_token_sell_to_sol_preserves_native_reporting(self):
        result, reads, native = self.run_swap('token-fixture',eng.SOL_MINT,
                                              [5191906,0],[134016000,177000000])
        self.assertEqual(result,('fixture-signature','42984000'))
        self.assertEqual(reads,['token-fixture','token-fixture'])
        self.assertEqual(native,2)

    def test_no_input_movement_does_not_report_success(self):
        with self.assertRaisesRegex(Exception,'reconciliation failed'):
            self.run_swap(eng.USDC_MINT,eng.SOL_MINT,[5191906]*13,[134016000])

    def test_onchain_failure_does_not_report_success(self):
        with self.assertRaisesRegex(Exception,'failed on-chain'):
            self.run_swap(eng.USDC_MINT,eng.SOL_MINT,[5191906],[134016000],failed=True)

if __name__=='__main__': unittest.main()
