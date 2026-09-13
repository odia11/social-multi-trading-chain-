"""Reliable Share-to-X fallback for OrcAgent.

Preserves direct posting when it succeeds. When it fails, opens X's official
composer with the permanent OrcAgent post link, English copy and @orcagent tag.
"""

_INSTALLED = False
_PREVIEW_VERSION = '7'

_SCRIPT = r'''
<script id="orca-x-share-fallback">
(function(){
  if (window.__orcaXShareFallbackInstalled) return;
  window.__orcaXShareFallbackInstalled = true;

  var nativeFetch = window.fetch.bind(window);
  var shareRe = /\/api\/feed\/share-to-x\/([^?#]+)/;
  var previewVersion = '7';

  function postIdFrom(input){
    try {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      var m = String(url).match(shareRe);
      return m ? decodeURIComponent(m[1]) : '';
    } catch(e) { return ''; }
  }

  function canonicalUrl(postId){
    return window.location.origin + '/post/' + encodeURIComponent(postId) + '?xv=' + previewVersion;
  }

  function xIntent(postId){
    var canonical = canonicalUrl(postId);
    var text = 'View this post on OrcAgent @orcagent';
    return 'https://twitter.com/intent/tweet?text=' + encodeURIComponent(text) +
           '&url=' + encodeURIComponent(canonical);
  }

  function syntheticSuccess(intent, postId){
    return new Response(JSON.stringify({
      success: true, ok: true, fallback: true,
      share_url: intent, canonical_url: canonicalUrl(postId)
    }), {status: 200, headers: {'Content-Type': 'application/json'}});
  }

  function isExplicitFailure(resp, data, raw){
    if (!resp || !resp.ok) return true;
    if (data) {
      if (data.success === false || data.ok === false) return true;
      if (data.error && data.success !== true && data.ok !== true) return true;
      if (data.failed === true) return true;
    }
    raw = String(raw || '').toLowerCase();
    return raw.indexOf('failed') >= 0 || raw.indexOf('not connected') >= 0 ||
           raw.indexOf('unauthorized') >= 0 || raw.indexOf('token expired') >= 0;
  }

  function openFallback(postId){
    var intent = xIntent(postId);
    setTimeout(function(){ window.location.href = intent; }, 0);
    return intent;
  }

  window.fetch = function(input, init){
    var postId = postIdFrom(input);
    if (!postId) return nativeFetch(input, init);
    return nativeFetch(input, init).then(function(resp){
      return resp.clone().text().then(function(raw){
        var data = null;
        try { data = raw ? JSON.parse(raw) : null; } catch(e) {}
        if (!isExplicitFailure(resp, data, raw)) return resp;
        return syntheticSuccess(openFallback(postId), postId);
      }).catch(function(){
        if (resp && resp.ok) return resp;
        return syntheticSuccess(openFallback(postId), postId);
      });
    }).catch(function(){
      return syntheticSuccess(openFallback(postId), postId);
    });
  };
})();
</script>
'''


def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = dashboard_module.app

    @app.after_request
    def _orca_x_share_fallback(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if 'orca-x-share-fallback' in body or '</body>' not in body:
                return response
            body = body.replace('</body>', _SCRIPT + '</body>', 1)
            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('X share fallback injection skipped: %s', exc)
        return response
