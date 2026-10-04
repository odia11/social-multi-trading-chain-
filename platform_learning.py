"""Learn question wording against reviewed topics, never facts from comments."""
import hashlib
import re
import unicodedata

RETENTION = 90 * 86400
QUORUM = 3
UNSAFE = re.compile(r'seed|recovery|private.?key|secret|password|credential|herstelzin|priv[eé]sleutel|ignore.{0,30}(rules|instructions)|system.?prompt|guarantee|guaranteed|profit|predict|password|https?://|www\.|[A-Za-z0-9+/=_-]{32,}', re.I)
FOLLOWUP = re.compile(r'^\s*(?:how|where|why|which|what next|what about|can i|is it|and |hoe|waar|welke|waarom|en )', re.I)

def key(message, mention):
    if not isinstance(message, str) or not mention.search(message):
        return None
    text = unicodedata.normalize('NFKC', mention.sub('', message)).casefold().strip()
    if len(text) > 240 or UNSAFE.search(text) or re.search(r'[\d@]',text):
        return None
    words = re.sub(r'[^\w]+',' ',text).strip().split()
    if not 2 <= len(words) <= 35:
        return None
    return hashlib.sha256(' '.join(words).encode()).hexdigest()

def initialize(c):
    c.executescript("""
CREATE TABLE IF NOT EXISTS platform_assistant_questions(
 question_key TEXT PRIMARY KEY,sample_reply_id INTEGER NOT NULL,
 seen INTEGER NOT NULL DEFAULT 1,topic TEXT,status TEXT NOT NULL DEFAULT 'pending',
 manual INTEGER NOT NULL DEFAULT 0,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS platform_assistant_votes(
 question_key TEXT NOT NULL,user_id INTEGER NOT NULL,topic TEXT NOT NULL,
 question_reply_id INTEGER NOT NULL,clarification_reply_id INTEGER NOT NULL,created_at REAL NOT NULL,
 PRIMARY KEY(question_key,user_id));
CREATE TABLE IF NOT EXISTS platform_assistant_reviews(
 id INTEGER PRIMARY KEY,question_key TEXT NOT NULL,topic TEXT,status TEXT NOT NULL,
 actor_wallet TEXT NOT NULL,created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS platform_assistant_vote_time ON platform_assistant_votes(created_at);
CREATE INDEX IF NOT EXISTS platform_assistant_question_time ON platform_assistant_questions(updated_at);
""")

def prior(c, d, source, author_id):
    """Use only this user's authenticated conversation, at most six ancestors."""
    parent = source[4]
    visited = set()
    for _ in range(6):
        if not parent or parent in visited:
            return None
        visited.add(parent)
        row = c.execute('SELECT user_id,post_id,message,created_at,parent_reply_id FROM feed_replies WHERE id=?',(parent,)).fetchone()
        if not row or row[1] != source[1] or row[0] not in (source[0],author_id):
            return None
        if row[0] == author_id:
            event = c.execute("SELECT topic FROM platform_assistant_events WHERE kind='reply' AND reply_id=? AND source_user_id=?",(parent,source[0])).fetchone()
            question = c.execute('SELECT id,user_id,post_id,message FROM feed_replies WHERE id=?',(row[4],)).fetchone()
            if event and question and question[1:3] == source[:2]:
                return event[0], question[0], question[3]
            return None
        parent = row[4]
    return None

def votes(c, d, question_key, mention, topics, now):
    tally = {}
    rows = c.execute("""SELECT v.topic,v.question_reply_id,v.clarification_reply_id,
 q.user_id,q.post_id,q.message,a.user_id,a.post_id
 FROM platform_assistant_votes v
 JOIN feed_replies q ON q.id=v.question_reply_id
 JOIN feed_replies a ON a.id=v.clarification_reply_id
 WHERE v.question_key=? AND v.created_at>?""",(question_key,now-RETENTION)).fetchall()
    for topic,qid,aid,uid,post,message,auid,apost in rows:
        if topic not in topics or uid != auid or post != apost or post[:1] not in ('p','t'):
            continue
        if key(message,mention) != question_key or not d._feed_post_created_at(c,post):
            continue
        tally[topic] = tally.get(topic,0)+1
    return tally

def refresh(c,d,question_key,mention,topics,now):
    row = c.execute('SELECT topic,status,manual FROM platform_assistant_questions WHERE question_key=?',(question_key,)).fetchone()
    if not row or row[2]:
        return row[:2] if row else (None,'pending')
    counts = votes(c,d,question_key,mention,topics,now)
    # A single contradictory clarification returns automatic wording to review.
    topic = next(iter(counts)) if len(counts)==1 else None
    status = 'learned' if topic and counts[topic]>=QUORUM else 'pending'
    c.execute('UPDATE platform_assistant_questions SET topic=?,status=? WHERE question_key=?',(topic,status,question_key))
    return topic,status

