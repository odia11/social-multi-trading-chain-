"""Production WSGI entry point.

Import the existing application first so every route, migration and background
loop is registered exactly as before. Then install the narrow EVM->Solana
auto-bridge adapter before Gunicorn starts accepting requests.
"""
import dashboard as _dashboard
from evm_to_solana_bridge import install as _install_evm_to_solana_bridge

_install_evm_to_solana_bridge(_dashboard)
app = _dashboard.app
