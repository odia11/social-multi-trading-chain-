"""Own followed traders, explicit alert preferences and their latest public calls."""
from __future__ import annotations

import sqlite3


def initialize(path):
    with sqlite3.connect(path, timeout=10) as c:
        columns={r[1] for r in c.execute('PRAGMA table_info(follows)')}
        if 'notify_mode' not in columns:
            try:
                c.execute("ALTER TABLE follows ADD COLUMN notify_mode TEXT NOT NULL DEFAULT 'all'")
            except sqlite3.OperationalError:
                if 'notify_mode' not in {r[1] for r in c.execute('PRAGMA table_info(follows)')}:
                    raise


def preferences(path, uid, before=None):
    with sqlite3.connect(path, timeout=10) as c:
        where='f.follower_id=?';args=[uid]
        if before is not None:
            where+=' AND f.following_id<?';args.append(before)
        rows=c.execute('SELECT u.id,u.username,u.wallet_address,u.is_verified,f.notify_enabled,f.notify_mode '
                       'FROM follows f JOIN users u ON u.id=f.following_id WHERE '+where+
                       ' ORDER BY f.following_id DESC LIMIT 101',args).fetchall()
        global_pref=c.execute('SELECT pref_notifications FROM users WHERE id=?',(uid,)).fetchone()
    return dict(traders=[dict(user_id=r[0],username=r[1] or r[2][:8],wallet=r[2],verified=r[3]==1,
                mode=('calls' if r[5]=='calls' else 'all') if r[4] else 'off') for r in rows[:100]],
                next_cursor=rows[99][0] if len(rows)>100 else None,
                notifications_enabled=global_pref is None or global_pref[0] is None or bool(global_pref[0]))


def set_preference(path, uid, target, mode):
    if mode not in ('off','calls','all'):
        raise ValueError('Choose off, calls or all')
    with sqlite3.connect(path, timeout=10) as c:
        changed=c.execute('UPDATE follows SET notify_enabled=?,notify_mode=? WHERE follower_id=? AND following_id=?',
                          (0 if mode=='off' else 1,'calls' if mode=='calls' else 'all',uid,target)).rowcount
    return bool(changed)


def recent_calls(path, uid):
    with sqlite3.connect(path, timeout=10) as c:
        rows=c.execute('SELECT t.id,t.mint,t.symbol,t.note,t.post_id,t.timestamp,t.price_at_call,'
                       'u.username,u.wallet_address,u.is_verified FROM token_calls t '
                       'JOIN follows f ON f.following_id=t.user_id AND f.follower_id=? '
                       'JOIN users u ON u.id=t.user_id WHERE COALESCE(t.chain,\'\') IN (\'\',\'solana\') '
                       'ORDER BY t.id DESC LIMIT 30',(uid,)).fetchall()
    return [dict(id=r[0],mint=r[1],symbol=r[2] or r[1][:8],note=r[3] or '',post_id=r[4],created_at=r[5],
                 price_at_call=r[6],username=r[7] or r[8][:8],wallet=r[8],verified=r[9]==1) for r in rows]


def install(d):
    from flask import jsonify, request, redirect
    app=d.app
    if getattr(app,'_orca_following_traders',False):
        return
    app._orca_following_traders=True
    initialize(d.DB_FILE)
    def owner():
        wallet=d._authenticated_wallet()
        if not wallet:
            return None
        with sqlite3.connect(d.DB_FILE,timeout=10) as c:
            return d._get_uid(c,wallet)

    @app.after_request
    def own_preferences_private(response):
        if request.path.startswith('/api/following/'):
            response.headers['Cache-Control']='private, no-store'
        return response

    @app.route('/following')
    def following_page():
        return redirect('/')

    @app.route('/api/following/preferences')
    @d.rate_limit(60,60)
    def following_preferences():
        uid=owner()
        if not uid:
            return jsonify(ok=False,msg='Connect your wallet first'),401
        before=request.args.get('before')
        try:
            before=int(before) if before is not None else None
            if before is not None and before<=0:
                raise ValueError
        except ValueError:
            return jsonify(ok=False,msg='Invalid cursor'),400
        return jsonify(ok=True,**preferences(d.DB_FILE,uid,before))

    @app.route('/api/following/preferences/<int:target>',methods=['PUT'])
    @d.rate_limit(60,60)
    def following_preferences_save(target):
        uid=owner()
        if not uid:
            return jsonify(ok=False,msg='Connect your wallet first'),401
        if not d._validate_csrf(request.headers.get('X-CSRF-Token','')):
            return jsonify(ok=False,msg='Refresh the page and try again'),403
        body=request.get_json(silent=True)
        if not isinstance(body,dict):
            return jsonify(ok=False,msg='Invalid preferences'),400
        try:
            changed=set_preference(d.DB_FILE,uid,target,body.get('mode'))
        except ValueError as e:
            return jsonify(ok=False,msg=str(e)),400
        if not changed:
            return jsonify(ok=False,msg='Follow this trader first'),404
        return jsonify(ok=True,mode=body['mode'])

    @app.route('/api/following/calls')
    @d.rate_limit(60,60)
    def following_calls():
        uid=owner()
        if not uid:
            return jsonify(ok=False,msg='Connect your wallet first'),401
        return jsonify(ok=True,calls=[c for c in recent_calls(d.DB_FILE,uid) if d.is_valid_solana_address(c['mint'])])
