"""Read-only, confirmed launch identity and current bonding curve snapshot."""
import json
import os
import sqlite3
import subprocess
from contextlib import closing


def lookup(db_file, base, mint, sol_usd=0):
    with closing(sqlite3.connect(db_file)) as db:
        db.row_factory=sqlite3.Row
        row=db.execute("""SELECT id,name,symbol,description,quote_asset,created_at
            FROM token_launches WHERE mint=? AND status='live' AND launch_signature<>''""",(mint,)).fetchone()
    if row is None:
        return None
    result={'ok':True,'address':mint,'chain':'solana','name':row['name'],
        'symbol':row['symbol'],'description':row['description'],
        'image_url':'/token-launch/icon/'+row['id'],
        'logo_url':'/token-launch/icon/'+row['id'],
        'quote_asset':row['quote_asset'],'source':'orcagent_launch',
        'pair_address':'','pair_created_at':row['created_at']*1000,
        'price_usd':None,'price':None,'market_cap':None,'mcap':None,
        'liquidity_usd':None,'volume_24h':None,'price_change_24h':None,
        'buyers_24h':None,'sellers_24h':None}
    try:
        runner=os.path.join(base,'pump_adapter','run-node.sh')
        helper=os.path.join(base,'pump_adapter','read-curve.cjs')
        proc=subprocess.run(['/bin/bash',runner,helper,mint],cwd=os.path.join(base,'pump_adapter'),
            capture_output=True,text=True,timeout=12,check=False)
        if proc.returncode or not proc.stdout:
            return result
        snapshot=json.loads(proc.stdout)
        if snapshot['quote_asset']!=row['quote_asset']:
            return result
        result.update(price_quote=snapshot['price_quote'],
            market_cap_quote=snapshot['market_cap_quote'],
            curve_complete=snapshot['complete'],source='solana_bonding_curve')
        factor=1 if row['quote_asset']=='USDC' else float(sol_usd or 0)
        if factor>0:
            result.update(price_usd=snapshot['price_quote']*factor,
                price=snapshot['price_quote']*factor,
                market_cap=snapshot['market_cap_quote']*factor,
                mcap=snapshot['market_cap_quote']*factor)
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired):
        pass
    return result
