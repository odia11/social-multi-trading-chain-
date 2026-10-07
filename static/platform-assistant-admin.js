(function(){
'use strict';
var form=document.getElementById('platform-settings'),status=document.getElementById('platform-status');
async function send(url,body){
var response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(body)});
var result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'Could not save.');
return result;
}
form.addEventListener('submit',async function(e){
e.preventDefault();var button=form.querySelector('button');button.disabled=true;
try{await send('/api/admin/platform-assistant',{posts:form.elements.posts.checked,replies:form.elements.replies.checked,learning:form.elements.learning.checked});status.textContent='Settings saved.';}
catch(error){status.textContent=error.message;}finally{button.disabled=false;}
});
var keyForm=document.getElementById('ai-key-form');
if(keyForm){
var keyStatus=document.getElementById('ai-key-status');
var csrf=function(){return document.querySelector('meta[name="csrf-token"]').content;};
keyForm.addEventListener('submit',async function(e){
e.preventDefault();var input=keyForm.elements.key,button=keyForm.querySelector('button[type=submit]');
if(!input.value.trim()){keyStatus.textContent='Paste a key first.';return;}
button.disabled=true;keyStatus.textContent='Checking the key…';
try{var r=await send('/api/admin/platform-assistant/ai-key',{key:input.value.trim()});input.value='';
keyStatus.textContent=(r.verified?'Key checked and saved':'Key saved (could not reach the API to check it)')+' · '+r.hint+'. Reload to see the status.';}
catch(error){keyStatus.textContent=error.message;}finally{button.disabled=false;}
});
var remove=document.getElementById('ai-key-remove');
if(remove)remove.addEventListener('click',async function(){
remove.disabled=true;
try{var resp=await fetch('/api/admin/platform-assistant/ai-key',{method:'DELETE',credentials:'same-origin',headers:{'X-CSRF-Token':csrf()}});
var r=await resp.json();if(!resp.ok||!r.ok)throw Error(r.error||'Could not remove.');keyStatus.textContent='Key removed. @orcagent uses its built-in brain.';}
catch(error){keyStatus.textContent=error.message;}finally{remove.disabled=false;}
});
}
document.querySelectorAll('.learning-review').forEach(function(review){
review.addEventListener('submit',async function(e){
e.preventDefault();var action=e.submitter&&e.submitter.value;if(!action)return;
var buttons=review.querySelectorAll('button'),message=review.querySelector('.learning-status');buttons.forEach(function(b){b.disabled=true;});
try{await send('/api/admin/platform-assistant/learning',{question:review.dataset.question,topic:review.elements.topic.value,status:action});message.textContent='Saved: '+action+'. Reload to see the current overview.';}
catch(error){message.textContent=error.message;}finally{buttons.forEach(function(b){b.disabled=false;});}
});
});
})();
