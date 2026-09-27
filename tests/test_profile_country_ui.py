"""Country flag UI is optional, keyboard/mobile friendly and not geolocated."""
from pathlib import Path
import re
import subprocess

root=Path(__file__).resolve().parents[1]
page=(root/'dashboard.html').read_text()
js=(root/'static/dashboard.js').read_text()
profile=(root/'templates/profile.html').read_text()
assert 'id="st-country-card"' in page
assert 'id="st-country-select"' in page and '<option value="">No country selected</option>' in page
assert 'id="st-country-visible" disabled' in page
assert 'id="st-country-save"' in page
assert 'Show flag on my profile' in page
assert 'OrcAgent never guesses your location' in page
assert '_loadCountrySettings();' in js
assert "headers:{'Content-Type':'application/json','X-CSRF-Token':_csrfToken}" in js
assert "fetch('/api/profile/country'" in js
assert 'document.createElement(\'option\')' in js
assert "preview.textContent=country?country.flag:'🌐'" in js
assert 'profile_country.flag' in profile and '{% if profile_country %}' in profile
assert 'class="pf-country-flag"' in profile
check=subprocess.run(['node','--check',str(root/'static/dashboard.js')],capture_output=True,text=True)
assert check.returncode==0,check.stderr
# Inline scripts: parse as JS with Jinja placeholders rather than ignoring them.
for filename in ('dashboard.html','templates/profile.html'):
    text=(root/filename).read_text()
    for n,source in enumerate(re.findall(r'<script(?:\s[^>]*)?>([\s\S]*?)</script>',text)):
        if not source.strip():continue
        source=re.sub(r'\{%[\s\S]*?%\}', '',source)
        source=re.sub(r'\{\{[\s\S]*?\}\}', 'null',source)
        check=subprocess.run(['node','--check'],input=source,capture_output=True,text=True)
        assert check.returncode==0,f'{filename} inline {n}: {check.stderr}'
print('PASS opt-in country selector, independent save and explicit privacy toggle')
print('PASS safe DOM country options, CSRF header, preview and flag on public profile')
print('PASS main dashboard JS and both templates inline JavaScript parse')

start=js.index('var _countryOptionMap={};')
end=js.index('/* ── X (Twitter) card (Card 4) ── */',start)
part=js[start:end]
script=part+'''
const assert=require('assert');
const map={
 'st-country-select':{value:'',options:[],replaceChildren(f){this.options=f.children;this.value=''},},
 'st-country-visible':{checked:false,disabled:true},
 'st-country-preview':{textContent:'🌐',title:''},
 'st-country-msg':{className:'',textContent:''},
 'st-country-save':{disabled:false}
};
const document={getElementById:k=>map[k],
 createDocumentFragment:()=>({children:[],appendChild(x){this.children.push(x)}}),
 createElement:()=>({value:'',textContent:''})};
let posted=null;
const _csrfToken='test-csrf';
const fetch=(url,options)=>{
 if(options&&options.method==='POST'){
   posted=JSON.parse(options.body);
   assert.equal(options.headers['X-CSRF-Token'],'test-csrf');
   return Promise.resolve({ok:true,json:()=>Promise.resolve({ok:true})});
 }
 return Promise.resolve({ok:true,json:()=>Promise.resolve({ok:true,country_code:'NL',show_country:false,
 countries:[{code:'NL',name:'Netherlands',flag:'🇳🇱'},{code:'LR',name:'Liberia',flag:'🇱🇷'}]})});
};
(async()=>{
 await _loadCountrySettings();
 assert.equal(map['st-country-visible'].checked,false,'existing country stays private');
 assert.equal(map['st-country-preview'].textContent,'🇳🇱');
 assert.equal(map['st-country-visible'].disabled,false);
 assert.equal(map['st-country-select'].options.length,3);
 map['st-country-visible'].checked=true;
 await _saveCountrySetting();
 assert.deepEqual(posted,{country_code:'NL',show_country:true});
 map['st-country-select'].value='';
 _countrySelectionChanged();
 assert.equal(map['st-country-visible'].disabled,true);
 assert.equal(map['st-country-visible'].checked,false);
 await _saveCountrySetting();
 assert.deepEqual(posted,{country_code:'',show_country:false});
 console.log('PASS client keeps selection private, saves opt-in and clears visibility');
})().catch(err=>{console.error(err);process.exitCode=1});
'''
r=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=15)
assert r.returncode==0,r.stderr
print(r.stdout.strip())
