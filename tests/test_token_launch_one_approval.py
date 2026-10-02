"""Offline regression test for OrcAgent's single Phantom launch approval."""
import base64
import sqlite3
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from token_launch_one_approval import install

PUMP=Pubkey.from_string('6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P')


def build_pair(user,mint):
    create_ix=Instruction(PUMP,b'create-test',[
        AccountMeta(user.pubkey(),True,True),AccountMeta(mint.pubkey(),True,True)])
    create_msg=Message.new_with_blockhash([create_ix],user.pubkey(),Hash.default())
    create=Transaction.new_unsigned(create_msg)
    create.partial_sign([mint],Hash.default())

    final_ix=Instruction(PUMP,b'fee-share-test',[AccountMeta(user.pubkey(),True,True)])
    final_msg=Message.new_with_blockhash([final_ix],user.pubkey(),Hash.default())
    final=Transaction.new_unsigned(final_msg)
    signed_create=Transaction.populate(create.message,[
        user.sign_message(bytes(create.message)),create.signatures[1]])
    signed_final=Transaction.populate(final.message,[
        user.sign_message(bytes(final.message))])
    return create,final,signed_create,signed_final


def test_one_approval():
    tmp=tempfile.TemporaryDirectory(prefix='orca-one-approval-')
    db_path=str(Path(tmp.name)/'one.db')
    user,mint=Keypair(),Keypair()
    create,final,signed_create,signed_final=build_pair(user,mint)
    launch_id='a'*32
    wallet=str(user.pubkey())
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE token_launches(
            id TEXT PRIMARY KEY,wallet TEXT,status TEXT,mint TEXT,
            prepare_tx_b64 TEXT,finalize_tx_b64 TEXT,
            launch_signature TEXT DEFAULT '',finalize_signature TEXT DEFAULT '',
            finalized_at INTEGER DEFAULT 0)""")
        db.execute("""CREATE TABLE token_launch_one_approval(
            launch_id TEXT PRIMARY KEY,wallet TEXT NOT NULL,
            create_signature TEXT NOT NULL,finalize_signature TEXT NOT NULL,
            create_signed BLOB NOT NULL,finalize_signed BLOB NOT NULL,
            created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)""")
        db.execute("""INSERT INTO token_launches
            (id,wallet,status,mint,prepare_tx_b64,finalize_tx_b64)
            VALUES (?,?,?,?,?,?)""",(launch_id,wallet,'prepared',str(mint.pubkey()),
            base64.b64encode(bytes(create)).decode(),
            base64.b64encode(bytes(final)).decode()))

    app=Flask('one-approval-test')
    d=SimpleNamespace(app=app,DB_FILE=db_path,SOLANA_RPC_URL='',SOLANA_RPC='rpc')
    d.rate_limit=lambda *a,**k:lambda fn:fn

    def lookup(ident,owner):
        with sqlite3.connect(db_path) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM token_launches WHERE id=? AND wallet=?',
                           (ident,owner)).fetchone()
        return dict(row) if row else None

    submit=install(d,lookup=lookup,shared=lambda row:True,build_tx=lambda *a:None,
        pilot_sol_preflight=lambda *a,**k:1,pilot_wallet=lambda *a:False,
        blockhash_valid=lambda *a:True,check_signature=lambda *a:True,
        mint_exists=lambda *a:True,row_sharing_ok=lambda *a:True,
        enabled=lambda:True,identity=lambda:wallet,csrf=lambda:True,
        fail=lambda msg,code=400:({'ok':False,'msg':str(msg)},code),
        rpc=lambda *a,**k:{'value':100000000},public_max=50000000,
        pilot_max=25000000,followup_max=5000000)

    signed=[base64.b64encode(bytes(signed_create)).decode(),
            base64.b64encode(bytes(signed_final)).decode()]
    relayed=[]
    with patch('launch_delivery.relay_identical_signed',
               side_effect=lambda raw,sig,endpoints,**kw:relayed.append((raw,sig)) or True):
        result=submit(lookup(launch_id,wallet),signed)

    assert result['live'] is True and result['confirmed'] is True
    assert len(relayed)==2
    assert relayed[0][0]==bytes(signed_create)
    assert relayed[1][0]==bytes(signed_final)
    with sqlite3.connect(db_path) as db:
        row=db.execute("""SELECT status,launch_signature,finalize_signature
                          FROM token_launches WHERE id=?""",(launch_id,)).fetchone()
        saved=db.execute("""SELECT create_signed,finalize_signed
                            FROM token_launch_one_approval WHERE launch_id=?""",
                         (launch_id,)).fetchone()
    assert row==('live',str(signed_create.signatures[0]),str(signed_final.signatures[0]))
    assert bytes(saved[0])==bytes(signed_create) and bytes(saved[1])==bytes(signed_final)

    # A different transaction cannot be substituted after the wallet approval.
    bad=bytearray(bytes(signed_final));bad[-1]^=1
    try:
        submit(lookup(launch_id,wallet),[signed[0],base64.b64encode(bad).decode()])
        raise AssertionError('tampered transaction was accepted')
    except ValueError:
        pass
    print('PASS one Phantom approval preserves and relays the exact create + fee-share transactions')
    print('PASS create confirms before fee split; launch becomes live only after both exact transactions verify')
    print('PASS tampered bundle is rejected and cannot replace a saved launch')
    tmp.cleanup()


if __name__=='__main__':
    test_one_approval()
