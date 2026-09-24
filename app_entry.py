"""Production WSGI entry point.

OrcAgent never subsidizes user gas. EVM BUYs use 0x Gasless and Solana
USDC BUYs use Jupiter gasless support, so a user can trade without first
holding the chain's native gas token when the provider offers a gasless route.
"""
import os

# Product invariant: OrcAgent's own wallet does not subsidize user gas.
os.environ['ORCAGENT_FRONTS_GAS'] = '0'

import dashboard as _dashboard
from tip_experience import install as _install_tip_experience
from portfolio_wallet_activity import install as _install_portfolio_wallet_activity
from profile_portfolio_balance import install as _install_profile_portfolio_balance
from search_seo import install as _install_search_seo
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
from auto_trading_bot_route import install as _install_auto_trading_bot_route
from multichain_auto_bot import install as _install_multichain_auto_bot
from live_market_pooled_buy_balance import install as _install_live_market_pooled_buy_balance
from canonical_domain import install as _install_canonical_domain
from browser_shared_secret_hardening import install as _install_browser_shared_secret_hardening
from secret_hygiene import install as _install_secret_hygiene
from security_hardening import install as _install_security_hardening
from authenticated_csrf_hardening import install as _install_authenticated_csrf_hardening
from injection_hardening import install as _install_injection_hardening
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
from cross_chain_budget_guard import install as _install_cross_chain_budget_guard
from solana_source_bridge_gasless import install as _install_solana_source_bridge_gasless
from header_stable_balance import install as _install_header_stable_balance
from portfolio_multichain_holdings import install as _install_portfolio_multichain_holdings
from video_uploads import install as _install_video_uploads
from portfolio_trade_history import install as _install_portfolio_trade_history
from portfolio_token_withdraw import install as _install_portfolio_token_withdraw
from live_market_sheet_overlap_fix import install as _install_live_market_sheet_overlap_fix
from mobile_footer_visibility_fix import install as _install_mobile_footer_visibility_fix
from wallet_onboarding import install as _install_wallet_onboarding
from trading_wallet_generator import install as _install_trading_wallet_generator
from response_privacy_hardening import install as _install_response_privacy_hardening
from audit_hardening import install as _install_audit_hardening
from security_monitoring import install as _install_security_monitoring
from backup_scheduler import install as _install_backup_scheduler

# Register SEO first so its response pass runs last, after preview decorators.
_install_search_seo(_dashboard)

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
_install_auto_trading_bot_route(_dashboard)

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
_install_authenticated_csrf_hardening(_dashboard)
_install_injection_hardening(_dashboard)
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

# The autonomous bot used to perform its own native-gas precheck before the
# shared EVM BUY flow, which meant a USDC-only wallet never reached 0x Gasless.
# Patch the bot entry scanner after installing the gasless execution layer so
# Start Trading can autonomously enter every supported EVM chain using USDC.
_install_multichain_auto_bot(_dashboard)

# Solana USDC BUYs use Jupiter's automatic gasless path when configured. The
# network fee/rent is recovered by Jupiter from the swap instead of requiring
# the user to pre-fund SOL.
_install_solana_gasless_trading(_dashboard)

# Short (<=30s) video posts: chunked upload, server-side ffmpeg re-encode to
# H.264 MP4 with metadata stripped, public media dir served by nginx.
_install_video_uploads(_dashboard)

# Cross-chain buying follows the same economic invariant: the number entered
# by the user is the absolute all-in ceiling. It also lets settled EVM->Solana
# buys continue through Jupiter gasless without demanding a separate SOL
# reserve after the USDC has arrived.
_install_cross_chain_budget_guard(_dashboard)

# If an EVM-destination buy is funded by USDC sitting on Solana while that
# trading wallet has zero SOL, use Jupiter Ultra gasless to turn a small slice
# of the SAME user-entered USDC ceiling into SOL, then continue the bridge with
# the remainder. OrcAgent still fronts nothing.
_install_solana_source_bridge_gasless(_dashboard)

# The Live Market BUY sheet must use the same pooled spending balance as the
# automatic bridge backend. Otherwise Robinhood (and every empty destination
# chain) is disabled in the browser before the auto-bridge can even start.
_install_live_market_pooled_buy_balance(_dashboard)

# The compact amount pill in the shared top bar shows the user's aggregate
# stablecoin spending balance across every supported chain, formatted as USD.
_install_header_stable_balance(_dashboard)

# Portfolio must show positions from every chain OrcAgent can trade, not only
# SPL accounts on Solana. This extends the existing token feed read-only and
# labels EVM assets with their chain in the UI.
_install_portfolio_multichain_holdings(_dashboard)

# Portfolio transaction history: collapsible BUY/SELL ledger with calendar
# filtering, sourced from completed Live Market executions and realized sells.
_install_portfolio_trade_history(_dashboard)

# Withdraw any actual Portfolio token to another wallet. The server owns source
# wallet identity and rechecks the on-chain token balance before broadcasting;
# all network fees remain the user's responsibility.
_install_portfolio_token_withdraw(_dashboard)
_install_tip_experience(_dashboard)
_install_portfolio_wallet_activity(_dashboard)
_install_profile_portfolio_balance(_dashboard)

# Keep mobile Live Market execution-sheet sections in normal document flow so
# stats, percentage shortcuts, keypad, fees and slider never overlap.
_install_live_market_sheet_overlap_fix(_dashboard)

# Keep the shared mobile footer fully inside the iPhone/PWA viewport, including
# its labels and safe-area padding, instead of letting the lower half clip off.
_install_mobile_footer_visibility_fix(_dashboard)

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

from portfolio_sol_swap import install as _install_portfolio_sol_swap
_install_portfolio_sol_swap(_dashboard)

app = _dashboard.app
