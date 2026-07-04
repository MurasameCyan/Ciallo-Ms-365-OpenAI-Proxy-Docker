
const i18n={
  zh:{
    title:'Ciallo Ms-365 Copilot 代理 · 用户',
    login_title:'登录',login_hint:'输入管理员分配给你的用户名与密码，管理自己的对话模式、提示词与账户 Token。',
    qs_title:'快速使用指南',qs_body:'1. 安装 <a href="https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/main/get_token.user.js" target="_blank" rel="noopener" class="qs-link">油猴脚本</a> 并打开 <a href="https://m365.cloud.microsoft/chat" target="_blank" rel="noopener" class="qs-link">M365 Copilot</a>，随意发一条消息触发 WebSocket。<br>2. 在脚本面板点击「一键推送」或 手动「推送/复制 Token」，「推送 Cookie」均可。<br>3. 在账户卡片中复制 Base URL 与 API Key，填入 OpenAI 兼容客户端即可使用。',
    username_ph:'用户名',password_ph:'密码',login_btn:'登录',login_failed:'用户名或密码错误',network_error:'网络错误',
    account_title:'账户控制台',push_token_label:'推送 / 更新账户 Token',
    push_token_hint:'粘贴 access_token 值或完整 wss:// URL。若尚未绑定账户，将自动创建并绑定。',push_token_ph:'粘贴 access_token 值或完整 wss:// URL。若尚未绑定账户，将自动创建并绑定。\naccess_token / wss://substrate.office.com/...',
    push_token_btn:'更新 Token',updating_token:'更新中...',saved:'已保存',push_ok:'已更新',token_update_failed:'更新失败',
    mode_profile_title:'默认配置',user_tone_hint:'保存后仅影响当前用户，不再跟随全局模板变化。',call_params_title:'调用参数',manual_update_title:'手动更新',status_panel_title:'账户状态',status_account:'账户名',status_login:'登录',status_refresh:'自动刷新',status_valid:'有效',status_expire:'过期时间',status_remaining:'剩余',status_yes:'是',status_no:'否',status_unknown:'未知',
    tone_title:'对话模式',tool_prompt_title:'提示词增强',system_prompt_title:'系统提示词',prompt_card_title:'提示词',click_expand:'点击展开',
    tool_prompt_hint:'追加到工具调用提示词后的自定义指令，仅作用于你自己的 Key。留空则不追加。',
    save:'保存',reset:'恢复默认',
    sys_prompt_title:'系统提示词（高级）',
    sys_prompt_hint:'覆盖工具调用的基础系统提示词。改错会导致工具调用失效，仅供高级用户调试。留空则使用内置默认。',
    sys_prompt_reset_confirm:'确定要将系统提示词恢复为内置默认吗？当前自定义内容将被清空。',
    system_prompt_unlock:'解锁编辑（高级）',
    system_prompt_warn:'警告：系统级提示词定义了工具调用（tool_call）的格式与核心规则。修改不当会直接导致工具调用失效、模型无法读写文件。仅在你清楚自己在做什么时继续。\n\n确定要解锁编辑吗？',
    endpoints_title:'OpenAI 兼容接口',endpoints_hint:'在你的 OpenAI 兼容客户端里填入上面的 Base URL 和你的 API Key。',
    api_grp_public:'公共接口',api_grp_v1:'OpenAI 兼容接口',api_chat:'OpenAI 兼容对话',api_messages:'Anthropic 兼容消息',api_models:'模型列表',api_responses:'Responses 接口',api_healthz:'健康检查',
    copy_base:'复制',copy_key:'复制',key_copied:'已复制',kf_cancel:'取消',confirm_btn:'确认',regen_my_key:'重置我的 API Key',regen_my_key_hint:'重置后旧密钥立即失效，需要在客户端换成新密钥。账户绑定与历史会话不受影响。',confirm_regen_my_key:'确定重置你的 API Key 吗？旧密钥立即失效，你需要在客户端换成新密钥。',regen_done:'新密钥已生效',regen_running:'重置中...',regen_failed:'重置失败',
    logout:'登出 Microsoft',console_logout:'登出 控制台',change_password:'修改 登录密码',old_password:'当前密码',new_password:'新密码',password_changed:'密码已修改',password_change_failed:'修改失败',logging_out_ms:'登出中...',logout_ok_ms:'已登出',logout_failed_ms:'登出失败',unbind_account:'解绑 Microsoft',unbinding_ms:'解绑中...',unbind_ok_ms:'已解绑',unbind_failed_ms:'解绑失败',unbind_confirm:'确认解绑当前 Microsoft 账户？将同时清除该账户 Token 和 Cookie 状态，之后需要重新推送 Token 才能使用。',unbind_confirm_btn:'确认解绑',displaced_notice:'你的账户绑定已被同一 Microsoft 账号的其他用户推送接管，当前账户已解绑。请重新推送 Token 或联系管理员。',no_account:'尚未绑定账户，推送 Token 后将自动创建。',
    key_name:'名称',bound_account:'绑定账户',token_valid:'有效',token_invalid:'无效/缺失',remaining:'剩余',
  },
  en:{
    title:'Ciallo Ms-365 Copilot Proxy · User',
    login_title:'Login',login_hint:'Enter the username and password assigned by the admin to manage your own conversation mode, prompts and account token.',
    qs_title:'Quick Start',qs_body:'1. Install the <a href="https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/main/get_token.user.js" target="_blank" rel="noopener" class="qs-link">Tampermonkey script</a> and open <a href="https://m365.cloud.microsoft/chat" target="_blank" rel="noopener" class="qs-link">M365 Copilot</a>, then send any message to trigger the WebSocket.<br>2. Click "One-click Push" / "Push Token" in the script panel, or manually copy the access_token and paste it below to update.<br>3. Copy the Base URL and API Key from the account card into your OpenAI-compatible client.',
    username_ph:'Username',password_ph:'Password',login_btn:'Login',login_failed:'Wrong username or password',network_error:'Network error',
    account_title:'Account Console',push_token_label:'Push / update account token',
    push_token_hint:'Paste the access_token value or the full wss:// URL. If no account is bound yet, one will be created and bound automatically.',push_token_ph:'Paste the access_token value or the full wss:// URL. If no account is bound yet, one will be created and bound automatically.\naccess_token / wss://substrate.office.com/...',
    push_token_btn:'Update Token',updating_token:'Updating...',saved:'Saved',push_ok:'Updated',token_update_failed:'Update failed',
    mode_profile_title:'Default Config',user_tone_hint:'After saving, this only affects the current user and will no longer follow the global template.',call_params_title:'Call Parameters',manual_update_title:'Manual Update',status_panel_title:'Account Status',status_account:'Account',status_login:'Login',status_refresh:'Auto refresh',status_valid:'Valid',status_expire:'Expires at',status_remaining:'Remaining',status_yes:'Yes',status_no:'No',status_unknown:'Unknown',
    tone_title:'Conversation Mode',tool_prompt_title:'Prompt Enhancement',system_prompt_title:'System Prompt',prompt_card_title:'Prompts',click_expand:'Click to expand',
    tool_prompt_hint:'Custom instruction appended after the tool-call prompt, applies only to your own key. Leave empty to append nothing.',
    save:'Save',reset:'Restore default',
    sys_prompt_title:'System Prompt (Advanced)',
    sys_prompt_hint:'Overrides the base system prompt for tool calls (defines tool_call format and rules). A wrong edit will break tool calling. For advanced debugging only. Leave empty to use the built-in default.',
    sys_prompt_reset_confirm:'Restore the system prompt to the built-in default? Your current custom content will be cleared.',
    system_prompt_unlock:'Unlock editing (advanced)',
    system_prompt_warn:'WARNING: the system prompt defines the format and core rules of tool calls (tool_call). An incorrect edit will break tool calling and the model will be unable to read/write files. Continue only if you know what you are doing.\n\nUnlock editing?',
    endpoints_title:'OpenAI-compatible',endpoints_hint:'Point your OpenAI-compatible client at the Base URL above with your API key.',
    api_grp_public:'Public',api_grp_v1:'OpenAI-compatible',api_chat:'OpenAI-compatible chat',api_messages:'Anthropic-compatible messages',api_models:'Model list',api_responses:'Responses API',api_healthz:'Health check',
    copy_base:'Copy',copy_key:'Copy',key_copied:'Copied',kf_cancel:'Cancel',confirm_btn:'Confirm',regen_my_key:'Reset my API key',regen_my_key_hint:'After reset the old key stops working immediately; update your client with the new key. Account binding and session history are unaffected.',confirm_regen_my_key:'Reset your API key? The old key stops working immediately and you must update your client with the new one.',regen_done:'New key is now active',regen_running:'Resetting...',regen_failed:'Reset failed',
    logout:'Sign out of Microsoft',console_logout:'Sign out Console',change_password:'Change Login Password',old_password:'Current password',new_password:'New password',password_changed:'Password changed',password_change_failed:'Change failed',logging_out_ms:'Signing out...',logout_ok_ms:'Signed out',logout_failed_ms:'Sign out failed',unbind_account:'Unbind Microsoft',unbinding_ms:'Unbinding...',unbind_ok_ms:'Unbound',unbind_failed_ms:'Unbind failed',unbind_confirm:'Unbind the current Microsoft account? This will clear this account token and cookie state. You will need to push a token again before using it.',unbind_confirm_btn:'Unbind',displaced_notice:'Your account binding was taken over by another user pushing the same Microsoft account. This key is now unbound. Push your token again or contact the admin.',no_account:'No account bound yet. Pushing a token will create one automatically.',
    key_name:'Name',bound_account:'Bound account',token_valid:'Valid',token_invalid:'Invalid/Missing',remaining:'Remaining',
  }
};
let lang=localStorage.getItem('lang')||'zh';
let toneOptions=[];
let sysDefault='';
function t(k){return i18n[lang][k]||k}
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function getKey(){return sessionStorage.getItem('user_api_key')||''}
function authHeaders(){return {'Content-Type':'application/json','Authorization':'Bearer '+getKey()}}
function applyLang(){
  const btn=document.getElementById('lang-toggle');
  btn.innerHTML=lang==='zh'?'&#127760; EN':'&#127760; 中文';
  document.querySelectorAll('[data-i18n]').forEach(el=>{const k=el.getAttribute('data-i18n');if(i18n[lang][k])el.textContent=i18n[lang][k]});
  document.querySelectorAll('[data-i18n-ph]').forEach(el=>{const k=el.getAttribute('data-i18n-ph');if(i18n[lang][k])el.placeholder=i18n[lang][k]});
  document.querySelectorAll('[data-i18n-html]').forEach(el=>{const k=el.getAttribute('data-i18n-html');if(i18n[lang][k])el.innerHTML=i18n[lang][k]});
  renderToneOptions();
}
function toggleLang(){lang=lang==='zh'?'en':'zh';localStorage.setItem('lang',lang);applyLang()}
function initGlassSelect(root){
  const scope=root||document;
  scope.querySelectorAll('select').forEach(sel=>{
    if(sel.dataset.glassReady==='1')return;
    sel.dataset.glassReady='1';sel.classList.add('glass-native');
    const wrap=document.createElement('span');wrap.className='glass-select';
    if(sel.classList.contains('page-select'))wrap.style.minWidth='76px';
    if(sel.classList.contains('tone-select'))wrap.style.minWidth='180px';
    if(sel.id==='rebind-select')wrap.style.width='100%';
    const trigger=document.createElement('button');trigger.type='button';trigger.className='glass-select-trigger';
    const menu=document.createElement('div');menu.className='glass-select-menu';
    wrap.appendChild(trigger);wrap.appendChild(menu);sel.parentNode.insertBefore(wrap,sel.nextSibling);
    const close=()=>wrap.classList.remove('open');
    const render=()=>{
      const opt=sel.options[sel.selectedIndex];trigger.textContent=opt?opt.textContent:'';menu.innerHTML='';
      Array.from(sel.options).forEach(o=>{const b=document.createElement('button');b.type='button';b.className='glass-select-option'+(o.value===sel.value?' active':'');b.textContent=o.textContent;b.onclick=e=>{e.stopPropagation();sel.value=o.value;sel.dispatchEvent(new Event('change',{bubbles:true}));render();close()};menu.appendChild(b)});
    };
    sel._glassRender=render;
    trigger.onclick=e=>{e.stopPropagation();document.querySelectorAll('.glass-select.open').forEach(x=>{if(x!==wrap)x.classList.remove('open')});render();wrap.classList.toggle('open')};
    sel.addEventListener('change',render);render();
  });
}
function refreshGlassSelect(sel){
  if(!sel)return;
  if(sel.dataset.glassReady!=='1')initGlassSelect(sel.parentElement||document);
  if(typeof sel._glassRender==='function')sel._glassRender();
}
document.addEventListener('click',()=>document.querySelectorAll('.glass-select.open').forEach(x=>x.classList.remove('open')));
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.glass-select.open').forEach(x=>x.classList.remove('open'))});
function applyTheme(){const theme=localStorage.getItem('user_theme')||'dark';document.body.setAttribute('data-theme',theme);const b=document.getElementById('theme-toggle');if(b)b.innerHTML=theme==='light'?'&#9728;':'&#127769;'}
function toggleTheme(){localStorage.setItem('user_theme',(localStorage.getItem('user_theme')||'dark')==='dark'?'light':'dark');applyTheme()}
function renderToneOptions(){
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
}
function flash(id){const s=document.getElementById(id);if(!s)return;s.textContent=t('saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
async function doLogin(){
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
  if(btn){btn.textContent=ok?t('password_changed'):(msg||t('password_change_failed'));btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(()=>{btn.textContent=t('change_password');btn.style.color='';btn.disabled=false},2500)}
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
  try{return new Date(iso).toLocaleString()}catch(e){return iso}
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
function renderAccountStatus(d){
  const box=document.getElementById('account-status-panel');if(!box)return;
  const a=d.account||null,st=a?(a.token_status||{}):{};
  const valid=!!st.valid;
  const login=!!(a&&a.cookie_valid);
  const refresh=!!(a&&a.token_source==='cdp');
  const name=a?(a.name||a.email||a.id):t('status_unknown');
  const mark=(ok)=>'<span class="status-mark '+(ok?'ok':'bad')+'"></span>';
  box.innerHTML='<h3 style="margin:0;color:var(--strong);font-size:1rem;display:none">'+t('status_panel_title')+'</h3>'
    +'<div class="status-grid">'
    +'<div class="status-line status-first"><span>'+t('status_account')+'</span><b>'+esc(name)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_login')+'</span><b>'+mark(login)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_refresh')+'</span><b>'+mark(refresh)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_valid')+'</span><b>'+mark(valid)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_expire')+'</span><b>'+fmtExpire(st.expires_at)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_remaining')+'</span><b data-user-remaining>'+fmtRemaining(st.seconds_remaining)+'</b></div>'
    +'</div>';
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
    document.getElementById('tool-prompt').value=d.tool_prompt||'';
    document.getElementById('sys-prompt').value=d.system_prompt||'';
    let acc='';
    if(d.displaced){
      acc+='<div class="msg err" style="display:block;margin-bottom:.6rem">'+t('displaced_notice')+'</div>';
    }
    const keyIcon='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7.5" cy="14.5" r="3.5"></circle><path d="M10.2 12L21 1.2M15.5 6.7l2.8 2.8M18.2 4l2.6 2.6"></path></svg>';
    const doorIcon='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5.5A1.5 1.5 0 0 1 4 19.5v-15A1.5 1.5 0 0 1 5.5 3H9"></path><path d="M14 8l4 4-4 4"></path><path d="M18 12H8"></path><path d="M10 3h7a1.5 1.5 0 0 1 1.5 1.5v4"></path></svg>';
    const consoleActions='<span style="display:inline-flex;gap:.35rem"><button class="btn-ghost account-action" title="'+t('change_password')+'" onclick="changeLoginPassword(this)" style="width:32px;height:32px;padding:0;display:inline-flex;align-items:center;justify-content:center;color:#facc15;background:rgba(250,204,21,.14);border-color:rgba(250,204,21,.38)">'+keyIcon+'</button><button class="btn-ghost account-action" title="'+t('console_logout')+'" onclick="logoutConsole()" style="width:32px;height:32px;padding:0;display:inline-flex;align-items:center;justify-content:center;color:#38bdf8;background:rgba(56,189,248,.14);border-color:rgba(56,189,248,.38)">'+doorIcon+'</button></span>';
    const actionBox=document.getElementById('account-console-actions');if(actionBox)actionBox.innerHTML=consoleActions;
    if(d.account){
      const st=d.account.token_status||{};
      const valid=st.valid;
      const rem=valid?(' · '+t('remaining')+' <span data-user-remaining>'+fmtRemaining(st.seconds_remaining)+'</span>'):'';
      acc+='<div class="row" style="flex-wrap:wrap;gap:.4rem;align-items:center"><span class="pill">'+t('bound_account')+': '+(d.account.name||d.account.id)+'</span>'
        +'<span class="pill '+(valid?'ok':'bad')+'">'+(valid?t('token_valid'):t('token_invalid'))+rem+'</span></div>';
    }else{
      acc+='<div class="row" style="flex-wrap:wrap;gap:.4rem;align-items:center"><span class="pill">'+t('no_account')+'</span></div>';
    }
    acc+='<div style="margin-top:.6rem;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center"><button class="btn-ghost account-action" onclick="logout(this)">'+t('logout')+'</button><button class="btn-ghost account-action" onclick="unbindAccount(this)">'+t('unbind_account')+'</button></div>';
    document.getElementById('account-info').innerHTML=acc;
    renderAccountStatus(d);
    startUserCountdown(d.account?.token_status?.seconds_remaining||0);
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
async function saveTone(){
  const tone=document.getElementById('tone').value;
  try{await fetch('/user/tone',{method:'POST',headers:authHeaders(),body:JSON.stringify({tone:tone})});flash('tone-msg')}catch(e){}
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
applyTheme();
applyLang();
setInterval(tickUserCountdown,1000);
loadMe();
