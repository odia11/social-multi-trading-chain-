"""OrcAgent only posts about things members can actually do in the app.

When nothing live is happening, OrcAgent posts a fixed product text. Some of
those texts described things the app cannot do: posting a 30-second video
(the composer only takes pictures), a private invitations dashboard (/invitations
just goes to Home), sharing a token card into a DM, sharing calls in a group,
your wallet approving each tip (tips go out from your OrcAgent wallet), and
Token Launch, which depends on a server switch and may be in preflight.

Every fixed text now has to point at the place in the app that does what it
says; a new text without that cannot be added by accident.
"""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
import platform_assistant as p

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
def read(*parts):
    return open(os.path.join(ROOT, *parts), encoding='utf-8').read()

# topic -> (file, text that proves the feature is there for members)
EVIDENCE = {
    'calls': ('static/feed-calls.js', 'Share call'),
    'community': ('static/dashboard.js', 'Following'),
    'sharing': ('static/call-sharing.js', "'Save card'"),
    'portfolio': ('templates/wallet.html', 'Portfolio'),
    'feedback': ('platform_assistant.py', 'MENTION = re.compile'),
    'wallet': ('templates/token_launch.html', 'Phantom'),
    'entry': ('templates/shared_call.html', 'Entry price recorded at publication'),
    'discussion': ('templates/messages.html', '_renderDmTokenCard'),
    'referrals': ('templates/referrals.html', 'Receive 20% of the trading fees from people you invite'),
    'charts': ('templates/shared_call.html', 'View chart &amp; trade'),
    'transparency': ('templates/shared_call.html', 'Called by'),
    'follow': ('static/dashboard.js', 'Following'),
    'costs': ('solana_gasless_trading.py', 'never uses its own sponsor wallet'),
    'learning': ('static/feed-calls.js', 'Share call'),
    'onboarding': ('templates/token_launch.html', 'Phantom'),
    'save': ('static/call-sharing.js', "'Share on X'"),
    'support': ('platform_assistant.py', 'MENTION = re.compile'),
    'portfolio_context': ('templates/wallet.html', 'Portfolio'),
    'feedback_loop': ('platform_assistant.py', 'MENTION = re.compile'),
    'share_context': ('call_invitations.py', "@app.route('/call/<int:call_id>')"),
    'independent': ('static/feed-calls.js', 'Share call'),
    'social': ('templates/profile.html', 'pf-btn-tip'),
    'recorded': ('templates/shared_call.html', 'Entry price recorded at publication'),
    'fees_not_volume': ('templates/referrals.html', 'trading fees'),
    'live_market': ('static/live-market-pro.js', 'watchlist'),
    'stop_loss': ('protection_exits.py', ''),
    'bot': ('auto_trading_bot_route.py', ''),
    'live_trades': ('live_trades_truth.py', ''),
    'tips': ('templates/profile.html', 'onclick="_openTip()"'),
    'dm_reactions': ('templates/messages.html', 'long-press'),
    'notifications': ('static/push-subscribe.js', ''),
    'groups': ('templates/groups.html', 'Join group'),
    'leaderboard': ('templates/leaderboard.html', ''),
    'images': ('dashboard.html', 'id="composer-image-input" accept="image/'),
    'withdraw': ('portfolio_token_withdraw.py', 're-reads the token balance on-chain'),
    'light_mode': ('dashboard.html', '<div class="st-tog-label">Light mode</div>'),
    'calls_tab': ('templates/calls.html', 'Share call'),
    'watchlist': ('static/live-market-pro.js', "star.setAttribute('aria-label', 'Watchlist')"),
    'pwa': ('static/push-subscribe.js', ''),
    'replies': ('static/dashboard.js', 'function _feedToggleReply(btn, postId)'),
    'reposts': ('static/dashboard.js', "e.type === 'repost'"),
    'profile': ('templates/profile.html', 'pf-avatar-input'),
    'risk': ('protection_exits.py', ''),
    'feed_filters': ('dashboard.html', '>Following<'),
    'search': ('dashboard.py', 'Search token, address, trader'),
    'top_traders': ('templates/live_market_pro.html', 'Top traders · 24h'),
    'market_pulse': ('templates/live_market_pro.html', 'Market pulse · 24h'),
    'safety_filters': ('templates/live_market_pro.html', 'Hide honeypots'),
    'sort_market': ('static/live-market-pro.js', 'Friends buying'),
    'dm_images': ('templates/messages.html', 'id="msgs-file-input" accept="image/'),
    'edit_post': ('static/dashboard.js', '_fcEditStart('),
}

topics = [t for t, _ in p.THESES]
missing = [t for t in topics if t not in EVIDENCE]
check('every fixed post text names where in the app it is true (missing: %s)' % missing, not missing)
bad = []
for t in topics:
    if t in EVIDENCE:
        path, needle = EVIDENCE[t]
        if not os.path.exists(os.path.join(ROOT, path)) or needle not in read(path):
            bad.append(t)
check('...and that place really is in the app (not found: %s)' % bad, not bad)

