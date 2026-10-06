import os
ROOT=os.path.join(os.path.dirname(__file__),'..')
dash=open(os.path.join(ROOT,'dashboard.py'),encoding='utf-8').read()
learn=open(os.path.join(ROOT,'bot_learning.py'),encoding='utf-8').read()
shadow=open(os.path.join(ROOT,'bot_shadow_learning.py'),encoding='utf-8').read()
page=open(os.path.join(ROOT,'templates','auto_trading_bot.html'),encoding='utf-8').read()

checks=[]
def check(name,cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+name)

loop=dash[dash.index('def user_trader_loop('):dash.index('def _guardian_pass():')]
entry=loop[loop.index('# ── Pass 2: pick the single best entry'):loop.index('# ── Pass 2 (EVM):')]

scanner=dash[dash.index('def token_loop():'):dash.index('# ── TRADE RECORDING ──')]
check('shadow learning is collected once by the shared eligible Solana universe, not once per user bot',
      '_shadow_universe = [t for t in display if _bot_gainers_eligible(t)]' in scanner
      and 'bot_shadow_learning.observe_many(DB_FILE, _shadow_universe, _shadow_now)' in scanner
      and 'bot_shadow_learning.observe(' not in entry)
check('shadow learning call receives only DB path and public scanner snapshots',
      '_shadow_universe = [t for t in display if _bot_gainers_eligible(t)]' in scanner
      and 'bot_shadow_learning.observe_many(DB_FILE, _shadow_universe, _shadow_now)' in scanner
      and 'bot_shadow_learning.observe_many(DB_FILE, user_id' not in scanner
      and 'bot_shadow_learning.observe_many(DB_FILE, wallet' not in scanner)
check('off-list paper candidates get a bounded fresh-price resolution pass',
      'bot_shadow_learning.due_mints(DB_FILE, _shadow_now, limit=3)' in scanner
      and 'bot_shadow_learning.resolve_price(' in scanner)
check('shadow module independently enforces the same +7% observation floor',
      'ENTRY_TRIGGER_PCT = 7.0' in shadow and 'move >= ENTRY_TRIGGER_PCT' in shadow)
check('public market intelligence can only veto after personal safety/learning gates',
      entry.index('bot_learning.avoid_reason(') < entry.index('bot_shadow_learning.veto_reason(DB_FILE, _t)'))
check('self-learning opt-out disables the public shadow veto for that user',
      '_shadow_enabled = bot_learning.learning_enabled(DB_FILE, user_id)' in entry
      and "bot_shadow_learning.veto_reason(DB_FILE, _t) if _shadow_enabled else ''" in entry)
check('shadow layer has no execution or exit-setting API',
      not any(('def '+name+'(') in shadow for name in ('buy','execute','open_position','set_take_profit','set_stop_loss')))
check('user TP/SL snapshot still receives no shadow tuning',
      'bot_shadow_learning' not in dash[dash.index('def _snapshot_entry_risk('):dash.index('def _upsert_open_position(')])
check('learning API exposes market brain status without exposing its raw observations',
      "'market_brain': shadow" in learn and 'bot_shadow_learning.status(d.DB_FILE)' in learn)
check('bot page explains paper/shadow learning and veto-only behavior',
      'paper/shadow mode' in page and 'never forces a buy' in page and 'never changes your take profit or stop loss' in page)
check('UI shows market brain readiness/sample count',
      'Market brain learning:' in page and 'Market brain active:' in page)
check('SOL remains the one Solana buy currency',
      "SOLANA_BASE_CURRENCY = 'SOL'" in dash)

raise SystemExit(0 if all(checks) else 1)