def lookup(c,d,message,mention,topics,now):
    question_key = key(message,mention)
    if not question_key:
        return None
    sample = c.execute('SELECT r.message,r.post_id FROM platform_assistant_questions q JOIN feed_replies r ON r.id=q.sample_reply_id WHERE q.question_key=?',(question_key,)).fetchone()
    if not sample or sample[1][:1] not in ('p','t') or key(sample[0],mention)!=question_key or not d._feed_post_created_at(c,sample[1]):
        return None
    topic,status = refresh(c,d,question_key,mention,topics,now)
    return topic if status in ('learned','approved') and topic in topics else None

def observe(c,d,source_id,source,explicit_topic,previous,mention,topics,now):
    # Store references and hashed wording, not another copy of public comments.
    c.execute('DELETE FROM platform_assistant_votes WHERE created_at<?',(now-RETENTION,))
    c.execute("DELETE FROM platform_assistant_questions WHERE manual=0 AND updated_at<?",(now-RETENTION,))
    question_key = key(source[2],mention)
    if explicit_topic == 'scope' and question_key:
        c.execute("""INSERT INTO platform_assistant_questions(question_key,sample_reply_id,updated_at)
 VALUES(?,?,?) ON CONFLICT(question_key) DO UPDATE SET
 sample_reply_id=excluded.sample_reply_id,seen=seen+1,updated_at=excluded.updated_at""",(question_key,source_id,now))
    clarified = previous and (previous[0]=='scope' or re.search(r'i mean|meant|actually|bedoel|clarify|talking about',source[2],re.I))
    if clarified and explicit_topic in topics and not UNSAFE.search(source[2]):
        old_key = key(previous[2],mention)
        if old_key and c.execute('SELECT 1 FROM platform_assistant_questions WHERE question_key=?',(old_key,)).fetchone():
            c.execute("""INSERT INTO platform_assistant_votes VALUES(?,?,?,?,?,?)
 ON CONFLICT(question_key,user_id) DO UPDATE SET topic=excluded.topic,
 question_reply_id=excluded.question_reply_id,clarification_reply_id=excluded.clarification_reply_id,
 created_at=excluded.created_at""",(old_key,source[0],explicit_topic,previous[1],source_id,now))
            refresh(c,d,old_key,mention,topics,now)

def review(c,question_key,topic,status,wallet,now,topics):
    if status not in ('approved','ignored','pending') or (status=='approved' and topic not in topics):
        raise ValueError('Choose a reviewed platform topic or reset/ignore the question')
    if not re.fullmatch(r'[0-9a-f]{64}',question_key or ''):
        raise ValueError('Invalid question')
    if not c.execute('SELECT 1 FROM platform_assistant_questions WHERE question_key=?',(question_key,)).fetchone():
        raise LookupError('Question no longer exists')
    topic = topic if status=='approved' else None
    c.execute('UPDATE platform_assistant_questions SET topic=?,status=?,manual=?,updated_at=? WHERE question_key=?',
              (topic,status,int(status!='pending'),now,question_key))
    if status=='pending':
        c.execute('DELETE FROM platform_assistant_votes WHERE question_key=?',(question_key,))
    c.execute('INSERT INTO platform_assistant_reviews(question_key,topic,status,actor_wallet,created_at) VALUES(?,?,?,?,?)',
              (question_key,topic,status,wallet,now))

def dashboard(c,d,mention,topics,now):
    keys = c.execute("""SELECT q.question_key FROM platform_assistant_questions q
 JOIN feed_replies r ON r.id=q.sample_reply_id ORDER BY q.updated_at DESC LIMIT 50""").fetchall()
    result=[]
    for (question_key,) in keys:
        topic,status = refresh(c,d,question_key,mention,topics,now)
        row = c.execute("""SELECT q.seen,r.message,r.post_id FROM platform_assistant_questions q
 JOIN feed_replies r ON r.id=q.sample_reply_id WHERE q.question_key=?""",(question_key,)).fetchone()
        if row and key(row[1],mention)==question_key and row[2][:1] in ('p','t') and d._feed_post_created_at(c,row[2]):
            result.append(dict(key=question_key,seen=row[0],question=mention.sub('',row[1])[:240],
                               post_id=row[2],topic=topic,status=status,
                               votes=sum(votes(c,d,question_key,mention,topics,now).values())))
    return result
