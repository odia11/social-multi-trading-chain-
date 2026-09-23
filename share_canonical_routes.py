"""Canonical sharing fixes for OrcAgent.

Keeps permanent app links attached to X shares, gives profiles a stable
user-id route that survives username changes, makes /post/<id> deep links
open the exact shared feed post, and exposes rich X/Open Graph metadata for
those canonical post URLs.
"""
from contextvars import ContextVar
from functools import wraps
import html
import json
import os
import re
import secrets
import sqlite3
from urllib.parse import quote


_share_link = ContextVar('orca_share_link', default='')
_INSTALLED = False
_POST_ID_RE = re.compile(r'^[pt]\d+$')


def _public_base_url():
    return (os.getenv('ORCAGENT_PUBLIC_URL') or 'https://orcagent.fun').rstrip('/')


def _append_canonical_link(text, link, limit=280):
    text = (text or '').strip()
    if not link or link in text:
        return text
    suffix = ' ' + link
    if len(text) + len(suffix) <= limit:
        return text + suffix
    keep = max(0, limit - len(suffix) - 1)
    trimmed = text[:keep].rstrip()
    if trimmed:
        trimmed += '…'
    return (trimmed + suffix).strip()


def _find_endpoint(app, rule_text):
    for rule in app.url_map.iter_rules():
        if rule.rule == rule_text and 'GET' in rule.methods:
            return rule.endpoint
    return None


def _find_feed_share_endpoint(app):
    for rule in app.url_map.iter_rules():
        if rule.rule == '/api/feed/share-to-x/<path:post_id>':
            return rule.endpoint
    return None


