"""Call creator pilot: funded fee shares, manual conversion and payout receipts.

No private keys, signing, client trade amounts or estimated cash balances.
"""
from decimal import Decimal, InvalidOperation
import json
import sqlite3
import time
from flask import request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from trader_rewards import SIG

USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
WSOL = 'So11111111111111111111111111111111111111112'
MIN_PAYOUT = 5_000_000
REVIEW_DELAY = 86400
SCHEMA = """
CREATE TABLE IF NOT EXISTS creator_members (
 user_id INTEGER PRIMARY KEY, status TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS creator_earnings (
 signature TEXT PRIMARY KEY, fee_id INTEGER NOT NULL UNIQUE,
 creator_id INTEGER NOT NULL, buyer_id INTEGER NOT NULL, call_id INTEGER NOT NULL,
 mint TEXT NOT NULL, currency TEXT NOT NULL, native_units INTEGER NOT NULL,
 usdc_units INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
 created_at REAL NOT NULL, conversion_signature TEXT, payout_id INTEGER);
CREATE INDEX IF NOT EXISTS creator_earnings_owner ON creator_earnings(creator_id,status);
CREATE TABLE IF NOT EXISTS creator_conversions (
 signature TEXT PRIMARY KEY, sol_units INTEGER NOT NULL, usdc_units INTEGER NOT NULL,
 allocated_sol INTEGER NOT NULL DEFAULT 0, allocated_usdc INTEGER NOT NULL DEFAULT 0,
 block_time REAL NOT NULL);
CREATE TABLE IF NOT EXISTS creator_payouts (
 id INTEGER PRIMARY KEY, creator_id INTEGER NOT NULL, recipient TEXT NOT NULL,
 usdc_units INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'requested',
 signature TEXT UNIQUE, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS creator_audit (
 id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
 detail TEXT NOT NULL, created_at REAL NOT NULL);
"""


def initialize(db):
    with sqlite3.connect(db, timeout=8) as c:
        c.executescript(SCHEMA)


def audit(c, actor, action, detail):
    c.execute('INSERT INTO creator_audit(actor,action,detail,created_at) VALUES(?,?,?,?)',
              (actor, action, json.dumps(detail, sort_keys=True), time.time()))


def approved(c, uid):
    row = c.execute("SELECT status FROM creator_members WHERE user_id=?", (uid,)).fetchone()
    return bool(row and row[0] == 'approved')


def record_fee_share(db, wallet, context, signature, currency, now=None):
    """Internal hook after confirmed execution and committed bundled fee receipt."""
    if not context or not SIG.fullmatch(str(signature)) or currency not in ('SOL','USDC'):
        return False
    now = time.time() if now is None else now
    with sqlite3.connect(db, timeout=8) as c:
        c.execute('BEGIN IMMEDIATE')
        buyer = c.execute('SELECT id FROM users WHERE wallet_address=?', (wallet,)).fetchone()
        if not buyer or buyer[0] != context['buyer_id'] or not approved(c, context['creator_id']):
            return False
        call = c.execute("SELECT user_id,mint,chain FROM token_calls WHERE id=?", (context['call_id'],)).fetchone()
        if not call or call[0] != context['creator_id'] or call[1] != context['mint'] or call[2] not in (None,'','solana'):
            return False
        if buyer[0] == call[0]:
            return False
        trade = c.execute("SELECT user_id,mint,side,eligibility FROM reward_trades WHERE signature=?", (signature,)).fetchone()
        if not trade or tuple(trade[:3]) != (buyer[0],call[1],'buy') or trade[3] == 'excluded':
            return False
        fee = c.execute("SELECT id,fee_amount,chain FROM fees WHERE user_wallet=? AND fee_tx=? AND kind='buy' AND status='ok' ORDER BY id LIMIT 1",
                        (wallet,'bundled:'+signature)).fetchone()
        if not fee or fee[2] not in (None,'','solana'):
            return False
        try:
            amount = Decimal(str(fee[1]))
            units = int(amount * (1_000_000_000 if currency == 'SOL' else 1_000_000)) // 10
        except (InvalidOperation, ValueError, OverflowError):
            return False
        if units <= 0 or units > 10**15:
            return False
        result = c.execute('INSERT OR IGNORE INTO creator_earnings '
            '(signature,fee_id,creator_id,buyer_id,call_id,mint,currency,native_units,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
            (signature,fee[0],call[0],buyer[0],context['call_id'],call[1],currency,units,now))
        return bool(result.rowcount)


