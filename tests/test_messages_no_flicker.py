"""Regression checks for the standalone Messages rendering lifecycle."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
html = (root / 'templates/messages.html').read_text()
ui = (root / 'static/messages-ui.js').read_text()
inj = (root / 'messages_premium_ui.py').read_text()

assert 'area.insertAdjacentHTML(\'beforeend\',renderedHtml)' in html
assert 'if (incremental) area.insertAdjacentHTML' in html
assert 'if (!!prev.is_read === !!next.is_read) return;' in html
assert 'if (!forceScroll && area.querySelector(\'.msg-edit-input\')) return;' in html
assert 'requestSeq !== _threadRequestSeq || peerId !== _activePeerId' in html
assert 'if (_renderConvList() !== false) _lastConvSig = sig;' in html
assert 'if (_lastConvSig === null)' in html
assert 'if (_activePeerId && window.innerWidth <= 767' in html
assert "if(main)mo.observe(main,{attributes:true,attributeFilter:['class']});" in ui
assert "subtree:true,attributes:true,attributeFilter:['class','style']" not in ui
assert 'messages-ui.js?v=5' in inj

# Validate both inline scripts as actual JavaScript, with only Jinja tags removed.
for idx, script in enumerate(re.findall(r'<script(?:\s[^>]*)?>([\s\S]*?)</script>', html)):
    if not script.strip():
        continue
    script = re.sub(r'\{%[\s\S]*?%\}', '', script)
    script = re.sub(r'\{\{[\s\S]*?\}\}', 'null', script)
    completed = subprocess.run(['node', '--check'], input=script, text=True, capture_output=True)
    assert completed.returncode == 0, f'inline script {idx}: {completed.stderr}'

print('PASS messages preserve existing DOM across poll/seen/new-message updates')
print('PASS thread responses from previous conversations are discarded')
print('PASS mobile thread avoids rebuilding hidden conversation list')
print('PASS observer no longer watches its own style writes')
print('PASS both inline scripts parse as JavaScript')
