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
document.querySelectorAll('.learning-review').forEach(function(review){
review.addEventListener('submit',async function(e){
e.preventDefault();var action=e.submitter&&e.submitter.value;if(!action)return;
var buttons=review.querySelectorAll('button'),message=review.querySelector('.learning-status');buttons.forEach(function(b){b.disabled=true;});
try{await send('/api/admin/platform-assistant/learning',{question:review.dataset.question,topic:review.elements.topic.value,status:action});message.textContent='Saved: '+action+'. Reload to see the current overview.';}
catch(error){message.textContent=error.message;}finally{buttons.forEach(function(b){b.disabled=false;});}
});
});
})();
