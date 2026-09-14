from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app_entry = (ROOT / 'app_entry.py').read_text()
service = (ROOT / 'deploy/orcagent.service').read_text()
install = (ROOT / 'deploy/install.sh').read_text()
env_example = (ROOT / 'deploy/env.example').read_text()

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

check('runtime forces no gas fronting before dashboard import',
      "os.environ['ORCAGENT_FRONTS_GAS'] = '0'" in app_entry
      and app_entry.index("os.environ['ORCAGENT_FRONTS_GAS'] = '0'") < app_entry.index('import dashboard as _dashboard'))
check('systemd service forces no gas fronting', 'Environment=ORCAGENT_FRONTS_GAS=0' in service)
check('installer normalizes production env policy',
      "sed -i '/^[[:space:]]*ORCAGENT_FRONTS_GAS=/d'" in install
      and "ORCAGENT_FRONTS_GAS=0" in install)
check('fresh installs default to user-funded gas', 'ORCAGENT_FRONTS_GAS=0' in env_example)
check('legacy sponsor keys are documented as unused', 'Legacy sponsor keys are intentionally unused' in env_example)

raise SystemExit(0 if all(checks) else 1)
