(function(){
'use strict';
var root=document.querySelector('[data-csrf]');
if(!root)return;
var busy=false;
async function submit(url,body,button){
 if(busy)return;
 busy=true;button.disabled=true;
 var message=document.querySelector('.cr-message');
 if(message)message.textContent='Checking…';
 try{
  var response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':root.dataset.csrf},body:JSON.stringify(body)});
  var result=await response.json();
  if(!response.ok||!result.ok)throw Error(result.error||'Could not complete this request');
  location.reload();
 }catch(error){
  if(message)message.textContent=error.message;
  busy=false;button.disabled=false;
 }
}
root.addEventListener('click',function(event){
 var button=event.target.closest('button[data-cr-action],button[data-cr-admin]');
 if(!button)return;
 if(button.dataset.crAction)submit('/api/creator-rewards/'+button.dataset.crAction,{},button);
 else submit('/api/admin/creator-rewards/'+button.dataset.crAdmin,JSON.parse(button.dataset.crPayload),button);
});
root.addEventListener('submit',function(event){
 var form=event.target.closest('[data-cr-form]');
 if(!form)return;
 event.preventDefault();
 var fields=new FormData(form),body={};
 fields.forEach(function(value,key){if(key!=='signatures')body[key]=value;});
 if(form.dataset.crForm==='settle')body.signatures=fields.getAll('signatures');
 if(body.payout_id)body.payout_id=Number(body.payout_id);
 submit('/api/admin/creator-rewards/'+form.dataset.crForm,body,form.querySelector('button[type=submit]'));
});
})();
