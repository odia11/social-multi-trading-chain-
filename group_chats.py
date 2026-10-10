"""Group chats in Messages, WhatsApp-style.

A member starts a group with people they are connected to -- their followers
and the people they follow -- found by username, and gives it a name. The one
who started it owns it: they can make members admins (and take that back) and
delete the group. Admins add and remove members, rename the group and change
its photo; anyone can leave. When the owner leaves, the longest-standing admin
(or member) takes over. Messages are text or a photo; joining, leaving, adding and
renaming show as small system lines in the chat, as in WhatsApp.

Unread is one number per member (the last message id they have seen), so it
costs nothing per message. Every member gets a phone push per message, tagged
per group so a busy group updates one alert instead of stacking them, and at
most one unread bell notification per group.
"""
from __future__ import annotations

import base64
import datetime
import re
import sqlite3

MAX_MEMBERS = 50
MAX_NAME = 40
MAX_TEXT = 1000
MAX_PHOTO = 1024 * 1024
PAGE = 100
_IMAGE_PREFIXES = ('data:image/jpeg;base64,', 'data:image/jpg;base64,', 'data:image/png;base64,',
                   'data:image/gif;base64,', 'data:image/webp;base64,')


def initialize(path):
    with sqlite3.connect(path, timeout=10) as c:
        c.executescript('''
            CREATE TABLE IF NOT EXISTS group_chats (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS group_chat_members (
                chat_id      INTEGER NOT NULL,
                user_id      INTEGER NOT NULL,
                role         TEXT NOT NULL DEFAULT 'member',
                joined_at    TEXT NOT NULL,
                last_read_id INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_gcm_user ON group_chat_members(user_id);
            CREATE TABLE IF NOT EXISTS group_chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL,
                sender_id  INTEGER,
                kind       TEXT NOT NULL DEFAULT 'text',
                body       TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_gcmsg_chat ON group_chat_messages(chat_id, id);
            CREATE TABLE IF NOT EXISTS group_chat_likes (
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(message_id,user_id)
            );
        ''')
        reaction_columns = {r[1] for r in c.execute('PRAGMA table_info(group_chat_likes)')}
        if 'emoji' not in reaction_columns:
            c.execute("ALTER TABLE group_chat_likes ADD COLUMN emoji TEXT NOT NULL DEFAULT '❤️'")
        have = {r[1] for r in c.execute('PRAGMA table_info(group_chats)')}
        if 'photo' not in have:
            c.execute("ALTER TABLE group_chats ADD COLUMN photo TEXT NOT NULL DEFAULT ''")
        if 'photo_v' not in have:
            c.execute('ALTER TABLE group_chats ADD COLUMN photo_v INTEGER NOT NULL DEFAULT 0')
        if 'change_version' not in have:
            c.execute('ALTER TABLE group_chats ADD COLUMN change_version INTEGER NOT NULL DEFAULT 0')
        if 'history_visible' not in have:
            c.execute('ALTER TABLE group_chats ADD COLUMN history_visible INTEGER NOT NULL DEFAULT 1')
        member_columns = {r[1] for r in c.execute('PRAGMA table_info(group_chat_members)')}
        if 'history_from_id' not in member_columns:
            c.execute('ALTER TABLE group_chat_members ADD COLUMN history_from_id INTEGER NOT NULL DEFAULT 0')
        message_columns = {r[1] for r in c.execute('PRAGMA table_info(group_chat_messages)')}
        for column, declaration in [('edited_at', 'TEXT'), ('version', 'INTEGER NOT NULL DEFAULT 0')]:
            if column not in message_columns:
                c.execute('ALTER TABLE group_chat_messages ADD COLUMN %s %s' % (column, declaration))
        c.execute('CREATE INDEX IF NOT EXISTS idx_gcmsg_version ON group_chat_messages(chat_id,version)')


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def _name_of(row):
    """users row (id, username, wallet_address) -> what people see."""
    username, wallet = row[1], row[2] or ''
    return username or (wallet[:4] + '…' + wallet[-4:] if len(wallet) > 8 else wallet)


def connections(c, uid):
    """Everyone this member may put in a group: followers and followed."""
    return {r[0] for r in c.execute(
        'SELECT following_id FROM follows WHERE follower_id=? '
        'UNION SELECT follower_id FROM follows WHERE following_id=?', (uid, uid))}


def unread_total(c, uid):
    """Unread group messages for the Messages badge (others' messages only)."""
    row = c.execute(
        'SELECT COUNT(*) FROM group_chat_members m JOIN group_chat_messages g '
        'ON g.chat_id=m.chat_id AND g.id>m.last_read_id '
        "WHERE m.user_id=? AND g.kind NOT IN ('system','deleted') AND COALESCE(g.sender_id,0)!=?", (uid, uid)).fetchone()
    return int(row[0] or 0)


