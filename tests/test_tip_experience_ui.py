"""Static UI guards for Tip receipt, account-specific histories and social display."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROFILE=(ROOT/'templates/profile.html').read_text()
WALLET=(ROOT/'templates/wallet.html').read_text()
NOTIFS=(ROOT/'templates/notifications.html').read_text()
SCRIPT=(ROOT/'static/tip-experience.js').read_text()
CSS=(ROOT/'static/tip-experience.css').read_text()
BACKEND=(ROOT/'portfolio_token_withdraw.py').read_text()
ENGINE=(ROOT/'tip_experience.py').read_text()
ENTRY=(ROOT/'app_entry.py').read_text()


def test_app_entry_installs_confirmation_worker_after_tip():
    assert ENTRY.index('_install_portfolio_token_withdraw(_dashboard)') < ENTRY.index('_install_tip_experience(_dashboard)')


def test_tip_success_receipt_shows_real_submitted_confirmed_failed():
    for item in ('oa-tip-receipt','oa-tip-receipt-explorer','oa-tip-receipt-status'):
        assert item in PROFILE
    assert 'OrcAgentTipReceipt(d, amount' in PROFILE
    assert "json('/api/tips/'" in SCRIPT
    assert "state==='confirmed'" in SCRIPT
    assert "state==='failed'" in SCRIPT
    assert 'noteCallback();refreshStats()' in SCRIPT


def test_portfolio_tab_history_and_individual_notification_deeplink():
    assert 'oa-tip-history' in WALLET
    assert '/api/tips/mine?limit=100' in SCRIPT
    assert "get('tab')" in (ROOT/'static/portfolio-redesign.js').read_text()
    assert 'tab=history&tip=' in ENGINE
    assert 'scrollIntoView' in SCRIPT
    assert '.oa-tip-row' in CSS


def test_profile_public_stats_and_private_sent_totals():
    assert 'oa-tip-received' in PROFILE
    assert 'oa-tip-supporters' in PROFILE
    assert '{% if is_own_profile %}' in PROFILE
    assert 'oa-tip-sent' in PROFILE
    assert "status='confirmed'" in ENGINE
    assert "if me == user_id:" in ENGINE


def test_recipient_notification_has_tips_tab_and_gold_icon():
    assert 'id="tab-tips"' in NOTIFS
    assert "type === 'tip'" in NOTIFS
    assert "'tip': '<svg" in NOTIFS
    assert "recipient_user_id" in ENGINE
    assert 'notification_sent_at' in ENGINE


def test_sender_does_not_claim_confirmation_at_submission():
    assert "'status':'submitted'" in BACKEND
    assert "'tip_id':tip_id" in BACKEND
    assert "'status':'confirmed'" not in BACKEND[BACKEND.index("return jsonify({",BACKEND.index("tip_id = _record_tip(")):BACKEND.index("except Exception as exc:",BACKEND.index("tip_id = _record_tip("))]


if __name__=='__main__':
    for n in sorted(x for x in globals() if x.startswith('test_')):
        globals()[n]()
        print('PASS',n)
    print('ALL TIP EXPERIENCE UI REGRESSIONS PASSED')
