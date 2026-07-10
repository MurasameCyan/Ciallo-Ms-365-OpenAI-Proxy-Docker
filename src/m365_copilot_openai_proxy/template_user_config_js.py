from __future__ import annotations

_USER_CONFIG_JS = """function renderToneOptions(){
  const sel=document.getElementById('tone');if(!sel||!toneOptions.length)return;
  const cur=sel.value;
  sel.innerHTML='';
  toneOptions.forEach(o=>{
    const opt=document.createElement('option');
    opt.value=o.value;
    opt.textContent=lang==='zh'?(o.label_zh||o.label):(o.label_en||o.label);
    sel.appendChild(opt);
  });
  if(cur)sel.value=cur;
  initGlassSelect(sel.parentElement);
  refreshGlassSelect(sel);
  renderRunPermissionOptions();
}
function renderRunPermissionOptions(){
  const sel=document.getElementById('user-run-permission');if(!sel)return;
  const cur=sel.value;
  sel.innerHTML='<option value="read_only">'+t('run_permission_read_only')+'</option><option value="full">'+t('run_permission_full')+'</option>';
  sel.value=cur==='read_only'||cur==='full'?cur:'full';
  sel.dataset.glassReady='';
  const old=sel.nextElementSibling;if(old&&old.classList.contains('glass-select'))old.remove();
  initGlassSelect(sel.parentElement);
  refreshGlassSelect(sel);
}
function flash(id){const s=document.getElementById(id);if(!s)return;s.textContent=t('saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
async function saveTone(){
  const tone=document.getElementById('tone').value;
  const model_alias=document.getElementById('user-model-alias')?.value||'';
  const time_zone=document.getElementById('user-time-zone')?.value||'';
  const run_permission=document.getElementById('user-run-permission')?.value||'full';
  const media_proxy_suffixes=document.getElementById('user-media-suffix')?.value||'';
  const ws_idle_timeout_minutes=Number(document.getElementById('user-ws-idle-timeout')?.value||0);
  userTimeZone=time_zone;
  try{
    const r=await fetch('/user/tone',{method:'POST',headers:authHeaders(),body:JSON.stringify({tone:tone,model_alias:model_alias,time_zone:time_zone,run_permission:run_permission,ws_idle_timeout_minutes:ws_idle_timeout_minutes,media_proxy_suffixes:media_proxy_suffixes})});
    if(r.ok){const d=await r.json();document.getElementById('user-model-alias').value=d.model_alias||'';userTimeZone=d.time_zone||'';document.getElementById('user-time-zone').value=userTimeZone;const uwit=document.getElementById('user-ws-idle-timeout');if(uwit&&document.activeElement!==uwit)uwit.value=(d.ws_idle_timeout_minutes>0)?d.ws_idle_timeout_minutes:'';const rp=document.getElementById('user-run-permission');if(rp){rp.value=d.run_permission||d.effective_run_permission||'full';refreshGlassSelect(rp)}const ums=document.getElementById('user-media-suffix');if(ums&&document.activeElement!==ums)ums.value=(d.media_proxy_suffixes||[]).join('\\n');flash('tone-msg')}
  }catch(e){}
}
async function saveToolPrompt(){
  const p=document.getElementById('tool-prompt').value;
  try{await fetch('/user/tool-prompt',{method:'POST',headers:authHeaders(),body:JSON.stringify({tool_prompt:p})});flash('tool-msg')}catch(e){}
}
async function unlockSysPrompt(){
  if(!await userDialog(t('system_prompt_title'),t('system_prompt_warn'),t('confirm_btn')))return;
  const l=document.getElementById('sys-prompt-locked');
  const e=document.getElementById('sys-prompt-editor');
  if(l)l.style.display='none';
  if(e)e.style.display='block';
}
async function saveSysPrompt(){
  const p=document.getElementById('sys-prompt').value;
  try{await fetch('/user/system-prompt',{method:'POST',headers:authHeaders(),body:JSON.stringify({system_prompt:p})});flash('sys-msg')}catch(e){}
}
async function resetSysPrompt(){
  if(!await userDialog(t('system_prompt_title'),t('sys_prompt_reset_confirm'),t('confirm_btn')))return;
  document.getElementById('sys-prompt').value='';
  try{await fetch('/user/system-prompt',{method:'POST',headers:authHeaders(),body:JSON.stringify({system_prompt:''})});flash('sys-msg')}catch(e){}
}
"""
