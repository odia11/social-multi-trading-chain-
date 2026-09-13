"""Daily encrypted verified backup scheduler.

Runs in every Gunicorn worker but coordinates through a filesystem flock, so exactly
one process creates a backup per UTC day. The encrypted artifact is immediately
decrypted into a temporary file and integrity-checked before it is considered valid.
"""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def _backup_once(dashboard_module):
    db_path = Path(str(dashboard_module.DB_FILE))
    if not db_path.exists():
        return
    out_dir = db_path.parent / 'backups' / 'daily'
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / '.backup.lock'
    day = time.strftime('%Y%m%d', time.gmtime())
    if list(out_dir.glob(f'orcagent-{day}*.db.gz.enc')):
        return

    secret = str(os.getenv('SECRET_KEY') or dashboard_module.app.config.get('SECRET_KEY') or '')
    if len(secret) < 32:
        dashboard_module.app.logger.error('daily backup skipped: production SECRET_KEY unavailable')
        return
    backup_key = hashlib.sha256(('orcagent-backup-v1:' + secret).encode()).hexdigest()

    with open(lock_path, 'a+b') as lockf:
        try:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if list(out_dir.glob(f'orcagent-{day}*.db.gz.enc')):
            return
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        final_path = out_dir / f'orcagent-{stamp}.db.gz.enc'
        with tempfile.TemporaryDirectory(dir=str(db_path.parent)) as td:
            plain = Path(td) / 'backup.db'
            gz = Path(td) / 'backup.db.gz'
            restored_gz = Path(td) / 'restore.db.gz'
            restored = Path(td) / 'restore.db'
            src = sqlite3.connect(str(db_path), timeout=30)
            dst = sqlite3.connect(str(plain))
            try:
                src.backup(dst)
            finally:
                dst.close(); src.close()
            conn = sqlite3.connect(str(plain))
            try:
                ok = conn.execute('PRAGMA integrity_check').fetchone()[0]
            finally:
                conn.close()
            if ok != 'ok':
                raise RuntimeError('SQLite integrity check failed before encryption')
            with open(plain, 'rb') as inp, gzip.open(gz, 'wb', compresslevel=9) as out:
                while True:
                    chunk = inp.read(1024 * 1024)
                    if not chunk: break
                    out.write(chunk)
            env = dict(os.environ); env['BACKUP_KEY'] = backup_key
            subprocess.run(['openssl','enc','-aes-256-cbc','-pbkdf2','-iter','200000','-salt',
                            '-in',str(gz),'-out',str(final_path),'-pass','env:BACKUP_KEY'],
                           check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            os.chmod(final_path, 0o600)
            subprocess.run(['openssl','enc','-d','-aes-256-cbc','-pbkdf2','-iter','200000',
                            '-in',str(final_path),'-out',str(restored_gz),'-pass','env:BACKUP_KEY'],
                           check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            with gzip.open(restored_gz, 'rb') as inp, open(restored, 'wb') as out:
                while True:
                    chunk = inp.read(1024 * 1024)
                    if not chunk: break
                    out.write(chunk)
            conn = sqlite3.connect(str(restored))
            try:
                ok = conn.execute('PRAGMA integrity_check').fetchone()[0]
            finally:
                conn.close()
            if ok != 'ok':
                final_path.unlink(missing_ok=True)
                raise RuntimeError('Encrypted backup failed restore verification')
        backups = sorted(out_dir.glob('orcagent-*.db.gz.enc'), key=lambda p:p.stat().st_mtime, reverse=True)
        for old in backups[14:]:
            old.unlink(missing_ok=True)
        dashboard_module.app.logger.info('verified encrypted daily backup created: %s', final_path)


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_backup_scheduler_installed', False):
        return
    app._orca_backup_scheduler_installed = True

    def loop():
        # Initial delay avoids competing with startup migrations and health checks.
        time.sleep(90)
        while True:
            try:
                _backup_once(dashboard_module)
            except Exception as exc:
                app.logger.error('daily encrypted backup failed: %s', exc)
            time.sleep(3600)

    threading.Thread(target=loop, name='orca-secure-backup', daemon=True).start()
