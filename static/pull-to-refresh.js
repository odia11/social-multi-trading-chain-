// ── PULL-TO-REFRESH (shared) ──────────────────────────────────────────────
// Desktop/tablet callers can still initialise this helper, but the custom
// touch gesture is deliberately disabled on OrcAgent mobile. In iOS/Phantom
// it competes with ordinary fast vertical scrolling and can turn a swipe into
// a reload. The app already refreshes live data through its normal polling and
// navigation flows, so mobile scrolling is kept native and predictable.
(function(){
  var _styleInjected = false;
  function _injectStyle(){
    if(_styleInjected) return;
    _styleInjected = true;
    var s = document.createElement('style');
    s.textContent = '@keyframes ptrSpin{to{transform:rotate(360deg)}}'
      + '.ptr-indicator-spin{width:20px;height:20px;border-radius:50%;'
      + 'border:2px solid rgba(255,255,255,.15);border-top-color:#f7b955;'
      + 'animation:ptrSpin .7s linear infinite;display:inline-block}';
    document.head.appendChild(s);
  }

  window.initPullToRefresh = function(opts){
    opts = opts || {};

    // A mobile social/trading app must never interpret an ordinary fast swipe
    // as a page reload. Keep all <=767px routes on native vertical scrolling.
    if(window.matchMedia('(max-width:767px)').matches) return;

    var PTR_THRESHOLD = 70;
    var touchTarget = _resolve(opts.touchTarget) || document.body;
    var onRefresh   = opts.onRefresh || function(){ location.reload(); };
    if(!touchTarget) return;
    _injectStyle();

    function _resolve(v){
      if(!v) return null;
      if(typeof v === 'function') v = v();
      if(!v) return null;
      return typeof v === 'string' ? document.querySelector(v) : v;
    }
    function scrollEl(){ return _resolve(opts.scrollEl); }
    function anchorEl(){ return _resolve(opts.anchorEl) || document.body.firstElementChild; }
    function scrollTop(){
      var el = scrollEl();
      if(el) return el.scrollTop;
      return window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
    }

    var _startY = 0, _active = false, _pulling = false, _indicator = null;
    function ensureIndicator(anchor){
      if(!_indicator){
        var wrap = document.createElement('div');
        wrap.className = 'ptr-indicator';
        wrap.style.cssText = 'display:flex;align-items:center;justify-content:center;height:0;overflow:hidden;transition:height .15s ease';
        var spin = document.createElement('span');
        spin.className = 'ptr-indicator-spin';
        wrap.appendChild(spin);
        _indicator = wrap;
      }
      if(_indicator.nextElementSibling !== anchor) anchor.parentNode.insertBefore(_indicator, anchor);
      return _indicator;
    }

    touchTarget.addEventListener('touchstart', function(e){
      if(opts.ignoreTarget && e.target.closest(opts.ignoreTarget)){ _active = false; return; }
      if(scrollTop() !== 0){ _active = false; return; }
      _startY = e.touches[0].clientY;
      _active = true;
      _pulling = false;
    }, {passive: true});

    touchTarget.addEventListener('touchmove', function(e){
      if(!_active) return;
      var dy = e.touches[0].clientY - _startY;
      if(dy <= 0 || scrollTop() !== 0){ _active = false; return; }
      var anchor = anchorEl();
      if(!anchor || !anchor.parentNode){ _active = false; return; }
      _pulling = true;
      e.preventDefault();
      ensureIndicator(anchor).style.height = Math.min(dy, PTR_THRESHOLD) + 'px';
    }, {passive: false});

    touchTarget.addEventListener('touchend', async function(){
      if(!_active) return;
      _active = false;
      if(_pulling && _indicator){
        var pulled = parseInt(_indicator.style.height, 10) || 0;
        if(pulled >= PTR_THRESHOLD){
          _indicator.style.height = PTR_THRESHOLD + 'px';
          try{ await onRefresh(); }catch(e){}
        }
        _indicator.style.height = '0px';
      }
      _pulling = false;
    }, {passive: true});
  };
})();