def _profile_user_id(dashboard_module, identifier):
    conn = sqlite3.connect(dashboard_module.DB_FILE)
    try:
        row = conn.execute(
            'SELECT id FROM users WHERE wallet_address=? OR username=? LIMIT 1',
            (identifier, identifier),
        ).fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def _profile_wallet(dashboard_module, user_id):
    conn = sqlite3.connect(dashboard_module.DB_FILE)
    try:
        row = conn.execute(
            'SELECT wallet_address FROM users WHERE id=? LIMIT 1',
            (int(user_id),),
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def _post_social_meta(post_id):
    """Return crawler-visible rich-card metadata for a canonical feed post."""
    base = _public_base_url()
    safe_id = quote(str(post_id or ''), safe='')
    canonical = f'{base}/post/{safe_id}'

    # The existing OrcAgent card renderer already produces the 1200x630 image
    # used by X media uploads/unfurls. Point X/Open Graph at the same source so
    # a pasted /post/<id> link renders visually on X instead of as plain text.
    image = f'{base}/api/trade-card/{safe_id}.png'
    title = 'OrcAgent · Social Trading Post'
    description = 'View this post, token call or trade on OrcAgent.'

    esc = lambda value: html.escape(value, quote=True)
    return (
        '\n<!-- OrcAgent canonical social preview -->\n'
        f'<link rel="canonical" href="{esc(canonical)}">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{esc(title)}">\n'
        f'<meta name="twitter:description" content="{esc(description)}">\n'
        f'<meta name="twitter:image" content="{esc(image)}">\n'
        '<meta name="twitter:image:alt" content="OrcAgent post preview">\n'
        '<meta property="og:type" content="website">\n'
        f'<meta property="og:site_name" content="OrcAgent">\n'
        f'<meta property="og:title" content="{esc(title)}">\n'
        f'<meta property="og:description" content="{esc(description)}">\n'
        f'<meta property="og:url" content="{esc(canonical)}">\n'
        f'<meta property="og:image" content="{esc(image)}">\n'
        '<meta property="og:image:width" content="1200">\n'
        '<meta property="og:image:height" content="630">\n'
        '<meta property="og:image:type" content="image/png">\n'
    )


def _inject_post_social_meta(body, post_id):
    if not body or not _POST_ID_RE.fullmatch(post_id or ''):
        return body, False
    meta = _post_social_meta(post_id)
    # Insert immediately after <head> so social crawlers see the canonical
    # post metadata before any generic page-level tags.
    updated, count = re.subn(
        r'(<head\b[^>]*>)',
        lambda m: m.group(1) + meta,
        body,
        count=1,
        flags=re.IGNORECASE,
    )
    return updated, bool(count)


def install(dashboard_module):
    """Install narrow, concurrency-safe runtime adapters on the Flask app."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = dashboard_module.app
    original_post_to_x = dashboard_module._post_to_x

    @wraps(original_post_to_x)
    def _post_to_x_with_canonical_link(wallet, text, media_ids=None):
        link = _share_link.get()
        if link:
            text = _append_canonical_link(text, link)
        return original_post_to_x(wallet, text, media_ids=media_ids)

    dashboard_module._post_to_x = _post_to_x_with_canonical_link

    endpoint = _find_feed_share_endpoint(app)
    if endpoint and endpoint in app.view_functions:
        original_feed_share = app.view_functions[endpoint]

        @wraps(original_feed_share)
        def _feed_share_with_canonical_context(*args, **kwargs):
            post_id = kwargs.get('post_id')
            if post_id is None and args:
                post_id = args[0]
            link = _public_base_url() + '/post/' + quote(str(post_id or ''), safe='')
            token = _share_link.set(link)
            try:
                return original_feed_share(*args, **kwargs)
            finally:
                _share_link.reset(token)

        app.view_functions[endpoint] = _feed_share_with_canonical_context

    root_endpoint = _find_endpoint(app, '/')
    if 'canonical_post_by_id' not in app.view_functions:
        @app.route('/post/<path:post_id>', endpoint='canonical_post_by_id')
        def canonical_post_by_id(post_id):
            if not _POST_ID_RE.fullmatch(post_id or ''):
                return dashboard_module.make_response('Post not found', 404)
            root_view = app.view_functions.get(root_endpoint) if root_endpoint else None
            if root_view is None:
                return dashboard_module.make_response('Post route unavailable', 503)
            return root_view()

    if 'canonical_profile_by_id' not in app.view_functions:
        @app.route('/u/<int:user_id>', endpoint='canonical_profile_by_id')
        def canonical_profile_by_id(user_id):
            wallet = _profile_wallet(dashboard_module, user_id)
            if not wallet:
                return dashboard_module.make_response('Profile not found', 404)
            return dashboard_module.profile_view(wallet)

    @app.after_request
    def _canonical_share_routes(response):
        try:
            from flask import g, request
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response

            path = request.path or ''
            body = response.get_data(as_text=True)
            changed = False

            if path.startswith('/post/'):
                post_id = path[len('/post/'):]
                if _POST_ID_RE.fullmatch(post_id or ''):
                    body, meta_changed = _inject_post_social_meta(body, post_id)
                    changed = changed or meta_changed

                if _POST_ID_RE.fullmatch(post_id or '') and '</body>' in body:
                    pid_js = json.dumps(post_id)
                    # The postId is templated in per response, so this can't
                    # become a static external file the way a fixed script
                    # could. Instead it carries CSP's own per-response nonce
                    # directly: `g.orca_csp_nonce` is set by
                    # security_hardening.py's before_request hook, which runs
                    # (like every before_request hook) before any
                    # after_request hook of any module, so it is always
                    # already set here regardless of after_request
                    # registration order. Without this, the tag would rely
                    # on security_hardening.py's after_request nonce-
                    # injection pass to nonce it after the fact -- but that
                    # pass actually runs BEFORE this hook's response, since
                    # Flask calls after_request hooks in REVERSE install()
                    # order and this module installs before security_hardening
                    # (see app_entry.py). The tag would never get nonced and
                    # CSP would silently drop it, meaning a shared post link
                    # (e.g. from X/Twitter) would never scroll to / highlight
                    # the exact post it pointed at.
                    nonce = getattr(g, 'orca_csp_nonce', '') or secrets.token_urlsafe(18)
                    script = """
<script nonce=\"%s\" id=\"orca-canonical-post-jump\">
(function(){""" % nonce + """
  var postId = %s;
  var jumpTries = 0;
  var sessionTries = 0;
  var reloadKey = 'orca-post-session-reload:' + postId;

  function onboardVisible(){
    var ob = document.getElementById('onboard');
    if(!ob) return false;
    return !ob.classList.contains('hide') && getComputedStyle(ob).display !== 'none';
  }

  function openExactPost(){
    if(typeof window._jumpToPost === 'function'){
      Promise.resolve(window._jumpToPost(postId)).then(function(){
        var card=document.getElementById('fc-card-'+postId);
        if(card){
          card.scrollIntoView({block:'center',behavior:'auto'});
          card.classList.add('orca-deep-linked-post');
          setTimeout(function(){card.classList.remove('orca-deep-linked-post');},1800);
        }
      });
      return;
    }
    if(++jumpTries < 100) setTimeout(openExactPost, 100);
  }

  function finishAuthenticatedFlow(){
    try{ sessionStorage.removeItem(reloadKey); }catch(e){}
    if(typeof window.launchApp === 'function'){
      try{ window.launchApp(); }catch(e){}
    }
    openExactPost();
  }

  function checkExistingSession(){
    fetch('/api/session', {credentials:'include', cache:'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(data){
        if(data && (data.wallet || data.wallet_address || data.ok)){
          if(onboardVisible()){
            var alreadyReloaded=false;
            try{ alreadyReloaded=sessionStorage.getItem(reloadKey)==='1'; }catch(e){}
            if(!alreadyReloaded){
              try{ sessionStorage.setItem(reloadKey,'1'); }catch(e){}
              location.replace(location.href);
              return;
            }
          }
          finishAuthenticatedFlow();
          return;
        }
        if(++sessionTries < 30) setTimeout(checkExistingSession, 250);
        else openExactPost();
      })
      .catch(function(){
        if(++sessionTries < 30) setTimeout(checkExistingSession, 250);
        else openExactPost();
      });
  }

  function boot(){
    if(!onboardVisible()){
      openExactPost();
      return;
    }
    checkExistingSession();
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', boot, {once:true});
  }else{
    boot();
  }
})();
</script>
<style>
.orca-deep-linked-post{outline:1px solid rgba(247,185,85,.7);box-shadow:0 0 0 3px rgba(247,185,85,.08);transition:outline-color .35s,box-shadow .35s}
</style>
""" % pid_js
                    body = body.replace('</body>', script + '</body>', 1)
                    changed = True

            user_id = None
            if path.startswith('/u/'):
                try:
                    user_id = int(path.split('/', 2)[2])
                except (TypeError, ValueError, IndexError):
                    user_id = None
            elif path.startswith('/profile/'):
                identifier = path[len('/profile/'):]
                if identifier:
                    user_id = _profile_user_id(dashboard_module, identifier)
            if user_id:
                old = 'var url = window.location.href;'
                if old in body:
                    stable = _public_base_url() + '/u/' + str(user_id)
                    body = body.replace(old, 'var url = ' + repr(stable) + ';', 1)
                    changed = True

            if changed:
                response.set_data(body)
                response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('canonical share route patch skipped: %s', exc)
        return response