text = '\n'.join(x for _, x in p.THESES).lower()
check('no post about video: the composer only takes pictures',
      'video' not in text and 'accept="image/' in read('dashboard.html')
      and 'video/' not in read('dashboard.html').split('id="composer-image-input"')[1].split('>')[0])
check('no post about an invitations dashboard: /invitations only goes to Home',
      'invitation' not in text and "def invitations_page():\n        return redirect('/')" in read('call_invitations.py'))
check('no post saying your wallet approves each tip: tips go out from the OrcAgent wallet',
      'approves every tip' not in text and 'signTransaction' not in read('templates', 'profile.html'))
check('no post about voting Bullish/Bearish in the feed: the trending card left the home feed',
      'bullish' not in text and 'home-trending-hero' not in read('dashboard.html'))
check('...and an earlier post saying so is removed again (the clean-up list has a new version)',
      any('Bullish or Bearish' in t for t in p.RETIRED) and "'retired_posts_cleanup_v2'" in read('platform_assistant.py'))
check('no post about a Trends tab: only the phone layout has one',
      'trends' not in text)
check('no post about sharing token cards in DMs or calls in groups',
      'token card' not in text and 'share calls' not in text)
check('no post about Token Launch while it can be switched off on the server',
      'launch' not in text and "ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED" in read('token_launch.py'))

# ── posts already published with an untrue text are removed, once ─────────
import sqlite3, tempfile
db = os.path.join(tempfile.mkdtemp(), 'retired.db')
with sqlite3.connect(db) as c:
    c.executescript("""
CREATE TABLE users(id INTEGER PRIMARY KEY,wallet_address TEXT,username TEXT,is_verified INTEGER);
INSERT INTO users VALUES(1,'officialwallet','Orcagent',1),(2,'memberwallet','member',0);
CREATE TABLE feed_posts(id INTEGER PRIMARY KEY AUTOINCREMENT,wallet TEXT,content TEXT,created_at TEXT,image_url TEXT);
CREATE TABLE feed_replies(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,post_id TEXT,message TEXT,created_at TEXT,parent_reply_id INTEGER);
CREATE TABLE post_likes(post_id TEXT,user_id INTEGER);
CREATE TABLE notifications(user_id INTEGER,type TEXT,content TEXT,link TEXT,actor_wallet TEXT);
""")
p.initialize(db)
video = next(t for t in p.RETIRED if 'video' in t)
with sqlite3.connect(db) as c:
    bad_id = c.execute("INSERT INTO feed_posts(wallet,content) VALUES('officialwallet',?)", (video,)).lastrowid
    good_id = c.execute("INSERT INTO feed_posts(wallet,content) VALUES('officialwallet',?)", (p.THESES[0][1],)).lastrowid
    member_id = c.execute("INSERT INTO feed_posts(wallet,content) VALUES('memberwallet',?)", (video,)).lastrowid
    for pid in (bad_id, good_id):
        c.execute("INSERT INTO platform_assistant_events VALUES(?,?,?,?,?,?,?)", ('slot%d' % pid, 'post', None, 'p%d' % pid, None, 't', 0))
    c.execute("INSERT INTO feed_replies(user_id,post_id,message) VALUES(2,?,'nice')", ('p%d' % bad_id,))
    c.execute("INSERT INTO post_likes VALUES(?,2)", ('p%d' % bad_id,))
    c.execute("INSERT INTO notifications VALUES(1,'like','x',?, 'memberwallet')", ('/#post-p%d' % bad_id,))
    c.execute("DELETE FROM platform_assistant_settings WHERE key='retired_posts_cleanup_v2'")
p.initialize(db)   # a restart after the deploy
with sqlite3.connect(db) as c:
    left = {r[0] for r in c.execute('SELECT id FROM feed_posts')}
    leftovers = [c.execute(q, ('p%d' % bad_id,)).fetchone()[0] for q in
                 ('SELECT COUNT(*) FROM feed_replies WHERE post_id=?', 'SELECT COUNT(*) FROM post_likes WHERE post_id=?')]
    leftovers.append(c.execute('SELECT COUNT(*) FROM notifications WHERE link=?', ('/#post-p%d' % bad_id,)).fetchone()[0])
check("OrcAgent's own post about video is removed, with its replies, likes and notifications",
      bad_id not in left and leftovers == [0, 0, 0])
check("...its posts that are true stay, and a member's own post is never touched",
      good_id in left and member_id in left)
with sqlite3.connect(db) as c:
    again = c.execute("INSERT INTO feed_posts(wallet,content) VALUES('officialwallet',?)", (video,)).lastrowid
    c.execute("INSERT INTO platform_assistant_events VALUES(?,?,?,?,?,?,?)", ('again', 'post', None, 'p%d' % again, None, 't', 0))
p.initialize(db)
with sqlite3.connect(db) as c:
    check('the clean-up runs once, not on every start',
          c.execute('SELECT COUNT(*) FROM feed_posts WHERE id=?', (again,)).fetchone()[0] == 1)

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
