#!/usr/bin/env python3
"""Read-only reconciliation report. Never signs, broadcasts or modifies the DB."""
import argparse
import json
import os
import sqlite3
from pathlib import Path
import requests
from dotenv import dotenv_values


def report(db_path, urls, group, limit):
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    rows = conn.execute('''SELECT t.id,t.state,t.quote,t.plan,t.created FROM group_tips t
        JOIN group_chats g ON g.id=t.chat_id WHERE g.name=? AND t.plan IS NOT NULL
        ORDER BY t.created DESC LIMIT ?''', (group, limit)).fetchall()
    conn.close()
    if not rows:
        print('No submitted tips found for this group.')
    for row in rows:
        q, plan = json.loads(row['quote']), json.loads(row['plan'])
        confirmed = failed = 0
        print('Tip', row['id'], '| app:', row['state'], '| total SOL:', q['total']/1e9,
              '| recipients:', len(q['recipients']))
        for batch in plan:
            observations = []
            for index, url in enumerate(urls[:3]):
                try:
                    response = requests.post(url, json={'jsonrpc':'2.0','id':1,'method':'getTransaction',
                        'params':[batch['signature'],{'commitment':'confirmed','maxSupportedTransactionVersion':0}]}, timeout=8)
                    response.raise_for_status()
                    body = response.json()
                    if body.get('error'):
                        observations.append('RPC error');continue
                    tx = body.get('result')
                    if tx is None:
                        observations.append('not found');continue
                    meta = tx.get('meta')
                    if not isinstance(meta,dict):
                        observations.append('unavailable');continue
                    if meta.get('err') is not None:
                        observations.append('FAILED on-chain');failed += len(batch['users'])
                    else:
                        observations.append('CONFIRMED on-chain');confirmed += len(batch['users'])
                    print('  Network fee SOL:',meta.get('fee',0)/1e9)
                    break
                except Exception as exc:
                    observations.append(type(exc).__name__)
            print('  Batch:',len(batch['users']),'recipients |', ' / '.join(observations))
            print('  Transaction:', batch['signature'])
        print('  Verified delivered:',confirmed,'| verified failed:',failed,
              '| unverified:',len(q['recipients'])-confirmed-failed)
        print('  No payments were sent or retried by this check.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default='/data/orcagent.db')
    parser.add_argument('--env',default='/opt/orcagent/.env')
    parser.add_argument('--group',default='Family John orcagent')
    parser.add_argument('--limit',type=int,default=3)
    args=parser.parse_args()
    env={**dotenv_values(args.env),**os.environ}
    urls=[]
    for url in [env.get('SOLANA_RPC_URL'),env.get('HELIUS_RPC'),
                ('https://mainnet.helius-rpc.com/?api-key='+env['HELIUS_API_KEY']) if env.get('HELIUS_API_KEY') else None,
                'https://solana-rpc.publicnode.com','https://api.mainnet-beta.solana.com']:
        if url and url not in urls:urls.append(url)
    report(args.db,urls,args.group,max(1,min(args.limit,10)))

if __name__=='__main__':
    main()
