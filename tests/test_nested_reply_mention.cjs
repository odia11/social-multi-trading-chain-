const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const src=fs.readFileSync(path.resolve(__dirname,'../static/dashboard.js'),'utf8');
const start=src.indexOf('function _feedToggleNestedReply(');
const end=src.indexOf('function _feedSubmitNestedReply(',start);
assert.ok(start>=0&&end>start,'nested reply function exists');
const code=src.slice(start,end);
let input=null,synced=null,focused=false,caret=null;
const box={
  style:{display:'none'},
  _html:'',
  set innerHTML(v){
    this._html=v;
    if(v){
      input={
        value:'',dataset:{},
        focus(opts){focused=!!(opts&&opts.preventScroll)},
        setSelectionRange(a,b){caret=[a,b]}
      };
    } else input=null;
  },
  get innerHTML(){return this._html}
};
const nameNode={textContent:'Orcagent'};
const row={querySelector(sel){return sel==='.fc-ri-name'?nameNode:null}};
const btn={closest(){return row}};
const ctx={
  document:{
    getElementById(id){if(id==='rnbox-7')return box;if(id==='rninp-7')return input;return null},
    querySelectorAll(){return []}
  },
  _fcReplyAvatarHtml(){return ''},
  _RC_SEND_ICON_SVG:'',
  esc(v){return String(v)},
  _fcReplyCardSync(id){synced=id},
  setTimeout(fn){fn()}
};
vm.createContext(ctx);vm.runInContext(code,ctx);
ctx._feedToggleNestedReply(7,'p1',btn);
assert.equal(input.value,'@Orcagent ','reply composer pre-fills exact author mention');
assert.equal(input.dataset.replyMention,'Orcagent');
assert.equal(synced,'rncard-7');
assert.equal(focused,true,'reply composer keeps iOS focus without scrolling');
assert.deepEqual(caret,[10,10],'caret lands after the mention');

box.style.display='none';nameNode.textContent='bad name<script>';
ctx._feedToggleNestedReply(7,'p1',btn);
assert.equal(input.value,'','invalid usernames are never injected as a mention');
console.log('PASS nested replies prefill a safe @username mention and keep mobile focus');
