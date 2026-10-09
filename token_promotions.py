"""Paid placements are isolated from organic rankings and trading decisions."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import math
import re
import secrets
import sqlite3
import time
import threading
from urllib.parse import urlparse
from flask import abort, jsonify, make_response, request, session

PACKAGES = {
    'basic': {'name': 'Basic', 'usd': 10, 'hours': 24, 'placements': ['feed']},
    'spotlight': {'name': 'Spotlight', 'usd': 25, 'hours': 24, 'placements': ['feed', 'market']},
    'premium': {'name': 'Premium', 'usd': 50, 'hours': 48, 'placements': ['feed', 'market', 'banner']},
}
CAPACITY = {'feed': 10, 'market': 10, 'banner': 5}
DEMO_WALLET = "Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9"
QUOTE_SECONDS = 600

@contextmanager
def connection(path, write=False):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        if write:
            db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path):
    with connection(path, True) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS promotion_campaigns (
            id INTEGER PRIMARY KEY, wallet TEXT NOT NULL, mint TEXT NOT NULL,
            symbol TEXT NOT NULL, name TEXT NOT NULL, logo TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL, website TEXT NOT NULL, social TEXT NOT NULL,
            package TEXT NOT NULL, price_usd INTEGER NOT NULL, lamports INTEGER NOT NULL,
            payer TEXT NOT NULL, treasury TEXT NOT NULL, created INTEGER NOT NULL,
            quote_until INTEGER NOT NULL, starts INTEGER NOT NULL, ends INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', signature TEXT UNIQUE,
            confirmed INTEGER, payment_method TEXT, last_checked INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS promotion_campaign_owner ON promotion_campaigns(wallet,created);
        CREATE TABLE IF NOT EXISTS promotion_slots (
            campaign INTEGER NOT NULL, placement TEXT NOT NULL, deliveries INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(campaign,placement));
        CREATE TABLE IF NOT EXISTS promotion_deliveries (
            token TEXT PRIMARY KEY, campaign INTEGER NOT NULL, placement TEXT NOT NULL,
            viewer TEXT NOT NULL, created INTEGER NOT NULL, viewed INTEGER, clicked INTEGER);
        CREATE INDEX IF NOT EXISTS promotion_delivery_campaign ON promotion_deliveries(campaign,viewed);
        CREATE INDEX IF NOT EXISTS promotion_delivery_rotation ON promotion_deliveries(campaign,placement,created);
        CREATE TABLE IF NOT EXISTS promotion_used_payments (
            signature TEXT PRIMARY KEY, campaign INTEGER NOT NULL UNIQUE);
        ''')
        columns={r[1] for r in db.execute('PRAGMA table_info(promotion_campaigns)')}
        if 'last_checked' not in columns:
            db.execute('ALTER TABLE promotion_campaigns ADD COLUMN last_checked INTEGER NOT NULL DEFAULT 0')
        db.execute('CREATE TABLE IF NOT EXISTS promotion_migrations(name TEXT PRIMARY KEY)')
        if not db.execute("SELECT 1 FROM promotion_migrations WHERE name='legacy-v1'").fetchone():
            # Preserve IDs, remaining duration, selected placements and payment
            # recovery for purchases made on the old page before this release.
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='promotions'").fetchone()
            if exists:
                for old in db.execute('SELECT * FROM promotions ORDER BY id').fetchall():
                    def epoch(value, fallback):
                        try:
                            return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())
                        except (ValueError,TypeError):
                            return fallback
                    created=epoch(old['created_at'],int(time.time()))
                    start=epoch(old['confirmed_at'],created)
                    end=epoch(old['expires_at'],start+14*3600)
                    db.execute('''INSERT OR IGNORE INTO promotion_campaigns
                        (id,wallet,mint,symbol,name,description,website,social,package,price_usd,lamports,
                        payer,treasury,created,quote_until,starts,ends,status,signature,confirmed,payment_method)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (old['id'],old['wallet'],old['token_mint'] or '',old['token_symbol'],old['token_name'],
                        '', '', '', 'legacy', 0, round(old['amount_sol']*1e9), old['wallet'], '', created,
                        created+QUOTE_SECONDS,start,end,old['status'],old['tx_signature'],start if old['status']=='confirmed' else None,'external'))
                    for place,column in [('feed','show_in_feed'),('market','show_in_market'),('traders','show_in_traders')]:
                        if old[column]:
                            db.execute('INSERT OR IGNORE INTO promotion_slots(campaign,placement) VALUES(?,?)',(old['id'],place))
            db.execute("INSERT INTO promotion_migrations VALUES('legacy-v1')")


def next_slot(db, placements, duration, now, earliest=None):
    """Sweep half-open reservations across every placement, not just start time."""
    rows = db.execute('''SELECT s.placement,c.starts,c.ends FROM promotion_slots s
        JOIN promotion_campaigns c ON c.id=s.campaign
        WHERE c.ends>? AND (c.status='confirmed' OR (c.status='pending' AND c.quote_until>?))''',
        (now, now)).fetchall()
    floor = max(now, earliest or now)
    candidates = sorted({floor} | {r['ends'] for r in rows if r['ends'] >= floor})
    for start in candidates:
        end = start + duration
        valid = True
        for place in placements:
            intervals = [r for r in rows if r['placement'] == place and r['starts'] < end and r['ends'] > start]
            boundaries = {start} | {r['starts'] for r in intervals if start <= r['starts'] < end}
            if any(sum(r['starts'] <= t < r['ends'] for r in intervals) >= CAPACITY[place] for t in boundaries):
                valid = False
                break
        if valid:
            return start, end
    raise ValueError('No promotion slot available')


def safe_url(value):
    value = str(value or '').strip()
    if not value:
        return ''
    parsed = urlparse(value)
    if len(value) > 500 or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a valid HTTPS link')
    return value


def public(row):
    return {k: row[k] for k in ('id','mint','symbol','name','logo','description','website','social','package','starts','ends')}


def verify_payment(d, row):
    """Exact treasury transfer, signer, timestamp and commitment; no balance-delta slack."""
    for rpc in d._PROXY_RPCS:
        try:
            response = d.requests.post(rpc, json={'jsonrpc':'2.0','id':1,'method':'getTransaction',
                'params':[row['signature'], {'encoding':'jsonParsed','commitment':'finalized','maxSupportedTransactionVersion':0}]}, timeout=8)
            tx = response.json().get('result')
            if not tx:
                continue
            if (tx.get('meta') or {}).get('err') is not None:
                return False
            blocktime = tx.get('blockTime')
            if not isinstance(blocktime, int) or blocktime < row['created'] - 30:
                return False
            message = (tx.get('transaction') or {}).get('message') or {}
            if not any(isinstance(k, dict) and k.get('pubkey') == row['payer'] and k.get('signer') for k in message.get('accountKeys', [])):
                return False
            for ix in message.get('instructions', []):
                parsed = ix.get('parsed') or {}
                info = parsed.get('info') or {}
                if (ix.get('program') == 'system' and parsed.get('type') == 'transfer'
                    and info.get('source') == row['payer'] and info.get('destination') == row['treasury']
                    and isinstance(info.get('lamports'), int) and info['lamports'] >= row['lamports']):
                    return True
            return False
        except (ValueError, TypeError, AttributeError, d.requests.RequestException):
            continue
    return False


def install(d):
    initialize(d.DB_FILE)
    app = d.app
    with connection(d.DB_FILE, True) as db:
        db.execute("UPDATE promotion_campaigns SET treasury=? WHERE package='legacy' AND treasury=''", (d.ADMIN_WALLET,))

    def result(**values):
        response = jsonify(ok=True, **values)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def error(message, status=400):
        return jsonify(ok=False, msg=message), status

    def authenticated():
        wallet = d._authenticated_wallet()
        if not wallet:
            abort(make_response(error('Authentication required', 401)))
        if request.method == 'POST' and not d._validate_csrf(request.headers.get('X-CSRF-Token') or request.headers.get('X-CSRFToken') or ''):
            abort(make_response(error('CSRF validation failed', 403)))
        return wallet

    def token_info(mint):
        # Reuse the same canonical lookup and supported-chain selection as trading.
        view = app.view_functions['api_token_info']
        response = view(mint)
        if isinstance(response, tuple):
            response = response[0]
        info = response.get_json()
        if not info or not info.get('ok') or not info.get('symbol') or not info.get('name'):
            raise ValueError('Token could not be verified on Solana. Try again later.')
        if info.get('chain', 'solana') != 'solana' or info.get('address', mint) != mint:
            raise ValueError('Token address does not match the Solana token')
        return info

    @app.get('/api/promote/packages')
    def promotion_packages():
        return result(packages=PACKAGES, capacity=CAPACITY, quote_seconds=QUOTE_SECONDS, can_demo=d._authenticated_wallet()==DEMO_WALLET)

    @d.rate_limit(10, 60)
    def create():
        wallet = authenticated()
        body = request.get_json(silent=True) or {}
        demo=body.get('demo') is True
        if demo and wallet!=DEMO_WALLET:
            return error('Demo mode is restricted to the designated wallet',403)
        package = body.get('package')
        if not isinstance(package, str) or package not in PACKAGES:
            return error('Choose Basic, Spotlight or Premium')
        mint = str(body.get('token_mint') or '').strip()
        if not d.is_valid_solana_address(mint):
            return error('Enter a valid Solana token address')
        try:
            description = str(body.get('description') or '').strip()
            if not 1 <= len(description) <= 120:
                raise ValueError('Description must contain 1–120 characters')
            website, social = safe_url(body.get('website')), safe_url(body.get('social'))
            info = token_info(mint)
            price = float(d._sol_price_usd or 0)
            if not demo and (not math.isfinite(price) or price <= 0):
                return error('SOL price unavailable. No payment quote created.', 503)
            if not d.is_valid_solana_address(d.ADMIN_WALLET):
                return error('Promotion payments are not configured', 503)
            pack = PACKAGES[package]
            amount = 0 if demo else int((Decimal(pack['usd']) / Decimal(str(price)) * 10**9).to_integral_value(rounding=ROUND_CEILING))
            now = int(time.time())
            payer = wallet
            if not demo and body.get('payment_method') == 'trading':
                payer = d._get_trading_wallet_address(wallet)
                if not payer:
                    raise ValueError('Create and fund your trading wallet first')
            method = 'demo' if demo else 'trading' if body.get('payment_method') == 'trading' else 'external'
            with connection(d.DB_FILE, True) as db:
                count = db.execute("SELECT COUNT(*) FROM promotion_campaigns WHERE wallet=? AND status='pending' AND quote_until>?", (wallet, now)).fetchone()[0]
                if count >= 3 and not demo:
                    return error('You already have three open payment quotes. Finish one or wait for expiry.', 429)
                earliest=now
                if body.get('extend_campaign') is not None:
                    try:
                        previous_id=int(body['extend_campaign'])
                    except (ValueError, TypeError):
                        raise ValueError('Invalid campaign to extend')
                    previous=db.execute("SELECT mint,ends FROM promotion_campaigns WHERE id=? AND wallet=? AND status='confirmed'", (previous_id,wallet)).fetchone()
                    if not previous or previous['mint']!=mint:
                        raise ValueError('Campaign to extend was not found for this token')
                    earliest=max(now,previous['ends'])
                start, end = (now,now+pack['hours']*3600) if demo else next_slot(db, pack['placements'], pack['hours'] * 3600, now, earliest=earliest)
                logo = info.get('image_url') or info.get('logo') or ''
                try:
                    logo = safe_url(logo)
                except ValueError:
                    logo = ''
                cur = db.execute('''INSERT INTO promotion_campaigns
                    (wallet,mint,symbol,name,logo,description,website,social,package,price_usd,lamports,payer,treasury,created,quote_until,starts,ends,payment_method)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (wallet,mint,str(info['symbol'])[:20],str(info['name'])[:80],logo,description,website,social,package,pack['usd'],amount,payer,d.ADMIN_WALLET,now,now+QUOTE_SECONDS,start,end,method))
                identifier = cur.lastrowid
                if demo:
                    db.execute("UPDATE promotion_campaigns SET status='demo_pending' WHERE id=?",(identifier,))
                db.executemany('INSERT INTO promotion_slots(campaign,placement) VALUES(?,?)', [(identifier,p) for p in pack['placements']])
            return result(promotion_id=identifier, treasury_wallet=d.ADMIN_WALLET, payer=payer,
                amount_sol=amount/1e9, lamports=amount, amount_usd=pack['usd'], duration_hours=pack['hours'],
                starts=start, ends=end, quote_until=now+QUOTE_SECONDS, payment_method=method,
                network_fee_extra=not demo, demo=demo)
        except ValueError as exc:
            return error(str(exc))

    @d.rate_limit(10, 60)
    def submit(promotion_id):
        wallet = authenticated()
        signature = str((request.get_json(silent=True) or {}).get('tx_signature') or '')
        if not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{64,100}', signature):
            return error('Invalid Solana transaction signature')
        try:
            with connection(d.DB_FILE, True) as db:
                row = db.execute('SELECT * FROM promotion_campaigns WHERE id=? AND wallet=?', (promotion_id,wallet)).fetchone()
                if not row:
                    return error('Campaign not found', 404)
                if row['signature']:
                    return result() if row['signature'] == signature else error('A payment has already been submitted', 409)
                if row['status'] != 'pending':
                    return error('This campaign cannot accept another payment', 409)
                # A delayed broadcast can still be reconciled after quote expiry;
                # it receives the next available slot, never overlaps paid inventory.
                legacy = db.execute('SELECT id FROM promotions WHERE tx_signature=? AND id!=?', (signature,promotion_id)).fetchone()
                if legacy:
                    return error('This payment has already been used', 409)
                db.execute('UPDATE promotion_campaigns SET signature=? WHERE id=?', (signature,promotion_id))
            return result()
        except sqlite3.IntegrityError:
            return error('This payment has already been used', 409)

    def reconcile(identifier, wallet):
        with connection(d.DB_FILE) as db:
            row = db.execute('SELECT * FROM promotion_campaigns WHERE id=? AND wallet=?', (identifier,wallet)).fetchone()
        if row and row['status'] == 'pending' and row['signature']:
            with connection(d.DB_FILE, True) as db:
                db.execute('UPDATE promotion_campaigns SET last_checked=? WHERE id=?',(int(time.time()),identifier))
        if row and row['status'] == 'pending' and row['signature'] and verify_payment(d,row):
            with connection(d.DB_FILE, True) as db:
                current = db.execute('SELECT * FROM promotion_campaigns WHERE id=?', (identifier,)).fetchone()
                if current['status'] == 'pending':
                    now = int(time.time())
                    # Remove own reservation, then atomically rebook from the
                    # later of the promised start and successful confirmation.
                    db.execute("UPDATE promotion_campaigns SET status='rebooking' WHERE id=?", (identifier,))
                    duration = current['ends'] - current['starts']
                    places=[r[0] for r in db.execute('SELECT placement FROM promotion_slots WHERE campaign=?',(identifier,)) if r[0] in CAPACITY]
                    start,end = next_slot(db,places,duration,now,earliest=current['starts'])
                    db.execute('INSERT OR IGNORE INTO promotion_used_payments VALUES(?,?)', (current['signature'],identifier))
                    db.execute("UPDATE promotion_campaigns SET status='confirmed',confirmed=?,starts=?,ends=? WHERE id=?", (now,start,end,identifier))
                row = db.execute('SELECT * FROM promotion_campaigns WHERE id=?', (identifier,)).fetchone()
        return row

    @d.rate_limit(60,60)
    def status(promotion_id):
        wallet = authenticated()
        row = reconcile(promotion_id,wallet)
        if not row:
            return error('Campaign not found',404)
        now = int(time.time())
        state = row['status']
        if state == 'confirmed':
            state = 'scheduled' if row['starts'] > now else 'expired' if row['ends'] <= now else 'active'
        elif row['status']=='demo_active':
            state='demo_active' if row['ends']>now else 'demo_expired'
        elif row['status']=='pending' and not row['signature'] and row['quote_until'] <= now:
            state = 'quote_expired'
        return result(status=state, starts=row['starts'], ends=row['ends'], quote_until=row['quote_until'], tx_signature=row['signature'])

    def simulate(promotion_id):
        wallet=authenticated()
        if wallet!=DEMO_WALLET:
            return error('Demo mode is restricted to the designated wallet',403)
        with connection(d.DB_FILE,True) as db:
            row=db.execute('SELECT * FROM promotion_campaigns WHERE id=? AND wallet=?',(promotion_id,wallet)).fetchone()
            if not row:
                return error('Campaign not found',404)
            if row['payment_method']!='demo':
                return error('A paid campaign cannot be demo-confirmed',403)
            if row['status']=='demo_pending':
                now=int(time.time())
                duration=row['ends']-row['starts']
                db.execute("UPDATE promotion_campaigns SET status='demo_active',confirmed=?,starts=?,ends=? WHERE id=?",(now,now,now+duration,promotion_id))
        return result(status='demo_active',demo=True)


    @app.get('/api/promote/mine')
    @d.rate_limit(60,60)
    def mine():
        wallet = authenticated()
        now = int(time.time())
        # Recover submitted payments even after navigation/restart, without
        # signing or broadcasting another payment.
        with connection(d.DB_FILE) as db:
            pending = db.execute("SELECT id FROM promotion_campaigns WHERE wallet=? AND status='pending' AND signature IS NOT NULL LIMIT 3", (wallet,)).fetchall()
        for p in pending:
            reconcile(p['id'],wallet)
        with connection(d.DB_FILE) as db:
            rows = db.execute('''SELECT c.*, COUNT(v.viewed) AS views,
                COUNT(DISTINCT CASE WHEN v.viewed IS NOT NULL THEN v.viewer END) AS unique_viewers,
                COUNT(v.clicked) AS clicks FROM promotion_campaigns c
                LEFT JOIN promotion_deliveries v ON v.campaign=c.id WHERE c.wallet=?
                GROUP BY c.id ORDER BY c.created DESC LIMIT 100''', (wallet,)).fetchall()
            campaigns=[]
            for row in rows:
                item=public(row)
                item.update(views=row['views'],unique_viewers=row['unique_viewers'],clicks=row['clicks'],
                    ctr=round(100*row['clicks']/row['views'],1) if row['views'] else 0,
                    price_usd=row['price_usd'] if row['package']!='legacy' else None, status=row['status'], quote_until=row['quote_until'],
                    signature=row['signature'], amount_sol=row['lamports']/1e9, lamports=row['lamports'], treasury_wallet=row['treasury'],
                    payment_method=row['payment_method'], payer=row['payer'])
                item['placements']=[r[0] for r in db.execute('SELECT placement FROM promotion_slots WHERE campaign=?',(row['id'],))]
                if row['status']=='confirmed':
                    item['status']='scheduled' if row['starts']>now else 'expired' if row['ends']<=now else 'active'
                elif row['status']=='demo_active':
                    item['status']='demo_active' if row['ends']>now else 'demo_expired'
                elif row['status']=='pending' and not row['signature'] and row['quote_until'] <= now:
                    item['status']='quote_expired'
                item['click_history']=[dict(r) for r in db.execute('''SELECT (clicked/3600)*3600 AS hour,COUNT(*) AS clicks
                    FROM promotion_deliveries WHERE campaign=? AND clicked IS NOT NULL GROUP BY hour ORDER BY hour''',(row['id'],))]
                campaigns.append(item)
        return result(campaigns=campaigns)

    def viewer():
        if 'promotion_viewer' not in session:
            session['promotion_viewer']=secrets.token_hex(24)
        return hashlib.sha256(session['promotion_viewer'].encode()).hexdigest()

    @d.rate_limit(120,60)
    def featured():
        placement=request.args.get('placement')
        if placement not in CAPACITY:
            return error('Invalid placement')
        now=int(time.time())
        person=viewer()
        limit=3 if placement=='market' else 1
        with connection(d.DB_FILE,True) as db:
            # Outstanding selections count too, so concurrent viewers cannot
            # all select the same currently underexposed campaign.
            rows=db.execute('''SELECT c.* FROM promotion_campaigns c JOIN promotion_slots s ON c.id=s.campaign
                WHERE c.status='confirmed' AND c.starts<=? AND c.ends>? AND s.placement=?
                ORDER BY (SELECT COUNT(*) FROM promotion_deliveries v WHERE v.campaign=c.id AND v.placement=s.placement AND (v.viewed IS NOT NULL OR v.created>?)) ASC,
                s.deliveries ASC,c.confirmed ASC,c.id ASC LIMIT ?''',(now,now,placement,now-10,limit)).fetchall()
            ads=[]
            for row in rows:
                receipt=secrets.token_urlsafe(24)
                db.execute('INSERT INTO promotion_deliveries(token,campaign,placement,viewer,created) VALUES(?,?,?,?,?)', (receipt,row['id'],placement,person,now))
                db.execute('UPDATE promotion_slots SET deliveries=deliveries+1 WHERE campaign=? AND placement=?',(row['id'],placement))
                item=public(row)
                item.update(token_symbol=row['symbol'],token_name=row['name'],token_mint=row['mint'],receipt=receipt,sponsored=True)
                ads.append(item)
            # Bound unused receipt storage; retain actual campaign metrics.
            db.execute('DELETE FROM promotion_deliveries WHERE viewed IS NULL AND created<?',(now-86400,))
        return result(promotions=ads)

    @app.post('/api/promote/event')
    @d.rate_limit(120,60)
    def event():
        # Session-bound delivery capability. A caller cannot record another
        # visitor's impression or fabricate arbitrary campaign identifiers.
        body=request.get_json(silent=True) or {}
        event_type=body.get('event')
        if event_type not in ('view','click'):
            return error('Invalid event')
        person=viewer()
        now=int(time.time())
        with connection(d.DB_FILE,True) as db:
            row=db.execute('SELECT * FROM promotion_deliveries WHERE token=? AND viewer=? AND created>?',
                (str(body.get('receipt') or ''),person,now-3600)).fetchone()
            if not row:
                return error('Delivery expired',404)
            if event_type=='view':
                db.execute('UPDATE promotion_deliveries SET viewed=COALESCE(viewed,?) WHERE token=?',(now,row['token']))
            elif row['viewed'] is not None:
                db.execute('UPDATE promotion_deliveries SET clicked=COALESCE(clicked,?) WHERE token=?',(now,row['token']))
        return result()

    @app.get('/api/promote/directory')
    @d.rate_limit(60,60)
    def directory():
        try:
            offset=max(0,int(request.args.get('offset',0)))
        except (ValueError,TypeError):
            return error('Invalid offset')
        query=str(request.args.get('q',''))[:80]
        now=int(time.time())
        with connection(d.DB_FILE) as db:
            rows=db.execute('''SELECT * FROM promotion_campaigns WHERE status='confirmed' AND starts<=? AND ends>?
                AND (instr(lower(symbol),lower(?))>0 OR instr(lower(name),lower(?))>0 OR mint=?)
                ORDER BY id DESC LIMIT 21 OFFSET ?''',(now,now,query,query,query,offset)).fetchall()
        return result(campaigns=[public(r) for r in rows[:20]],has_more=len(rows)>20)

    @app.post('/api/promote/<int:promotion_id>/pay')
    @d.rate_limit(10,60)
    def pay(promotion_id):
        wallet=authenticated()
        from sol_native_payments import native_transfer
        import portfolio_token_withdraw as provider
        try:
            # Existing wallet lock provides idempotent signing. Do not hold
            # a SQLite transaction across network I/O.
            with provider._lock_for(wallet,'solana'):
                with connection(d.DB_FILE) as db:
                    row=db.execute('SELECT * FROM promotion_campaigns WHERE id=? AND wallet=?',(promotion_id,wallet)).fetchone()
                if not row:
                    return error('Campaign not found',404)
                if row['signature']:
                    return result(signature=row['signature'])
                if row['payment_method']!='trading' or row['quote_until']<=time.time():
                    return error('Payment quote expired or wrong wallet selected',409)
                if d._get_trading_wallet_address(wallet)!=row['payer']:
                    return error('Trading wallet changed. Create a new quote.',409)
                # Existing primitive deducts its exact fee from the ceiling.
                # Standard SOL transfer costs 5,000 lamports; ensure the
                # resulting treasury payment is sufficient before confirmation.
                budget=Decimal(row['lamports']+5000)/Decimal(10**9)
                signature,sent=native_transfer(d,wallet,row['treasury'],str(budget),'promotion_payment_'+str(row['id']))
                with connection(d.DB_FILE,True) as db:
                    db.execute('UPDATE promotion_campaigns SET signature=? WHERE id=?',(signature,promotion_id))
                return result(signature=signature,amount_sent=sent)
        except (ValueError,provider._SolanaPreflightError) as exc:
            return error(str(exc))
        except Exception:
            return error('Payment confirmation unavailable. Check My campaigns before retrying.',502)

    # Replace legacy handlers while retaining URLs and all global auth guards.
    for name,view in [('api_promote_create',create),('api_promote_submit_tx',submit),
        ('api_promote_status',status),('api_promote_simulate_confirm',simulate),('api_promote_featured',featured)]:
        app.view_functions[name]=view

    @app.after_request
    def placements_assets(response):
        if response.status_code==200 and response.mimetype=='text/html' and request.path in ('/','/live-market') and not response.direct_passthrough:
            html=response.get_data(as_text=True)
            assets='<meta name="promo-csrf-token" content="'+d._get_csrf_token()+'"><link rel="stylesheet" href="/static/promotions.css?v=1"><script defer src="/static/promotion-placements.js?v=1"></script>'
            response.set_data(html.replace('</head>',assets+'</head>',1))
        return response

    def recover_submitted():
        with connection(d.DB_FILE) as db:
            pending=db.execute("SELECT id,wallet FROM promotion_campaigns WHERE status='pending' AND signature IS NOT NULL ORDER BY last_checked,id LIMIT 3").fetchall()
        for row in pending:
            try:
                reconcile(row['id'],row['wallet'])
            except Exception:
                app.logger.exception('Promotion payment recovery failed id=%s',row['id'])

    app._orca_reconcile_promotions=recover_submitted
    def recovery_loop():
        while True:
            try:
                recover_submitted()
            except Exception:
                app.logger.exception('Promotion recovery sweep failed')
            time.sleep(30)
    threading.Thread(target=recovery_loop,name='promotion-payment-recovery',daemon=True).start()
