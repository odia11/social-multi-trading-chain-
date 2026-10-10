"""Real deposit transaction shapes: RPC index failures, priority fees and swaps."""
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solders.keypair import Keypair
import portfolio_wallet_activity as activity

OWNER = str(Keypair().pubkey())
TOKEN='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN22='TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
COMPUTE='ComputeBudget111111111111111111111111111111'

class DepositDetectionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.NamedTemporaryFile()
        self.d=SimpleNamespace(DB_FILE=self.temp.name,TOKEN_PROGRAM_ID=TOKEN,
            TOKEN_2022_PROGRAM_ID=TOKEN22,_get_trading_wallet_address=lambda _:OWNER)
        activity._TX_CACHE.clear();activity._TOKEN_ACCOUNTS.clear();activity._ACCOUNT_CURSOR.clear()
        self.native={'program':'system','programId':'11111111111111111111111111111111',
            'parsed':{'type':'transfer','info':{'source':'sender','destination':OWNER,'lamports':500000000}}}
        self.tx={'blockTime':200,'meta':{'err':None},'transaction':{'message':{'instructions':[self.native,{'programId':COMPUTE,'data':'priority'}]}}}

    def tearDown(self):
        self.temp.close()

    def rpc(self, _,method,params,**kw):
        if method=='getTokenAccountsByOwner':raise RuntimeError('Index unavailable')
        if method=='getSignaturesForAddress':
            return ([{'signature':'deposit','blockTime':200,'err':None}] if params[0]==OWNER else []),'rpc'
        if method=='getTransaction':return self.tx,'rpc'
        raise AssertionError(method)

    def test_native_sol_survives_both_failed_token_indexes_and_compute_budget(self):
        with patch('portfolio_token_withdraw._rpc_call_any',side_effect=self.rpc):
            events=activity._wallet_events(self.d,'session',since=100)
        self.assertEqual([(e['currency'],e['amount'],e['type']) for e in events],[('SOL',0.5,'receive')])

    def test_spl_receive_with_ata_creation_and_priority_fee(self):
        self.tx['transaction']['message']['instructions']=[
            {'programId':COMPUTE}, {'programId':'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'},
            {'programId':TOKEN,'program':'spl-token'}]
        self.tx['meta']['postTokenBalances']=[{'owner':OWNER,'mint':activity.USDC,'uiTokenAmount':{'amount':'3000000','decimals':6}}]
        with patch('portfolio_token_withdraw._rpc_call_any',side_effect=self.rpc):
            events=activity._wallet_events(self.d,'session',since=100)
        self.assertEqual([(e['currency'],e['amount']) for e in events],[('USDC',3)])

    def test_usdc_ata_is_scanned_without_token_index(self):
        def rpc(d,method,params,**kw):
            if method=='getSignaturesForAddress':
                return ([] if params[0]==OWNER else [{'signature':'deposit','blockTime':200,'err':None}]),'rpc'
            return self.rpc(d,method,params,**kw)
        self.tx['transaction']['message']['instructions']=[{'programId':TOKEN}]
        self.tx['meta']['postTokenBalances']=[{'owner':OWNER,'mint':activity.USDC,'uiTokenAmount':{'amount':'9000000','decimals':6}}]
        with patch('portfolio_token_withdraw._rpc_call_any',side_effect=rpc):
            events=activity._wallet_events(self.d,'session',since=100)
        self.assertEqual(events[0]['amount'],9)

    def test_failed_and_swap_transactions_never_notify(self):
        with patch('portfolio_token_withdraw._rpc_call_any',side_effect=self.rpc):
            self.tx['meta']['err']={'InstructionError':[1,'failed']}
            self.assertEqual(activity._wallet_events(self.d,'session',since=100),[])
            activity._TX_CACHE.clear()
            self.tx['meta']['err']=None
            self.tx['transaction']['message']['instructions'].append({'programId':'UnknownSwapRouter'})
            self.assertEqual(activity._wallet_events(self.d,'session',since=100),[])

    def test_read_transaction_cache_avoids_starving_older_deposits(self):
        with patch('portfolio_token_withdraw._rpc_call_any',side_effect=self.rpc) as rpc:
            activity._wallet_events(self.d,'session',since=100)
            activity._wallet_events(self.d,'session',since=100)
        self.assertEqual(sum(call.args[1]=='getTransaction' for call in rpc.call_args_list),1)

if __name__=='__main__':unittest.main()
