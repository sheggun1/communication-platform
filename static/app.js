let contacts = [];
const fileInput = document.getElementById("contactFile");
const previewBox = document.getElementById("contactPreview");
const sendBtn = document.getElementById("sendBtn");
const mode = document.getElementById("mode");
const channelInputs = document.querySelectorAll('input[name="channel"]');

function currentChannel(){return document.querySelector('input[name="channel"]:checked').value}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function updateMode(){
 const individual=mode.value==="individual";
 document.getElementById("templateWrap").classList.toggle("hidden",individual);
 document.getElementById("individualWrap").classList.toggle("hidden",!individual);
 document.getElementById("subjectWrap").classList.toggle("hidden",currentChannel()!=="email");
 if(individual) renderIndividualInputs();
}
mode.addEventListener("change",updateMode);
channelInputs.forEach(x=>x.addEventListener("change",updateMode));
function renderIndividualInputs(){
 const host=document.getElementById("individualMessages");
 host.innerHTML=contacts.map((c,i)=>'<div class="individual-card"><label>'+esc(c.name||c.Name||c.email||c.phone||("Contact "+(i+1)))+'</label><textarea rows="2" data-message-index="'+i+'" placeholder="Write this person's message...">'+esc(c._message||"")+'</textarea></div>').join("");
}
fileInput.addEventListener("change",async()=>{
 const file=fileInput.files[0]; if(!file)return;
 document.getElementById("fileInfo").textContent="Reading "+file.name+"...";
 const form=new FormData();form.append("file",file);
 try{
  const res=await fetch("/api/preview",{method:"POST",body:form});
  const data=await res.json();if(!res.ok)throw new Error(data.error||"Could not read file.");
  contacts=data.contacts;
  document.getElementById("fileInfo").textContent=contacts.length+" contacts loaded from "+file.name+". Maximum 500 contacts per campaign.";
  previewBox.innerHTML='<p class="hint">Preview of first contacts · Columns: '+data.columns.map(esc).join(", ")+'</p><div class="table-wrap"><table><thead><tr>'+data.columns.map(c=>"<th>"+esc(c)+"</th>").join("")+'</tr></thead><tbody>'+data.sample.map(row=>"<tr>"+data.columns.map(c=>"<td>"+esc(row[c])+"</td>").join("")+"</tr>").join("")+'</tbody></table></div>';
  sendBtn.disabled=false;updateMode();
 }catch(e){contacts=[];sendBtn.disabled=true;document.getElementById("fileInfo").textContent=e.message;previewBox.innerHTML=""}
});
sendBtn.addEventListener("click",async()=>{
 if(!contacts.length)return;
 if(!confirm("You are about to send a campaign to "+contacts.length+" contacts via "+currentChannel().toUpperCase()+". Continue?"))return;
 if(mode.value==="individual"){
  document.querySelectorAll("[data-message-index]").forEach(el=>contacts[Number(el.dataset.messageIndex)]._message=el.value);
 }
 sendBtn.disabled=true;sendBtn.textContent="Sending messages...";
 const result=document.getElementById("sendResult");result.innerHTML="";
 const payload={contacts,channel:currentChannel(),mode:mode.value,message:document.getElementById("message").value,subject:document.getElementById("subject").value,name:document.getElementById("campaignName").value};
 try{
  const res=await fetch("/api/send",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const data=await res.json();if(!res.ok)throw new Error(data.error||"Campaign could not be sent.");
  result.innerHTML='<div class="'+(data.failed?"failure":"success")+'"><b>Campaign finished</b><br>Accepted: '+data.sent+' · Failed: '+data.failed+' · Total: '+data.total+'<br><small>Campaign ID: '+esc(data.id)+'</small></div><div class="table-wrap"><table><thead><tr><th>Recipient</th><th>Status</th><th>Details</th></tr></thead><tbody>'+data.results.map(r=>"<tr><td>"+esc(r.recipient)+"</td><td>"+esc(r.status)+"</td><td>"+esc(r.detail)+"</td></tr>").join("")+"</tbody></table></div>";
  setTimeout(()=>location.reload(),5000);
 }catch(e){result.innerHTML='<div class="failure">'+esc(e.message)+'</div>'}
 finally{sendBtn.disabled=false;sendBtn.textContent="Review and send campaign"}
});
updateMode();
