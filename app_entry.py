"""Production WSGI entry point.

OrcAgent never subsidizes user gas. EVM BUYs use 0x Gasless and Solana
USDC BUYs use Jupiter gasless support, so a user can trade without first
holding the chain's native gas token when the provider offers a gasless route.
"""
import os

# Product invariant: OrcAgent's own wallet does not subsidize user gas.
os.environ['ORCAGENT_FRONTS_GAS'] = '0'

import dashboard as _dashboard
from evm_to_solana_bridge import install as _install_evm_to_solana_bridge
from wallet_deposit_guidance import install as _install_wallet_deposit_guidance
from app_performance import install as _install_app_performance
from x_post_preview_fix import install as _install_x_post_preview_fix
from x_share_cache_bust import install as _install_x_share_cache_bust
from share_canonical_routes import install as _install_share_canonical_routes
from mobile_ui_hotfix import install as _install_mobile_ui_hotfix
from trusted_phantom_autoconnect import install as _install_trusted_phantom_autoconnect
from share_card_concept_d import install as _install_share_card_concept_d
from messages_premium_ui import install as _install_messages_premium_ui
from live_market_deeplink_fix import install as _install_live_market_deeplink_fix
from canonical_domain import install as _install_canonical_domain
from browser_shared_secret_hardening import install as _install_browser_shared_secret_hardening
from secret_hygiene import install as _install_secret_hygiene
from security_hardening import install as _install_security_hardening
from ssrf_hardening import install as _install_ssrf_hardening
from auth_replay_hardening import install as _install_auth_replay_hardening
from authorization_hardening import install as _install_authorization_hardening
from admin_csrf_hardening import install as _install_admin_csrf_hardening
from financial_authorization_hardening import install as _install_financial_authorization_hardening
from owner_money_hardening import install as _install_owner_money_hardening
from abuse_rate_hardening import install as _install_abuse_rate_hardening
from upload_hardening import install as _install_upload_hardening
from bsc_gasless_trading import install as _install_evm_gasless_trading
from solana_gasless_trading import install as _install_solana_gasless_trading
from wallet_onboarding import install as _install_wallet_onboarding
from trading_wallet_generator import install as _install_trading_wallet_generator
from response_privacy_hardening import install as _install_response_privacy_hardening
from audit_hardening import install as _install_audit_hardening
from security_monitoring import install as _install_security_monitoring
from backup_scheduler import install as _install_backup_scheduler

_install_evm_to_solana_bridge(_dashboard)
_install_wallet_deposit_guidance(_dashboard)
_install_app_performance(_dashboard)
_install_x_post_preview_fix(_dashboard)
_install_x_share_cache_bust(_dashboard)
_install_share_canonical_routes(_dashboard)
_install_mobile_ui_hotfix(_dashboard)
_install_trusted_phantom_autoconnect(_dashboard)
_install_share_card_concept_d(_dashboard)
_install_messages_premium_ui(_dashboard)
_install_live_market_deeplink_fix(_dashboard)

# Reject untrusted Host headers before any security- or auth-sensitive route
# can derive an absolute URL/origin from them. Loopback remains allowed for
# the server-side health/security smoke checks.
_install_canonical_domain(_dashboard)

# A server-wide credential rendered into browser HTML is public, not secret.
# Disable that legacy boundary before requests begin; browser mutations rely
# on authenticated session + CSRF + the route/object authorization layers.
_install_browser_shared_secret_hardening(_dashboard)

# Security layers.
_install_secret_hygiene(_dashboard)
_install_security_hardening(_dashboard)
_install_ssrf_hardening(_dashboard)
_install_auth_replay_hardening(_dashboard)
_install_authorization_hardening(_dashboard)
_install_admin_csrf_hardening(_dashboard)
_install_financial_authorization_hardening(_dashboard)
_install_owner_money_hardening(_dashboard)
_install_abuse_rate_hardening(_dashboard)
_install_upload_hardening(_dashboard)

# Every EVM BUY (BNB Chain, Base, Arbitrum, Polygon, Robinhood Chain) uses
# 0x Gasless: native BNB/ETH/POL is not a prerequisite for a stablecoin-funded
# buy, and OrcAgent does not front it.
_install_evm_gasless_trading(_dashboard)

# Solana USDC BUYs use Jupiter's automatic gasless path when configured. The
# network fee/rent is recovered by Jupiter from the swap instead of requiring
# the user to pre-fund SOL.
_install_solana_gasless_trading(_dashboard)

# Guest homepage onboarding mirrors the familiar wallet-app choice: create a
# new self-custodial wallet, import an existing private key, or connect Phantom.
# Generated/imported wallet keys are encrypted before storage and never logged.
_install_wallet_onboarding(_dashboard)

# Existing authenticated users can still create a dedicated trading-wallet pair
# from Settings/Manage Wallet without replacing any funded wallet.
_install_trading_wallet_generator(_dashboard)

_install_response_privacy_hardening(_dashboard)
_install_audit_hardening(_dashboard)
_install_security_monitoring(_dashboard)
_install_backup_scheduler(_dashboard)

app = _dashboard.app
