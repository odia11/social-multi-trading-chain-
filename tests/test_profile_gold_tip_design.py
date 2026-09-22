"""Profile gold CTA design must retain the live USDC tip flow and privacy UI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'templates/profile.html').read_text()
CSS = (ROOT / 'static/profile-gold-tip.css').read_text()


def test_gold_style_loads_after_profile_v2_and_cache_busts():
    old = '/static/profile-v2.css?v={{ app_version }}'
    new = '/static/profile-gold-tip.css?v={{ app_version }}-gold-v1'
    assert HTML.count(old) == 1
    assert HTML.count(new) == 1
    assert HTML.index(old) < HTML.index(new)


def test_reference_gold_pill_and_dark_coin():
    assert '.oa-profile-v2 .pf-action-row .pf-btn-tip {' in CSS
    assert 'linear-gradient(108deg, #ffc05f' in CSS
    assert 'min-height: 49px' in CSS
    assert 'border-radius: 13px' in CSS
    assert '.pf-btn-tip::before {' in CSS
    assert "content: '$'" in CSS
    assert 'border-radius: 50%' in CSS
    assert 'background: radial-gradient(' in CSS
    assert '.pf-btn-tip > svg {' in CSS
    assert 'display: none;' in CSS


def test_original_tip_route_and_other_profile_elements_intact():
    assert '<button class="pf-btn-tip" type="button" onclick="_openTip()">' in HTML
    assert 'Tip USDC' in HTML
    assert 'id="oa-profile-balance"' in HTML
    assert 'id="oa-tip-stats"' in HTML
    assert 'pf-btn-primary' in HTML
    assert 'href="/messages/{{ wallet }}"' in HTML


def test_mobile_and_accessible_interactions():
    assert '@media (max-width: 767px)' in CSS
    assert ':focus-visible' in CSS
    assert 'outline-offset: 3px' in CSS
    assert '@media (prefers-reduced-motion: reduce)' in CSS
    assert ':active' in CSS


if __name__ == '__main__':
    for name in sorted(x for x in globals() if x.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL PROFILE GOLD TIP DESIGN REGRESSIONS PASSED')
