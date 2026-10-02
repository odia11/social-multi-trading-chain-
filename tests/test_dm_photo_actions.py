"""Messages photo actions: download, forward and post-to-feed."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / 'templates' / 'messages.html').read_text(encoding='utf-8')

checks = []
def check(name, cond):
    checks.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name)

check('every rendered DM image exposes a photo-actions button',
      'class="dm-photo-more"' in html and '_openDmPhotoActions(event,' in html)
check('photo action sheet exposes download, forward and Home feed post',
      'data-photo-action="download"' in html
      and 'data-photo-action="forward"' in html
      and 'data-photo-action="post"' in html)
check('download uses an image blob and a real download filename',
      "URL.createObjectURL(blob)" in html
      and "a.download='orcagent-photo-'" in html)
check('forward reuses the secured DM image route',
      "fetch('/api/messages/'+peerId" in html
      and "'X-CSRF-Token':_csrfToken" in html
      and "message_type:'image'" in html)
check('forward picker supports recent chats and user search',
      '_dmForwardUsersFromConversations' in html
      and "fetch('/api/users/search?q='" in html)
check('post reuses the existing feed photo endpoint',
      "fetch('/api/feed/post'" in html
      and "image_data:imageData" in html)
check('old static DM image URLs are converted before forward/post',
      '_dmPhotoAsDataUrl' in html
      and "fetch(src,{credentials:'same-origin'})" in html
      and 'readAsDataURL(blob)' in html)
check('photo actions are mobile bottom-sheet friendly',
      '.dm-photo-sheet-backdrop{position:fixed' in html
      and 'align-items:flex-end' in html
      and 'env(safe-area-inset-bottom' in html)
check('photo action button does not replace normal photo lightbox',
      '_showImgLightbox(this.src)' in html)

raise SystemExit(0 if all(checks) else 1)
