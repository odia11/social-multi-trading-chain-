"""Production WSGI entry point.

Import the existing application first so every route, migration and background
loop is registered exactly as before. Then install the narrow runtime adapters
before Gunicorn starts accepting requests.
"""
import dashboard as _dashboard
from evm_to_solana_bridge import install as _install_evm_to_solana_bridge
from wallet_deposit_guidance import install as _install_wallet_deposit_guidance
from app_performance import install as _install_app_performance

_install_evm_to_solana_bridge(_dashboard)
_install_wallet_deposit_guidance(_dashboard)
_install_app_performance(_dashboard)
app = _dashboard.app
