from __future__ import annotations

_USER_ACCOUNT_JS = """async function doLogin(){
  const username=document.getElementById('username').value.trim();
  const password=document.getElementById('password').value;
  const msg=document.getElementById('login-msg');
  if(!username||!password)return;
  const fail=()=>{msg.className='msg';msg.style.color='#fca5a5';msg.style.opacity='1';msg.textContent=t('login_failed')};
  try{
    const r=await fetch('/user/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username,password:password})});
    if(!r.ok){fail();return}
    const d=await r.json();
    sessionStorage.setItem('user_api_key',d.key);
    const ok=await loadMe();
    if(!ok){fail();sessionStorage.removeItem('user_api_key')}
  }catch(e){msg.className='msg';msg.style.color='#fca5a5';msg.style.opacity='1';msg.textContent=t('network_error')}
}
function userPasswordDialog(){
  return new Promise(resolve=>{
    const ov=document.createElement('div');ov.className='modal-backdrop';
    ov.innerHTML='<div class="modal-card flow-box"><div style="font-weight:700;color:var(--strong);margin-bottom:.55rem">'+t('change_password')+'</div><div style="display:grid;gap:.55rem"><input id="rp-old" type="password" placeholder="'+t('old_password')+'"><input id="rp-new" type="password" placeholder="'+t('new_password')+'"></div><div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem"><button id="rp-cancel" class="btn-ghost" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button><button id="rp-ok" style="font-size:.8rem;padding:6px 14px">'+t('confirm_btn')+'</button></div></div>';
    document.body.appendChild(ov);
    const oldEl=ov.querySelector('#rp-old'),newEl=ov.querySelector('#rp-new');
    const done=v=>{ov.remove();resolve(v)};
    const submit=()=>{const oldPassword=oldEl.value,newPassword=newEl.value;if(!oldPassword||!newPassword)return;done({oldPassword,newPassword})};
    ov.addEventListener('click',e=>{if(e.target===ov)done(null)});
    ov.querySelector('#rp-cancel').onclick=()=>done(null);
    ov.querySelector('#rp-ok').onclick=submit;
    ov.addEventListener('keydown',e=>{if(e.key==='Enter')submit();if(e.key==='Escape')done(null)});
    setTimeout(()=>oldEl.focus(),30);
  });
}
async function changeLoginPassword(btn){
  const form=await userPasswordDialog();
  if(!form)return;
  if(btn){btn.disabled=true}
  let ok=false,msg='';
  try{
    const r=await fetch('/user/repassword',{method:'POST',headers:{...authHeaders(),'Content-Type':'application/json'},body:JSON.stringify({old_password:form.oldPassword,new_password:form.newPassword})});
    const d=await r.json().catch(()=>({}));ok=r.ok;msg=(d.error&&d.error.message)||'';
  }catch(e){msg=t('network_error')}
  if(btn){const oldTitle=btn.title;btn.title=ok?t('password_changed'):(msg||t('password_change_failed'));btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(()=>{btn.title=oldTitle||t('change_password');btn.style.color='';btn.disabled=false},2500)}
}
async function logout(btn){if(btn){btn.disabled=true;btn.textContent=t('logging_out_ms')}let ok=false;try{const r=await fetch('/user/account/logout',{method:'POST',headers:authHeaders()});ok=r.ok}catch(e){}if(btn){btn.textContent=ok?t('logout_ok_ms'):t('logout_failed_ms');btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(async()=>{btn.textContent=t('logout');btn.style.color='';btn.disabled=false;await loadMe()},3000)}else{await loadMe()}}
function logoutConsole(){_userRemainSec=0;sessionStorage.removeItem('user_api_key');document.getElementById('app').classList.add('hidden');document.getElementById('login-card').classList.remove('hidden');const p=document.getElementById('password');if(p)p.value='';const m=document.getElementById('login-msg');if(m)m.textContent=''}
function userDialog(title,message,okText){
  return new Promise(resolve=>{
    const ov=document.createElement('div');ov.className='modal-backdrop';
    ov.innerHTML='<div class="modal-card flow-box"><div style="font-weight:700;color:var(--strong);margin-bottom:.55rem">'+title+'</div><div style="font-size:.84rem;color:var(--muted);line-height:1.55">'+message+'</div><div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem"><button id="dlg-cancel" class="btn-ghost" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button><button id="dlg-ok" style="font-size:.8rem;padding:6px 14px">'+okText+'</button></div></div>';
    document.body.appendChild(ov);const done=v=>{ov.remove();resolve(v)};ov.addEventListener('click',e=>{if(e.target===ov)done(false)});ov.querySelector('#dlg-cancel').onclick=()=>done(false);ov.querySelector('#dlg-ok').onclick=()=>done(true);
  });
}
function confirmUnbindAccount(){
  return new Promise(resolve=>{
    const ov=document.createElement('div');
    ov.className='modal-backdrop';
    ov.innerHTML='<div class="modal-card flow-box">'
      +'<div style="font-weight:700;color:var(--strong);margin-bottom:.55rem">'+t('unbind_account')+'</div>'
      +'<div style="font-size:.84rem;color:var(--muted);line-height:1.55">'+t('unbind_confirm')+'</div>'
      +'<div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem">'
      +'<button id="unbind-cancel" class="btn-ghost" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>'
      +'<button id="unbind-ok" style="font-size:.8rem;padding:6px 14px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('unbind_confirm_btn')+'</button>'
      +'</div></div>';
    document.body.appendChild(ov);
    const done=v=>{ov.remove();resolve(v)};
    ov.addEventListener('click',e=>{if(e.target===ov)done(false)});
    ov.querySelector('#unbind-cancel').onclick=()=>done(false);
    ov.querySelector('#unbind-ok').onclick=()=>done(true);
  });
}
async function unbindAccount(btn){
  if(!await confirmUnbindAccount())return;
  if(btn){btn.disabled=true;btn.textContent=t('unbinding_ms')}
  let ok=false;try{const r=await fetch('/user/account/unbind',{method:'POST',headers:authHeaders()});ok=r.ok}catch(e){}
  if(btn){btn.textContent=ok?t('unbind_ok_ms'):t('unbind_failed_ms');btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(async()=>{btn.textContent=t('unbind_account');btn.style.color='';btn.disabled=false;await loadMe()},3000)}else{await loadMe()}
}
function fmtExpire(iso){
  if(!iso)return t('status_unknown');
  try{return new Date(iso).toLocaleString(undefined,userTimeZone?{timeZone:userTimeZone}:undefined)}catch(e){return iso}
}
function fmtRemaining(sec){
  sec=Math.max(0,Math.floor(sec||0));
  const h=String(Math.floor(sec/3600)).padStart(2,'0');
  const m=String(Math.floor((sec%3600)/60)).padStart(2,'0');
  const s=String(sec%60).padStart(2,'0');
  return h+':'+m+':'+s;
}
let _userRemainSec=0;
function startUserCountdown(sec){_userRemainSec=Math.max(0,Math.floor(sec||0));renderUserCountdown()}
function renderUserCountdown(){
  const text=fmtRemaining(_userRemainSec);
  document.querySelectorAll('[data-user-remaining]').forEach(el=>{el.textContent=text});
}
function tickUserCountdown(){if(_userRemainSec>0){_userRemainSec--;renderUserCountdown()}}
function boundAccountName(a){
  if(!a)return t('status_unknown');
  const state=a.binding_state||(a.cookie_valid?'cookie':(a.has_token?'token_only':'none'));
  if(state==='cookie')return a.name||a.email||a.id;
  return state==='token_only'?t('account_none_token'):t('account_none');
}
function renderAccountStatus(d){
  const box=document.getElementById('account-status-panel');if(!box)return;
  const a=d.account||null,st=a?(a.token_status||{}):{};
  const valid=!!st.valid;
  const login=!!(a&&a.cookie_valid);
  const refresh=!!(a&&(a.provider==='consumer'||a.token_source==='cdp'));
  const expiryKnown=!!st.expires_at;
  const name=boundAccountName(a);
  const mark=(ok)=>'<span class="status-mark '+(ok?'ok':'bad')+'"></span>';
  box.innerHTML='<h3 style="margin:0;color:var(--strong);font-size:1rem;display:none">'+t('status_panel_title')+'</h3>'
    +'<div class="status-grid">'
    +'<div class="status-line status-first"><span>'+t('status_account')+'</span><b>'+esc(name)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_login')+'</span><b>'+mark(login)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_refresh')+'</span><b>'+mark(refresh)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_valid')+'</span><b>'+mark(valid)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_remaining')+'</span><b'+(expiryKnown?' data-user-remaining':'')+'>'+(expiryKnown?fmtRemaining(st.seconds_remaining):t('status_unknown'))+'</b></div>'
    +'<div class="status-line"><span>'+t('status_expire')+'</span><b>'+fmtExpire(st.expires_at)+'</b></div>'
    +'</div>';
}

let _userMeCache=null;
function renderAccountInfo(d){
  if(!d)return;
  let acc='';
  if(d.displaced){
    acc+='<div class="msg err" style="display:block;margin-bottom:.6rem">'+t('displaced_notice')+'</div>';
  }
  const keyIcon='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7.5" cy="14.5" r="3.5"></circle><path d="M10.2 12L21 1.2M15.5 6.7l2.8 2.8M18.2 4l2.6 2.6"></path></svg>';
  const doorIcon='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5.5A1.5 1.5 0 0 1 4 19.5v-15A1.5 1.5 0 0 1 5.5 3H9"></path><path d="M14 8l4 4-4 4"></path><path d="M18 12H8"></path><path d="M10 3h7a1.5 1.5 0 0 1 1.5 1.5v4"></path></svg>';
  const consoleActions='<span class="account-console-icons" style="height:32px;display:inline-flex;align-items:center;gap:.4rem"><button type="button" class="account-icon-btn account-icon-btn-pass" title="'+t('change_password')+'" onclick="changeLoginPassword(this)" aria-label="'+t('change_password')+'">'+keyIcon+'</button><button type="button" class="account-icon-btn account-icon-btn-out" title="'+t('console_logout')+'" onclick="logoutConsole()" aria-label="'+t('console_logout')+'">'+doorIcon+'</button></span>';
  const actionBox=document.getElementById('account-console-actions');if(actionBox)actionBox.innerHTML=consoleActions;
  if(d.account){
    const st=d.account.token_status||{};
    const valid=st.valid;
    const rem=valid&&st.expires_at?(' · '+t('remaining')+' <span data-user-remaining>'+fmtRemaining(_userRemainSec>0?_userRemainSec:st.seconds_remaining)+'</span>'):'';
    acc+='<div class="row" style="flex-wrap:wrap;gap:.4rem;align-items:center"><span class="pill">'+t('bound_account')+': '+esc(boundAccountName(d.account))+'</span>'
      +'<span class="pill '+(valid?'ok':'bad')+'">'+(valid?t('token_valid'):t('token_invalid'))+rem+'</span></div>';
  }else{
    acc+='<div class="row" style="flex-wrap:wrap;gap:.4rem;align-items:center"><span class="pill">'+t('no_account')+'</span></div>';
  }
  acc+='<div style="margin-top:.6rem;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center"><button class="btn-ghost account-action" onclick="logout(this)">'+t('logout')+'</button><button class="btn-ghost account-action" onclick="unbindAccount(this)">'+t('unbind_account')+'</button></div>';
  const info=document.getElementById('account-info');if(info)info.innerHTML=acc;
  const upx=document.getElementById('user-proxy-url');if(upx&&document.activeElement!==upx)upx.value=(d.account&&d.account.proxy_url)||'';
  renderAccountStatus(d);
}
function applyUserLangDynamic(){
  if(!_userMeCache)return;
  renderAccountInfo(_userMeCache);
  // refresh placeholders that depend on language
  try{
    const uwit=document.getElementById('user-ws-idle-timeout');
    if(uwit){const dw=_userMeCache.default_ws_idle_timeout_minutes||0;uwit.placeholder=dw?(t('user_ws_idle_timeout_inherit')+dw):''}
    const ums=document.getElementById('user-media-suffix');
    if(ums){const dg=(_userMeCache.default_media_proxy_suffixes||[]).join(' ');ums.placeholder=dg?(t('user_media_suffix_inherit')+dg):''}
    renderToneOptions();
    const tone=document.getElementById('tone');if(tone){tone.value=_userMeCache.tone||tone.value||'Magic';refreshGlassSelect(tone)}
    renderRunPermissionOptions();
    const rp=document.getElementById('user-run-permission');if(rp){rp.value=_userMeCache.run_permission||_userMeCache.effective_run_permission||rp.value||'full';refreshGlassSelect(rp)}
  }catch(e){}
}
async function loadMe(){
  if(!getKey())return false;
  try{
    const r=await fetch('/user/me',{headers:authHeaders()});
    if(!r.ok)return false;
    const d=await r.json();
    toneOptions=d.tone_options||[];
    sysDefault=d.default_system_prompt||'';
    document.getElementById('login-card').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    document.getElementById('base-url').textContent=location.origin+'/v1';
    const mk=document.getElementById('my-key');if(mk)mk.textContent=getKey();
    renderToneOptions();
    document.getElementById('tone').value=d.tone||'Magic';
    refreshGlassSelect(document.getElementById('tone'));
    renderRunPermissionOptions();
    document.getElementById('user-run-permission').value=d.run_permission||d.effective_run_permission||'full';
    refreshGlassSelect(document.getElementById('user-run-permission'));
    document.getElementById('user-model-alias').value=d.model_alias||'';
    userTimeZone=d.time_zone||'';
    document.getElementById('user-time-zone').value=userTimeZone;
    const uwit=document.getElementById('user-ws-idle-timeout');
    if(uwit){uwit.value=(d.ws_idle_timeout_minutes>0)?d.ws_idle_timeout_minutes:'';const dw=d.default_ws_idle_timeout_minutes||0;uwit.placeholder=dw?(t('user_ws_idle_timeout_inherit')+dw):''}
    const ums=document.getElementById('user-media-suffix');
    if(ums){ums.value=(d.media_proxy_suffixes||[]).join('\\n');const dg=(d.default_media_proxy_suffixes||[]).join(' ');ums.placeholder=dg?(t('user_media_suffix_inherit')+dg):''}
    document.getElementById('tool-prompt').value=d.tool_prompt||'';
    document.getElementById('sys-prompt').value=d.system_prompt||'';
    _userMeCache=d;
    startUserCountdown(d.account?.token_status?.seconds_remaining||0);
    renderAccountInfo(d);
    return true;
  }catch(e){return false}
}
function _userFallbackCopy(text){try{const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();const ok=document.execCommand('copy');document.body.removeChild(ta);return ok}catch(e){return false}}
function _userCopy(text,cb){if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(()=>cb(true),()=>cb(_userFallbackCopy(text)))}else{cb(_userFallbackCopy(text))}}
function _copyFeedback(btn,defKey){if(!btn)return;btn.textContent=t('key_copied');btn.style.color='#22c55e';clearTimeout(btn._copyTimer);btn._copyTimer=setTimeout(()=>{btn.textContent=t(defKey);btn.style.color=''},1200)}
function copyMyKey(btn){
  const k=getKey();if(!k)return;
  _userCopy(k,ok=>{if(ok)_copyFeedback(btn,'copy_key')});
}
function copyBaseUrl(btn){
  const v=document.getElementById('base-url')?.textContent||'';if(!v)return;
  _userCopy(v,ok=>{if(ok)_copyFeedback(btn,'copy_base')});
}
async function regenMyKey(btn){
  if(!await userDialog(t('regen_my_key'),t('confirm_regen_my_key'),t('confirm_btn')))return;
  if(btn){btn.disabled=true;btn.textContent=t('regen_running')}
  let ok=false;
  try{
    const r=await fetch('/user/regenerate-key',{method:'POST',headers:authHeaders()});
    if(r.ok){
      const d=await r.json();
      if(d.key){sessionStorage.setItem('user_api_key',d.key);const mk=document.getElementById('my-key');if(mk)mk.textContent=d.key;ok=true}
    }
  }catch(e){}
  if(btn){btn.textContent=ok?t('regen_done'):t('regen_failed');btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(()=>{btn.textContent=t('regen_my_key');btn.style.color='';btn.disabled=false},3000)}
}

function autoGrowTokenBox(){const el=document.getElementById('acct-token');if(!el)return;el.style.height='75px';el.style.height=Math.min(Math.max(el.scrollHeight,75),180)+'px'}
async function pushToken(btn){
  const token=document.getElementById('acct-token').value.trim();
  if(!token)return;
  if(btn){btn.disabled=true;btn.textContent=t('updating_token')}
  let ok=false;
  try{const r=await fetch('/user/account/token',{method:'POST',headers:authHeaders(),body:JSON.stringify({token:token})});ok=r.ok}catch(e){}
  if(ok)document.getElementById('acct-token').value='';
  if(btn){btn.textContent=ok?t('push_ok'):t('token_update_failed');btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(async()=>{btn.textContent=t('push_token_btn');btn.style.color='';btn.disabled=false;if(ok)await loadMe()},3000)}
}

async function saveAccountProxy(){
  const el=document.getElementById('user-proxy-url');if(!el)return;
  const msg=document.getElementById('user-proxy-msg');
  const show=k=>{if(!msg)return;msg.textContent=t(k);msg.style.opacity='1';setTimeout(()=>{msg.style.opacity='0'},2500)};
  try{
    const r=await fetch('/user/account/proxy',{method:'POST',headers:authHeaders(),body:JSON.stringify({proxy_url:el.value.trim()})});
    const d=await r.json().catch(()=>({}));
    // A rejected URL leaves the stored value untouched, so restore the input
    // from the response rather than leaving the bad text looking accepted.
    if(r.ok){el.value=d.proxy_url||'';show('user_proxy_saved')}
    else show('user_proxy_invalid');
  }catch(e){show('user_proxy_invalid')}
}
"""
