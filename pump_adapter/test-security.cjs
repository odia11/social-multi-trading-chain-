'use strict';
// A native-free replacement MUST behave like bigint-buffer for Solana integer
// layouts and fail closed for malformed/unbounded binary inputs.
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const buffer=require('bigint-buffer');
const trusted=path.resolve(__dirname,'vendor/bigint-buffer-safe/index.js');
// npm's file: dependency is a symlink on some versions, a physical copy on
// others (notably the Node 18/npm used by the deployment script). Enforce
// actual code identity, not the incidental installation path. Check imports
// resolved FROM Solana's transitive dependency as well as from the adapter.
const fromSolana=require.resolve('bigint-buffer',{
  paths:[path.dirname(require.resolve('@solana/buffer-layout-utils'))]});
const sha256=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
assert.equal(sha256(require.resolve('bigint-buffer')),sha256(trusted),
 'Root bigint-buffer differs from audited native-free source');
assert.equal(sha256(fromSolana),sha256(trusted),
 'Solana transitive bigint-buffer differs from audited native-free source');
assert.equal(require('bigint-buffer/package.json').version,'1.1.6');
assert.equal(fs.readdirSync(path.dirname(require.resolve('bigint-buffer')))
  .some(name=>name.endsWith('.node')),false,'Unexpected native addon');
for(let w=0;w<=64;w++){
 for(let j=0;j<8;j++){
  const bytes=crypto.randomBytes(w);
  for(const [read,write] of [
   [buffer.toBigIntLE,buffer.toBufferLE],[buffer.toBigIntBE,buffer.toBufferBE]]){
   assert.deepEqual(write(read(bytes),w),bytes);
  }
 }
}
for(const fn of [buffer.toBigIntLE,buffer.toBigIntBE]){
 assert.throws(()=>fn(Buffer.alloc(65537)),RangeError);
 assert.throws(()=>fn('hex'),TypeError);
}
for(const fn of [buffer.toBufferLE,buffer.toBufferBE]){
 assert.throws(()=>fn(256n,1),RangeError);
 assert.throws(()=>fn(-1n,8),RangeError);
 assert.throws(()=>fn(1n,65537),RangeError);
 assert.throws(()=>fn(1n,-1),RangeError);
}
for(const dir of [path.dirname(require.resolve('bigint-buffer')),
                   path.dirname(fromSolana)]){
  const native=path.resolve(dir,'build/Release/bigint_buffer.node');
  assert.ok(!fs.existsSync(native),'Native BigInt addon must not be installed');
}
console.log('PASS safe bigint-buffer is native-free and is the version used by Solana dependencies');
console.log('PASS 1040 randomized endian/width round trips, bounds and negative-value validation');
