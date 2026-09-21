"""No-network regression checks for the approved Auto Trading and Portfolio mobile UI."""
from pathlib import Path
from html.parser import HTMLParser
import ast
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BOT = (ROOT / 'templates/auto_trading_bot.html').read_text()
WALLET = (ROOT / 'templates/wallet.html').read_text()
PORT_JS = (ROOT / 'static/portfolio-redesign.js').read_text()
PORT_CSS = (ROOT / 'static/portfolio-redesign.css').read_text()
DASHBOARD = (ROOT / 'dashboard.py').read_text()

class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
    def handle_starttag(self, name, attributes):
        for key, value in attributes:
            if key == 'id':
                self.ids.append(value)

def test_bot_fields_and_live_settings():
    parser = IDs()
    parser.feed(BOT)
    for field in ('bot-toggle-btn','bot-save','bot-max-trade','bot-loss-limit',
                  'bot-tp','bot-sl','bot-status-text','bot-live-word'):
        assert parser.ids.count(field) == 1, field
    assert "fetch('/api/settings/save'" in BOT
    assert "fetch('/api/bot/overview'" in BOT
    assert "fetch(prev?'/api/bot/stop':'/api/bot/start'" in BOT
    assert '_scan_interval = 2.0' in DASHBOARD
    assert 'Scan Interval</span><strong>2 seconds' in BOT

def test_portfolio_single_real_balance_and_actions():
    parser = IDs()
    parser.feed(WALLET)
    for field in ('pf-total','pf-spark-line','pf-usdc-asset','pf-sol-asset','tokens'):
        assert parser.ids.count(field) == 1, field
    for function in ('_modalDeposit()', '_modalSend()'):
        assert function in WALLET
    assert "data-portfolio-tab=\"assets\"" in WALLET
    assert "data-portfolio-tab=\"chains\"" in WALLET
    assert "data-portfolio-tab=\"history\"" in WALLET
    assert "hero=document.createElement" not in PORT_JS
    assert "allocation=document.createElement" not in PORT_JS
    assert 'body.oa-portfolio .pf-allocation{display:none!important}' in PORT_CSS

def test_cache_and_backend_contract():
    assert 'approved-bot.css?v={{ app_version }}' in BOT
    assert 'approved-portfolio.js?v={{ app_version }}' in WALLET
    assert 'portfolio-redesign.css?v={{ app_version }}' in WALLET
    assert "'max_trade_size': max_trade_size if max_trade_size is not None" in DASHBOARD
    assert "'daily_loss_limit': daily_loss_limit if daily_loss_limit is not None" in DASHBOARD
    assert "('max_trade_size', 100000.0)" in DASHBOARD
    assert "('daily_loss_limit', 500000.0)" in DASHBOARD
    assert '24h change unavailable' not in (ROOT/'static/approved-portfolio.js').read_text()
    assert 'body.oa-portfolio .portfolio-tabs button.selected' in PORT_CSS

if __name__ == '__main__':
    for name, value in tuple(globals().items()):
        if name.startswith('test_') and callable(value):
            value()
            print('PASS', name)
