(function(){
'use strict';
var form=document.getElementById('platform-settings'),status=document.getElementById('platform-status');
form.addEventListener('submit',async function(e){
e.preventDefault();var button=form.querySelector('button');button.disabled=true;
try{
var response=await fetch('/api/admin/platform-assistant',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({posts:form.elements.posts.checked,replies:form.elements.replies.checked})});
var result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'Could not save settings.');
status.textContent='Settings saved.';
}catch(error){status.textContent=error.message;}finally{button.disabled=false;}
});
})();