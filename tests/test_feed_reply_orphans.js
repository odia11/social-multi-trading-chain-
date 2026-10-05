const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('static/dashboard.js','utf8');
const code=src.slice(src.indexOf('function _feedRenderReplyTree('),src.indexOf('function _feedLoadReplies('));
let rows=[];
const ctx={Map,Set,String,_renderReplyRow(r,p,d){rows.push([r.id,p,d]);return String(r.id)+','}};
vm.createContext(ctx);vm.runInContext(code,ctx);
function render(replies){rows=[];ctx._feedRenderReplyTree(replies,'p554');return rows.map(r=>r[0])}
const screenshot=[{id:134},{id:136,parent_reply_id:135},{id:137,parent_reply_id:136},{id:138,parent_reply_id:137},{id:139,parent_reply_id:138}];
assert.deepEqual(render(screenshot),[134,136,137,138,139]);
assert.equal(rows[4][2],3);
assert.deepEqual(render([{id:2,parent_reply_id:1},{id:1},{id:3,parent_reply_id:2}]),[1,2,3]);
assert.deepEqual(render([{id:1,parent_reply_id:2},{id:2,parent_reply_id:1},{id:3,parent_reply_id:3}]).sort(),[1,2,3]);
assert.deepEqual(render([]),[]);
const deep=Array.from({length:15000},(_,i)=>({id:i+1,parent_reply_id:i||null}));
assert.equal(render(deep).length,15000,'deep threads must not overflow call stack');
console.log('PASS screenshot orphan thread, child-before-parent ordering, cycles, empty and deep threads');
