from __future__ import annotations

_ADMIN_SETTINGS_JS = """async function loadTone(){
  try{
    const r=await fetch('/admin/tone',{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    window.__toneOpts=d.options||[];
    window.__toneCur=d.tone||'Magic';
    renderTone();
  }catch(e){}
}
// Pure render from cached tone options; safe to call on language switch (no network).
function renderTone(){
  const sel=document.getElementById('tone-select');
  if(!sel)return;
  const opts=window.__toneOpts||[];
  const cur=window.__toneCur||'Magic';
  // Skip re-render if unchanged (avoids resetting an open dropdown). Signature
  // includes lang so switching language re-renders the localized labels.
  const sig=JSON.stringify(opts)+'|'+cur+'|'+lang;
  if(sig===window.__toneSig)return;
  window.__toneSig=sig;
  const lbl=o=>(lang==='en'?(o.label_en||o.label):(o.label_zh||o.label))||o.label;
  // Tool-calling status: a coloured wrench (green verified / amber routed-or-flaky
  // / red unsupported), painted by the glass select from data-tc. It used to be a
  // symbol glued onto the label -- ' 🔧✕' -- which sat exactly where a select's
  // clear button sits and was read as one, and the status has a tooltip either way
  // because colour on its own is not a signal everyone can see.
  // Unmarked means "not measured" (server sends 'unknown'), never "measured fine".
  const TIPS={verified:'tc_tip_verified',router:'tc_tip_router',flaky:'tc_tip_flaky',unsupported:'tc_tip_unsupported'};
  sel.innerHTML='';
  opts.forEach(o=>{
    const op=document.createElement('option');
    op.value=o.value;op.textContent=lbl(o);
    if(TIPS[o.tool_calling]){op.dataset.tc=o.tool_calling;op.title=t(TIPS[o.tool_calling])}
    sel.appendChild(op);
  });
  sel.value=opts.some(o=>o.value===cur)?cur:(opts[0]?opts[0].value:'');
  initGlassSelect(sel.parentElement);
  refreshGlassSelect(sel);
  sel.onchange=()=>saveTone(sel.value);
}
async function saveTone(tone){
  try{
    const r=await fetch('/admin/tone',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({tone})});
    if(!r.ok)return;
    window.__toneCur=tone;window.__toneSig='';
    const s=document.getElementById('tone-saved');
    if(s){s.textContent=t('tone_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
async function loadRuntimeSettings(){
  try{
    const r=await fetch('/admin/runtime-settings',{credentials:'include'});if(!r.ok)return;
    const d=await r.json(),s=d.settings||{};
    __runtimeSettings={...s};
    renderRuntimeSettings(__runtimeSettings);
  }catch(e){}
}
// Pure render from cached settings; safe to call on language switch (no network).
function renderRuntimeSettings(s){
  try{
    s=s||{};
    const set=(id,v)=>{const el=document.getElementById(id);if(el)el.value=v??''};
    set('runtime-time-zone',s.time_zone);set('runtime-refresh-before',s.refresh_before_seconds);set('runtime-idle-timeout',s.idle_timeout_minutes);set('runtime-ws-idle-timeout',s.ws_idle_timeout_minutes);set('runtime-keepalive-check',s.keepalive_check_minutes);set('runtime-cookie-keepalive-before',s.cookie_keepalive_before_hours);set('runtime-auto-cleanup-minutes',s.auto_cleanup_minutes);set('runtime-session-idle-hours',s.session_idle_hours);set('runtime-cloud-cleanup-idle-hours',s.cloud_cleanup_idle_hours);set('runtime-account-cdp-port-base',s.account_cdp_port_base);set('runtime-rate-limit-rpm',s.rate_limit_rpm);set('runtime-rate-limit-burst',s.rate_limit_burst);set('runtime-account-concurrency',s.account_concurrency);set('runtime-proxy-url',s.proxy_url);set('runtime-log-level',s.log_level);set('runtime-call-log-limit',s.call_log_limit);
    const ll=document.getElementById('runtime-log-level');if(ll)refreshGlassSelect(ll);
    const ms=document.getElementById('media-suffix-input');if(ms&&document.activeElement!==ms)ms.value=(s.media_proxy_suffixes||[]).join('\\n');
    const to=document.getElementById('tone-options-input');if(to&&document.activeElement!==to)to.value=_toneOptionsToText(s.tone_options||[]);
    const co=document.getElementById('consumer-mode-options-input');if(co&&document.activeElement!==co)co.value=_consumerModeOptionsToText(s.consumer_mode_options||[]);
    const mt=document.getElementById('media-proxy-ttl-input');if(mt&&document.activeElement!==mt)mt.value=s.media_proxy_ttl_seconds?Math.max(1,Math.round(s.media_proxy_ttl_seconds/86400)):'';
    const ar=document.getElementById('runtime-auto-refresh');if(ar){ar.innerHTML='<option value="true">'+t('status_yes')+'</option><option value="false">'+t('status_no')+'</option>';ar.value=s.auto_refresh?'true':'false';initGlassSelect(ar.parentElement);refreshGlassSelect(ar)};
    const rp=document.getElementById('runtime-run-permission');if(rp){rp.innerHTML='<option value="read_only">'+t('run_permission_read_only')+'</option><option value="full">'+t('run_permission_full')+'</option>';rp.value=s.run_permission||'full';initGlassSelect(rp.parentElement);refreshGlassSelect(rp)};
    const tp=document.getElementById('runtime-tool-planning-mode');if(tp){tp.innerHTML='<option value="auto">'+t('tool_planning_auto')+'</option><option value="native">'+t('tool_planning_native')+'</option><option value="router">'+t('tool_planning_router')+'</option><option value="studio">'+t('tool_planning_studio')+'</option>';tp.value=s.tool_planning_mode||'auto';initGlassSelect(tp.parentElement);refreshGlassSelect(tp)};
    const uv=document.getElementById('runtime-user-log-verbose');if(uv){uv.innerHTML='<option value="true">'+t('status_yes')+'</option><option value="false">'+t('status_no')+'</option>';uv.value=s.user_log_verbose?'true':'false';initGlassSelect(uv.parentElement);refreshGlassSelect(uv)};
    const ue=document.getElementById('runtime-user-log-errors');if(ue){ue.innerHTML='<option value="true">'+t('status_yes')+'</option><option value="false">'+t('status_no')+'</option>';ue.value=s.user_log_errors?'true':'false';initGlassSelect(ue.parentElement);refreshGlassSelect(ue)};
    const sa=document.getElementById('runtime-suppress-access-log');if(sa){sa.innerHTML='<option value="true">'+t('status_yes')+'</option><option value="false">'+t('status_no')+'</option>';sa.value=s.suppress_access_log?'true':'false';initGlassSelect(sa.parentElement);refreshGlassSelect(sa)};
  }catch(e){}
}
async function saveRuntimeSettings(btnId){
  const btn=btnId?document.getElementById(btnId):null;
  const oldText=btn?.textContent;
  if(btn){btn.disabled=true;btn.textContent='...'}
  const body={...__runtimeSettings};
  const put=(key,id,cast)=>{const el=document.getElementById(id);if(el)body[key]=cast?cast(el.value):el.value};
  put('time_zone','runtime-time-zone');put('refresh_before_seconds','runtime-refresh-before',v=>Number(v||0));put('idle_timeout_minutes','runtime-idle-timeout',v=>Number(v||1));put('ws_idle_timeout_minutes','runtime-ws-idle-timeout',v=>Number(v||1));put('keepalive_check_minutes','runtime-keepalive-check',v=>Number(v||1));put('cookie_keepalive_before_hours','runtime-cookie-keepalive-before',v=>Number(v||1));put('auto_cleanup_minutes','runtime-auto-cleanup-minutes',v=>Number(v||0));put('session_idle_hours','runtime-session-idle-hours',v=>Number(v||0));put('cloud_cleanup_idle_hours','runtime-cloud-cleanup-idle-hours',v=>Number(v||0));put('account_cdp_port_base','runtime-account-cdp-port-base',v=>Number(v||9322));put('rate_limit_rpm','runtime-rate-limit-rpm',v=>Number(v||0));put('rate_limit_burst','runtime-rate-limit-burst',v=>Number(v||15));put('account_concurrency','runtime-account-concurrency',v=>Number(v||0));put('proxy_url','runtime-proxy-url');put('log_level','runtime-log-level');put('call_log_limit','runtime-call-log-limit',v=>Number(v||100));
  const ar=document.getElementById('runtime-auto-refresh');if(ar)body.auto_refresh=ar.value==='true';
  const rp=document.getElementById('runtime-run-permission');if(rp)body.run_permission=rp.value;
  const tp=document.getElementById('runtime-tool-planning-mode');if(tp)body.tool_planning_mode=tp.value;
  const uv=document.getElementById('runtime-user-log-verbose');if(uv)body.user_log_verbose=uv.value==='true';
  const ue=document.getElementById('runtime-user-log-errors');if(ue)body.user_log_errors=ue.value==='true';
  const sa=document.getElementById('runtime-suppress-access-log');if(sa)body.suppress_access_log=sa.value==='true';
  body.media_proxy_suffixes=_mediaSuffixListFromInput();
  const mt=document.getElementById('media-proxy-ttl-input');if(mt&&mt.value!=='')body.media_proxy_ttl_seconds=Math.max(1,Number(mt.value||1)||1)*86400;
  try{
    const r=await fetch('/admin/runtime-settings',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    // Surface the server's rejection reason: a validation failure (e.g. a
    // malformed proxy URL) is otherwise indistinguishable from a successful save.
    if(!r.ok){const d=await r.json().catch(()=>({}));const sp=document.getElementById('runtime-settings-saved');if(sp){sp.style.display='';sp.style.color='#ef4444';sp.style.fontSize='.75rem';sp.textContent=(d.error&&d.error.message)||'error'}if(btn){btn.disabled=false;btn.textContent=oldText}return;}
    const sp0=document.getElementById('runtime-settings-saved');if(sp0){sp0.textContent='';sp0.style.display='none'}
    const d=await r.json();if(d.settings)__runtimeSettings={...d.settings};
    // Tool planning is one of the fields just saved, and it decides each mode's
    // effective tool-calling status -- so re-pull the picker rather than leave its
    // wrenches showing the previous mode's answer until the next page load.
    window.__toneSig='';loadTone();
    if(btn){btn.textContent=t('tone_saved');setTimeout(()=>{btn.disabled=false;btn.textContent=oldText},1500)}
  }catch(e){if(btn){btn.disabled=false;btn.textContent=oldText}}
}
function _mediaSuffixListFromInput(){
  const ta=document.getElementById('media-suffix-input');
  return (ta?.value||'').split(/[\\s,;]+/).map(s=>s.trim().replace(/^\\.+/,'').toLowerCase()).filter(Boolean);
}
async function saveMediaSuffixes(){
  const body={...__runtimeSettings,media_proxy_suffixes:_mediaSuffixListFromInput()};
  try{
    const r=await fetch('/admin/runtime-settings',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)return;
    const d=await r.json();if(d.settings)__runtimeSettings={...d.settings};
    const ta=document.getElementById('media-suffix-input');if(ta)ta.value=(__runtimeSettings.media_proxy_suffixes||[]).join('\\n');
    const s=document.getElementById('media-suffix-saved');if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
async function resetMediaSuffixes(){
  const body={...__runtimeSettings,media_proxy_suffixes:[]};
  try{
    const r=await fetch('/admin/runtime-settings',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)return;
    const d=await r.json();if(d.settings)__runtimeSettings={...d.settings};
    const ta=document.getElementById('media-suffix-input');if(ta)ta.value=(__runtimeSettings.media_proxy_suffixes||[]).join('\\n');
    const s=document.getElementById('media-suffix-saved');if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
function _toneOptionsToText(opts){
  return (opts||[]).map(o=>{
    const v=o.value||'';const zh=o.label_zh||o.label||v;
    return v+' | '+zh;
  }).join('\\n');
}
function _toneOptionsFromInput(){
  const ta=document.getElementById('tone-options-input');
  const out=[];
  (ta?.value||'').split(/\\r?\\n/).forEach(line=>{
    line=line.trim();if(!line)return;
    const p=line.split('|').map(s=>s.trim());
    const v=p[0];if(!v)return;
    const zh=p[1]||v;
    out.push({value:v,label_zh:zh});
  });
  return out;
}
async function saveToneOptions(){
  const body={...__runtimeSettings,tone_options:_toneOptionsFromInput()};
  try{
    const r=await fetch('/admin/runtime-settings',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)return;
    const d=await r.json();if(d.settings)__runtimeSettings={...d.settings};
    const ta=document.getElementById('tone-options-input');if(ta)ta.value=_toneOptionsToText(__runtimeSettings.tone_options||[]);
    window.__toneSig='';loadTone();
    const s=document.getElementById('tone-options-saved');if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
async function resetToneOptions(){
  const body={...__runtimeSettings,tone_options:[]};
  try{
    const r=await fetch('/admin/runtime-settings',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)return;
    const d=await r.json();if(d.settings)__runtimeSettings={...d.settings};
    const ta=document.getElementById('tone-options-input');if(ta)ta.value=_toneOptionsToText(__runtimeSettings.tone_options||[]);
    window.__toneSig='';loadTone();
    const s=document.getElementById('tone-options-saved');if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
function _consumerModeOptionsToText(opts){
  return (opts||[]).map(o=>o.model+' | '+o.mode+' | '+o.status).join('\\n');
}
function _showConsumerModeResult(message,error){
  const s=document.getElementById('consumer-mode-options-saved');if(!s)return;
  s.textContent=message;s.style.color=error?'#ef4444':'#22c55e';s.style.opacity='1';
  if(!error)setTimeout(()=>{s.style.opacity='0'},1500);
}
async function saveConsumerModeOptions(){
  const ta=document.getElementById('consumer-mode-options-input');if(!ta)return;
  const body={...__runtimeSettings,consumer_mode_options:ta.value};
  try{
    const r=await fetch('/admin/runtime-settings',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok){const d=await r.json().catch(()=>({}));_showConsumerModeResult((d.error&&d.error.message)||'error',true);return;}
    const d=await r.json();if(d.settings)__runtimeSettings={...d.settings};
    ta.value=_consumerModeOptionsToText(__runtimeSettings.consumer_mode_options||[]);
    _showConsumerModeResult(t('consumer_mode_saved'),false);
  }catch(e){_showConsumerModeResult(String(e),true)}
}
async function resetConsumerModeOptions(){
  const body={...__runtimeSettings,consumer_mode_options:[]};
  try{
    const r=await fetch('/admin/runtime-settings',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok){const d=await r.json().catch(()=>({}));_showConsumerModeResult((d.error&&d.error.message)||'error',true);return;}
    const d=await r.json();if(d.settings)__runtimeSettings={...d.settings};
    const ta=document.getElementById('consumer-mode-options-input');if(ta)ta.value=_consumerModeOptionsToText(__runtimeSettings.consumer_mode_options||[]);
    _showConsumerModeResult(t('consumer_mode_saved'),false);
  }catch(e){_showConsumerModeResult(String(e),true)}
}
async function loadToolPrompt(){
  try{
    const r=await fetch('/admin/tool-prompt',{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    const ta=document.getElementById('tool-prompt-input');
    if(!ta)return;
    if(document.activeElement!==ta)ta.value=d.tool_prompt||'';
  }catch(e){}
}
async function saveToolPrompt(){
  try{
    const ta=document.getElementById('tool-prompt-input');
    if(!ta)return;
    const r=await fetch('/admin/tool-prompt',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({tool_prompt:ta.value})});
    if(!r.ok)return;
    const s=document.getElementById('tool-prompt-saved');
    if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
async function resetToolPrompt(){
  // Extra instruction default is empty.
  const ta=document.getElementById('tool-prompt-input');
  if(ta)ta.value='';
  await saveToolPrompt();
}

let __systemPromptDefault='';
async function loadSystemPrompt(){
  try{
    const r=await fetch('/admin/system-prompt',{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    __systemPromptDefault=d.default||'';
    const ta=document.getElementById('system-prompt-input');
    if(!ta)return;
    // Show the saved override, or fall back to the default text for reference.
    if(document.activeElement!==ta)ta.value=(d.system_prompt&&d.system_prompt.length)?d.system_prompt:__systemPromptDefault;
  }catch(e){}
}
async function unlockSystemPrompt(){
  if(!await adminConfirm(t('system_prompt_warn')))return;
  const locked=document.getElementById('system-prompt-locked');
  const editor=document.getElementById('system-prompt-editor');
  if(locked)locked.style.display='none';
  if(editor)editor.style.display='block';
}
async function saveSystemPrompt(){
  try{
    const ta=document.getElementById('system-prompt-input');
    if(!ta)return;
    const r=await fetch('/admin/system-prompt',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({system_prompt:ta.value})});
    if(!r.ok)return;
    const s=document.getElementById('system-prompt-saved');
    if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
async function resetSystemPrompt(){
  if(!await adminConfirm(t('system_prompt_reset_confirm')))return;
  const ta=document.getElementById('system-prompt-input');
  // Saving an empty override makes the backend fall back to the built-in default.
  if(ta)ta.value=__systemPromptDefault;
  try{
    const r=await fetch('/admin/system-prompt',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({system_prompt:''})});
    if(!r.ok)return;
    const s=document.getElementById('system-prompt-saved');
    if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}"""
