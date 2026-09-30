"""Admin console: five groups on desktop and phone, nothing lost.

- Every page is still reachable by its own nav button (same ids and
  handlers, so role rules and deep links keep working) and belongs to
  exactly one group: Overview, People, Money, Trading, System.
- A phone gets a bottom tab bar per group (replacing the app's own bottom
  bar on this page) and the group's pages as sub-tabs in the top bar.
- A group a role cannot open disappears, and so do its attention cards.
- Overview opens with "Needs your attention", built only from real signals
  the role may see: open support cases, pending AI filter proposals, failed
  fee transfers, blocked IP addresses.
"""
import json, os, re, subprocess
ROOT = os.path.join(os.path.dirname(__file__), '..')
html = open(os.path.join(ROOT, 'templates', 'admin.html')).read()

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

script = re.findall(r'<script>(.*?)</script>', html, re.S)[0]
def js_literal(name):
    m = re.search(r'var ' + name + r' = (\{.*?\n\});', script, re.S)
    return json.loads(subprocess.run(['node', '-e', 'console.log(JSON.stringify(' + m.group(1) + '))'],
                                     capture_output=True, text=True, timeout=20).stdout)
groups, roles = js_literal('_GROUPS'), js_literal('_ROLE_TABS')
all_views = roles['admin']
flat = [v for g in groups.values() for v in g]

check('five groups: Overview, People, Money, Trading, System', list(groups) == ['overview', 'people', 'money', 'trading', 'system'])
check('every page is in exactly one group', sorted(flat) == sorted(all_views) and len(flat) == len(set(flat)))
check('every page keeps its own nav button and view', all(
    'id="nav-%s" onclick="showView(\'%s\')"' % (v, v) in html and 'id="view-%s"' % v in html for v in all_views))
check('the sidebar is grouped', all('<div class="sb-grp" data-grp="%s">' % g in html for g in ('people', 'money', 'trading', 'system')))
check('a phone gets one tab per group', all('class="adm-tab' in html and 'data-grp="%s" onclick="showGroup(\'%s\')"' % (g, g) in html
                                          for g in groups))
check("...which replaces the app's own bottom bar on this page",
      '#oa-bottom-nav{display:none!important}' in html and 'aside{display:none!important}' in html)
check('the top bar shows the group and its pages as sub-tabs',
      'id="topbar-grp"' in html and 'id="adm-subtabs"' in html and 'function _renderSubtabs()' in html
      and '_renderSubtabs();' in script.split('function showView(name)')[1].split('\n}')[0])
check('a group the role cannot open is hidden, with its attention cards',
      ".sb-grp[data-grp=\"' + g + '\"], .adm-tab[data-grp=\"' + g + '\"]" in script
      and "card.style.display = allowed.indexOf(card.dataset.att) >= 0" in script)
mod = roles['moderator']
visible = [g for g, pages in groups.items() if any(v in mod for v in pages)]
check('a moderator sees only the groups holding their pages (People, Money › Trades, System › Security)',
      visible == ['people', 'money', 'system'])

cards = re.findall(r'data-att="(\w+)" onclick="showView\(\'(\w+)\'\)"', html)
check('attention cards each open their own page', cards and all(a == b and a in all_views for a, b in cards)
      and {a for a, _ in cards} == {'support', 'aifilters', 'revenue', 'moderation'})
att = script.split('async function loadAttention()')[1].split('\n}\n')[0]
check('...fed only by real endpoints, and only those the role may open',
      "can('support') ? _a('/api/admin/support/threads?status=open')" in att
      and "can('aifilters') ? _a('/api/admin/ai-filters')" in att
      and "can('revenue') ? _a('/api/admin/revenue')" in att
      and "can('moderation') ? _a('/api/admin/bans')" in att
      and "p.status === 'pending'" in att and "t.status === 'failed'" in att)
check('Overview loads it', 'loadAttention();' in script.split('async function loadOverview()')[1][:80])
check('no emoji section titles left', not re.search(r'>(⚡|🚩|👤|⛽|💰) ', html))

src = re.sub(r'\{\{.*?\}\}', '0', script)
src = re.sub(r'\{%.*?%\}', '', src)
r = subprocess.run(['node', '-e', 'new Function(require("fs").readFileSync(0,"utf8"))'], input=src,
                   capture_output=True, text=True, timeout=20)
check('the page script still parses', r.returncode == 0)
raise SystemExit(0 if all(checks) else 1)
