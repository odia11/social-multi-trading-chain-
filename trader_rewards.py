"""Earned activity badges. Trade evidence is written only by confirmed execution.

Never infer historical USD volume from today's SOL price, or accept client volume.
Identity verification stays independent from these rolling activity statuses.
"""
from decimal import Decimal, ROUND_DOWN
import datetime as dt
import math
import re
import sqlite3
import time

WINDOW = 30 * 86400
SIG = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{64,88}$')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS reward_activity (
 user_id INTEGER NOT NULL, day TEXT NOT NULL, PRIMARY KEY(user_id,day));
CREATE TABLE IF NOT EXISTS reward_trades (
 signature TEXT PRIMARY KEY, user_id INTEGER NOT NULL, mint TEXT NOT NULL,
 side TEXT NOT NULL, volume_usdc REAL NOT NULL, executed_at REAL NOT NULL,
 eligibility TEXT NOT NULL DEFAULT 'eligible');
CREATE INDEX IF NOT EXISTS reward_trades_user_time ON reward_trades(user_id,executed_at);
CREATE TABLE IF NOT EXISTS reward_fee_discounts (
 signature TEXT PRIMARY KEY, user_id INTEGER NOT NULL, saved_base TEXT NOT NULL,
 currency TEXT NOT NULL, saved_usdc TEXT NOT NULL, charged_bps INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS reward_fee_discounts_user ON reward_fee_discounts(user_id);
'''


def initialize(db):
    with sqlite3.connect(db, timeout=8) as c:
        c.executescript(SCHEMA)


def record_confirmed_trade(db, wallet, signature, mint, side, amount, currency, sol_price, now=None):
    """Internal execution hook, called after confirmation, with realized amounts.

    Deduplicate globally by signature. Rapid repeated trades are excluded; rapid
    reversals are held for review on both legs. This is a conservative abuse
    filter, not a claim that wallet ownership or manipulation can be proven.
    """
    if side not in ('buy', 'sell') or not SIG.fullmatch(str(signature)) or not mint:
        return False
    amount, sol_price = float(amount), float(sol_price or 0)
    if currency not in ('SOL', 'USDC'):
        return False
    volume = amount * sol_price if currency == 'SOL' else amount
    if not math.isfinite(volume) or volume < 1:
        return False
    now = time.time() if now is None else now
    with sqlite3.connect(db, timeout=8) as c:
        c.execute('BEGIN IMMEDIATE')
        user = c.execute('SELECT id FROM users WHERE wallet_address=?', (wallet,)).fetchone()
        if not user or c.execute('SELECT 1 FROM reward_trades WHERE signature=?', (signature,)).fetchone():
            return False
        previous = c.execute('SELECT signature,side,executed_at FROM reward_trades WHERE user_id=? AND mint=? AND executed_at>?',
                             (user[0], mint, now-1800)).fetchall()
        status = 'eligible'
        if any(row[1] != side for row in previous):
            status = 'review'
            c.execute("UPDATE reward_trades SET eligibility='review' WHERE user_id=? AND mint=? AND executed_at>?",
                      (user[0], mint, now-1800))
        elif any(now-row[2] < 600 for row in previous):
            status = 'excluded'
        c.execute('INSERT INTO reward_trades VALUES (?,?,?,?,?,?,?)',
                  (signature, user[0], mint, side, round(volume, 6), now, status))
    return True


def progress(db, wallet, now=None):
    now = time.time() if now is None else now
    with sqlite3.connect(db, timeout=8) as c:
        user = c.execute('SELECT id,created_at FROM users WHERE wallet_address=?', (wallet,)).fetchone()
        if not user:
            return None
        try:
            created = dt.datetime.fromisoformat(str(user[1]).replace('Z', '+00:00'))
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.timezone.utc)
            age = max(0, int((now-created.timestamp())//86400))
        except (ValueError, TypeError):
            age = 0
        rows = c.execute("SELECT volume_usdc,executed_at,eligibility FROM reward_trades WHERE user_id=? AND executed_at>? AND executed_at<=?", (user[0],now-WINDOW,now)).fetchall()
        eligible = [r for r in rows if r[2]=='eligible']
        volume = float(sum((Decimal(str(r[0])) for r in eligible), Decimal(0)).quantize(Decimal('0.01'), rounding=ROUND_DOWN))
        days = len({dt.datetime.fromtimestamp(r[1], dt.timezone.utc).date() for r in eligible})
        active_days = c.execute('SELECT COUNT(*) FROM reward_activity WHERE user_id=? AND day>=? AND day<=?',
                               (user[0], (dt.datetime.fromtimestamp(now,dt.timezone.utc).date()-dt.timedelta(days=29)).isoformat(),dt.datetime.fromtimestamp(now,dt.timezone.utc).date().isoformat())).fetchone()[0]
        status = 'New Member'
        if age>=14 and active_days>=7: status='Active Member'
        if age>=14 and len(eligible)>=5 and days>=3 and volume>=250: status='Active Trader'
        if age>=14 and len(eligible)>=5 and days>=7 and volume>=2500: status='Pro Trader'
        return dict(status=status,account_days=age,active_days=active_days,trades=len(eligible),trading_days=days,
                    volume_usdc=volume,review_trades=sum(r[2]=='review' for r in rows),
                    target_usdc=2500 if status in ('Active Trader','Pro Trader') else 250,
                    percent=min(100,round(volume/(2500 if status in ('Active Trader','Pro Trader') else 250)*100,1)))


def install(d):
    initialize(d.DB_FILE)

    @d.app.before_request
    def record_activity():
        # Authenticated page visits, never anonymous requests, assets or API polls.
        if d.request.method!='GET' or d.request.path not in ('/','/profile','/live-market','/wallet','/referrals'):
            return
        wallet=d._authenticated_wallet()
        if not wallet:return
        try:
            with sqlite3.connect(d.DB_FILE,timeout=2) as c:
                seen=c.execute("SELECT 1 FROM reward_activity a JOIN users u ON u.id=a.user_id WHERE u.wallet_address=? AND a.day=date('now')",(wallet,)).fetchone()
                if not seen:
                    c.execute("INSERT OR IGNORE INTO reward_activity SELECT id,date('now') FROM users WHERE wallet_address=?",(wallet,))
        except sqlite3.Error:
            # Activity bookkeeping cannot block the wallet or market pages.
            pass

    @d.app.context_processor
    def reward_context():
        # Lazy evaluation: ordinary page renders perform no reward queries.
        def reward_status(wallet, details=False):
            try:
                value=progress(d.DB_FILE,wallet)
                if not value:return None
                if details and wallet==d._authenticated_wallet():return value
                return {'status':value['status']}
            except sqlite3.Error:
                return None
        return {'reward_status':reward_status}

    @d.app.route('/rewards')
    def rewards_page():
        return d.redirect('/')

    @d.app.route('/api/rewards/progress')
    def rewards_progress():
        wallet=d._authenticated_wallet()
        if not wallet:return d.jsonify(ok=False,error='Authentication required'),401
        # No wallet/user parameter: caller can only read their own trading volume.
        response=d.jsonify(ok=True,reward=progress(d.DB_FILE,wallet),benefit=benefits(d.DB_FILE,wallet))
        response.headers['Cache-Control']='private, no-store'
        return response

    @d.app.route('/admin/rewards')
    def rewards_review_page():
        err=d._require_role('admin','executive')
        if err:return err
        with sqlite3.connect(d.DB_FILE,timeout=8) as c:
            c.row_factory=sqlite3.Row
            rows=c.execute("SELECT r.signature,r.side,r.volume_usdc,r.mint,u.username "
                           "FROM reward_trades r JOIN users u ON u.id=r.user_id "
                           "WHERE r.eligibility='review' ORDER BY r.executed_at DESC LIMIT 100").fetchall()
        return d._render_no_cache('rewards_review.html',reviews=rows,csrf_token=d._get_csrf_token())

    @d.app.route('/api/admin/rewards/review',methods=['POST'])
    def review_reward_trade():
        err=d._require_role('admin','executive')
        if err:return err
        data=d.request.get_json(silent=True) or {}
        signature=data.get('signature','')
        decision=data.get('decision')
        if not SIG.fullmatch(str(signature)) or decision not in ('eligible','excluded'):
            return d.jsonify(ok=False,error='Invalid review'),400
        with sqlite3.connect(d.DB_FILE,timeout=8) as c:
            result=c.execute("UPDATE reward_trades SET eligibility=? WHERE signature=? AND eligibility='review'",(decision,signature))
        if not result.rowcount:return d.jsonify(ok=False,error='Review not found'),404
        d._log_security_event('reward_trade_review',d._authenticated_wallet(),f'{signature}: {decision}')
        return d.jsonify(ok=True)


NORMAL_FEE_BPS = 75
PRO_FEE_BPS = 70


def manual_trade_fee_bps(db, wallet, now=None):
    """Server-earned Pro benefit, exclusively for manual Live Market trades.

    Unknown status never authorizes a discount. The caller binds the displayed
    maximum fee to execution, so fallback cannot silently exceed that maximum.
    """
    try:
        value = progress(db, wallet, now)
        return PRO_FEE_BPS if value and value['status'] == 'Pro Trader' else NORMAL_FEE_BPS
    except sqlite3.Error:
        return NORMAL_FEE_BPS


def validate_fee_ceiling(value, actual_bps):
    if value is None:
        value = NORMAL_FEE_BPS  # Old clients display the normal maximum.
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= NORMAL_FEE_BPS:
        raise ValueError('Invalid maximum platform fee')
    return actual_bps <= value


def record_fee_discount(db, wallet, signature, gross_base, currency, charged_bps, sol_price):
    """Execution-only receipt: savings are a lower fee, never a cash balance.

    Called only after a confirmed fill with positive evidence of bundled fee
    collection. No client can submit a receipt or spend a saved-fee amount.
    """
    if not SIG.fullmatch(str(signature)) or charged_bps != PRO_FEE_BPS or currency not in ('SOL', 'USDC'):
        return False
    gross = Decimal(str(gross_base))
    rate = Decimal(str(sol_price or 0)) if currency == 'SOL' else Decimal(1)
    if not gross.is_finite() or gross <= 0 or not rate.is_finite() or rate <= 0:
        return False
    units = Decimal(1000000000 if currency == 'SOL' else 1000000)
    normal_fee_raw = int(gross * units * Decimal(NORMAL_FEE_BPS) / Decimal(10000))
    charged_fee_raw = int(gross * units * Decimal(charged_bps) / Decimal(10000))
    saved = Decimal(normal_fee_raw - charged_fee_raw) / units
    if saved <= 0:
        return False
    with sqlite3.connect(db, timeout=8) as c:
        result = c.execute('INSERT OR IGNORE INTO reward_fee_discounts '
            '(signature,user_id,saved_base,currency,saved_usdc,charged_bps) '
            'SELECT ?,id,?,?,?,? FROM users WHERE wallet_address=?',
            (signature,str(saved),currency,str(saved*rate),charged_bps,wallet))
    return bool(result.rowcount)


def benefits(db, wallet, now=None):
    bps = manual_trade_fee_bps(db, wallet, now)
    with sqlite3.connect(db, timeout=8) as c:
        values = c.execute('SELECT r.saved_usdc FROM reward_fee_discounts r JOIN users u ON u.id=r.user_id WHERE u.wallet_address=?', (wallet,)).fetchall()
    savings = sum((Decimal(row[0]) for row in values), Decimal(0))
    return {'manual_fee_bps':bps,'manual_fee_pct':bps/100,
            'standard_fee_pct':NORMAL_FEE_BPS/100,'saved_fees_usdc':str(savings.quantize(Decimal('0.01'),rounding=ROUND_DOWN)),
            'discount_active':bps==PRO_FEE_BPS,'scope':'manual_live_market','cash_payout':False}
