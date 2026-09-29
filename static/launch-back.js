/* Launch page navigation: preserve real same-site history, offer a reliable fallback. */
(function () {
  'use strict';
  var back = document.getElementById('orca-launch-back');
  if (!back) return;
  back.addEventListener('click', function (event) {
    var prior;
    try { prior = new URL(document.referrer); } catch (_) { return; }
    // Do not unexpectedly send users away from OrcAgent, nor loop back to
    // the same route after a refresh/direct visit. The anchor still works.
    if (prior.origin !== location.origin ||
        prior.pathname === location.pathname || history.length < 2) return;
    event.preventDefault();
    history.back();
  });
})();