def token_delta(tx, owner, mint):
    meta = tx['meta']
    def total(key):
        return sum(int(v['uiTokenAmount']['amount']) for v in meta.get(key,[])
                   if v.get('owner') == owner and v.get('mint') == mint
                   and v['uiTokenAmount'].get('decimals') == (6 if mint == USDC else 9))
    return total('postTokenBalances') - total('preTokenBalances')


def valid_receipt(tx, treasury, after, signature=None):
    if not isinstance(tx,dict) or not tx.get('meta') or tx['meta'].get('err') is not None:
        raise ValueError('Confirmed successful transaction required')
    if not tx.get('blockTime') or tx['blockTime'] < int(after):
        raise ValueError('Receipt predates this reward or payout')
    if signature and (tx['transaction'].get('signatures') or [None])[0] != signature:
        raise ValueError('Receipt signature does not match')
    keys = tx['transaction']['message']['accountKeys']
    if not any(isinstance(k,dict) and k.get('pubkey') == treasury and k.get('signer') for k in keys):
        raise ValueError('Treasury must sign the transaction')
    return keys


def conversion_amounts(tx, treasury, after, signature=None):
    keys = valid_receipt(tx, treasury, after, signature)
    idx = next(i for i,k in enumerate(keys) if k['pubkey'] == treasury)
    meta = tx['meta']
    spent = int(meta['preBalances'][idx]) - int(meta['postBalances'][idx])
    if idx == 0:
        spent -= int(meta['fee'])
    spent -= token_delta(tx,treasury,WSOL)
    received = token_delta(tx,treasury,USDC)
    if spent <= 0 or received <= 0:
        raise ValueError('Receipt must prove treasury SOL spent and USDC received')
    return spent,received


def settle(db, ids, conversion_signature, tx, treasury, actor, now=None):
    """Allocate actual conversion proceeds; never a market-price estimate."""
    now = time.time() if now is None else now
    if not ids or len(ids)>100 or len(set(ids)) != len(ids):
        raise ValueError('Select 1–100 distinct pending rewards')
    if conversion_signature and not SIG.fullmatch(str(conversion_signature)):
        raise ValueError('Invalid conversion signature')
    with sqlite3.connect(db,timeout=8) as c:
        c.execute('BEGIN IMMEDIATE')
        marks=','.join('?' for _ in ids)
        rows=c.execute(f'SELECT signature,creator_id,currency,native_units,created_at FROM creator_earnings WHERE signature IN ({marks}) AND status=\'pending\'',ids).fetchall()
        if len(rows)!=len(ids):
            raise ValueError('Some rewards are no longer pending')
        for sig,uid,cur,units,created in rows:
            t=c.execute('SELECT eligibility FROM reward_trades WHERE signature=?',(sig,)).fetchone()
            if not approved(c,uid) or not t or t[0]!='eligible' or now-created<REVIEW_DELAY:
                raise ValueError('Only approved creators and eligible trades after 24h review can settle')
        sol_rows=[r for r in rows if r[2]=='SOL']
        allocations={r[0]:r[3] for r in rows if r[2]=='USDC'}
        if sol_rows:
            if not conversion_signature or tx is None:
                raise ValueError('SOL rewards require a verified SOL to USDC conversion receipt')
            if c.execute('SELECT 1 FROM creator_payouts WHERE signature=?',(conversion_signature,)).fetchone():
                raise ValueError('Receipt already used as payout')
            spent,received=conversion_amounts(tx,treasury,max(r[4] for r in sol_rows),conversion_signature)
            existing=c.execute('SELECT sol_units,usdc_units,allocated_sol,allocated_usdc FROM creator_conversions WHERE signature=?',(conversion_signature,)).fetchone()
            if existing and existing[:2]!=(spent,received):
                raise ValueError('Conversion evidence changed')
            used_sol,used_usdc=existing[2:] if existing else (0,0)
            total_sol=sum(r[3] for r in sol_rows)
            if total_sol+used_sol>spent:
                raise ValueError('Conversion has insufficient unallocated SOL')
            for sig,uid,cur,units,created in sol_rows:
                allocations[sig]=received*units//spent
                if allocations[sig]<=0:
                    raise ValueError('Reward is too small to convert; keep it pending')
            allocated=sum(allocations[r[0]] for r in sol_rows)
            if used_usdc+allocated>received:
                raise ValueError('Conversion has insufficient USDC')
            c.execute('INSERT OR IGNORE INTO creator_conversions(signature,sol_units,usdc_units,block_time) VALUES(?,?,?,?)',
                      (conversion_signature,spent,received,tx['blockTime']))
            c.execute('UPDATE creator_conversions SET allocated_sol=allocated_sol+?,allocated_usdc=allocated_usdc+? WHERE signature=?',
                      (total_sol,allocated,conversion_signature))
        for sig,uid,cur,units,created in rows:
            c.execute("UPDATE creator_earnings SET status='available',usdc_units=?,conversion_signature=? WHERE signature=?",
                      (allocations[sig],conversion_signature if cur=='SOL' else None,sig))
        audit(c,actor,'settle',dict(rewards=ids,conversion=conversion_signature))
    return sum(allocations.values())


