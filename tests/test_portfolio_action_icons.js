/* The Portfolio Deposit/Send/Receive/Swap buttons used unicode glyphs
   (↓ → ▣ ⇄) that render differently per OS/font -- "▣" looked like an empty
   box on phones. They are now inline duotone SVGs in the same gold style as
   the Home shortcut tiles (approved design "Option C"). */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const html=fs.readFileSync('templates/wallet.html','utf8');
const row=html.slice(html.indexOf('_modalDeposit()"'),html.indexOf('>Swap</button>')+14);
assert(row.length>100,'action row not found');
for(const label of ['Deposit','Send','Receive','Swap']){
  const re=new RegExp('<span class="wlt-action-ic" aria-hidden="true"><svg class="wlt-ic-svg"[^]*?</svg></span>'+label+'</button>');
  assert(re.test(row),label+' must use an inline SVG icon');
}
for(const glyph of ['↓','→','▣','⇄'])assert(!row.includes(glyph),'unicode glyph '+glyph+' must not be used as an action icon');
assert(/\.wlt-ic-svg\{display:block;width:28px;height:28px/.test(html),'SVG icons need a fixed size');
console.log('PASS portfolio action icons: inline duotone SVGs, no OS-dependent unicode glyphs');
