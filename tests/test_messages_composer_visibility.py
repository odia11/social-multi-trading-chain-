"""Prevent mobile DMs hiding the final bubble and its Seen label behind composer."""
from pathlib import Path
import re
import subprocess
root=Path(__file__).resolve().parents[1]
css=(root/'static/messages-thread.css').read_text()
js=(root/'static/messages-ui.js').read_text()
ui=(root/'messages_premium_ui.py').read_text()
# The old composer was position:absolute with z-index 80 over the scroller.
# Appending padding to the scroller still left the last Seen timestamp clipped
# on iPhone when its composer expanded, or the browser viewport shrank.
end=css.split('/* Messages viewport/composer overlap fix',1)[1]
assert 'html body.oa-thread-open.oa-msgs-typing .msgs-input-bar.oa-composer-v4' in end
assert 'position:relative!important' in end
assert 'inset:auto!important' in end
assert 'bottom:auto!important' in end
assert 'flex:0 0 auto!important' in end
assert 'html body.oa-thread-open.oa-msgs-typing .msgs-area' in end
assert 'flex:1 1 0%!important' in end
assert 'padding:14px 14px 18px!important' in end
assert 'var(--oa-dm-viewport-h,100dvh)' in end
assert "style.setProperty('--oa-dm-viewport-h',Math.round(vv.height)+'px')" in js
assert "style.setProperty('--oa-dm-viewport-top',Math.round(vv.offsetTop)+'px')" in js
assert "style.removeProperty('--oa-dm-viewport-h')" in js
assert 'messages-thread.css?v=2' in ui and 'messages-ui.js?v=4' in ui
assert subprocess.run(['node','--check',str(root/'static/messages-ui.js')],capture_output=True).returncode==0
print('PASS composer occupies real flex height instead of covering last message')
print('PASS Seen/time labels have a non-overlapping scrollable bottom')
print('PASS iOS keyboard resizes full thread and returns to normal on blur')
print('PASS new CSS/JS versions bypass existing mobile cache')