def request_payout(db, uid, now=None):
    now=time.time() if now is None else now
    with sqlite3.connect(db,timeout=8) as c:
        c.execute('BEGIN IMMEDIATE')
        if not approved(c,uid):
            raise ValueError('Creator approval required')
        if c.execute("SELECT 1 FROM creator_payouts WHERE creator_id=? AND status='requested'",(uid,)).fetchone():
            raise ValueError('A payout is already under review')
        # Recheck trade eligibility before reserving the funds.
        amount=c.execute("SELECT COALESCE(SUM(e.usdc_units),0) FROM creator_earnings e JOIN reward_trades t ON t.signature=e.signature WHERE e.creator_id=? AND e.status='available' AND t.eligibility='eligible'",(uid,)).fetchone()[0]
        if amount<MIN_PAYOUT:
            raise ValueError('Minimum payout is 5 USDC')
        wallet=c.execute('SELECT wallet_address FROM users WHERE id=?',(uid,)).fetchone()[0]
        payout=c.execute('INSERT INTO creator_payouts(creator_id,recipient,usdc_units,created_at) VALUES(?,?,?,?)',
                         (uid,wallet,amount,now)).lastrowid
        c.execute("UPDATE creator_earnings SET status='processing',payout_id=? WHERE creator_id=? AND status='available' AND signature IN (SELECT signature FROM reward_trades WHERE eligibility='eligible')",(payout,uid))
        audit(c,wallet,'request_payout',dict(id=payout,usdc_units=amount))
    return payout


def finish_payout(db, payout_id, signature, tx, treasury, actor):
    if not SIG.fullmatch(str(signature)):
        raise ValueError('Invalid payout signature')
    with sqlite3.connect(db,timeout=8) as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT creator_id,recipient,usdc_units,created_at FROM creator_payouts WHERE id=? AND status='requested'",(payout_id,)).fetchone()
        if not row:
            raise ValueError('Pending payout not found')
        uid,recipient,amount,created=row
        valid_receipt(tx,treasury,created,signature)
        if recipient==treasury or token_delta(tx,recipient,USDC)!=amount or token_delta(tx,treasury,USDC)>-amount:
            raise ValueError('Receipt must prove the exact USDC payout to this creator')
        if c.execute('SELECT 1 FROM creator_conversions WHERE signature=?',(signature,)).fetchone() or c.execute('SELECT 1 FROM creator_payouts WHERE signature=?',(signature,)).fetchone():
            raise ValueError('Receipt already used')
        c.execute("UPDATE creator_payouts SET status='paid',signature=? WHERE id=?",(signature,payout_id))
        c.execute("UPDATE creator_earnings SET status='paid' WHERE payout_id=?",(payout_id,))
        audit(c,actor,'paid',dict(id=payout_id,signature=signature,usdc_units=amount))


def summary(db, uid):
    with sqlite3.connect(db,timeout=8) as c:
        c.row_factory=sqlite3.Row
        member=c.execute('SELECT status FROM creator_members WHERE user_id=?',(uid,)).fetchone()
        rows=c.execute("SELECT e.signature,e.call_id,e.currency,e.native_units,e.usdc_units,CASE WHEN e.status='available' AND COALESCE(t.eligibility,'')!='eligible' THEN 'held' ELSE e.status END AS status,e.created_at FROM creator_earnings e LEFT JOIN reward_trades t ON t.signature=e.signature WHERE e.creator_id=? ORDER BY e.created_at DESC LIMIT 100",(uid,)).fetchall()
        totals=c.execute("SELECT CASE WHEN e.status='available' AND COALESCE(t.eligibility,'')!='eligible' THEN 'held' ELSE e.status END AS effective_status,e.currency,SUM(e.native_units),SUM(e.usdc_units) FROM creator_earnings e LEFT JOIN reward_trades t ON t.signature=e.signature WHERE e.creator_id=? GROUP BY effective_status,e.currency",(uid,)).fetchall()
        payouts=c.execute('SELECT id,usdc_units,status,signature,created_at FROM creator_payouts WHERE creator_id=? ORDER BY id DESC LIMIT 30',(uid,)).fetchall()
    values=dict(available=0,processing=0,paid=0,pending_sol=0,pending_usdc=0,held_usdc=0)
    for status,cur,native,usdc in totals:
        if status in ('available','processing','paid'):
            values[status]+=usdc
        elif status=='pending':
            values['pending_sol' if cur=='SOL' else 'pending_usdc']+=native
        elif status=='held':
            values['held_usdc']+=usdc
    return dict(status=member['status'] if member else 'not_enrolled',totals=values,
                rewards=[dict(r) for r in rows],payouts=[dict(r) for r in payouts])


