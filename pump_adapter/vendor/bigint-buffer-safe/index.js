'use strict';
// OrcAgent security override for the deprecated bigint-buffer native addon.
// This package NEVER loads or compiles a .node module. Input lengths are
// bounded before parsing to prevent overflow / BigInt allocation DoS.
const MAX_WIDTH=65536;
function read(buf,little){
  if(!(Buffer.isBuffer(buf)||buf instanceof Uint8Array)){
    throw new TypeError('Expected a Buffer or Uint8Array');
  }
  if(buf.length>MAX_WIDTH)throw new RangeError('BigInt buffer exceeds maximum supported size');
  if(buf.length===0)return 0n;
  const hex=Buffer.from(buf);
  if(little)hex.reverse();
  return BigInt('0x'+hex.toString('hex'));
}
function write(num,width,little){
  if(typeof num!=='bigint')throw new TypeError('Expected BigInt');
  if(!Number.isSafeInteger(width)||width<0||width>MAX_WIDTH){
    throw new RangeError('Invalid BigInt byte width');
  }
  if(num<0n)throw new RangeError('Cannot encode a negative unsigned BigInt');
  if(width===0){
    if(num!==0n)throw new RangeError('Number does not fit requested byte width');
    return Buffer.alloc(0);
  }
  let hex=num.toString(16);
  if(hex.length>width*2)throw new RangeError('Number does not fit requested byte width');
  hex=hex.padStart(width*2,'0');
  const out=Buffer.from(hex,'hex');
  if(little)out.reverse();
  return out;
}
exports.toBigIntLE=(buf)=>read(buf,true);
exports.toBigIntBE=(buf)=>read(buf,false);
exports.toBufferLE=(num,width)=>write(num,width,true);
exports.toBufferBE=(num,width)=>write(num,width,false);
