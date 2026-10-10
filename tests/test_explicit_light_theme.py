"""Explicit light-theme colours must survive the generated companion sheet."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from theme_light import light_css

source = '''
.card{background:#10151c;color:#edf1f5}
html[data-theme="light"] .card{background:#fff;color:#121820}
html[data-theme='light'] .overlay{background:rgba(20,28,40,.38)}
@media(max-width:600px){html[data-theme=light] .card{color:#66717e}}
'''
result = light_css(source)
assert 'html[data-theme="light"] .card{background:#fff;color:#121820}' in result
assert "html[data-theme='light'] .overlay{background:rgba(20,28,40,.38)}" in result
assert 'html[data-theme=light] .card{color:#66717e}' in result
assert '#edf1f5' not in result, 'ordinary dark rules should still be converted'
print('PASS explicit light colours, translucent overlay and nested media rules')