def install(d):
    app=d.app
    if getattr(app,'_orca_creator_rewards',False):return
    app._orca_creator_rewards=True
    initialize(d.DB_FILE)
    signer=URLSafeTimedSerializer(app.secret_key,salt='orca-creator-call-v1')
    def owner():
        wallet=d._authenticated_wallet()
        if not wallet:return None
        with sqlite3.connect(d.DB_FILE,timeout=8) as c:
            row=c.execute('SELECT id FROM users WHERE wallet_address=?',(wallet,)).fetchone()
        return row[0] if row else None

    def csrf():
        if not d._validate_csrf(request.headers.get('X-CSRF-Token','')):
            return d.jsonify(ok=False,error='Refresh and try again'),403

    def context(wallet,mint,token):
        if not isinstance(token,str) or len(token)>2048:return None
        try:value=signer.loads(token,max_age=1800)
        except BadSignature:return None
        if not isinstance(value,dict) or value.get('mint')!=mint:return None
        with sqlite3.connect(d.DB_FILE,timeout=8) as c:
            buyer=c.execute('SELECT id FROM users WHERE wallet_address=?',(wallet,)).fetchone()
            call=c.execute("SELECT user_id,mint FROM token_calls WHERE id=? AND COALESCE(chain,'') IN ('','solana')",(value.get('call_id'),)).fetchone()
            if not buyer or not call or call[1]!=mint or buyer[0]==call[0] or not approved(c,call[0]):return None
        return dict(buyer_id=buyer[0],creator_id=call[0],call_id=value['call_id'],mint=mint)
    app._orca_creator_context=context
    app._orca_creator_record=lambda wallet,ctx,sig,cur:record_fee_share(d.DB_FILE,wallet,ctx,sig,cur)

    @app.after_request
    def private(response):
        if request.path.startswith(('/creator-rewards','/api/creator-rewards','/admin/creator-rewards','/api/admin/creator-rewards')):
            response.headers['Cache-Control']='private, no-store'
        return response

    @app.route('/call/<int:call_id>/trade')
    @d.rate_limit(60,60)
    def call_trade(call_id):
        from call_invitations import public_call
        value=public_call(d.DB_FILE,call_id)
        if not value or not d.is_valid_solana_address(value['mint']):return 'Call not found',404
        with sqlite3.connect(d.DB_FILE,timeout=8) as c:active=approved(c,value['author_id'])
        from urllib.parse import urlencode
        args=dict(mint=value['mint'])
        if active:args['creator_context']=signer.dumps(dict(call_id=call_id,mint=value['mint']))
        return d.redirect('/live-market?'+urlencode(args))

    @app.route('/creator-rewards')
    def page():
        # The standalone call-based Creator Rewards page was retired from the
        # product UI. Keep this redirect for old bookmarks/shared links so
        # users land back in the main app instead of a dead page.
        return d.redirect('/')

    @app.route('/api/creator-rewards')
    def own():
        uid=owner()
        if uid is None:return d.jsonify(ok=False,error='Connect your wallet'),401
        return d.jsonify(ok=True,**summary(d.DB_FILE,uid))

    @app.route('/api/creator-rewards/apply',methods=['POST'])
    @d.rate_limit(5,60)
    def apply():
        uid=owner()
        if uid is None:return d.jsonify(ok=False,error='Connect your wallet'),401
        err=csrf()
        if err:return err
        with sqlite3.connect(d.DB_FILE,timeout=8) as c:
            c.execute("INSERT OR IGNORE INTO creator_members VALUES(?,'applied',?)",(uid,time.time()))
            audit(c,d._authenticated_wallet(),'apply',dict(user_id=uid))
        return d.jsonify(ok=True)

    @app.route('/api/creator-rewards/payout',methods=['POST'])
    @d.rate_limit(5,60)
    def payout():
        uid=owner()
        if uid is None:return d.jsonify(ok=False,error='Connect your wallet'),401
        err=csrf()
        if err:return err
        with sqlite3.connect(d.DB_FILE,timeout=8) as c:wallet=c.execute('SELECT wallet_address FROM users WHERE id=?',(uid,)).fetchone()[0]
        if not d.is_valid_solana_address(wallet):return d.jsonify(ok=False,error='A Solana wallet is required'),400
        try:pid=request_payout(d.DB_FILE,uid)
        except ValueError as e:return d.jsonify(ok=False,error=str(e)),409
        return d.jsonify(ok=True,payout_id=pid)

    @app.route('/admin/creator-rewards')
    def review():
        err=d._require_role('admin','executive')
        if err:return err
        with sqlite3.connect(d.DB_FILE,timeout=8) as c:
            c.row_factory=sqlite3.Row
            members=[dict(r) for r in c.execute('SELECT m.*,u.username FROM creator_members m JOIN users u ON u.id=m.user_id ORDER BY m.updated_at DESC LIMIT 100')]
            earnings=[dict(r) for r in c.execute("SELECT e.*,u.username,t.eligibility FROM creator_earnings e JOIN users u ON u.id=e.creator_id JOIN reward_trades t ON t.signature=e.signature WHERE e.status IN ('pending','held') ORDER BY e.created_at LIMIT 100")]
            payouts=[dict(r) for r in c.execute("SELECT p.*,u.username FROM creator_payouts p JOIN users u ON u.id=p.creator_id WHERE p.status='requested' ORDER BY p.id LIMIT 100")]
        return d._render_no_cache('creator_rewards_admin.html',members=members,earnings=earnings,payouts=payouts,csrf_token=d._get_csrf_token())

    def transaction(signature):
        if not SIG.fullmatch(str(signature)):raise ValueError('Invalid signature')
        for url in d.CLAIM_SOL_RPCS:
            try:
                r=d.requests.post(url,json=dict(jsonrpc='2.0',id=1,method='getTransaction',params=[signature,dict(encoding='jsonParsed',commitment='finalized',maxSupportedTransactionVersion=0)]),timeout=12)
                value=r.json().get('result')
                if value:return value
            except (ValueError,d.requests.RequestException):continue
        raise ValueError('Finalized receipt not available; try again later')

    @app.route('/api/admin/creator-rewards/<action>',methods=['POST'])
    def admin_action(action):
        err=d._require_role('admin','executive')
        if err:return err
        err=csrf()
        if err:return err
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return d.jsonify(ok=False,error='Invalid request'),400
        actor=d._authenticated_wallet()
        try:
            if action=='member':
                uid=data.get('user_id');status=data.get('status')
                if type(uid) is not int or status not in ('approved','paused','rejected'):raise ValueError('Invalid creator')
                with sqlite3.connect(d.DB_FILE,timeout=8) as c:
                    if not c.execute('SELECT 1 FROM creator_members WHERE user_id=?',(uid,)).fetchone():raise ValueError('Application not found')
                    wallet=c.execute('SELECT wallet_address FROM users WHERE id=?',(uid,)).fetchone()
                    if status=='approved' and (not wallet or not d.is_valid_solana_address(wallet[0])):raise ValueError('A Solana account wallet is required')
                    c.execute('UPDATE creator_members SET status=?,updated_at=? WHERE user_id=?',(status,time.time(),uid))
                    audit(c,actor,'member',dict(user_id=uid,status=status))
            elif action=='settle':
                ids=data.get('signatures')
                if not isinstance(ids,list) or not all(isinstance(x,str) and SIG.fullmatch(x) for x in ids):raise ValueError('Invalid reward selection')
                signature=data.get('conversion_signature') or None
                with sqlite3.connect(d.DB_FILE,timeout=8) as c:
                    needs_sol=any(c.execute("SELECT 1 FROM creator_earnings WHERE signature=? AND currency='SOL'",(s,)).fetchone() for s in ids)
                tx=transaction(signature) if needs_sol else None
                settle(d.DB_FILE,ids,signature,tx,d.FEE_WALLET,actor)
            elif action=='paid':
                pid=data.get('payout_id');signature=data.get('signature')
                if type(pid) is not int:raise ValueError('Invalid payout')
                finish_payout(d.DB_FILE,pid,signature,transaction(signature),d.FEE_WALLET,actor)
            else:raise ValueError('Unknown action')
        except (ValueError,sqlite3.IntegrityError) as e:return d.jsonify(ok=False,error=str(e)),409
        return d.jsonify(ok=True)
