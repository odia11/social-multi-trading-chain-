from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
service = (ROOT/'deploy/orcagent.service').read_text()
monitor = (ROOT/'deploy/orcagent-monitor.service').read_text()
backup = (ROOT/'deploy/orcagent-backup.service').read_text()
install = (ROOT/'deploy/install.sh').read_text()
smoke = (ROOT/'deploy/security-smoke.sh').read_text()
nginx = (ROOT/'deploy/nginx-orcagent.conf').read_text()
nginx_server = (ROOT/'deploy/nginx-server-security.conf').read_text()
nginx_zones = (ROOT/'deploy/nginx-security-zones.conf').read_text()

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
check('app uses owner-only umask', 'UMask=0077' in service)
check('backup runs unprivileged', 'User=orcagent' in backup and 'Group=orcagent' in backup and 'User=root' not in backup)
check('backup only writes backup directory', 'ReadWritePaths=/data/backups' in backup)
check('installer verifies systemd units', 'systemd-analyze verify' in install)
check('installer executes backup service', 'systemctl start orcagent-backup.service' in install)
check('installer installs smoke checker executable', 'security-smoke.sh' in install and 'chmod 755' in install)
check('installer repairs data directory ownership', 'chown -R "$APP_USER:$APP_USER" "$DATA_DIR"' in install)
check('installer strips group/world access from data directories', 'find "$DATA_DIR" -xdev -type d -exec chmod 700' in install)
check('installer strips group/world access from data files', 'find "$DATA_DIR" -xdev -type f -exec chmod 600' in install)
check('smoke validates CSP', 'Content-Security-Policy' in smoke and "frame-ancestors 'none'" in smoke)
check('smoke validates loopback binding', 'gunicorn port 8080 is publicly bound' in smoke)
check('smoke validates env permissions', '/etc/orcagent.env permissions' in smoke)
check('smoke validates persistent state permissions', 'persistent application state is owner-only' in smoke and '/data permissions are' in smoke)
check('smoke validates backup timer', 'orcagent-backup.timer' in smoke)

check('nginx template loads server security snippet', 'orcagent-server-security.conf' in nginx)
check('nginx hides version tokens', 'server_tokens off' in nginx_server)
check('nginx rejects TRACE and CONNECT', 'TRACE|CONNECT' in nginx_server and 'return 405' in nginx_server)
check('nginx connection limit has a shared zone', 'limit_conn_zone' in nginx_zones and 'orca_conn' in nginx_zones)
check('nginx server enforces connection cap', 'limit_conn orca_conn 80' in nginx_server)
check('static route is read-only at the edge', 'location /static/' in nginx and 'limit_except GET { deny all; }' in nginx)
check('static assets carry nosniff protection', 'X-Content-Type-Options "nosniff"' in nginx)
check('health route is non-cacheable', 'location = /health' in nginx and 'Cache-Control "no-store"' in nginx)
check('upstream implementation header is hidden', 'proxy_hide_header X-Powered-By;' in nginx)
check('installer preserves Certbot TLS while injecting security snippet', "grep -q 'ssl_certificate'" in install and 'sed -i' in install and 'orcagent-server-security.conf' in install)
check('installer validates live nginx security config', 'nginx -T' in install and 'server_tokens off' in install and 'limit_conn orca_conn 80' in install)

raise SystemExit(0 if all(checks) else 1)
