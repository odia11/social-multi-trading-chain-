// Compatibility API for existing route initializers. Swiping must only scroll,
// never reload or refetch the page, at any viewport width or orientation.
// Live data continues to update through each page's existing polling.
(function(){
  window.initPullToRefresh = function(){};
})();
