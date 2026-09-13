"""Production WSGI entry point.

Import the existing application first so every route, migration and background
loop is registered exactly as before. Then install the narrow runtime adapters
before Gunicorn starts accepting requests.
"""
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
from x_share_fallback import install as _install_x_share_fallback
from secret_hygiene import install as _install_secret_hygiene
from security_hardening import install as _install_security_hardening
from ssrf_hardening import install as _install_ssrf_hardening
from auth_replay_hardening import install as _install_auth_replay_hardening
from authorization_hardening import install as _install_authorization_hardening
from financial_authorization_hardening import install as _install_financial_authorization_hardening
from owner_money_hardening import install as _install_owner_money_hardening
from upload_hardening import install as _install_upload_hardening
from response_privacy_hardening import install as _install_response_privacy_hardening
from audit_hardening import install as _install_audit_hardening
from security_monitoring import install as _install_security_monitoring
from backup_scheduler import install as _install_backup_scheduler

_install_evm_to_solana_bridge(_dashboard)
_install_wallet_deposit_guidance(_dashboard)
_install_app_performance(_dashboard)
# Register this before share_canonical_routes: Flask runs app-level
# after_request handlers in reverse registration order, so this executes last
# and leaves one authoritative OG/Twitter metadata set for /post/<id>.
_install_x_post_preview_fix(_dashboard)
# Install before share_canonical_routes. That route adapter appends the
# permanent /post/<id> link, then calls this wrapped _post_to_x which adds a
# harmless version query so X cannot reuse its stale generic-card cache.
_install_x_share_cache_bust(_dashboard)
_install_share_canonical_routes(_dashboard)
_install_mobile_ui_hotfix(_dashboard)
_install_trusted_phantom_autoconnect(_dashboard)
_install_share_card_concept_d(_dashboard)
_install_messages_premium_ui(_dashboard)
_install_live_market_deeplink_fix(_dashboard)
_install_x_share_fallback(_dashboard)

# Security layers. Startup secret validation runs before request guards. The
# remaining adapters are defense-in-depth around the route-level checks that
# already exist in dashboard.py.
_install_secret_hygiene(_dashboard)
_install_security_hardening(_dashboard)
_install_ssrf_hardening(_dashboard)
_install_auth_replay_hardening(_dashboard)
_install_authorization_hardening(_dashboard)
_install_financial_authorization_hardening(_dashboard)
_install_owner_money_hardening(_dashboard)
_install_upload_hardening(_dashboard)
_install_response_privacy_hardening(_dashboard)
_install_audit_hardening(_dashboard)
_install_security_monitoring(_dashboard)
_install_backup_scheduler(_dashboard)

app = _dashboard.app
