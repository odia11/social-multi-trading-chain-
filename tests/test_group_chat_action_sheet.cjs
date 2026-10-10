/* Premium mobile message sheet: presentation changes must not change actions. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const js=fs.readFileSync(path.join(root,'static/group-chats.js'),'utf8');
const css=fs.readFileSync(path.join(root,'static/group-chats.css'),'utf8');
const start=js.indexOf('var MESSAGE_ACTION_ICONS=');
const end=js.indexOf('function messageMenu(mid){',start);
assert.ok(start>0 && end>start);
const vmContext={esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')}};
vm.createContext(vmContext);
vm.runInContext(js.slice(start,end),vmContext);
const row=vmContext.messageActionRow;
assert.equal(typeof row,'function');
const expected=[
  ['like','Like message','heart','like'],
  ['edit','Edit message','edit','edit'],
  ['delete','Delete for everyone','trash','danger'],
  ['cancel','Cancel','cancel','cancel']
];
for(const [action,label,icon,tone] of expected){
  const html=row(action,label,icon,tone);
  assert.ok(html.startsWith('<button type="button"'),'all menu actions must be accessible buttons');
  assert.ok(html.includes('data-message-act="'+action+'"'),'existing delegated handler must still work: '+action);
  assert.ok(html.includes('gc-message-action-'+tone),'correct design variant: '+action);
  assert.ok(html.includes(label),'correct action label: '+action);
  assert.ok(html.includes('gc-message-action-icon'),'icon badge missing: '+action);
}
assert.ok(row('delete','Delete tip from chat','trash','danger').includes('Delete tip from chat'));
assert.ok(row('like','Remove reaction','heart','like').includes('Remove reaction'));
assert.ok(row('edit','<unsafe>','edit','edit').includes('&lt;unsafe>'),'label must be escaped');
assert.ok(!row('edit','<unsafe>','edit','edit').includes('<unsafe>'));
const menu=js.slice(end,js.indexOf('function setPhoto(file)',end));
assert.ok(menu.includes("'gc-sheet-menu gc-sheet-message-actions'"),'premium style must affect only this menu');
assert.ok(menu.includes("classList.add('gc-message-actions-back')"),'scoped backdrop must be applied');
assert.ok(menu.includes("m.mine&&m.kind==='text'"),'only text author can edit');
assert.ok(menu.includes("m.kind==='tip'&&!m.mine"),'other users cannot alter tip cards');
assert.ok(menu.includes("m.mine?messageActionRow('delete'"),'only sender gets delete');
assert.ok(menu.includes("data-message-act"),'delegated button events remain');
assert.ok(menu.includes("toggleLike(mid,"),'like action unchanged');
assert.ok(menu.includes("method:editing?'PUT':'DELETE'"),'existing edit/delete API preserved');
assert.ok(menu.includes("closeSheet();fetchNew();loadList()"),'updated message sync preserved');
const requiredSelectors=[
  '.gc-message-actions-back.on',
  '.gc-sheet.gc-sheet-message-actions',
  '.gc-message-actions-title',
  '.gc-message-action-icon',
  '.gc-message-action-danger',
  '.gc-message-action-cancel',
  'html[data-theme="light"] body .gc-sheet.gc-sheet-message-actions',
  'env(safe-area-inset-bottom',
  '@media (max-width:430px)',
  '@media (prefers-reduced-motion:reduce)'
];
requiredSelectors.forEach(sel=>assert.ok(css.includes(sel),'missing scoped style: '+sel));
assert.ok(css.includes('backdrop-filter:blur(5px)'),'chat backdrop should be subtly blurred');
console.log('PASS: group action sheet design, icon rows, sender permissions, handlers, light/iPhone variants');
