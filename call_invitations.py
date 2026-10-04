"""Public call cards and first-touch invites; private, confirmed conversion totals.

No client trade counters, wallet balances, payout rules or signing operations.
"""
from __future__ import annotations

import io
from functools import lru_cache
import math
from pathlib import Path
import re
import secrets
import sqlite3
import time

BASE = 'https://orcagent.fun'
COOKIE = 'orca_invite'
WINDOW = 30 * 86400
CODE = re.compile(r'^[A-Z0-9]{8,16}$')
TOKEN = re.compile(r'^[A-Za-z0-9_-]{24}$')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS call_share_links (
 token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, call_id INTEGER NOT NULL,
 created_at REAL NOT NULL, UNIQUE(user_id,call_id));
CREATE TABLE IF NOT EXISTS invitation_accounts (
 user_id INTEGER PRIMARY KEY, created_at REAL NOT NULL, verified_at REAL,
 pending_json TEXT);
CREATE TABLE IF NOT EXISTS call_invitation_attributions (
 user_id INTEGER PRIMARY KEY, referrer_id INTEGER NOT NULL,
 share_token TEXT, call_id INTEGER, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS call_invitation_owner ON call_invitation_attributions(referrer_id,created_at);
'''


def initialize(path):
    with sqlite3.connect(path, timeout=10) as c:
        c.executescript(SCHEMA)


def public_call(path, call_id):
    with sqlite3.connect(path, timeout=10) as c:
        c.row_factory = sqlite3.Row
        row = c.execute('''SELECT t.id,t.mint,t.symbol,t.note,t.price_at_call,
            t.timestamp,t.post_id,t.chain,t.token_name,t.image_url,u.id AS author_id,u.username,u.is_verified
            FROM token_calls t JOIN users u ON u.id=t.user_id WHERE t.id=?
            AND COALESCE(t.chain,'') IN ('','solana')''', (call_id,)).fetchone()
    return dict(row) if row else None


def resolve_invite(c, *, token=None, code=None):
    if isinstance(token, str) and TOKEN.fullmatch(token):
        row = c.execute('''SELECT s.user_id,s.token,s.call_id,u.username FROM call_share_links s
            JOIN users u ON u.id=s.user_id JOIN token_calls t ON t.id=s.call_id
            WHERE s.token=? AND COALESCE(t.chain,'') IN ('','solana')''', (token,)).fetchone()
        if row:
            return dict(referrer_id=row[0],share_token=row[1],call_id=row[2],username=row[3] or 'OrcAgent trader')
    if isinstance(code, str) and CODE.fullmatch(code):
        row = c.execute('SELECT id,username FROM users WHERE referral_code=?', (code,)).fetchone()
        if row:
            return dict(referrer_id=row[0],share_token=None,call_id=None,username=row[1] or 'OrcAgent trader')
    return None


def complete_signup(path, uid, invite, now=None):
    """Only first proven login of an account created after installation is eligible."""
    import json
    now = time.time() if now is None else now
    with sqlite3.connect(path, timeout=10) as c:
        c.execute('BEGIN IMMEDIATE')
        account = c.execute('SELECT created_at,verified_at,pending_json FROM invitation_accounts WHERE user_id=?', (uid,)).fetchone()
        if not account or account[1] is not None:
            return False
        c.execute('UPDATE invitation_accounts SET verified_at=? WHERE user_id=?', (now,uid))
        # Pending referral was captured at account creation, before a wallet
        # onboarding flow may change cookies. A later link cannot replace it.
        invite = json.loads(account[2]) if account[2] else invite
        if not invite or now-account[0]>WINDOW or invite.get('referrer_id') == uid:
            return False
        referrer = c.execute('SELECT wallet_address FROM users WHERE id=?', (invite.get('referrer_id'),)).fetchone()
        user = c.execute('SELECT referred_by FROM users WHERE id=?', (uid,)).fetchone()
        if not referrer or not user or user[0] and user[0]!=referrer[0]:
            return False
        c.execute('UPDATE users SET referred_by=? WHERE id=? AND (referred_by IS NULL OR referred_by=\'\')', (referrer[0],uid))
        c.execute('INSERT OR IGNORE INTO call_invitation_attributions VALUES (?,?,?,?,?)',
                  (uid,invite['referrer_id'],invite.get('share_token'),invite.get('call_id'),now))
        return True


def metrics(path, uid):
    """Aggregate only; do not return referred users' identities or balances."""
    with sqlite3.connect(path, timeout=10) as c:
        signups = c.execute('SELECT COUNT(*) FROM call_invitation_attributions WHERE referrer_id=?', (uid,)).fetchone()[0]
        links = c.execute('SELECT COUNT(*) FROM call_share_links WHERE user_id=?', (uid,)).fetchone()[0]
        trades = c.execute('''SELECT r.user_id,r.volume_usdc FROM reward_trades r
            JOIN call_invitation_attributions a ON a.user_id=r.user_id
            WHERE a.referrer_id=? AND r.executed_at>=a.created_at
            AND r.eligibility='eligible' AND r.side IN ('buy','sell') AND r.volume_usdc>=1''', (uid,)).fetchall()
        shares = c.execute('''SELECT s.token,s.call_id,t.symbol,s.created_at,
            COUNT(a.user_id) FROM call_share_links s LEFT JOIN token_calls t ON t.id=s.call_id
            LEFT JOIN call_invitation_attributions a ON a.share_token=s.token AND a.referrer_id=s.user_id
            WHERE s.user_id=? GROUP BY s.token ORDER BY s.created_at DESC LIMIT 50''', (uid,)).fetchall()
    valid = [r for r in trades if math.isfinite(r[1])]
    return dict(share_links=links,signups=signups,traders=len({r[0] for r in valid}),trades=len(valid),
                volume_usdc=round(math.fsum(r[1] for r in valid),2),
                shares=[dict(call_id=r[1],symbol=r[2] or 'Removed call',created_at=r[3],signups=r[4],
                             url=f'{BASE}/call/{r[1]}?via={r[0]}') for r in shares])


def format_card_price(value):
    """Readable recorded USD price, including very small token prices."""
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError):
        return 'Unavailable'
    if not math.isfinite(price) or price <= 0:
        return 'Unavailable'
    if price < 1e-18:
        return '< $0.000000000000000001'
    places = 4 if price >= 1 else min(18, max(6, 2 - math.floor(math.log10(price))))
    return '$' + f'{price:,.{places}f}'.rstrip('0').rstrip('.')


@lru_cache(maxsize=128)
def _card_logo(d, url, bucket):
    """Reuse the existing HTTPS/SSRF/size guard; cache failures as well."""
    from share_token_card import _fetch_image
    from PIL import Image, ImageOps
    logo = _fetch_image(d, url)
    return ImageOps.fit(logo, (80,80), method=Image.Resampling.LANCZOS) if logo is not None else None


def render_card(call, inviter=None, logo_img=None):
    """1200×630 PNG from recorded call data and an optional guarded token logo."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    root = Path(__file__).resolve().parent / 'fonts'
    def font(size):
        return ImageFont.truetype(str(root/'Geist-Bold.ttf'), size)
    image = Image.new('RGB', (1200,630), '#080d11')
    draw = ImageDraw.Draw(image)
    gold, white, muted = '#f7b955', '#f2f4f7', '#9aa3af'
    draw.rounded_rectangle((24,24,1176,606), radius=30, fill='#111a20', outline='#34434b', width=2)
    def fitted(text, size, width):
        text = ' '.join(str(text or '').split())
        f = font(size)
        if draw.textlength(text, font=f) > width:
            while text and draw.textlength(text+'…', font=f) > width:
                text = text[:-1]
            text += '…'
        return text, f
    def line(text, x, y, size, color=white, width=1088):
        text, f = fitted(text, size, width)
        draw.text((x,y), text, font=f, fill=color)

    draw.rounded_rectangle((56,51,108,103), radius=14, fill=gold)
    draw.polygon(((82,64),(69,89),(95,89)), fill='#080d11')
    line('OrcAgent',122,48,32)
    line('SOLANA TOKEN CALL',124,88,16,gold)
    draw.rounded_rectangle((966,57,1144,97), radius=15, fill='#202d36')
    line('CALL #'+str(call['id']),986,65,18,muted,138)

    symbol = str(call.get('symbol') or call['mint'][:8]).lstrip('$')
    draw.ellipse((56,146,144,234), fill='#24313a', outline='#3d4c55', width=2)
    if logo_img is not None:
        logo = ImageOps.fit(logo_img.convert('RGB'), (80,80), method=Image.Resampling.LANCZOS)
        mask = Image.new('L', (80,80), 0)
        ImageDraw.Draw(mask).ellipse((0,0,79,79), fill=255)
        image.paste(logo, (60,150), mask)
    else:
        initials = symbol[:2].upper()
        f = font(27)
        draw.text((100-draw.textlength(initials,font=f)/2,169), initials, font=f, fill=gold)
    line('$'+symbol,164,141,48,width=610)
    line(call.get('token_name') or 'Solana token',166,201,23,muted,610)
    line('Analysis by '+str(call.get('username') or 'OrcAgent trader'),166,239,18,muted,610)

    draw.rounded_rectangle((810,139,1144,271), radius=20, fill='#1a2730', outline='#34434b')
    line('ENTRY PRICE · USD',834,157,17,gold,286)
    price = format_card_price(call.get('price_at_call'))
    size = 32
    while size > 16 and draw.textlength(price,font=font(size)) > 286:
        size -= 1
    line(price,834,193,size,width=286)
    line('Recorded at publication',834,240,15,muted,286)

    draw.rounded_rectangle((56,297,1144,444), radius=20, fill='#0c1319')
    line('THE CALL',78,312,16,gold)
    words = str(call.get('note') or 'Open the call, explore its chart and decide whether to trade.').split()
    first = []
    while words and (not first or draw.textlength(' '.join(first+[words[0]]),font=font(26)) <= 1040):
        first.append(words.pop(0))
    line(' '.join(first),78,342,26,width=1040)
    if words:
        line(' '.join(words),78,381,26,width=1040)

    line('CALLED BY',56,471,15,muted)
    author = str(call.get('username') or 'OrcAgent trader')
    line(author+(' · Verified' if call.get('is_verified')==1 else ''),56,494,26,width=510)
    line('SHARED BY' if inviter else 'OPEN CALL & CHART',624,471,15,muted)
    line(inviter['username'] if inviter else 'Trade on OrcAgent',624,494,26,gold,520)
    line(str(call.get('timestamp') or '')+' UTC',56,550,18,muted,510)
    line('orcagent.fun/call/'+str(call['id']),624,548,22,gold,520)
    line('A call is an opinion, not a buy or a guarantee of returns.',56,581,14,muted)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def install(d):
    import json
    from flask import g, has_request_context, jsonify, redirect, request, session
    from itsdangerous import BadSignature, URLSafeTimedSerializer
    app=d.app
    if getattr(app,'_orca_call_invitations',False):return
    app._orca_call_invitations=True
    initialize(d.DB_FILE)
    serializer=URLSafeTimedSerializer(app.secret_key,salt='orca-invite-v1')

    def pending():
        if not has_request_context():return None
        raw=request.cookies.get(COOKIE)
        if raw:
            try:
                value=serializer.loads(raw,max_age=WINDOW)
                if isinstance(value,dict):return value
            except BadSignature:pass
        return getattr(g,'orca_pending_invite',None)

    def created(c,uid,wallet,ref_code):
        proven=has_request_context() and (d._authenticated_wallet()==wallet or
                request.path in ('/api/onboarding/wallet/confirm','/api/onboarding/wallet/import'))
        invite=pending() if proven else None
        # Explicit legacy codes are accepted only after the caller has proved
        # ownership. Read-only wallet addresses cannot assign another user.
        if not invite and has_request_context() and d._authenticated_wallet()==wallet:
            invite=resolve_invite(c,code=ref_code)
        c.execute('INSERT OR IGNORE INTO invitation_accounts(user_id,created_at,pending_json) VALUES (?,?,?)',
                  (uid,time.time(),json.dumps(invite) if invite else None))
    app._orca_invitation_user_created=created

    def owner():
        wallet=d._authenticated_wallet()
        if not wallet:return None
        with sqlite3.connect(d.DB_FILE,timeout=10) as c:return d._get_uid(c,wallet)

    def call_data(call_id):
        value=public_call(d.DB_FILE,call_id)
        return value if value and d.is_valid_solana_address(value['mint']) else None

    def inviter_for(call_id):
        with sqlite3.connect(d.DB_FILE,timeout=10) as c:
            value=resolve_invite(c,token=request.args.get('via'))
        return value if value and value['call_id']==call_id else None

    @app.before_request
    def capture_invite():
        if request.method=='GET' and request.path=='/' and request.args.get('call_return'):
            raw=request.args.get('call_return','')
            if raw.isascii() and raw.isdigit() and len(raw)<12 and call_data(int(raw)):
                session['orca_call_return']=[int(raw),time.time()]
        if request.method!='GET' or request.path.startswith(('/api/','/static/','/media/')) or d._authenticated_wallet():return
        if pending():return
        with sqlite3.connect(d.DB_FILE,timeout=10) as c:
            invite=None
            if request.path.startswith('/call/'):
                try:call_id=int(request.path.split('/')[-1])
                except ValueError:return
                invite=resolve_invite(c,token=request.args.get('via'))
                if invite and invite['call_id']!=call_id:invite=None
            elif request.path in ('/','/live-market') or request.path.startswith(('/post/','/u/')):
                invite=resolve_invite(c,code=request.args.get('ref'))
        if invite:g.orca_pending_invite=invite

    @app.after_request
    def invitations_response(response):
        private=request.path=='/invitations' or request.path.startswith('/api/invitations') or request.path.endswith('/share') and request.path.startswith('/api/calls/')
        if private:response.headers['Cache-Control']='private, no-store'
        if response.status_code<400 and not request.path.startswith(('/static/','/media/','/api/call-card/')):
            invite=getattr(g,'orca_pending_invite',None)
            if invite:
                response.set_cookie(COOKIE,serializer.dumps(invite),max_age=WINDOW,httponly=True,
                                    secure=request.is_secure,samesite='Lax',path='/')
                response.headers['Cache-Control']='private, no-store'
            uid=owner()
            if uid:
                try:complete_signup(d.DB_FILE,uid,pending())
                except sqlite3.Error:app.logger.warning('Invitation signup bookkeeping temporarily unavailable')
        if response.status_code==200 and response.mimetype=='text/html' and request.path in ('/','/calls','/following'):
            body=response.get_data(as_text=True)
            if 'src="/static/call-sharing.js' not in body:
                tag='<script src="/static/call-sharing.js?v='+d._APP_VERSION+'" defer></script><link rel="stylesheet" href="/static/call-sharing.css?v='+d._APP_VERSION+'">'
                response.set_data(body.replace('</head>',tag+'</head>',1))
        return response

    if not any(item and item[0]=='/invitations' for item in d._NAVBAR_MORE_LINKS):
        d._NAVBAR_MORE_LINKS.insert(0,('/invitations','Invitations & shared calls','referrals'))

    @app.route('/call/<int:call_id>')
    @d.rate_limit(60,60)
    def shared_call(call_id):
        value=call_data(call_id)
        if not value:return 'Call not found',404
        destination=session.get('orca_call_return')
        if d._authenticated_wallet() and destination and destination[0]==call_id:
            session.pop('orca_call_return',None)
        return d._render_no_cache('shared_call.html',call=value,inviter=inviter_for(call_id),base=BASE)

    @app.route('/api/call-card/<int:call_id>.png')
    @d.rate_limit(30,60)
    def call_card(call_id):
        value=call_data(call_id)
        if not value:return 'Call not found',404
        logo=_card_logo(d,value['image_url'],int(time.time()//900)) if value.get('image_url') else None
        response=d.make_response(render_card(value,inviter_for(call_id),logo))
        response.headers['Content-Type']='image/png'
        response.headers['Cache-Control']='public, max-age=300'
        response.headers['Content-Disposition']='inline; filename="orcagent-call-'+str(call_id)+'.png"'
        return response

    @app.route('/api/calls/<int:call_id>/share',methods=['POST'])
    @d.rate_limit(30,60)
    def share_call(call_id):
        uid=owner()
        if not uid:return jsonify(ok=False,msg='Connect your wallet to create a personal invitation link'),401
        if not d._validate_csrf(request.headers.get('X-CSRF-Token','')):return jsonify(ok=False,msg='Refresh and try again'),403
        value=call_data(call_id)
        if not value:return jsonify(ok=False,msg='Call not found'),404
        with sqlite3.connect(d.DB_FILE,timeout=10) as c:
            c.execute('INSERT OR IGNORE INTO call_share_links VALUES (?,?,?,?)',(secrets.token_urlsafe(18),uid,call_id,time.time()))
            token=c.execute('SELECT token FROM call_share_links WHERE user_id=? AND call_id=?',(uid,call_id)).fetchone()[0]
        url=f'{BASE}/call/{call_id}?via={token}'
        return jsonify(ok=True,url=url,card_url=f'{BASE}/api/call-card/{call_id}.png?v=2&via={token}',
                       text=f'${value["symbol"] or value["mint"][:8]} · Token call on OrcAgent')

    @app.route('/invitations')
    def invitations_page():
        uid=owner()
        if not uid:return redirect('/?next=/invitations')
        return d._render_no_cache('invitations.html',csrf_token=d._get_csrf_token())

    @app.route('/api/invitations')
    @d.rate_limit(60,60)
    def own_invitations():
        uid=owner()
        if not uid:return jsonify(ok=False,msg='Connect your wallet first'),401
        return jsonify(ok=True,**metrics(d.DB_FILE,uid))

    @app.route('/api/invitations/return')
    @d.rate_limit(60,60)
    def invitation_return():
        destination=session.get('orca_call_return')
        waiting=bool(destination and time.time()-destination[1]<1800)
        path='/call/'+str(destination[0]) if waiting and d._authenticated_wallet() else None
        return jsonify(ok=True,pending=waiting,path=path)
