'use strict';
const expected=require('node:fs').readFileSync(require('node:path').join(__dirname,'.node-version'),'utf8').trim();
if(process.versions.node!==expected || process.features.require_module!==true){
  throw Error('Pump requires pinned Node '+expected+' with require(esm); got '+process.versions.node+'. Run deploy/install-pump-runtime.sh.');
}