def _system(c, chat_id, text):
    return c.execute('INSERT INTO group_chat_messages (chat_id, sender_id, kind, body, created_at) '
                     "VALUES (?,NULL,'system',?,?)", (chat_id, text, _now())).lastrowid


def _member_role(c, chat_id, uid):
    row = c.execute('SELECT role FROM group_chat_members WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone()
    return row[0] if row else None


def _history_floor(c, chat_id, uid):
    row = c.execute('SELECT history_from_id FROM group_chat_members WHERE chat_id=? AND user_id=?',
                    (chat_id, uid)).fetchone()
    return int(row[0]) if row else 0


def photo_url(chat_id, photo_v):
    """Where the group photo is served, or '' -- versioned, so a new photo is a new address."""
    return '/api/group-chats/%d/photo?v=%d' % (chat_id, photo_v) if photo_v else ''


def _users(c, ids):
    ids = list(ids)
    if not ids:
        return {}
    marks = ','.join('?' * len(ids))
    return {r[0]: r for r in c.execute(
        'SELECT id, username, wallet_address, avatar_url, is_verified FROM users WHERE id IN (%s)' % marks, ids)}


def install(d):
    from flask import jsonify, request
    app = d.app
    if getattr(app, '_orca_group_chats', False):
        return
    app._orca_group_chats = True
    initialize(d.DB_FILE)
    d._group_chat_unread_total = unread_total

    def me(c):
        wallet = d._authenticated_wallet()
        return (wallet, d._get_uid(c, wallet)) if wallet else (None, None)

    def fail(msg, status):
        return jsonify({'ok': False, 'msg': msg}), status

    def connect():
        return sqlite3.connect(d.DB_FILE, timeout=10)

    def likes_for(c, message_ids, uid):
        ids=list(set(message_ids))
        if not ids:
            return {}
        marks=','.join('?' * len(ids))
        likes={}
        for mid, liker, username, wallet, avatar, emoji in c.execute(
                'SELECT l.message_id,l.user_id,u.username,u.wallet_address,u.avatar_url,l.emoji '
                'FROM group_chat_likes l JOIN users u ON u.id=l.user_id '
                'WHERE l.message_id IN (%s) ORDER BY l.created_at,l.user_id' % marks, ids):
            likes.setdefault(mid,[]).append({'user_id':liker,'username':_name_of((liker,username,wallet)),
                                          'wallet':wallet,'avatar':avatar or '', 'mine':liker==uid,'emoji':emoji})
        return likes

    @app.route('/api/group-chats/<int:chat_id>/messages/<int:message_id>/likes', methods=['GET', 'POST'])
    @d.rate_limit(60, 60)
    def group_chats_likes(chat_id, message_id):
        with connect() as c:
            if request.method=='POST':
                c.execute('BEGIN IMMEDIATE')
            wallet, uid=me(c)
            if not uid:
                return fail('No wallet connected',401)
            if not _member_role(c,chat_id,uid):
                return fail('Group not found',404)
            row=c.execute('SELECT kind FROM group_chat_messages WHERE chat_id=? AND id=? AND id>?',(chat_id,message_id,_history_floor(c,chat_id,uid))).fetchone()
            if not row or row[0] in ('system','deleted'):
                return fail('Message not found',404)
            if request.method=='POST':
                body=request.get_json(silent=True)
                if body is None:
                    body={}
                if not isinstance(body,dict):
                    return fail('Invalid reaction',400)
                emoji=body.get('emoji','❤️')
                if not isinstance(emoji,str) or emoji not in d._DM_REACTION_EMOJIS:
                    return fail('Invalid reaction',400)
                existing=c.execute('SELECT emoji FROM group_chat_likes WHERE message_id=? AND user_id=?',(message_id,uid)).fetchone()
                if existing and existing[0]==emoji:
                    c.execute('DELETE FROM group_chat_likes WHERE message_id=? AND user_id=?',(message_id,uid))
                else:
                    c.execute('INSERT INTO group_chat_likes(message_id,user_id,created_at,emoji) VALUES(?,?,?,?) '
                              'ON CONFLICT(message_id,user_id) DO UPDATE SET emoji=excluded.emoji,created_at=excluded.created_at',
                              (message_id,uid,_now(),emoji))
                c.execute('UPDATE group_chats SET change_version=change_version+1 WHERE id=?',(chat_id,))
                version=c.execute('SELECT change_version FROM group_chats WHERE id=?',(chat_id,)).fetchone()[0]
                c.execute('UPDATE group_chat_messages SET version=? WHERE id=?',(version,message_id))
            likes=likes_for(c,[message_id],uid).get(message_id,[])
            version=c.execute('SELECT version FROM group_chat_messages WHERE id=?',(message_id,)).fetchone()[0]
        return jsonify({'ok':True,'likes':likes,'liked':any(l['mine'] for l in likes),'version':version})

    def add_people(c, chat_id, actor_uid, actor_name, user_ids):
        """Add connections of the actor; returns the names added."""
        allowed = connections(c, actor_uid)
        present = {r[0] for r in c.execute('SELECT user_id FROM group_chat_members WHERE chat_id=?', (chat_id,))}
        wanted = [u for u in dict.fromkeys(user_ids) if u not in present and u != actor_uid]
        if any(u not in allowed for u in wanted):
            raise ValueError('You can add people who follow you or whom you follow')
        if len(present) + len(wanted) > MAX_MEMBERS:
            raise ValueError('A group can have up to %d members' % MAX_MEMBERS)
        people = _users(c, wanted)
        if len(people) != len(wanted):
            raise ValueError('Member not found')
        now = _now()
        top = c.execute('SELECT COALESCE(MAX(id),0) FROM group_chat_messages WHERE chat_id=?', (chat_id,)).fetchone()[0]
        visible = c.execute('SELECT history_visible FROM group_chats WHERE id=?', (chat_id,)).fetchone()[0]
        floor = 0 if visible else top
        names = []
        for u in wanted:
            c.execute('INSERT INTO group_chat_members (chat_id, user_id, role, joined_at, last_read_id, history_from_id) '
                      "VALUES (?,?,'member',?,?,?)", (chat_id, u, now, top, floor))
            names.append(_name_of(people[u]))
        return names

    def summary(c, uid, chat_id):
        row = c.execute('SELECT id, name, created_by, created_at, photo_v, history_visible FROM group_chats WHERE id=?', (chat_id,)).fetchone()
        members = c.execute('SELECT user_id, role FROM group_chat_members WHERE chat_id=? ORDER BY joined_at, user_id',
                            (chat_id,)).fetchall()
        people = _users(c, [m[0] for m in members])
        return {'id': row[0], 'name': row[1], 'created_by': row[2], 'created_at': row[3],
                'photo': photo_url(row[0], row[4]), 'history_visible': bool(row[5]),
                'role': dict(members).get(uid), 'is_owner': row[2] == uid,
                'members': [{'user_id': m[0], 'role': m[1], 'owner': m[0] == row[2],
                             'username': _name_of(people[m[0]]),
                             'wallet': people[m[0]][2], 'avatar': people[m[0]][3] or '',
                             'verified': bool(people[m[0]][4])} for m in members if m[0] in people]}

    @app.after_request
    def _group_chats_private(response):
        if request.path.startswith('/api/group-chats'):
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.route('/api/group-chats', methods=['GET'])
    @d.rate_limit(60, 60)
    def group_chats_list():
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            rows = c.execute(
                'SELECT g.id, g.name, m.role, m.last_read_id, '
                '(SELECT COUNT(*) FROM group_chat_members x WHERE x.chat_id=g.id), '
                '(SELECT COUNT(*) FROM group_chat_messages y WHERE y.chat_id=g.id AND y.id>m.last_read_id '
                "   AND y.kind NOT IN ('system','deleted') AND COALESCE(y.sender_id,0)!=?), "
                "(SELECT MAX(id) FROM group_chat_messages z WHERE z.chat_id=g.id AND z.id>m.history_from_id AND z.kind!='deleted'), g.photo_v "
                'FROM group_chat_members m JOIN group_chats g ON g.id=m.chat_id WHERE m.user_id=?',
                (uid, uid)).fetchall()
            last_ids = [r[6] for r in rows if r[6]]
            last = {}
            if last_ids:
                marks = ','.join('?' * len(last_ids))
                for r in c.execute('SELECT g.chat_id, g.kind, g.body, g.created_at, g.sender_id, u.username, u.wallet_address '
                                   'FROM group_chat_messages g LEFT JOIN users u ON u.id=g.sender_id '
                                   'WHERE g.id IN (%s)' % marks, last_ids):
                    last[r[0]] = {'kind': r[1], 'text': '' if r[1] == 'image' else 'Group tip' if r[1] == 'tip' else r[2][:120], 'created_at': r[3],
                                  'mine': r[4] == uid, 'sender': (_name_of((r[4], r[5], r[6])) if r[4] else '')}
            # A few faces per group for its avatar.
            faces = {}
            for chat_id, uid2, avatar, username, wallet2 in c.execute(
                    'SELECT m.chat_id, u.id, u.avatar_url, u.username, u.wallet_address FROM group_chat_members m '
                    'JOIN users u ON u.id=m.user_id WHERE m.chat_id IN (SELECT chat_id FROM group_chat_members WHERE user_id=?) '
                    'AND u.id!=? ORDER BY m.joined_at', (uid, uid)):
                lst = faces.setdefault(chat_id, [])
                if len(lst) < 3:
                    lst.append({'avatar': avatar or '', 'name': _name_of((uid2, username, wallet2)), 'wallet': wallet2})
        chats = [{'id': r[0], 'name': r[1], 'role': r[2], 'members': r[4], 'unread': r[5],
                  'photo': photo_url(r[0], r[7]),
                  'last': last.get(r[0]), 'faces': faces.get(r[0], [])} for r in rows]
        chats.sort(key=lambda x: (x['last'] or {}).get('created_at', ''), reverse=True)
        return jsonify({'ok': True, 'chats': chats})

    @app.route('/api/group-chats/candidates', methods=['GET'])
    @d.rate_limit(60, 60)
    def group_chats_candidates():
        q = (request.args.get('q') or '').strip().lstrip('@').lower()[:40]
        try:
            chat_id = int(request.args.get('chat_id') or 0)
        except ValueError:
            chat_id = 0
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            ids = connections(c, uid)
            if chat_id:
                ids -= {r[0] for r in c.execute('SELECT user_id FROM group_chat_members WHERE chat_id=?', (chat_id,))}
            ids.discard(uid)
            people = _users(c, ids)
            follows_me = {r[0] for r in c.execute('SELECT follower_id FROM follows WHERE following_id=?', (uid,))}
        out = []
        for u, row in people.items():
            name = _name_of(row)
            # A username matches anywhere; a wallet only from its start, so a
            # short search does not turn up random addresses that contain it.
            if q and q not in name.lower() and not (len(q) >= 4 and (row[2] or '').lower().startswith(q)):
                continue
            out.append({'user_id': u, 'username': name, 'wallet': row[2], 'avatar': row[3] or '',
                        'verified': bool(row[4]), 'follows_you': u in follows_me})
        out.sort(key=lambda x: (not x['follows_you'], x['username'].lower()))
        return jsonify({'ok': True, 'people': out[:40]})

    @app.route('/api/group-chats', methods=['POST'])
    @d.rate_limit(10, 60)
    def group_chats_create():
        body = request.get_json(silent=True) or {}
        name = re.sub(r'\s+', ' ', d._sanitize(str(body.get('name') or ''))).strip()
        try:
            user_ids = [int(x) for x in (body.get('user_ids') or [])][:MAX_MEMBERS]
        except (TypeError, ValueError):
            return fail('Invalid members', 400)
        if not name:
            return fail('Give the group a name', 400)
        if len(name) > MAX_NAME:
            return fail('Name too long (max %d characters)' % MAX_NAME, 400)
        if not user_ids:
            return fail('Add at least one person', 400)
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            c.execute('BEGIN IMMEDIATE')
            chat_id = c.execute('INSERT INTO group_chats (name, created_by, created_at) VALUES (?,?,?)',
                                (name, uid, _now())).lastrowid
            c.execute("INSERT INTO group_chat_members (chat_id, user_id, role, joined_at) VALUES (?,?,'admin',?)",
                      (chat_id, uid, _now()))
            actor = _name_of(_users(c, [uid])[uid])
            _system(c, chat_id, '%s created the group' % actor)
            try:
                names = add_people(c, chat_id, uid, actor, user_ids)
            except ValueError as e:
                c.rollback()
                return fail(str(e), 400)
            _system(c, chat_id, '%s added %s' % (actor, ', '.join(names)))
            out = summary(c, uid, chat_id)
            added = [m['user_id'] for m in out['members'] if m['user_id'] != uid]
        _announce(added, out['name'], '%s added you to %s' % (actor, out['name']), chat_id)
        return jsonify({'ok': True, 'chat': out})

    @app.route('/api/group-chats/<int:chat_id>', methods=['GET'])
    @d.rate_limit(60, 60)
    def group_chats_get(chat_id):
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            if not _member_role(c, chat_id, uid):
                return fail('Group not found', 404)
            return jsonify({'ok': True, 'chat': summary(c, uid, chat_id)})

    @app.route('/api/group-chats/<int:chat_id>', methods=['PUT'])
    @d.rate_limit(20, 60)
    def group_chats_rename(chat_id):
        name = re.sub(r'\s+', ' ', d._sanitize(str((request.get_json(silent=True) or {}).get('name') or ''))).strip()
        if not name or len(name) > MAX_NAME:
            return fail('Name must be 1-%d characters' % MAX_NAME, 400)
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            role = _member_role(c, chat_id, uid)
            if not role:
                return fail('Group not found', 404)
            if role != 'admin':
                return fail('Only admins can rename the group', 403)
            c.execute('UPDATE group_chats SET name=? WHERE id=?', (name, chat_id))
            _system(c, chat_id, '%s renamed the group to "%s"' % (_name_of(_users(c, [uid])[uid]), name))
            return jsonify({'ok': True, 'chat': summary(c, uid, chat_id)})

    @app.route('/api/group-chats/<int:chat_id>/history', methods=['PUT'])
    @d.rate_limit(20, 60)
    def group_chats_history(chat_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or type(body.get('visible')) is not bool:
            return fail('Choose whether new members can see history', 400)
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            role = _member_role(c, chat_id, uid)
            if not role:
                return fail('Group not found', 404)
            if role != 'admin':
                return fail('Only admins can change history access', 403)
            c.execute('UPDATE group_chats SET history_visible=? WHERE id=?', (int(body['visible']), chat_id))
            return jsonify({'ok': True, 'chat': summary(c, uid, chat_id)})

    @app.route('/api/group-chats/<int:chat_id>/members', methods=['POST'])
    @d.rate_limit(20, 60)
    def group_chats_add(chat_id):
        try:
            user_ids = [int(x) for x in ((request.get_json(silent=True) or {}).get('user_ids') or [])][:MAX_MEMBERS]
        except (TypeError, ValueError):
            return fail('Invalid members', 400)
        if not user_ids:
            return fail('Choose someone to add', 400)
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            role = _member_role(c, chat_id, uid)
            if not role:
                return fail('Group not found', 404)
            if role != 'admin':
                return fail('Only admins can add people', 403)
            c.execute('BEGIN IMMEDIATE')
            actor = _name_of(_users(c, [uid])[uid])
            before = {r[0] for r in c.execute('SELECT user_id FROM group_chat_members WHERE chat_id=?', (chat_id,))}
            try:
                names = add_people(c, chat_id, uid, actor, user_ids)
            except ValueError as e:
                c.rollback()
                return fail(str(e), 400)
            if names:
                _system(c, chat_id, '%s added %s' % (actor, ', '.join(names)))
            out = summary(c, uid, chat_id)
        _announce([m['user_id'] for m in out['members'] if m['user_id'] not in before], out['name'],
                  '%s added you to %s' % (actor, out['name']), chat_id)
        return jsonify({'ok': True, 'chat': out})

    @app.route('/api/group-chats/<int:chat_id>/members/<int:member_id>', methods=['DELETE'])
    @d.rate_limit(20, 60)
    def group_chats_remove(chat_id, member_id):
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            role = _member_role(c, chat_id, uid)
            if not role:
                return fail('Group not found', 404)
            if member_id == uid:
                return fail('Use Leave group', 400)
            if role != 'admin':
                return fail('Only admins can remove people', 403)
            target = _member_role(c, chat_id, member_id)
            if not target:
                return fail('Not in this group', 404)
            owner = c.execute('SELECT created_by FROM group_chats WHERE id=?', (chat_id,)).fetchone()[0]
            if member_id == owner:
                return fail('The owner of the group cannot be removed', 403)
            if target == 'admin' and uid != owner:
                return fail('Only the owner can remove an admin', 403)
            people = _users(c, [uid, member_id])
            c.execute('DELETE FROM group_chat_members WHERE chat_id=? AND user_id=?', (chat_id, member_id))
            _system(c, chat_id, '%s removed %s' % (_name_of(people[uid]), _name_of(people[member_id])))
            return jsonify({'ok': True, 'chat': summary(c, uid, chat_id)})

    def owner_of(c, chat_id):
        row = c.execute('SELECT created_by FROM group_chats WHERE id=?', (chat_id,)).fetchone()
        return row[0] if row else None

    @app.post('/api/group-chats/<int:chat_id>/owner')
    @d.rate_limit(10, 60)
    def group_chats_transfer_owner(chat_id):
        try:
            target = int((request.get_json(silent=True) or {}).get('user_id'))
        except (ValueError, TypeError):
            return fail('Choose a group member', 400)
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            if not _member_role(c, chat_id, uid):
                return fail('Group not found', 404)
            if owner_of(c, chat_id) != uid:
                return fail('Only the owner can transfer ownership', 403)
            if target == uid:
                return fail('You already own this group', 400)
            if not _member_role(c, chat_id, target):
                return fail('Choose an existing group member', 404)
            people = _users(c, [uid, target])
            c.execute('UPDATE group_chats SET created_by=? WHERE id=?', (target, chat_id))
            c.execute("UPDATE group_chat_members SET role='admin' WHERE chat_id=? AND user_id=?", (chat_id, target))
            _system(c, chat_id, '%s transferred ownership to %s' % (_name_of(people[uid]), _name_of(people[target])))
            return jsonify({'ok': True, 'chat': summary(c, uid, chat_id)})

    @app.route('/api/group-chats/<int:chat_id>/members/<int:member_id>', methods=['PUT'])
    @d.rate_limit(20, 60)
    def group_chats_set_role(chat_id, member_id):
        """The owner makes a member an admin, or takes it back."""
        role = str((request.get_json(silent=True) or {}).get('role') or '')
        if role not in ('admin', 'member'):
            return fail('Invalid role', 400)
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            if not _member_role(c, chat_id, uid):
                return fail('Group not found', 404)
            if owner_of(c, chat_id) != uid:
                return fail('Only the owner can choose admins', 403)
            if member_id == uid:
                return fail('You own this group', 400)
            current = _member_role(c, chat_id, member_id)
            if not current:
                return fail('Not in this group', 404)
            if current != role:
                people = _users(c, [uid, member_id])
                c.execute('UPDATE group_chat_members SET role=? WHERE chat_id=? AND user_id=?', (role, chat_id, member_id))
                _system(c, chat_id, ('%s made %s an admin' if role == 'admin' else '%s removed %s as admin')
                        % (_name_of(people[uid]), _name_of(people[member_id])))
            return jsonify({'ok': True, 'chat': summary(c, uid, chat_id)})

    @app.route('/api/group-chats/<int:chat_id>/photo', methods=['PUT', 'DELETE'])
    @d.rate_limit(10, 60)
    def group_chats_set_photo(chat_id):
        photo = ''
        if request.method == 'PUT':
            photo = str((request.get_json(silent=True) or {}).get('photo') or '').strip()
            if not photo.startswith(_IMAGE_PREFIXES):
                return fail('Only JPEG, PNG, GIF, or WebP images are accepted', 400)
            photo = d._shrink_image_data_uri(photo, max_edge=512, target_kb=120)
            try:
                size = len(base64.b64decode(photo.split(',', 1)[1], validate=True))
            except (ValueError, IndexError):
                return fail('That photo could not be read', 400)
            if size > MAX_PHOTO:
                return fail('Photo too large (max 1 MB)', 400)
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            role = _member_role(c, chat_id, uid)
            if not role:
                return fail('Group not found', 404)
            if role != 'admin':
                return fail('Only admins can change the group photo', 403)
            c.execute('UPDATE group_chats SET photo=?, photo_v=? WHERE id=?',
                      (photo, (c.execute('SELECT photo_v FROM group_chats WHERE id=?', (chat_id,)).fetchone()[0] + 1)
                       if photo else 0, chat_id))
            _system(c, chat_id, ('%s changed the group photo' if photo else '%s removed the group photo')
                    % _name_of(_users(c, [uid])[uid]))
            return jsonify({'ok': True, 'chat': summary(c, uid, chat_id)})

    @app.route('/api/group-chats/<int:chat_id>/photo', methods=['GET'])
    @d.rate_limit(240, 60)
    def group_chats_photo(chat_id):
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            if not _member_role(c, chat_id, uid):
                return fail('Group not found', 404)
            photo = c.execute('SELECT photo FROM group_chats WHERE id=?', (chat_id,)).fetchone()[0]
        m = re.match(r'^data:(image/(?:jpeg|jpg|png|gif|webp));base64,(.+)$', photo or '', re.S)
        if not m:
            return fail('No photo', 404)
        try:
            raw = base64.b64decode(m.group(2), validate=True)
        except ValueError:
            return fail('No photo', 404)
        resp = app.response_class(raw, mimetype=m.group(1).replace('image/jpg', 'image/jpeg'))
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        return resp

    @app.route('/api/group-chats/<int:chat_id>', methods=['DELETE'])
    @d.rate_limit(10, 60)
    def group_chats_delete(chat_id):
        """The owner deletes the group for everyone."""
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            if not _member_role(c, chat_id, uid):
                return fail('Group not found', 404)
            if owner_of(c, chat_id) != uid:
                return fail('Only the owner can delete the group', 403)
            name = c.execute('SELECT name FROM group_chats WHERE id=?', (chat_id,)).fetchone()[0]
            actor = _name_of(_users(c, [uid])[uid])
            others = [r[0] for r in c.execute('SELECT user_id FROM group_chat_members WHERE chat_id=? AND user_id!=?',
                                              (chat_id, uid))]
            c.execute('DELETE FROM group_chat_likes WHERE message_id IN (SELECT id FROM group_chat_messages WHERE chat_id=?)', (chat_id,))
            c.execute('DELETE FROM group_chat_messages WHERE chat_id=?', (chat_id,))
            c.execute('DELETE FROM group_chat_members WHERE chat_id=?', (chat_id,))
            c.execute('DELETE FROM group_chats WHERE id=?', (chat_id,))
            c.execute('DELETE FROM notifications WHERE link=?', ('/messages?group=%d' % chat_id,))
            if others:
                c.executemany('INSERT INTO notifications (user_id, type, content, link, actor_wallet) VALUES (?,?,?,?,?)',
                              [(u, 'message', '%s deleted the group "%s"' % (actor, name), '/messages', wallet)
                               for u in others])
        return jsonify({'ok': True})

    @app.route('/api/group-chats/<int:chat_id>/leave', methods=['POST'])
    @d.rate_limit(20, 60)
    def group_chats_leave(chat_id):
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            if not _member_role(c, chat_id, uid):
                return fail('Group not found', 404)
            name = _name_of(_users(c, [uid])[uid])
            c.execute('DELETE FROM group_chat_members WHERE chat_id=? AND user_id=?', (chat_id, uid))
            left = c.execute('SELECT user_id, role FROM group_chat_members WHERE chat_id=? ORDER BY joined_at, user_id',
                             (chat_id,)).fetchall()
            if not left:
                c.execute('DELETE FROM group_chat_likes WHERE message_id IN (SELECT id FROM group_chat_messages WHERE chat_id=?)', (chat_id,))
                c.execute('DELETE FROM group_chat_messages WHERE chat_id=?', (chat_id,))
                c.execute('DELETE FROM group_chats WHERE id=?', (chat_id,))
            else:
                _system(c, chat_id, '%s left' % name)
                owner = c.execute('SELECT created_by FROM group_chats WHERE id=?', (chat_id,)).fetchone()[0]
                if owner == uid:
                    heir = next((r[0] for r in left if r[1] == 'admin'), left[0][0])
                    c.execute('UPDATE group_chats SET created_by=? WHERE id=?', (heir, chat_id))
                    c.execute("UPDATE group_chat_members SET role='admin' WHERE chat_id=? AND user_id=?", (chat_id, heir))
                    _system(c, chat_id, '%s now owns the group' % _name_of(_users(c, [heir])[heir]))
                elif not any(r[1] == 'admin' for r in left):
                    c.execute("UPDATE group_chat_members SET role='admin' WHERE chat_id=? AND user_id=?",
                              (chat_id, left[0][0]))
            c.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND link=? AND is_read=0",
                      (uid, '/messages?group=%d' % chat_id))
        return jsonify({'ok': True})

    @app.route('/api/group-chats/<int:chat_id>/messages', methods=['GET'])
    @d.rate_limit(120, 60)
    def group_chats_messages(chat_id):
        try:
            after = max(0, int(request.args.get('after') or 0))
            changes_since = max(0, int(request.args.get('changes_since') or 0))
            before = max(0, int(request.args.get('before') or 0))
        except ValueError:
            after = changes_since = before = 0
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            if not _member_role(c, chat_id, uid):
                return fail('Group not found', 404)
            floor = _history_floor(c, chat_id, uid)
            if after and not before:
                rows = c.execute('SELECT id, sender_id, kind, body, created_at, edited_at, version FROM group_chat_messages '
                                 'WHERE chat_id=? AND id>? ORDER BY id LIMIT ?', (chat_id, max(after, floor), PAGE)).fetchall()
            else:
                rows = c.execute('SELECT * FROM (SELECT id, sender_id, kind, body, created_at, edited_at, version FROM group_chat_messages '
                                 'WHERE chat_id=? AND id>? AND (?=0 OR id<?) ORDER BY id DESC LIMIT ?) ORDER BY id',
                                 (chat_id, floor, before, before, PAGE)).fetchall()
            has_more = bool(rows and c.execute('SELECT 1 FROM group_chat_messages WHERE chat_id=? AND id>? AND id<? LIMIT 1',
                                               (chat_id, floor, rows[0][0])).fetchone())
            updates = [] if before else c.execute('SELECT id, sender_id, kind, body, created_at, edited_at, version FROM group_chat_messages '
                                'WHERE chat_id=? AND id>? AND version>? ORDER BY version LIMIT ?', (chat_id, floor, changes_since, PAGE)).fetchall()
            version = max([changes_since] + [r[6] for r in updates])
            people = _users(c, {r[1] for r in rows + updates if r[1]})
            reactions=likes_for(c,[r[0] for r in rows + updates],uid)
            if rows:
                c.execute('UPDATE group_chat_members SET last_read_id=MAX(last_read_id, ?) WHERE chat_id=? AND user_id=?',
                          (rows[-1][0], chat_id, uid))
                c.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND link=? AND is_read=0",
                          (uid, '/messages?group=%d' % chat_id))
        def serialize(items):
            return [
            {'id': r[0], 'sender_id': r[1], 'kind': r[2], 'body': r[3], 'created_at': r[4], 'mine': r[1] == uid,
             'edited_at': r[5], 'version': r[6],
             'likes': reactions.get(r[0],[]), 'liked': any(l['mine'] for l in reactions.get(r[0],[])),
             'sender': _name_of(people[r[1]]) if r[1] in people else '',
             'sender_wallet': people[r[1]][2] if r[1] in people else '',
             'sender_avatar': (people[r[1]][3] or '') if r[1] in people else ''} for r in items]
        return jsonify({'ok': True, 'messages': serialize(rows), 'updates': serialize(updates), 'change_version': version, 'has_more': has_more})

    @app.route('/api/group-chats/<int:chat_id>/messages/<int:message_id>', methods=['PUT', 'DELETE'])
    @d.rate_limit(30, 60)
    def group_chats_change_message(chat_id, message_id):
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            if not _member_role(c, chat_id, uid):
                return fail('Group not found', 404)
            row = c.execute('SELECT sender_id,kind FROM group_chat_messages WHERE chat_id=? AND id=? AND id>?',
                            (chat_id, message_id, _history_floor(c, chat_id, uid))).fetchone()
            if not row:
                return fail('Message not found', 404)
            if row[0] != uid or row[1] in ('system','tip'):
                return fail('You can only change your own messages', 403)
            if row[1] == 'deleted':
                return jsonify({'ok': True}) if request.method == 'DELETE' else fail('Message was deleted', 409)
            text = ''
            if request.method == 'PUT':
                if row[1] != 'text':
                    return fail('Only text messages can be edited', 400)
                text = d._sanitize(str((request.get_json(silent=True) or {}).get('message') or '')).strip()
                if not text or len(text) > MAX_TEXT:
                    return fail('Message must contain 1 to %d characters' % MAX_TEXT, 400)
            c.execute('UPDATE group_chats SET change_version=change_version+1 WHERE id=?', (chat_id,))
            version = c.execute('SELECT change_version FROM group_chats WHERE id=?', (chat_id,)).fetchone()[0]
            if request.method == 'DELETE':
                c.execute('DELETE FROM group_chat_likes WHERE message_id=?', (message_id,))
                c.execute("UPDATE group_chat_messages SET kind='deleted',body='',version=? WHERE id=?", (version, message_id))
            else:
                c.execute('UPDATE group_chat_messages SET body=?,edited_at=?,version=? WHERE id=?', (text, _now(), version, message_id))
            # Do not retain the removed/old body in pending bell previews.
            c.execute("UPDATE notifications SET content='Group message updated' WHERE link=? AND actor_wallet=? AND is_read=0",
                      ('/messages?group=%d' % chat_id, wallet))
        return jsonify({'ok': True})

    @app.route('/api/group-chats/<int:chat_id>/messages', methods=['POST'])
    @d.rate_limit(30, 60)
    def group_chats_send(chat_id):
        body = request.get_json(silent=True) or {}
        kind = 'image' if body.get('message_type') == 'image' else 'text'
        text = str(body.get('message') or '')
        if kind == 'image':
            text = text.strip()
            if not text.startswith(_IMAGE_PREFIXES):
                return fail('Only JPEG, PNG, GIF, or WebP images are accepted', 400)
            text = d._shrink_image_data_uri(text)
            if len(text.split(',', 1)[-1]) * 3 // 4 > 3 * 1024 * 1024:
                return fail('Image too large (max 3 MB)', 400)
        else:
            text = d._sanitize(text).strip()
            if not text:
                return fail('Message cannot be empty', 400)
            if len(text) > MAX_TEXT:
                return fail('Message too long (max %d characters)' % MAX_TEXT, 400)
        with connect() as c:
            wallet, uid = me(c)
            if not uid:
                return fail('No wallet connected', 401)
            if not _member_role(c, chat_id, uid):
                return fail('Group not found', 404)
            now = _now()
            mid = c.execute('INSERT INTO group_chat_messages (chat_id, sender_id, kind, body, created_at) '
                            'VALUES (?,?,?,?,?)', (chat_id, uid, kind, text, now)).lastrowid
            c.execute('UPDATE group_chat_members SET last_read_id=? WHERE chat_id=? AND user_id=?', (mid, chat_id, uid))
            group = c.execute('SELECT name FROM group_chats WHERE id=?', (chat_id,)).fetchone()[0]
            sender = _name_of(_users(c, [uid])[uid])
            others = [r[0] for r in c.execute('SELECT user_id FROM group_chat_members WHERE chat_id=? AND user_id!=?',
                                              (chat_id, uid))]
        preview = '📷 Photo' if kind == 'image' else (text[:60] + ('…' if len(text) > 60 else ''))
        _announce(others, group, '%s: %s' % (sender, preview), chat_id, actor_wallet=wallet)
        return jsonify({'ok': True, 'message': {'id': mid, 'sender_id': uid, 'kind': kind, 'body': text,
                                                'created_at': now, 'mine': True, 'sender': sender,
                                                'sender_wallet': wallet, 'sender_avatar': ''}})

    def _announce(user_ids, group_name, line, chat_id, actor_wallet=None):
        """One unread bell entry per group per member, and a push per message
        that replaces the previous one for this group on the phone."""
        if not user_ids:
            return
        link = '/messages?group=%d' % chat_id
        try:
            with connect() as c:
                marks = ','.join('?' * len(user_ids))
                c.execute("DELETE FROM notifications WHERE type='message' AND link=? AND is_read=0 "
                          'AND user_id IN (%s)' % marks, [link] + list(user_ids))
                c.executemany('INSERT INTO notifications (user_id, type, content, link, actor_wallet) VALUES (?,?,?,?,?)',
                              [(u, 'message', '%s · %s' % (group_name, line), link, actor_wallet) for u in user_ids])
        except sqlite3.Error as e:
            print('[group-chats] notification failed: %s' % type(e).__name__, flush=True)
        try:
            d._send_push_notifications_bulk(list(user_ids), group_name, line, link, '', 'gc-%d' % chat_id)
        except Exception as e:
            print('[group-chats] push failed: %s' % type(e).__name__, flush=True)
