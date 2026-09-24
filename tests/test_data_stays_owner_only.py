"""security-smoke.sh (ExecStartPost of orcagent.service) refuses to start the
app while anything under /data is group/world accessible. The first deploy of
the video backup mirror broke that: `rsync -a` copied the PUBLIC media dir's
755/644 modes into /data/backups/media, install.sh's backup run created it,
and the app would not come back up. This runs the real mirror block against a
755/644 source and applies the smoke script's exact `find -perm /0077` test."""
import os, re, shutil, subprocess, tempfile, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

backup = (ROOT / 'deploy/backup.sh').read_text()
smoke = (ROOT / 'deploy/security-smoke.sh').read_text()
check('the smoke check still enforces owner-only /data', 'find /data -xdev' in smoke and '-perm /0077' in smoke)
check('the mirror forces owner-only modes', '--chmod=D700,F600' in backup)

if shutil.which('rsync'):
    t = Path(tempfile.mkdtemp())
    src, data = t / 'src', t / 'data'
    src.mkdir(); (data / 'backups').mkdir(parents=True)
    os.chmod(src, 0o755)
    for name in ('a' * 32 + '.mp4', 'b' * 32 + '.jpg'):
        (src / name).write_bytes(b'x'); os.chmod(src / name, 0o644)
    block = backup[backup.index('# ── Video posts'):]
    block = (block.replace('/var/lib/orcagent-media/videos', str(src))
                  .replace('/data/backups', str(data / 'backups')))
    for stamp in ('s1', 's2'):
        if stamp == 's2':
            (src / ('a' * 32 + '.mp4')).unlink()   # a deleted post
        subprocess.run(['bash', '-c', block], env={**os.environ, 'STAMP': stamp}, check=True,
                       capture_output=True)
    bad = subprocess.run(['find', str(data), '-xdev', '(', '-type', 'f', '-o', '-type', 'd', ')',
                          '-perm', '/0077', '-print'], capture_output=True, text=True).stdout.strip()
    bad = [p for p in bad.splitlines() if p not in (str(data), str(data / 'backups'))]
    check('nothing the mirror creates under /data is group/world accessible', not bad)
    check('the mirror still copies the videos', (data / 'backups/media/videos' / ('b' * 32 + '.jpg')).exists())
    check('a removed video is still kept (owner-only) for 14 days',
          (data / 'backups/media-deleted/s2' / ('a' * 32 + '.mp4')).exists())
    shutil.rmtree(t, ignore_errors=True)
else:
    print('SKIP rsync part: rsync not installed')

src_v = (ROOT / 'video_uploads.py').read_text()
check('the /data fallback media dir is never opened up to nginx',
      'if not _is_within(root, d._DATA_DIR):' in src_v and 'if not _is_within(_media_root(d), d._DATA_DIR):' in src_v)
raise SystemExit(0 if all(checks) else 1)
