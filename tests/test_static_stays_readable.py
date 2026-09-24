"""nginx serves /static/ straight from /opt/orcagent/static. install.sh
rsyncs the git clone there with `rsync -a`, which copies the clone's modes --
so after an accidental `chmod -R go-rwx ~/orcagent` every CSS/JS request got
"13: Permission denied" and the whole site rendered unstyled. The installer
must always leave the app dir traversable and static assets world-readable,
after the rsync that could have removed those bits."""
import os, re, shutil, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
install = (ROOT / 'deploy/install.sh').read_text()
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

rs = install.index('rsync -a --delete')
fix = install.find('find "$APP_DIR/static" -type f -exec chmod 644 {} +')
check('install.sh re-opens static assets for nginx', fix > 0 and 'chmod 755 "$APP_DIR"' in install)
check('...after the rsync that copies the clone modes', fix > rs)

# Run the real lines against a tree whose modes were stripped.
t = Path(tempfile.mkdtemp()); app = t / 'app'
(app / 'static' / 'sub').mkdir(parents=True)
(app / 'static' / 'navbar.css').write_text('x'); (app / 'static' / 'sub' / 'a.js').write_text('y')
subprocess.run(['chmod', '-R', 'go-rwx', str(app)], check=True)
block = '\n'.join(l for l in install.splitlines()
                  if l.startswith(('chmod 755 "$APP_DIR"', 'find "$APP_DIR/static"')))
subprocess.run(['bash', '-c', block], env={**os.environ, 'APP_DIR': str(app)}, check=True)
modes = {p.relative_to(app).as_posix(): oct(p.stat().st_mode)[-3:] for p in [app, *app.rglob('*')]}
check('the app dir is traversable again', modes['.'] == '755')
check('static dirs are 755 and files 644',
      modes['static'] == '755' and modes['static/sub'] == '755'
      and modes['static/navbar.css'] == '644' and modes['static/sub/a.js'] == '644')
shutil.rmtree(t, ignore_errors=True)
raise SystemExit(0 if all(checks) else 1)
