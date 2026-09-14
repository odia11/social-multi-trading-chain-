from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
service = (ROOT/'deploy/orcagent.service').read_text()
monitor = (ROOT/'deploy/orcagent-monitor.service').read_text()
backup = (ROOT/'deploy/orcagent-backup.service').read_text()
install = (ROOT/'deploy/install.sh').read_text()
smoke = (ROOT/'deploy/security-smoke.sh').read_text()

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

for name, text in [('app', service), ('monitor', monitor), ('backup', backup)]:
    check(name+' has no new privileges', 'NoNewPrivileges=true' in text)
    check(name+' protects kernel tunables', 'ProtectKernelTunables=true' in text)
    check(name+' protects kernel modules', 'ProtectKernelModules=true' in text)
    check(name+' blocks capability inheritance', 'CapabilityBoundingSet=' in text and 'AmbientCapabilities=' in text)
    check(name+' restricts namespaces', 'RestrictNamespaces=true' in text)

check('app is loopback only', '--bind 127.0.0.1:8080' in service)
check('app startup executes security smoke check', 'ExecStartPost=/bin/bash /opt/orcagent/deploy/security-smoke.sh' in service)
check('backup runs unprivileged', 'User=orcagent' in backup and 'Group=orcagent' in backup and 'User=root' not in backup)
check('backup only writes backup directory', 'ReadWritePaths=/data/backups' in backup)
check('installer verifies systemd units', 'systemd-analyze verify' in install)
check('installer executes backup service', 'systemctl start orcagent-backup.service' in install)
check('installer installs smoke checker executable', 'security-smoke.sh' in install and 'chmod 755' in install)
check('smoke validates CSP', 'Content-Security-Policy' in smoke and "frame-ancestors 'none'" in smoke)
check('smoke validates loopback binding', 'gunicorn port 8080 is publicly bound' in smoke)
check('smoke validates env permissions', '/etc/orcagent.env permissions' in smoke)
check('smoke validates backup timer', 'orcagent-backup.timer' in smoke)

raise SystemExit(0 if all(checks) else 1)
