"""Run actual render functions in Node, parse HTML, then execute decoded handlers.

This catches both HTML-attribute and JavaScript-string injection without network,
wallets or the full dashboard startup. It is not a full browser integration test.
"""
import json
from html.parser import HTMLParser
from pathlib import Path
import subprocess

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'static/dashboard.js'
PAYLOADS = [
    'So11111111111111111111111111111111111111112',
    "');globalThis.__xss=1;//",
    '\"><svg onload="globalThis.__xss=1"></svg>',
    'quote" backslash\\ newline\n ampersand& apostrophe\' ',
]


def node(code, data):
    result = subprocess.run(['node', '-e', code], input=json.dumps(data),
                            text=True, capture_output=True, check=True, timeout=10)
    return json.loads(result.stdout)


RENDER = r'''
const fs = require('fs'), vm = require('vm');
const {source, sink, value} = JSON.parse(fs.readFileSync(0, 'utf8'));
function section(start, end) {
  const a=source.indexOf(start), b=source.indexOf(end, a+start.length);
  if(a<0||b<0)throw Error('Missing renderer '+start);
  return source.slice(a,b);
}
const elements={};
function el(id){return elements[id]||(elements[id]={innerHTML:'',style:{},classList:{add(){}}});}
const ctx={document:{getElementById:el},window:{},URL,AbortController,
  location:{origin:'https://orcagent.fun'}, setTimeout:()=>0,clearTimeout(){},
  phantomKey:'',currentWallet:'',_iadminSelWallet:'', dd:el('search'),
  _composerChainLabels:()=>({solana:'SOL'}),fmtTokenPrice:()=>'$1.00',
  _composerReshapeTokenInfo:()=>({pairAddress:value,chainId:'solana',baseToken:{symbol:'TEST'},
                                txns:{h24:{buys:value,sells:value}}})};
vm.createContext(ctx);
vm.runInContext(section('function esc(s){','function safeMint(m){'),ctx);
const choices={
 admin:['async function iadminFetchUsers(){','function iadminSelectUser(', 'ia-users-tbody',
        {users:[{wallet_full:value,wallet:value,positions:value,total_trades:value}]}],
 wallet:['async function loadWalletTokens(){','function _startWalletRefresh(', 'wallet-token-list',
        {ok:true,tokens:[{mint:value,symbol:'TEST',amount:1,value_usd:2}]}],
 search:['  async function doSearch(q){',"  inp.addEventListener('keyup'",'search',
        {ok:true,users:[],tokens:[{address:value,symbol:'TEST'}]}],
 pair:['async function showTokenCard(symbol,knownAddr){','function _feedSparkline(', 'tc-body',{ok:true}],
 inc:['function _incRenderRow(t, i){','async function _incLoad(', 'inc',{}],
};
const [start,end,id,response]=choices[sink];
ctx.fetch=async()=>({json:async()=>response});
ctx._e=ctx.esc;ctx._short=x=>x;
vm.runInContext(section(start,end),ctx);
(async()=>{
 if(sink==='admin')await ctx.iadminFetchUsers();
 if(sink==='wallet')await ctx.loadWalletTokens();
 if(sink==='search')await ctx.doSearch('test');
 if(sink==='pair')await ctx.showTokenCard('TEST','known');
 if(sink==='inc')el(id).innerHTML=ctx._incRenderRow({mint:value,pubkey:value,balance:value,
                                                symbol:value,reason:'unknown',can_close:true},0);
 process.stdout.write(JSON.stringify(el(id).innerHTML));
})().catch(e=>{console.error(e);process.exitCode=1});
'''


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


@pytest.mark.parametrize('sink', ['admin', 'wallet', 'search', 'pair', 'inc'])
@pytest.mark.parametrize('value', PAYLOADS)
def test_external_data_cannot_escape_html_or_inline_handler(sink, value):
    rendered = node(RENDER, {'source': SOURCE.read_text(), 'sink': sink, 'value': value})
    tags = Tags(rendered).tags
    assert tags, rendered
    assert not any(tag in {'script', 'svg', 'iframe', 'img'} for tag, _ in tags)
    assert not any('onload' in attrs for _, attrs in tags)
    if sink == 'inc':
        checkbox = next(attrs for tag, attrs in tags if tag == 'input')
        anchor = next(attrs for tag, attrs in tags if tag == 'a')
        assert checkbox['data-account'] == value
        assert anchor['title'] == value
        assert anchor['href'] == 'https://solscan.io/token/' + value
        return
    handlers = [attrs['onclick'] for _, attrs in tags if 'onclick' in attrs]
    assert len(handlers) == 1
    result = node(r'''
const vm=require('vm'),fs=require('fs');
const handler=JSON.parse(fs.readFileSync(0,'utf8'));
const calls=[];const record=(...args)=>{calls.push(args);return Promise.resolve()};
const ctx={__xss:0,window:{openTokenPanel:record,_hdrCloseDD(){}},
 iadminSelectUser:record,navigator:{clipboard:{writeText:record}},setTimeout(){}};
vm.createContext(ctx);
vm.runInContext('(function(){'+handler+'}).call({})',ctx);
process.stdout.write(JSON.stringify({xss:ctx.__xss,calls}));
''', handlers[0])
    assert result['xss'] == 0
    assert result['calls'] == ([ [value, value] ] if sink == 'admin' else [ [value] ])
