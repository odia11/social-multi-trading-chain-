from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app_entry = (ROOT / 'app_entry.py').read_text()
service = (ROOT / 'deploy/orcagent.service').read_text()
install = (ROOT / 'deploy/install.sh').read_text()
env_example = (ROOT / 'deploy/env.example').read_text()
gasless = (ROOT / 'bsc_gasless_trading.py').read_text()
solana_test = (ROOT / 'tests/test_solana_gasless_trading.py').read_text()

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

check('runtime disables OrcAgent-funded native-gas sponsorship before dashboard import',
      "os.environ['ORCAGENT_FRONTS_GAS'] = '0'" in app_entry
      and app_entry.index("os.environ['ORCAGENT_FRONTS_GAS'] = '0'") < app_entry.index('import dashboard as _dashboard'))
check('systemd also disables the legacy platform sponsor rail',
      'Environment=ORCAGENT_FRONTS_GAS=0' in service)
check('installer normalizes production env policy',
      "sed -i '/^[[:space:]]*ORCAGENT_FRONTS_GAS=/d'" in install
      and 'ORCAGENT_FRONTS_GAS=0' in install)
check('fresh installs disable platform subsidy',
      'ORCAGENT_FRONTS_GAS=0' in env_example)

check('every supported EVM BUY uses 0x Gasless instead of requiring native gas',
      "'/gasless/quote'" in gasless
      and "'/gasless/submit'" in gasless
      and 'get_chain(chain_name)' in gasless
      and "kind == 'evm'" in gasless
      and 'EVM BUYs use 0x Gasless on every supported EVM chain.' in env_example)

check('Solana USDC BUYs have a zero-SOL gasless rail',
      'JUPITER_API_KEY=' in env_example
      and 'Solana USDC BUYs use Jupiter gasless' in env_example
      and ('zero SOL' in solana_test or 'zero/low SOL' in env_example))

check('legacy sponsor keys are documented as unused under the no-subsidy policy',
      'Legacy platform sponsor keys are intentionally unused under this policy.' in env_example
      and 'GAS_SPONSOR_PRIVATE_KEY=' in env_example
      and 'SOL_GAS_SPONSOR_PRIVATE_KEY=' in env_example)

raise SystemExit(0 if all(checks) else 1)
