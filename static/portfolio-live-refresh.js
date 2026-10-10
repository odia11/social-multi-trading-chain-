/* Refresh confirmed holdings in place, with no overlapping reads or page reload. */
(function(){
'use strict';
var busy=false;
var scope=OrcPageLifecycle.routeScope('portfolio-live-refresh',document.body);
function refresh(){
  if(document.hidden||busy||typeof window.OrcAgentGetPortfolioSnapshot!=='function')return;
  busy=true;
  window.OrcAgentGetPortfolioSnapshot(false).catch(function(){}).finally(function(){busy=false;});
}
scope.setInterval(refresh,5000);
scope.addEventListener(document,'visibilitychange',refresh);
scope.addEventListener(window,'online',refresh);
scope.addEventListener(window,'focus',refresh);
})();
