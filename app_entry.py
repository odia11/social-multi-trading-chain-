"""Production WSGI entry point.

OrcAgent is Solana-only. Trading and swaps use the Solana/Jupiter paths;
legacy EVM data remains readable but no EVM/0x runtime module is installed.
"""
import os

# Product invariant: OrcAgent's own wallet does not subsidize user gas.
os.environ['ORCAGENT_FRONTS_GAS'] = '0'

import dashboard as _dashboard
from tip_experience import install as _install_tip_experience
from portfolio_wallet_activity import install as _install_portfolio_wallet_activity
from profile_portfolio_balance import install as _install_profile_portfolio_balance
from search_seo import install as _install_search_seo
from app_performance import install as _install_app_performance
from x_post_preview_fix import install as _install_x_post_preview_fix
from x_share_cache_bust import install as _install_x_share_cache_bust
from share_canonical_routes import install as _install_share_canonical_routes
from mobile_ui_hotfix import install as _install_mobile_ui_hotfix
from trusted_phantom_autoconnect import install as _install_trusted_phantom_autoconnect
from share_card_concept_d import install as _install_share_card_concept_d
from share_token_card import install as _install_share_token_card
from messages_premium_ui import install as _install_messages_premium_ui
from auto_trading_bot_route import install as _install_auto_trading_bot_route
from bot_learning import install as _install_bot_learning
from bot_entry_policy import install as _install_bot_entry_policy
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
from header_stable_balance import install as _install_header_stable_balance
from portfolio_multichain_holdings import install as _install_portfolio_multichain_holdings
from video_uploads import install as _install_video_uploads
from trending_hero import install as _install_trending_hero
from token_launch import install as _install_token_launch
from trending_share import install as _install_trending_share
from portfolio_trade_history import install as _install_portfolio_trade_history
from portfolio_token_withdraw import install as _install_portfolio_token_withdraw
from live_market_sheet_overlap_fix import install as _install_live_market_sheet_overlap_fix
from mobile_footer_visibility_fix import install as _install_mobile_footer_visibility_fix
from new_wallet_accounts import install as _install_new_wallet_accounts
from trading_wallet_generator import install as _install_trading_wallet_generator
from response_privacy_hardening import install as _install_response_privacy_hardening
from audit_hardening import install as _install_audit_hardening
from security_monitoring import install as _install_security_monitoring
from backup_scheduler import install as _install_backup_scheduler

# Light mode is registered before everything else so its pass over the page
# runs last (after_request hooks run in reverse order) and sees every
# stylesheet the other passes added.
from theme_light import install as _install_theme_light
_install_theme_light(_dashboard)

# Register SEO first so its response pass runs last, after preview decorators.
_install_search_seo(_dashboard)

_install_app_performance(_dashboard)
_install_x_post_preview_fix(_dashboard)
_install_x_share_cache_bust(_dashboard)
_install_share_canonical_routes(_dashboard)
_install_mobile_ui_hotfix(_dashboard)
_install_trusted_phantom_autoconnect(_dashboard)
_install_share_card_concept_d(_dashboard)
# X preview of a token post = the app's own token card (share_token_card.py).
_install_share_token_card(_dashboard)
_install_messages_premium_ui(_dashboard)
_install_auto_trading_bot_route(_dashboard)
_install_bot_learning(_dashboard)
_install_bot_entry_policy(_dashboard)

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

# Solana-only product: no EVM gasless, sponsor or cross-chain execution layer
# is installed. The base bot follows the Solana scanner/trading path only.

# Native SOL buys use the Jupiter swap executor. Users fund costs with SOL.

# Short (<=30s) video posts: chunked upload, server-side ffmpeg re-encode to
# H.264 MP4 with metadata stripped, public media dir served by nginx.
_install_video_uploads(_dashboard)

# Home feed "Trending now" hero card: the scanner's hottest scam-filtered
# token while it is trending, with bull/bear votes and likes.
_install_trending_hero(_dashboard)
_install_token_launch(_dashboard)
# Wallet-independent recovery of already-signed submissions after RPC 429,
# a deployment, or iOS browser suspension. No transaction is signed or sent.
import threading as _orca_reconcile_threading
_orca_reconcile_threading.Thread(
    target=_dashboard.app._orca_reconcile_submitted_launches,
    name='orca-pump-confirmation-recovery',daemon=True).start()
# ...and a share link for it: /trending/<chain>/<token> unfurls on X as that
# card (/api/trending-card/<chain>/<token>.png) and opens it in the app.
_install_trending_share(_dashboard)

# Shared balance and Portfolio snapshot are Solana-only. Legacy module names
# remain for compatibility, but neither adapter queries EVM state.
_install_header_stable_balance(_dashboard)
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

# Guest accounts: server-generated wallet, backup + credentials, or local
# signature-only key import through the existing wallet authentication route.
_install_new_wallet_accounts(_dashboard)

# Existing authenticated users can still create a dedicated Solana trading wallet
# from Settings/Manage Wallet without replacing any funded wallet.
_install_trading_wallet_generator(_dashboard)

_install_response_privacy_hardening(_dashboard)
_install_audit_hardening(_dashboard)
_install_security_monitoring(_dashboard)
_install_backup_scheduler(_dashboard)

from portfolio_sol_swap import install as _install_portfolio_sol_swap
_install_portfolio_sol_swap(_dashboard)

from sol_native_payments import install as _install_sol_native_payments
_install_sol_native_payments(_dashboard)

from trader_rewards import install as _install_trader_rewards
_install_trader_rewards(_dashboard)

from watchlist_alerts import install as _install_watchlist_alerts
_install_watchlist_alerts(_dashboard)

from following_traders import install as _install_following_traders
_install_following_traders(_dashboard)

from group_chats import install as _install_group_chats
_install_group_chats(_dashboard)

from group_tips import install as _install_group_tips
_install_group_tips(_dashboard)

from call_invitations import install as _install_call_invitations
_install_call_invitations(_dashboard)

from creator_rewards import install as _install_creator_rewards
_install_creator_rewards(_dashboard)

# Pictures for @orcagent's live posts, served at /media/agent/<hash>.webp.
from agent_post_images import install as _install_agent_post_images
_install_agent_post_images(_dashboard)

from platform_assistant import install as _install_platform_assistant
_install_platform_assistant(_dashboard)

from live_trades_truth import install as _install_live_trades_truth
_install_live_trades_truth(_dashboard)

from portfolio_inventory import install as _install_portfolio_inventory
_install_portfolio_inventory(_dashboard)

# Drops long-expired cache entries and returns freed heap to the OS every few
# minutes, so the one long-running process does not creep up in memory.
from memory_hygiene import install as _install_memory_hygiene
_install_memory_hygiene(_dashboard)

# Registered last so it runs first among the response passes: a page the
# browser navigates to gets an OrcAgent error page, never bare JSON.
from friendly_errors import install as _install_friendly_errors
_install_friendly_errors(_dashboard)

app = _dashboard.app

from call_live_data import install as _install_call_live_data
_install_call_live_data(_dashboard)

from token_promotions import install as _install_token_promotions
_install_token_promotions(_dashboard)

from public_avatar_cache import install as _install_public_avatar_cache
_install_public_avatar_cache(_dashboard)
