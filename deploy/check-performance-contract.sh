#!/usr/bin/env bash
# OrcAgent protected UX contract.
#
# Feature deploys MUST preserve the native-app navigation layer. This guard is
# intentionally called from BOTH update.sh and install.sh so ordinary deploys
# cannot accidentally regress the instant-navigation behaviour.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for test_file in \
  tests/test_instant_navigation.py \
  tests/test_app_performance.py \
  tests/test_instant_navigation_contract.py \
  tests/test_home_balance_consistency.py \
  tests/test_safari_mobile_chrome.py
do
  python3 "$REPO_DIR/$test_file"
done

echo "protected instant-navigation contract passed"
