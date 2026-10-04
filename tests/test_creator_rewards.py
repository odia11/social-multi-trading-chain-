"""Money boundaries for the creator pilot; synthetic receipts only."""
import copy
import sqlite3
import tempfile
from pathlib import Path
import unittest
import creator_rewards as cr

SIG='3'*88
CONV='4'*88
PAY='5'*88
TREASURY='treasury'


def balance(owner,mint,units,idx=1):
    return dict(accountIndex=idx,owner=owner,mint=mint,
                uiTokenAmount=dict(amount=str(units),decimals=6 if mint==cr.USDC else 9))


def receipt(sol_spent=2_000_000_000,usdc_received=200_000_000):
    return dict(blockTime=200,transaction=dict(signatures=[CONV],message=dict(accountKeys=[dict(pubkey=TREASURY,signer=True)])),
                meta=dict(err=None,fee=5000,preBalances=[sol_spent+5000],postBalances=[0],
                          preTokenBalances=[balance(TREASURY,cr.USDC,0)],
                          postTokenBalances=[balance(TREASURY,cr.USDC,usdc_received)]))


class CreatorRewards(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=str(Path(self.tmp.name)/'db')
        with sqlite3.connect(self.db) as c:
            c.executescript("""
CREATE TABLE users(id INTEGER PRIMARY KEY,wallet_address TEXT);
INSERT INTO users VALUES(1,'creator'),(2,'buyer'),(3,'other');
CREATE TABLE token_calls(id INTEGER PRIMARY KEY,user_id INTEGER,mint TEXT,chain TEXT);
INSERT INTO token_calls VALUES(7,1,'mint','solana');
CREATE TABLE reward_trades(signature TEXT PRIMARY KEY,user_id INTEGER,mint TEXT,side TEXT,eligibility TEXT);
CREATE TABLE fees(id INTEGER PRIMARY KEY,user_wallet TEXT,fee_amount REAL,fee_tx TEXT,kind TEXT,status TEXT,chain TEXT);
""")
        cr.initialize(self.db)
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO creator_members VALUES(1,'approved',0)")
            c.execute("INSERT INTO reward_trades VALUES(?,2,'mint','buy','eligible')",(SIG,))
            c.execute("INSERT INTO fees VALUES(1,'buyer',10,?,'buy','ok','solana')",('bundled:'+SIG,))
        self.ctx=dict(buyer_id=2,creator_id=1,call_id=7,mint='mint')

    def tearDown(self):
        self.tmp.cleanup()

    def record(self):
        return cr.record_fee_share(self.db,'buyer',self.ctx,SIG,'SOL',100)

    def settle(self):
        return cr.settle(self.db,[SIG],CONV,receipt(),TREASURY,'admin',90000)

    def test_only_ten_percent_of_received_fee_and_signature_dedup(self):
        self.assertTrue(self.record())
        self.assertFalse(self.record())
        self.assertEqual(cr.summary(self.db,1)['totals']['pending_sol'],1_000_000_000)
        self.assertEqual(cr.summary(self.db,2)['rewards'],[])

    def test_unapproved_self_wrong_mint_and_missing_receipt_never_earn(self):
        for mutation in [
            "UPDATE creator_members SET status='paused'",
            "UPDATE token_calls SET user_id=2",
            "UPDATE token_calls SET mint='other'",
            "UPDATE fees SET status='failed'",
            "UPDATE fees SET fee_tx='bundled-in-swap'",
            "UPDATE reward_trades SET side='sell'",
            "UPDATE reward_trades SET eligibility='excluded'",
        ]:
            with self.subTest(mutation=mutation):
                with sqlite3.connect(self.db) as c:c.execute(mutation)
                self.assertFalse(self.record())
                with sqlite3.connect(self.db) as c:
                    c.execute("UPDATE creator_members SET status='approved'")
                    c.execute("UPDATE token_calls SET user_id=1,mint='mint'")
                    c.execute("UPDATE fees SET status='ok',fee_tx=?",('bundled:'+SIG,))
                    c.execute("UPDATE reward_trades SET side='buy',eligibility='eligible'")

    def test_pending_sol_is_not_spendable_usdc(self):
        self.record()
        with self.assertRaises(ValueError):cr.request_payout(self.db,1)
        self.assertEqual(cr.summary(self.db,1)['totals']['available'],0)

    def test_actual_conversion_proceeds_are_allocated_proportionally_once(self):
        self.record()
        self.assertEqual(self.settle(),100_000_000)
        with self.assertRaises(ValueError):self.settle()
        self.assertEqual(cr.summary(self.db,1)['totals']['available'],100_000_000)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT allocated_sol,allocated_usdc FROM creator_conversions').fetchone(),(1_000_000_000,100_000_000))

    def test_conversion_cannot_overallocate_or_use_failed_old_foreign_receipt(self):
        self.record()
        variants=[]
        small=receipt(sol_spent=10);variants.append(small)
        failed=receipt();failed['meta']['err']={'InstructionError':[0,'fail']};variants.append(failed)
        old=receipt();old['blockTime']=90;variants.append(old)
        foreign=receipt();foreign['transaction']['message']['accountKeys'][0]['pubkey']='attacker';variants.append(foreign)
        no_usdc=receipt(usdc_received=0);variants.append(no_usdc)
        for tx in variants:
            with self.subTest(tx=tx):
                with self.assertRaises(ValueError):cr.settle(self.db,[SIG],CONV,tx,TREASURY,'admin',90000)
        self.assertEqual(cr.summary(self.db,1)['totals']['available'],0)

    def test_review_delay_and_reversal_hold_block_settlement(self):
        self.record()
        with self.assertRaises(ValueError):cr.settle(self.db,[SIG],CONV,receipt(),TREASURY,'admin',200)
        with sqlite3.connect(self.db) as c:c.execute("UPDATE reward_trades SET eligibility='review'")
        with self.assertRaises(ValueError):self.settle()

    def test_atomic_payout_reservation_and_exact_verified_payment(self):
        self.record();self.settle()
        pid=cr.request_payout(self.db,1,100000)
        with self.assertRaises(ValueError):cr.request_payout(self.db,1,100001)
        summary=cr.summary(self.db,1)['totals']
        self.assertEqual((summary['available'],summary['processing'],summary['paid']),(0,100_000_000,0))
        tx=receipt();tx['blockTime']=100010;tx['transaction']['signatures']=[PAY]
        tx['meta']['preTokenBalances']=[balance(TREASURY,cr.USDC,100_000_000),balance('creator',cr.USDC,0,2)]
        tx['meta']['postTokenBalances']=[balance(TREASURY,cr.USDC,0),balance('creator',cr.USDC,100_000_000,2)]
        wrong=copy.deepcopy(tx);wrong['meta']['postTokenBalances'][1]['owner']='attacker'
        with self.assertRaises(ValueError):cr.finish_payout(self.db,pid,PAY,wrong,TREASURY,'admin')
        self.assertEqual(cr.summary(self.db,1)['totals']['paid'],0)
        cr.finish_payout(self.db,pid,PAY,tx,TREASURY,'admin')
        with self.assertRaises(ValueError):cr.finish_payout(self.db,pid,PAY,tx,TREASURY,'admin')
        self.assertEqual(cr.summary(self.db,1)['totals']['paid'],100_000_000)

    def test_trade_review_and_creator_pause_block_payout_request(self):
        self.record();self.settle()
        with sqlite3.connect(self.db) as c:c.execute("UPDATE reward_trades SET eligibility='review'")
        with self.assertRaises(ValueError):cr.request_payout(self.db,1)
        self.assertEqual(cr.summary(self.db,1)['totals']['available'],0)
        self.assertEqual(cr.summary(self.db,1)['totals']['held_usdc'],100_000_000)
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE reward_trades SET eligibility='eligible'")
            c.execute("UPDATE creator_members SET status='paused'")
        with self.assertRaises(ValueError):cr.request_payout(self.db,1)

    def test_distinct_rewards_cannot_reuse_conversion_capacity(self):
        self.record()
        self.settle()
        sig='6'*88
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO reward_trades VALUES(?,2,'mint','buy','eligible')",(sig,))
            c.execute("INSERT INTO fees VALUES(2,'buyer',20,?,'buy','ok','solana')",('bundled:'+sig,))
        self.assertTrue(cr.record_fee_share(self.db,'buyer',self.ctx,sig,'SOL',100))
        with self.assertRaises(ValueError):cr.settle(self.db,[sig],CONV,receipt(),TREASURY,'admin',90000)
        self.assertEqual(cr.summary(self.db,1)['totals']['available'],100_000_000)


if __name__=='__main__':
    unittest.main()
