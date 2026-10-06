const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('static/dashboard.js','utf8');
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctx={console,Number,String,esc,safeMint:s=>/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(s),_fcRichText:esc,_replyRelTime:()=> 'now'};
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('var _TEAM_ROLE_STYLE ='),src.indexOf('// Only the server',src.indexOf('var _TEAM_ROLE_STYLE ='))),ctx);
vm.runInContext(src.slice(src.indexOf('function _agentPriceReplyHtml('),src.indexOf('async function _assistantTokenChoices(')),ctx);
const mint='98kfF7rmsg1QDUEoCqNE7g7M1FdrTt92TEp2CLzypump';
const quote='PAID: 0.004466 USD · 13:47:22 UTC. Source: DexScreener (retrieved). Solana contract: '+mint+'. https://orcagent.fun/live-market';
const official={id:139,username:'Orcagent',verified:true,team_role:'admin',message:quote};
let html=ctx._renderReplyRow(official,'p554',1);
const visible=html.replace(/<[^>]*>/g,'');
assert.ok(visible.includes('$PAID')&&visible.includes('$0.004466')&&visible.includes('USD'));
assert.ok(visible.includes('AI AGENT'));
for(const text of ['ADMIN','DexScreener','Source:','UTC',mint,'Show more'])assert.ok(!visible.includes(text),text);
assert.ok(html.includes('showTokenCard')&&html.includes(mint),'chart must retain exact selected identity');
assert.ok(!ctx._renderReplyRow({...official,verified:false},'p554',1).includes('fc-agent-price-value'));
assert.ok(ctx._teamBadgeHtml('admin','AnotherUser',true).includes('ADMIN'));
assert.ok(ctx._agentPriceReplyHtml('BTC: 85,873.19 USD · 13:47:22 UTC. Source: Coinbase (updated).').includes('$85,873.19'));
assert.ok(ctx._agentPriceReplyHtml('SOL: 107.70 EUR · 13:47:22 UTC. Source: CoinGecko (updated).').includes('€107.70'));
assert.equal(ctx._agentPriceReplyHtml('BTC: NaN USD · 13:47:22 UTC. Source: Coinbase'), '');
const callMessage='Best call today: $SK\nPeak: +96%\nEntry: $0.00006769\nTop: $0.000133\nView call: https://orcagent.fun/call/85';
const callHtml=ctx._renderReplyRow({...official,message:callMessage},'p554',1);
const callVisible=callHtml.replace(/<[^>]*>/g,'');
for(const text of ['Best call today','$SK','+96%','Entry','$0.00006769','Top','$0.000133','View call'])assert.ok(callVisible.includes(text),text);
assert.ok(callHtml.includes('fc-agent-call-hero')&&callHtml.includes('fc-agent-call-peak')&&callHtml.includes("location.href='/call/85'"),'best call must render as the clean call card');
assert.ok(!callVisible.includes('https://orcagent.fun/call/85'),'raw call URL must be replaced by the button');

const whyMessage='Best call today: $SK\nPeak: +96%\nEntry: $0.00006769\nTop: $0.000133\nWhy: Best recorded peak today (+96%)\nWhy: 24h volume $51.5K\nWhy: Liquidity $39.6K\nView call: https://orcagent.fun/call/85';
const whyHtml=ctx._renderReplyRow({...official,message:whyMessage},'p554',1);
assert.ok(whyHtml.includes('Why this call?')&&whyHtml.includes('24h volume $51.5K')&&whyHtml.includes('Liquidity $39.6K'),'why question gets short factual reasons');

const chartMessage='Best call today: $SK\nPeak: +96%\nEntry: $0.00006769\nTop: $0.000133\nChart: yes\nView call: https://orcagent.fun/call/85';
const chartHtml=ctx._renderReplyRow({...official,message:chartMessage},'p554',1);
assert.ok(chartHtml.includes('fc-agent-call-chart')&&chartHtml.includes('data-agent-call-chart="85"'),'show question gets a chart preview');

const topMessage='Top 3 calls today:\n1. $SK | +96% | /call/85\n2. $EMBER | +48.2% | /call/86\n3. $NIO | +31.7% | /call/87\nView all calls: https://orcagent.fun/calls';
const topHtml=ctx._renderReplyRow({...official,message:topMessage},'p554',1);
for(const text of ['Top 3 calls today','$SK','+96%','$EMBER','+48.2%','$NIO','+31.7%','View all calls'])assert.ok(topHtml.replace(/<[^>]*>/g,'').includes(text),text);
assert.ok(topHtml.includes("location.href='/call/85'")&&topHtml.includes("location.href='/calls'"),'top calls rows link directly to calls');

const emptyMessage='No clear best call today.\nThere is no winning public call in the last 24h yet.\nView trending: https://orcagent.fun/live-market';
const emptyHtml=ctx._renderReplyRow({...official,message:emptyMessage},'p554',1);
assert.ok(emptyHtml.includes('No clear best call yet')&&emptyHtml.includes("location.href='/live-market'"),'no-winner state is simple and actionable');

const legacy='Best-performing OrcAgent call in the last 24h: $SK — 1.96x peak from $6.769e-05 to $0.000133. orcagent.fun/#post-p557';
const legacyHtml=ctx._renderReplyRow({...official,message:legacy},'p554',1);
assert.ok(legacyHtml.includes('fc-agent-call-card')&&legacyHtml.includes('+96%')&&legacyHtml.includes("location.href='/#post-p557'"),'legacy long best-call replies are upgraded to the new card');

assert.ok(!ctx._renderReplyRow({...official,verified:false,message:callMessage},'p554',1).includes('fc-agent-call-card'),'only the verified OrcAgent account may render the call card');
html=ctx._renderReplyRow({id:138,username:'Trader',message:'@orcagent $PAID ('+mint+') what is the price?'},'p554',1);
assert.ok(!html.replace(/<[^>]*>/g,'').includes(mint));
html=ctx._renderReplyRow({...official,message:'Do you mean $PAID? Several Solana tokens match. Choose the right contract below, then send your price question.'},'p554',1);
assert.ok(html.includes('Select the $PAID token.')&&html.includes('Choose $PAID token'));
assert.ok(!html.includes('Several Solana tokens match'));
console.log('PASS compact legacy/current quotes, exact-token chart action, identity badge, native currencies, invalid price and compact chooser');
if(process.env.AGENT_PREVIEW){
 fs.writeFileSync(process.env.AGENT_PREVIEW,ctx._renderReplyRow({id:136,username:'degentrader1990',verified:true,team_role:'executive',is_mine:true,message:'@orcagent what is the price of $paid'},'p554',0)+ctx._renderReplyRow({...official,id:137,message:'Do you mean $PAID? Several Solana tokens match. Choose the right contract below, then send your price question.'},'p554',1)+ctx._renderReplyRow({id:138,username:'degentrader1990',verified:true,team_role:'executive',is_mine:true,message:'@orcagent $PAID ('+mint+') what is the price?'},'p554',1)+ctx._renderReplyRow(official,'p554',1));
}
