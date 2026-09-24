"""Short video posts (up to 30 seconds) for the Home feed.

Flow, all from the post composer:

  1. POST /api/feed/video/start           {size, mime}  -> {id, chunk_size}
  2. POST /api/feed/video/<id>/chunk?offset=N   raw bytes, <= CHUNK_BYTES each
  3. POST /api/feed/video/<id>/finish                     -> status 'processing'
  4. GET  /api/feed/video/<id>                            -> 'processing' | 'ready' | 'failed'
  5. POST /api/feed/post {content, video_id}              (dashboard.feed_post_create)

Why chunks: nginx and Flask both cap a request body at 12 MB, and a 30-second
phone video is routinely 20-80 MB. Uploading in 4 MB pieces stays inside the
existing limits (no nginx/Certbot surgery), gives the composer a real progress
bar, and survives a flaky mobile connection (a failed piece is simply resent).

Why every video is re-encoded with ffmpeg before it can be posted:
  * the 30-second limit is enforced on the server from the file itself, not
    trusted from the browser;
  * phones record HEVC (.mov) that Android/desktop Chrome often can't play --
    the output is always H.264/AAC MP4, which plays everywhere;
  * phone videos carry GPS/location and device metadata -- it is stripped
    (-map_metadata -1) before anything is published;
  * the short side is capped at 720px, so a feed of videos stays light;
  * +faststart lets playback begin before the whole file has downloaded;
  * a poster frame is generated so the feed shows a picture, not a black box.
If ffmpeg isn't installed, uploads are refused up front with a clear message
rather than publishing an unprocessed original.

Published files live in a dedicated PUBLIC media directory (not /data, which
is deliberately owner-only) so nginx can serve them directly; the Flask route
below is the fallback for development and for servers where nginx hasn't
been given that location yet.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

MAX_SECONDS = 30.0
_DURATION_GRACE = 0.6          # container rounding; a "30s" clip can read 30.03s
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
CHUNK_BYTES = 4 * 1024 * 1024
MAX_UPLOADS_PER_DAY = 20
ALLOWED_MIME = {'video/mp4', 'video/quicktime', 'video/webm', 'video/x-m4v',
                'video/3gpp', 'video/3gpp2', 'video/x-matroska', ''}
_ID_RE = re.compile(r'^[a-f0-9]{32}$')
_FILE_RE = re.compile(r'^[a-f0-9]{32}\.(mp4|jpg)$')
PUBLIC_MEDIA_DIR = '/var/lib/orcagent-media'
_STALE_UPLOAD_SECS = 2 * 3600       # unfinished uploads
_UNUSED_READY_SECS = 24 * 3600      # processed but never posted
_STUCK_PROCESSING_SECS = 15 * 60    # worker died mid-transcode

_transcode_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='video-transcode')
_cleanup_lock = threading.Lock()
_last_cleanup = {'at': 0.0}


def _ffmpeg() -> str:
    return os.getenv('ORCAGENT_FFMPEG') or shutil.which('ffmpeg') or ''


def _ffprobe() -> str:
    return os.getenv('ORCAGENT_FFPROBE') or shutil.which('ffprobe') or ''


def _media_root(d) -> str:
    explicit = os.getenv('ORCAGENT_MEDIA_DIR', '').strip()
    if explicit:
        return explicit
    if os.path.isdir(PUBLIC_MEDIA_DIR) and os.access(PUBLIC_MEDIA_DIR, os.W_OK):
        return PUBLIC_MEDIA_DIR
    return os.path.join(d._DATA_DIR, 'media')


def _videos_dir(d) -> str:
    path = os.path.join(_media_root(d), 'videos')
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o755)   # the service runs with UMask=0077; nginx must read this
    except OSError:
        pass
    return path


def _tmp_dir(d) -> str:
    # Raw uploads are private until processed: they may still carry location
    # metadata, so they stay under the owner-only data directory.
    path = os.path.join(d._DATA_DIR, 'video_uploads_tmp')
    os.makedirs(path, exist_ok=True)
    return path


def _probe_duration(src: str):
    """(duration_seconds, has_video) for any container ffmpeg understands."""
    probe = _ffprobe()
    if probe:
        try:
            out = subprocess.run(
                [probe, '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                 '-of', 'default=noprint_wrappers=1', src],
                capture_output=True, text=True, timeout=30).stdout
            dur = None
            m = re.search(r'duration=([0-9.]+)', out)
            if m:
                dur = float(m.group(1))
            return dur, 'codec_type=video' in out
        except Exception:
            pass
    # No ffprobe (e.g. a static ffmpeg build): read ffmpeg's own banner.
    try:
        err = subprocess.run([_ffmpeg(), '-hide_banner', '-i', src],
                             capture_output=True, text=True, timeout=30).stderr
    except Exception:
        return None, False
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', err)
    dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else None
    return dur, bool(re.search(r'Stream #\S+.*Video:', err))


def _looks_like_video(head: bytes) -> bool:
    """Container magic: ISO-BMFF (mp4/mov/3gp) or Matroska/WebM."""
    if len(head) >= 12 and head[4:8] in (b'ftyp', b'moov', b'mdat', b'wide', b'free', b'skip'):
        return True
    return head[:4] == b'\x1a\x45\xdf\xa3'


def install(d):
    app = d.app
    if getattr(app, '_orca_video_uploads_installed', False):
        return
    app._orca_video_uploads_installed = True
    from flask import jsonify, request, send_from_directory, abort

    def _db():
        conn = sqlite3.connect(d.DB_FILE, timeout=10)
        conn.execute('PRAGMA busy_timeout=10000')
        return conn

    conn = _db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS video_uploads (
            id TEXT PRIMARY KEY, wallet TEXT NOT NULL, status TEXT NOT NULL,
            size INTEGER NOT NULL, received INTEGER NOT NULL DEFAULT 0,
            mime TEXT, duration REAL, file TEXT, poster TEXT, error TEXT,
            created_at INTEGER NOT NULL, post_id INTEGER)''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_video_uploads_wallet ON video_uploads(wallet, created_at)')
        for ddl in ('ALTER TABLE feed_posts ADD COLUMN video_url TEXT DEFAULT NULL',
                    'ALTER TABLE feed_posts ADD COLUMN video_poster TEXT DEFAULT NULL'):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass   # already there
        conn.commit()
    finally:
        conn.close()

    def _row(conn, vid):
        r = conn.execute('SELECT id, wallet, status, size, received, duration, file, poster, error, post_id '
                         'FROM video_uploads WHERE id=?', (vid,)).fetchone()
        if not r:
            return None
        keys = ('id', 'wallet', 'status', 'size', 'received', 'duration', 'file', 'poster', 'error', 'post_id')
        return dict(zip(keys, r))

    def _public(v):
        out = {'ok': True, 'id': v['id'], 'status': v['status']}
        if v['status'] == 'ready':
            out.update({'url': '/media/videos/' + v['file'],
                        'poster': ('/media/videos/' + v['poster']) if v['poster'] else '',
                        'duration': v['duration']})
        if v['status'] == 'failed':
            out['msg'] = v['error'] or 'Video could not be processed'
        return out

    def _remove(*paths):
        for p in paths:
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def _cleanup(force=False):
        """Drop abandoned uploads, stuck jobs, unused processed videos and
        videos whose post no longer exists (any delete path, incl. admin)."""
        now = time.time()
        with _cleanup_lock:
            if not force and now - _last_cleanup['at'] < 600:
                return
            _last_cleanup['at'] = now
        conn = _db()
        try:
            vids = _videos_dir(d)
            tmp = _tmp_dir(d)
            rows = conn.execute('SELECT id, status, file, poster, created_at, post_id FROM video_uploads').fetchall()
            live_posts = {r[0] for r in conn.execute(
                'SELECT id FROM feed_posts WHERE video_url IS NOT NULL').fetchall()}
            for vid, status, f, poster, created, post_id in rows:
                age = now - (created or 0)
                gone = (
                    (status == 'uploading' and age > _STALE_UPLOAD_SECS)
                    or (status == 'processing' and age > _STUCK_PROCESSING_SECS)
                    or (status == 'failed' and age > _STALE_UPLOAD_SECS)
                    or (status == 'ready' and post_id is None and age > _UNUSED_READY_SECS)
                    or (status == 'posted' and post_id not in live_posts)
                )
                if gone:
                    _remove(os.path.join(tmp, vid),
                            os.path.join(vids, f) if f else None,
                            os.path.join(vids, poster) if poster else None)
                    conn.execute('DELETE FROM video_uploads WHERE id=?', (vid,))
            conn.commit()
        except Exception as e:
            print(f'[video] cleanup failed: {e}', flush=True)
        finally:
            conn.close()

    def _transcode(vid: str):
        src = os.path.join(_tmp_dir(d), vid)
        vids = _videos_dir(d)
        out_name, poster_name = vid + '.mp4', vid + '.jpg'
        out_path, poster_path = os.path.join(vids, out_name), os.path.join(vids, poster_name)
        part = out_path + '.part'

        def _fail(msg):
            _remove(src, part, out_path, poster_path)
            c = _db()
            try:
                c.execute("UPDATE video_uploads SET status='failed', error=? WHERE id=?", (msg, vid))
                c.commit()
            finally:
                c.close()

        try:
            duration, has_video = _probe_duration(src)
            if not has_video:
                return _fail('That file has no video in it')
            if duration is None:
                return _fail('Could not read that video — try recording it again')
            if duration > MAX_SECONDS + _DURATION_GRACE:
                return _fail(f'Videos can be at most {int(MAX_SECONDS)} seconds (this one is {duration:.0f}s)')
            # Short side <= 720px, H.264 + AAC, metadata (GPS!) stripped,
            # moov atom first so playback starts immediately.
            scale = ("scale='if(gt(iw,ih),-2,min(720,iw))':'if(gt(iw,ih),min(720,ih),-2)'")
            cmd = [_ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', src,
                   '-t', str(MAX_SECONDS), '-map', '0:v:0', '-map', '0:a:0?',
                   '-map_metadata', '-1', '-map_chapters', '-1',
                   '-vf', scale, '-r', '30',
                   '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26',
                   '-profile:v', 'high', '-pix_fmt', 'yuv420p',
                   '-c:a', 'aac', '-b:a', '96k', '-ac', '2',
                   '-movflags', '+faststart', '-f', 'mp4', part]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
            if res.returncode != 0 or not os.path.exists(part) or os.path.getsize(part) == 0:
                print(f'[video] transcode failed {vid}: {(res.stderr or "")[-300:]}', flush=True)
                return _fail('Video could not be processed — try a different file')
            os.replace(part, out_path)
            subprocess.run([_ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
                            '-ss', str(min(0.5, max(0.0, duration / 2))), '-i', out_path,
                            '-frames:v', '1', '-q:v', '4', poster_path],
                           capture_output=True, timeout=60)
            for p in (out_path, poster_path):
                if os.path.exists(p):
                    os.chmod(p, 0o644)
            final_dur, _ = _probe_duration(out_path)
            _remove(src)
            c = _db()
            try:
                c.execute("UPDATE video_uploads SET status='ready', file=?, poster=?, duration=? WHERE id=?",
                          (out_name, poster_name if os.path.exists(poster_path) else None,
                           round(final_dur or duration, 2), vid))
                c.commit()
            finally:
                c.close()
        except subprocess.TimeoutExpired:
            _fail('Processing took too long — try a shorter or smaller video')
        except Exception as e:
            print(f'[video] transcode error {vid}: {e}', flush=True)
            _fail('Video could not be processed — try a different file')

    @app.route('/api/feed/video/start', methods=['POST'])
    @d.rate_limit(12, 600)
    def feed_video_start():
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify({'ok': False, 'msg': 'Not logged in'}), 401
        if not _ffmpeg():
            return jsonify({'ok': False, 'msg': 'Video uploads are not available right now'}), 503
        body = request.get_json(silent=True) or {}
        try:
            size = int(body.get('size') or 0)
        except (TypeError, ValueError):
            size = 0
        mime = str(body.get('mime') or '').lower().split(';')[0].strip()
        if size <= 0:
            return jsonify({'ok': False, 'msg': 'Empty file'}), 400
        if size > MAX_UPLOAD_BYTES:
            return jsonify({'ok': False, 'msg': f'Video too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)'}), 400
        if mime not in ALLOWED_MIME:
            return jsonify({'ok': False, 'msg': 'Only MP4, MOV or WebM videos are accepted'}), 400
        _cleanup()
        now = int(time.time())
        conn = _db()
        try:
            today = conn.execute('SELECT COUNT(*) FROM video_uploads WHERE wallet=? AND created_at>?',
                                 (wallet, now - 86400)).fetchone()[0]
            if today >= MAX_UPLOADS_PER_DAY:
                return jsonify({'ok': False, 'msg': 'Daily video limit reached — try again tomorrow'}), 429
            vid = secrets.token_hex(16)
            open(os.path.join(_tmp_dir(d), vid), 'wb').close()
            conn.execute("INSERT INTO video_uploads (id, wallet, status, size, mime, created_at) VALUES (?,?,?,?,?,?)",
                         (vid, wallet, 'uploading', size, mime, now))
            conn.commit()
        finally:
            conn.close()
        return jsonify({'ok': True, 'id': vid, 'chunk_size': CHUNK_BYTES})

    @app.route('/api/feed/video/<vid>/chunk', methods=['POST'])
    @d.rate_limit(120, 60)
    def feed_video_chunk(vid):
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify({'ok': False, 'msg': 'Not logged in'}), 401
        if not _ID_RE.match(vid or ''):
            return jsonify({'ok': False, 'msg': 'Unknown upload'}), 404
        try:
            offset = int(request.args.get('offset', '-1'))
        except ValueError:
            offset = -1
        if (request.content_length or 0) > CHUNK_BYTES:
            return jsonify({'ok': False, 'msg': 'Chunk too large'}), 413
        data = request.get_data(cache=False)
        if not data or len(data) > CHUNK_BYTES:
            return jsonify({'ok': False, 'msg': 'Bad chunk'}), 400
        conn = _db()
        try:
            v = _row(conn, vid)
            if not v or v['wallet'] != wallet:
                return jsonify({'ok': False, 'msg': 'Unknown upload'}), 404
            if v['status'] != 'uploading':
                return jsonify({'ok': False, 'msg': 'Upload already finished'}), 409
            if offset != v['received']:
                # Lets the client resume exactly where the server is.
                return jsonify({'ok': False, 'msg': 'Wrong offset', 'received': v['received']}), 409
            if v['received'] + len(data) > v['size']:
                return jsonify({'ok': False, 'msg': 'More data than announced'}), 400
            if offset == 0 and not _looks_like_video(data[:16]):
                conn.execute("UPDATE video_uploads SET status='failed', error=? WHERE id=?",
                             ('That file is not a video', vid))
                conn.commit()
                return jsonify({'ok': False, 'msg': 'That file is not a video'}), 400
            with open(os.path.join(_tmp_dir(d), vid), 'ab') as fh:
                fh.write(data)
            received = v['received'] + len(data)
            conn.execute('UPDATE video_uploads SET received=? WHERE id=?', (received, vid))
            conn.commit()
            return jsonify({'ok': True, 'received': received})
        finally:
            conn.close()

    @app.route('/api/feed/video/<vid>/finish', methods=['POST'])
    @d.rate_limit(20, 60)
    def feed_video_finish(vid):
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify({'ok': False, 'msg': 'Not logged in'}), 401
        if not _ID_RE.match(vid or ''):
            return jsonify({'ok': False, 'msg': 'Unknown upload'}), 404
        conn = _db()
        try:
            v = _row(conn, vid)
            if not v or v['wallet'] != wallet:
                return jsonify({'ok': False, 'msg': 'Unknown upload'}), 404
            if v['status'] != 'uploading':
                return jsonify(_public(v))
            if v['received'] != v['size']:
                return jsonify({'ok': False, 'msg': 'Upload incomplete', 'received': v['received']}), 409
            conn.execute("UPDATE video_uploads SET status='processing', created_at=? WHERE id=?",
                         (int(time.time()), vid))
            conn.commit()
            v['status'] = 'processing'
        finally:
            conn.close()
        _transcode_pool.submit(_transcode, vid)
        return jsonify(_public(v))

    @app.route('/api/feed/video/<vid>', methods=['GET'])
    @d.rate_limit(120, 60)
    def feed_video_status(vid):
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify({'ok': False, 'msg': 'Not logged in'}), 401
        if not _ID_RE.match(vid or ''):
            return jsonify({'ok': False, 'msg': 'Unknown upload'}), 404
        conn = _db()
        try:
            v = _row(conn, vid)
        finally:
            conn.close()
        if not v or v['wallet'] != wallet:
            return jsonify({'ok': False, 'msg': 'Unknown upload'}), 404
        return jsonify(_public(v))

    @app.route('/media/videos/<name>')
    def feed_video_file(name):
        # Normally nginx serves /media/videos/ straight from disk (see
        # deploy/apply-nginx-media.sh); this keeps playback working without it.
        if not _FILE_RE.match(name or ''):
            abort(404)
        resp = send_from_directory(_videos_dir(d), name, conditional=True, max_age=31536000,
                                   mimetype='video/mp4' if name.endswith('.mp4') else 'image/jpeg')
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return resp

    def claim_feed_video(conn, wallet: str, vid: str):
        """For feed_post_create: (video_url, poster_url, None) for a processed
        video this wallet uploaded and hasn't posted yet, else (None, None, msg).
        Runs inside the post's own transaction; the caller marks it posted."""
        if not _ID_RE.match(str(vid or '')):
            return None, None, 'Unknown video'
        v = _row(conn, vid)
        if not v or v['wallet'] != wallet:
            return None, None, 'Unknown video'
        if v['status'] == 'processing' or v['status'] == 'uploading':
            return None, None, 'Your video is still processing — try again in a moment'
        if v['status'] != 'ready' or v['post_id'] is not None:
            return None, None, (v['error'] or 'That video can no longer be posted')
        return ('/media/videos/' + v['file'],
                ('/media/videos/' + v['poster']) if v['poster'] else None, None)

    def mark_feed_video_posted(conn, vid: str, post_id: int):
        conn.execute("UPDATE video_uploads SET status='posted', post_id=? WHERE id=?", (post_id, vid))

    def attach_feed_videos(conn, items):
        """Add video_url/video_poster to feed items -- and, for a repost, to
        the original it points at -- in one query per page."""
        def _orig_pid(it):
            ro = str(it.get('repost_of') or '')
            return int(ro[1:]) if ro.startswith('p') and ro[1:].isdigit() else None
        ids = set()
        for it in items or []:
            if it.get('type') == 'text' and isinstance(it.get('id'), int):
                ids.add(it['id'])
            op = _orig_pid(it)
            if op is not None:
                ids.add(op)
        if not ids:
            return
        ids = list(ids)[:500]
        found = {}
        for pid, url, poster in conn.execute(
                'SELECT id, video_url, video_poster FROM feed_posts WHERE video_url IS NOT NULL AND id IN (%s)'
                % ','.join('?' * len(ids)), ids):
            found[pid] = (url, poster or '')
        for it in items or []:
            if it.get('type') == 'text' and it.get('id') in found:
                it['video_url'], it['video_poster'] = found[it['id']]
            op = _orig_pid(it)
            if op in found and isinstance(it.get('original'), dict):
                it['original']['video_url'], it['original']['video_poster'] = found[op]

    d._claim_feed_video = claim_feed_video
    d._mark_feed_video_posted = mark_feed_video_posted
    d._attach_feed_videos = attach_feed_videos
    d._video_cleanup = _cleanup
