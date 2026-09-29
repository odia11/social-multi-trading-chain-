/* Shared browser wallet selection. */
(function(root){
  'use strict';
  function provider(type){
    if(type==='phantom'){
      if(root.phantom && root.phantom.solana && root.phantom.solana.isPhantom) return root.phantom.solana;
      if(root.solana && root.solana.isPhantom) return root.solana;
      return null;
    }
    if(type==='solflare') return root.solflare && root.solflare.isSolflare ? root.solflare : null;
    return null;
  }
  function connected(address){
    var available=['phantom','solflare'].map(provider).filter(Boolean);
    return available.find(function(p){return p.publicKey && p.publicKey.toString()===address;})||(available.length===1?available[0]:null);
  }
  root.OrcAgentWalletAdapter=Object.freeze({provider:provider,connected:connected});
})(window);
