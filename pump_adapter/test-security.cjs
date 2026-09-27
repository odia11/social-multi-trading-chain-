'use strict';
// A native-free replacement MUST behave like bigint-buffer for Solana integer
// layouts and fail closed for malformed/unbounded binary inputs.
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const buffer=require('bigint-buffer');
const trusted=path.resolve(__dirname,'vendor/bigint-buffer-safe/index.js');
assert.equal(fs.realpathSync(require.resolve('bigint-buffer')),trusted);
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
const oldNative=path.resolve(__dirname,'node_modules/bigint-buffer/build/Release/bigint_buffer.node');
assert.ok(!fs.existsSync(oldNative),'Native code must not be installed in the token-launch runtime');
console.log('PASS safe bigint-buffer is native-free and is the version used by Solana dependencies');
console.log('PASS 1040 randomized endian/width round trips, bounds and negative-value validation');
