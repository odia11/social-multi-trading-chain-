"""Regression guards for Anthropic auth breaker and X-buzz request coalescing."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'dashboard.py').read_text()


def block(start_marker,end_marker):
    a=SRC.index(start_marker); b=SRC.index(end_marker,a); return SRC[a:b]


def test_process_wide_auth_breaker_exists():
    b=block("_anthropic_auth_state =", "_ANTHROPIC_URL")
    assert "'failed': False" in b
    assert 'def _anthropic_operationally_available' in b
    assert 'def _mark_anthropic_auth_failed' in b
    assert "globals()['_ai_disabled_until'] = float('inf')" in b
    assert 'if first:' in b


def test_x_buzz_obeys_breaker_and_marks_401_once():
    b=block('def _discover_x_buzz()', '\ndef _resolve_buzz_pairs')
    assert 'if not _anthropic_operationally_available()' in b
    assert 'with _x_buzz_call_lock:' in b
    assert "if resp.status_code == 401:" in b
    assert "_mark_anthropic_auth_failed('x-buzz')" in b
    assert "resp.text[:500]" not in b


def test_empty_buzz_is_a_real_cache_hit():
    b=block('def get_multichain_x_buzz()', '\ndef _match_buzz_to_mints')
    assert "if _buzz_cache['ts'] and now - _buzz_cache['ts'] < _BUZZ_TTL:" in b
    assert "and _buzz_cache['data']" not in b
    assert 'with _buzz_refresh_lock:' in b
    assert "_buzz_cache['ts'] = now" in b


def test_narrative_agent_reuses_cached_buzz():
    b=block('def _narrative_agent_gather_candidates()', '\ndef _narrative_agent_evaluate_candidates')
    assert 'for buzz_cand in get_multichain_x_buzz():' in b
    assert '_discover_x_buzz()' not in b
    assert "!= 'solana'" in b


def test_other_operational_ai_calls_share_breaker():
    checks=[
      ('def get_ai_signal(', '\n_AI_TRADE_GATE_CACHE', '_mark_anthropic_auth_failed(\'ai-signal\')'),
      ('def get_ai_trade_decision(', '\n# ── AI SELF-ANALYSIS LOOP', '_mark_anthropic_auth_failed(\'ai-trade-gate\')'),
      ('def run_ai_self_analysis(', '\ndef get_narrative_signal', '_mark_anthropic_auth_failed(\'ai-self-analysis\')'),
      ('def get_narrative_signal(', '\n_x_buzz_call_lock', '_mark_anthropic_auth_failed(\'narrative-signal\')'),
    ]
    for a,z,marker in checks:
        b=block(a,z)
        assert '_anthropic_operationally_available()' in b
        assert marker in b


def test_admin_test_can_clear_breaker_after_key_replacement():
    b=block("@app.route('/api/admin/test'", "@app.route('/api/admin/test_fee'")
    assert '_clear_anthropic_auth_failure()' in b
    assert "_mark_anthropic_auth_failed('admin-test')" in b


if __name__=='__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS',name)
    print('ALL ANTHROPIC AUTH CIRCUIT REGRESSIONS PASSED')
