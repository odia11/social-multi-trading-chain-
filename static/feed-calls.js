/* Token calls on the home feed.

   - _feedCallCardHtml(call, postId): the card under a call post. Every number
     comes from the server's token_calls row (price fetched by the server when
     the call was made, peak/now kept fresh by its peak loop) -- never from
     the post text.
   - _openCallSheet(): the Call button in the composer. Search a token, add an
     optional reason, call it. The call is posted to the feed.
   - _feedCallsTabChanged(tab): the Calls tab's "best calls today" strip.
   - A small line chart since the call, drawn when a card scrolls into view. */
(function(){
  'use strict';

  var CHAIN_LABELS = {solana:'Solana', bsc:'BSC', base:'Base', arbitrum:'Arbitrum', polygon:'Polygon', robinhood:'Robinhood'};
  var NOTE_MAX = 280;

  function esc(v){
    return String(v == null ? '' : v).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function num(v){ v = Number(v); return isFinite(v) ? v : 0; }
  function fmtUsd(n){
    n = num(n);
    if(n <= 0) return '—';
    if(n >= 1e9) return '$' + (n/1e9).toFixed(2) + 'B';
    if(n >= 1e6) return '$' + (n/1e6).toFixed(n >= 1e8 ? 0 : 1) + 'M';
    if(n >= 1e3) return '$' + (n/1e3).toFixed(n >= 1e5 ? 0 : 1) + 'K';
    return '$' + n.toFixed(2);
  }
  function fmtPrice(p){
    p = num(p);
    if(p <= 0) return '—';
    if(p >= 1) return '$' + p.toFixed(p >= 1000 ? 0 : 2);
    var s = p.toPrecision(3);
    if(s.indexOf('e') !== -1) s = p.toFixed(12).replace(/0+$/, '');
    return '$' + s;
  }
  function fmtMulti(m){
    m = num(m);
    if(m <= 0) return '—';
    if(m >= 100) return Math.round(m) + 'x';
    if(m >= 10) return m.toFixed(1) + 'x';
    return m.toFixed(2).replace(/0$/, '') + 'x';
  }
  function safeImg(url){
    url = String(url || '');
    return (/^https:\/\/[^\s"'<>]+$/.test(url) || /^\/token-launch\/icon\/[A-Za-z0-9]{1,64}$/.test(url)) ? url : '';
  }
  function jsArg(v){ return esc(JSON.stringify(String(v == null ? '' : v))); }
  function tileColor(sym){
    var h = 0; sym = String(sym || '?');
    for(var i = 0; i < sym.length; i++) h = (h * 31 + sym.charCodeAt(i)) % 360;
    return 'hsl(' + h + ',32%,22%)';
  }
  function parseTs(ts){
    // token_calls.timestamp is SQLite CURRENT_TIMESTAMP (UTC, no zone).
    var t = Date.parse(String(ts || '').replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(ts || '') ? '' : 'Z'));
    return isFinite(t) ? t : 0;
  }

  /* ── the card under a call post ── */
  function tileHtml(c, cls){
    var img = safeImg(c.image_url);
    var ini = esc(String(c.symbol || '?').slice(0, 4).toUpperCase());
    return '<span class="' + cls + '" style="background:' + tileColor(c.symbol) + '">'
      + '<span aria-hidden="true">' + ini + '</span>'
      + (img ? '<img src="' + esc(img) + '" alt="" loading="lazy" onerror="this.remove()">' : '')
      + '</span>';
  }

  window._feedCallCardHtml = function(c, postId){
    if(!c || !c.mint) return '';
    var sym = c.symbol || '?';
    var chain = CHAIN_LABELS[c.chain] || (c.chain ? String(c.chain).toUpperCase() : '');
    var peak = num(c.multiplier), now = num(c.now_multiplier);
    var hasMcap = num(c.mcap_at_call) > 0;
    var stat = function(label, value, cls){
      return '<div class="fcall-stat"><span>' + label + '</span><b' + (cls ? ' class="' + cls + '"' : '') + '>' + value + '</b></div>';
    };
    var nowCls = now >= 1 ? 'up' : 'down';
    return '<div class="fcall-card" data-call-id="' + esc(c.id) + '" onclick="event.stopPropagation()">'
      + '<div class="fcall-top">'
        + tileHtml(c, 'fcall-tile')
        + '<div class="fcall-id"><div class="fcall-sym">$' + esc(sym) + '</div>'
        + '<div class="fcall-sub">' + esc(c.name && c.name !== sym ? c.name : '') + (c.name && c.name !== sym && chain ? ' · ' : '') + esc(chain) + '</div></div>'
        + '<div class="fcall-multi"><b class="' + (peak > 1 ? 'up' : '') + '">' + fmtMulti(peak) + '</b><span>peak since call</span></div>'
      + '</div>'
      + '<svg class="fcall-spark" viewBox="0 0 300 44" preserveAspectRatio="none" aria-hidden="true"'
        + ' data-mint="' + esc(c.mint) + '" data-chain="' + esc(c.chain || 'solana') + '"'
        + ' data-entry="' + esc(num(c.price_at_call)) + '" data-called="' + esc(c.called_at || '') + '"></svg>'
      + '<div class="fcall-stats">'
        + stat(hasMcap ? 'Called at' : 'Entry', hasMcap ? fmtUsd(c.mcap_at_call) : fmtPrice(c.price_at_call))
        + stat('Now', hasMcap ? fmtUsd(c.mcap_now) : fmtPrice(c.last_price), nowCls)
        + stat('Peak', hasMcap ? fmtUsd(c.mcap_peak) : fmtPrice(c.peak_price), peak > 1 ? 'up' : '')
      + '</div>'
      + '<div class="fcall-actions">'
        + '<button type="button" class="fcall-buy" onclick="event.stopPropagation();if(typeof showTokenCard===\'function\')showTokenCard(' + jsArg(sym) + ',' + jsArg(c.mint) + ')">Buy $' + esc(sym) + '</button>'
        + '<a class="fcall-chart" href="/live-market?mint=' + encodeURIComponent(c.mint) + '" onclick="event.stopPropagation()">Chart</a>'
      + '</div>'
    + '</div>';
  };

  /* ── line chart since the call, drawn when the card is on screen ── */
  var sparkCache = {};
  function tfForAge(ms){
    var h = ms / 3600000;
    return h < 1 ? '1m' : h < 5 ? '5m' : h < 15 ? '15m' : h < 48 ? '1h' : h < 168 ? '4h' : 'D';
  }
  function drawSpark(svg, candles){
    var entry = num(svg.getAttribute('data-entry'));
    var called = parseTs(svg.getAttribute('data-called')) / 1000;
    var pts = (candles || []).filter(function(k){ return num(k.t) >= called - 3600 && num(k.c) > 0; });
    if(pts.length < 2) pts = (candles || []).slice(-24);
    if(pts.length < 2){ svg.classList.add('fcall-spark-empty'); return; }
    var vals = pts.map(function(k){ return num(k.c); });
    var lo = Math.min.apply(null, vals.concat(entry > 0 ? [entry] : [])),
        hi = Math.max.apply(null, vals.concat(entry > 0 ? [entry] : []));
    var span = hi - lo || hi || 1;
    var y = function(v){ return (40 - ((v - lo) / span) * 36).toFixed(1); };
    var d = vals.map(function(v, i){ return (i ? 'L' : 'M') + (i * 300 / (vals.length - 1)).toFixed(1) + ' ' + y(v); }).join(' ');
    var up = vals[vals.length - 1] >= (entry || vals[0]);
    var base = entry > 0 ? '<path d="M0 ' + y(entry) + ' L300 ' + y(entry) + '" class="fcall-spark-base"/>' : '';
    svg.innerHTML = base + '<path d="' + d + '" class="fcall-spark-line ' + (up ? 'up' : 'down') + '"/>';
  }
  function loadSpark(svg){
    if(svg.getAttribute('data-loaded')) return;
    svg.setAttribute('data-loaded', '1');
    var mint = svg.getAttribute('data-mint'), chain = svg.getAttribute('data-chain') || 'solana';
    var age = Date.now() - (parseTs(svg.getAttribute('data-called')) || Date.now());
    var tf = tfForAge(age), key = chain + ':' + mint + ':' + tf;
    var hit = sparkCache[key];
    if(hit && Date.now() - hit.at < 120000){ hit.promise.then(function(c){ drawSpark(svg, c); }); return; }
    var promise = fetch('/api/chart/' + encodeURIComponent(mint) + '?chain=' + encodeURIComponent(chain) + '&tf=' + tf)
      .then(function(r){ return r.ok ? r.json() : {}; })
      .then(function(d){ return Array.isArray(d.candles) ? d.candles : []; })
      .catch(function(){ return []; });
    sparkCache[key] = {at: Date.now(), promise: promise};
    promise.then(function(c){ drawSpark(svg, c); });
  }
  var sparkObserver = ('IntersectionObserver' in window) ? new IntersectionObserver(function(entries){
    entries.forEach(function(en){
      if(en.isIntersecting){ sparkObserver.unobserve(en.target); loadSpark(en.target); }
    });
  }, {rootMargin: '200px 0px'}) : null;
  function watchSparks(root){
    (root || document).querySelectorAll('svg.fcall-spark:not([data-watched])').forEach(function(svg){
      svg.setAttribute('data-watched', '1');
      if(sparkObserver) sparkObserver.observe(svg); else loadSpark(svg);
    });
  }
  function startWatching(){
    var feed = document.getElementById('center-feed');
    if(!feed) return;
    watchSparks(feed);
    new MutationObserver(function(){ watchSparks(feed); }).observe(feed, {childList: true, subtree: true});
  }

  /* ── Calls tab: best calls today + a way in ── */
  var topSeq = 0;
  function openCallPost(postId){
    if(!postId) { location.href = '/calls'; return; }
    location.hash = 'post-p' + postId;
  }
  window._feedCallOpenPost = openCallPost;
  function renderTop(box, calls, left){
    var podium = calls.slice(0, 3).map(function(c, i){
      return '<button type="button" class="fcall-top-card' + (i === 0 ? ' first' : '') + '" onclick="_feedCallOpenPost(' + (num(c.post_id) || 0) + ')">'
        + '<span class="fcall-rank">#' + (i + 1) + '</span>'
        + '<span class="fcall-top-sym">$' + esc(c.symbol || '?') + '</span>'
        + '<b class="' + (num(c.multiplier) > 1 ? 'up' : '') + '">' + fmtMulti(c.multiplier) + '</b>'
        + '<span class="fcall-top-by">' + esc(c.caller_username || '') + '</span>'
      + '</button>';
    }).join('');
    box.innerHTML = '<div class="fcall-top-head"><h2>Best calls today</h2><a href="/calls">Leaderboard</a></div>'
      + (podium ? '<div class="fcall-podium">' + podium + '</div>' : '<p class="fcall-top-empty">No calls in the last 24 hours yet.</p>')
      + '<div class="fcall-cta"><div><b>Spot the next one early?</b><span>'
      + (left == null ? 'Your call is tracked live, from the moment you make it.' : esc(left) + ' of ' + perDay + ' calls left today')
      + '</span></div><button type="button" onclick="if(typeof checkGuest===\'function\'&&checkGuest())return;_openCallSheet()">Call a token</button></div>';
  }
  // The daily limit comes from the server (CALLS_PER_DAY_LIMIT), never a
  // number written here.
  var perDay = 5;
  function callsLeft(){
    return fetch('/api/calls/mine').then(function(r){ return r.ok ? r.json() : null; })
      .then(function(d){
        if(!d || !d.ok) return null;
        if(d.calls_per_day > 0) perDay = d.calls_per_day;
        return d.calls_left_today;
      }).catch(function(){ return null; });
  }
  window._feedCallsTabChanged = function(tab){
    var box = document.getElementById('feed-calls-top');
    if(!box) return;
    if(tab !== 'calls'){ box.hidden = true; return; }
    box.hidden = false;
    var seq = ++topSeq;
    if(!box.innerHTML) box.innerHTML = '<div class="fcall-top-loading">Loading calls…</div>';
    Promise.all([
      fetch('/api/calls/top?window=24h').then(function(r){ return r.ok ? r.json() : {}; }).catch(function(){ return {}; }),
      callsLeft()
    ]).then(function(res){
      if(seq !== topSeq) return;
      renderTop(box, (res[0] && res[0].calls) || [], res[1]);
    });
  };

  /* ── the Call sheet ── */
  var sheet = null, picked = null, searchTimer = null, searchSeq = 0, busy = false;
  function el(tag, cls, text){
    var e = document.createElement(tag);
    if(cls) e.className = cls;
    if(text != null) e.textContent = text;
    return e;
  }
  function buildSheet(){
    var wrap = el('div', 'fcall-sheet-wrap');
    wrap.id = 'fcall-sheet';
    wrap.hidden = true;
    wrap.innerHTML =
      '<div class="fcall-sheet" role="dialog" aria-modal="true" aria-labelledby="fcall-sheet-title">'
      + '<div class="fcall-grab" aria-hidden="true"></div>'
      + '<div class="fcall-sheet-head"><div><h2 id="fcall-sheet-title">Call a token</h2>'
      + '<p>Tracked live from this moment. Everyone sees how your call does.</p></div>'
      + '<button type="button" class="fcall-close" aria-label="Close"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>'
      + '<label class="fcall-search"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>'
      + '<input id="fcall-q" type="text" autocomplete="off" spellcheck="false" placeholder="Search a token or paste its address" aria-label="Search a token or paste its address"></label>'
      + '<div class="fcall-results" id="fcall-results" role="listbox" aria-label="Tokens"></div>'
      + '<label class="fcall-note"><span>Why? <i>(optional)</i></span>'
      + '<textarea id="fcall-note" rows="3" maxlength="' + NOTE_MAX + '" placeholder="What makes this one worth calling?"></textarea>'
      + '<em id="fcall-note-count">0/' + NOTE_MAX + '</em></label>'
      + '<div class="fcall-info"><div class="fcall-info-row"><span>Calls today</span><span id="fcall-left">…</span></div>'
      + '<p>OrcAgent reads the price itself at the moment you call, so no one can fake a result. A call is not a buy.</p></div>'
      + '<p class="fcall-msg" id="fcall-msg" role="status"></p>'
      + '<button type="button" class="fcall-submit" id="fcall-submit" disabled>Pick a token to call</button>'
      + '</div>';
    document.body.appendChild(wrap);
    wrap.addEventListener('click', function(ev){ if(ev.target === wrap) closeSheet(); });
    wrap.querySelector('.fcall-close').addEventListener('click', closeSheet);
    wrap.querySelector('#fcall-q').addEventListener('input', onSearch);
    var note = wrap.querySelector('#fcall-note');
    note.addEventListener('input', function(){
      wrap.querySelector('#fcall-note-count').textContent = note.value.length + '/' + NOTE_MAX;
    });
    wrap.querySelector('#fcall-submit').addEventListener('click', submit);
    document.addEventListener('keydown', function(ev){ if(ev.key === 'Escape' && !wrap.hidden) closeSheet(); });
    return wrap;
  }
  function setMsg(text, bad){
    var m = sheet.querySelector('#fcall-msg');
    m.textContent = text || '';
    m.classList.toggle('bad', !!bad);
  }
  function updateSubmit(){
    var b = sheet.querySelector('#fcall-submit');
    b.disabled = !picked || busy;
    b.textContent = busy ? 'Calling…' : (picked ? 'Call $' + picked.symbol : 'Pick a token to call');
  }
  function toRow(t){
    return {mint: t.mint || '', symbol: t.symbol || '?', name: t.name || '', chain: t.chain || '',
            price: num(t.price), mcap: num(t.market_cap), change: t.change_24h, image: t.image_url || ''};
  }
  function renderResults(rows, note){
    var box = sheet.querySelector('#fcall-results');
    box.replaceChildren();
    if(note){ box.appendChild(el('p', 'fcall-results-note', note)); return; }
    rows.forEach(function(t){
      var b = el('button', 'fcall-result' + (picked && picked.mint === t.mint && picked.chain === t.chain ? ' on' : ''));
      b.type = 'button';
      b.setAttribute('role', 'option');
      var tile = el('span', 'fcall-tile');
      tile.style.background = tileColor(t.symbol);
      tile.appendChild(el('span', null, String(t.symbol).slice(0, 4).toUpperCase()));
      var img = safeImg(t.image);
      if(img){ var i = document.createElement('img'); i.src = img; i.alt = ''; i.onerror = function(){ i.remove(); }; tile.appendChild(i); }
      var mid = el('span', 'fcall-result-id');
      var top = el('span', 'fcall-result-sym', '$' + t.symbol);
      if(t.name) top.appendChild(el('i', null, ' ' + t.name));
      mid.appendChild(top);
      mid.appendChild(el('span', 'fcall-result-sub', [CHAIN_LABELS[t.chain] || t.chain, t.mcap ? 'MC ' + fmtUsd(t.mcap) : ''].filter(Boolean).join(' · ')));
      var right = el('span', 'fcall-result-px');
      right.appendChild(el('b', null, fmtPrice(t.price)));
      if(t.change != null && isFinite(t.change)){
        var ch = num(t.change);
        right.appendChild(el('span', ch >= 0 ? 'up' : 'down', (ch >= 0 ? '+' : '') + ch.toFixed(1) + '%'));
      }
      b.appendChild(tile); b.appendChild(mid); b.appendChild(right);
      b.addEventListener('click', function(){
        picked = t; setMsg('');
        renderResults(rows); updateSubmit();
        sheet.querySelector('#fcall-note').focus();
      });
      box.appendChild(b);
    });
  }
  function onSearch(){
    var q = this.value.trim();
    picked = null; updateSubmit(); setMsg('');
    clearTimeout(searchTimer);
    if(q.length < 2){ renderResults([]); return; }
    searchTimer = setTimeout(function(){
      var seq = ++searchSeq;
      renderResults([], 'Searching…');
      // One server lookup for every chain: the app's own market data,
      // DexScreener, GeckoTerminal and OrcAgent launches -- a pasted address
      // of any token this app can trade is found even while one source is
      // rate-limited or has not indexed it yet.
      fetch('/api/calls/lookup?q=' + encodeURIComponent(q)).then(function(r){ return r.json(); }).then(function(d){
        if(seq !== searchSeq) return;
        var rows = ((d && d.tokens) || []).map(toRow).filter(function(t){ return t.mint; });
        renderResults(rows, rows.length ? '' : (/^(0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})$/.test(q)
          ? 'No live price found for this address on any supported chain yet — try again in a minute'
          : 'No tokens found — paste the contract address'));
      }).catch(function(){ if(seq === searchSeq) renderResults([], 'Search failed — try again'); });
    }, 280);
  }
  function refreshLeft(){
    var out = sheet.querySelector('#fcall-left');
    callsLeft().then(function(left){
      if(left == null){ out.textContent = perDay + ' per day'; return; }
      out.replaceChildren();
      for(var i = 0; i < perDay; i++) out.appendChild(el('i', i < left ? 'on' : ''));
      out.appendChild(el('b', null, left + ' of ' + perDay + ' left'));
    });
  }
  function submit(){
    if(!picked || busy) return;
    busy = true; updateSubmit(); setMsg('');
    fetch('/api/calls', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mint: picked.mint, chain: picked.chain, note: sheet.querySelector('#fcall-note').value.trim(), post_to_feed: true})})
      .then(function(r){ return r.text().then(function(t){ var d = {}; try{ d = JSON.parse(t); }catch(e){} return {ok: r.ok, d: d}; }); })
      .then(function(res){
        busy = false;
        if(!res.ok || !res.d.ok){ setMsg(res.d.msg || 'Could not place the call — try again', true); updateSubmit(); return; }
        closeSheet();
        if(typeof openAlertModal === 'function') openAlertModal({text: 'You called $' + (res.d.symbol || picked.symbol) + '. It is in the feed and tracked live.'});
        if(typeof loadHomeFeed === 'function') loadHomeFeed();
        window._feedCallsTabChanged && window._feedCallsTabChanged(typeof _homeFeedFilter !== 'undefined' ? _homeFeedFilter : '');
      })
      .catch(function(){ busy = false; setMsg('Network error — check your connection and try again', true); updateSubmit(); });
  }
  function closeSheet(){
    if(!sheet) return;
    sheet.hidden = true;
    document.documentElement.classList.remove('fcall-sheet-open');
  }
  window._openCallSheet = function(){
    sheet = sheet || buildSheet();
    picked = null; busy = false;
    sheet.querySelector('#fcall-q').value = '';
    sheet.querySelector('#fcall-note').value = '';
    sheet.querySelector('#fcall-note-count').textContent = '0/' + NOTE_MAX;
    renderResults([]); setMsg(''); updateSubmit(); refreshLeft();
    sheet.hidden = false;
    document.documentElement.classList.add('fcall-sheet-open');
    setTimeout(function(){ sheet.querySelector('#fcall-q').focus(); }, 60);
  };

  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', startWatching);
  else startWatching();
})();
