"""Prevent future Git commits accidentally exposing OrcAgent server data."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
paths = [
    'dump.sql', 'orcagent_corrupt.db.bak', 'backups/daily.db',
    'other/cache.sqlite-wal', 'other/restore.sql.gz',
    'src/dump.backup', 'venv/lib/python3.12/site.py', '.venv/bin/python',
    '.env', '.env.production', 'secrets/private.pem',
]
for path in paths:
    result = subprocess.run(
        ['git', '-C', str(root), 'check-ignore', '-q', '--no-index', path],
        capture_output=True,
    )
    assert result.returncode == 0, f'Unsafe path not excluded by Git: {path}'
tracked = subprocess.check_output(
    ['git', '-C', str(root), 'ls-files', '-z'], text=True,
).split('\0')
for path in tracked:
    if not path:
        continue
    assert path not in {'dump.sql', 'orcagent_corrupt.db.bak'}
    assert not path.startswith(('backups/', 'venv/', '.venv/'))
print('PASS sensitive database/dump/backup and venv paths are Git-ignored')
print('PASS sensitive local recovery files are not tracked')
