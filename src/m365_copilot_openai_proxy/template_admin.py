from __future__ import annotations

from .template_admin_accounts import _ADMIN_ACCOUNTS_JS
from .template_admin_copy import _ADMIN_COPY_JS
from .template_admin_dashboard import _ADMIN_DASHBOARD_JS
from .template_admin_dialogs import _ADMIN_DIALOGS_JS
from .template_admin_i18n import _ADMIN_I18N_JS
from .template_admin_keys import _ADMIN_KEYS_JS
from .template_admin_modeltest import _ADMIN_MODELTEST_JS
from .template_admin_sessions import _ADMIN_SESSIONS_JS
from .template_admin_settings_js import _ADMIN_SETTINGS_JS
from .template_admin_tables import _ADMIN_TABLES_JS
from .template_admin_css import _ADMIN_CSS
from .template_admin_shell import _ADMIN_SHELL_HTML
from .template_assets import _GLASS_SELECT_JS
from .template_pkce import _ADMIN_PKCE_JS

_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ciallo Ms-365 OpenAI Proxy</title>
<style>
""" + _ADMIN_CSS + """
</style>
</head>
<body>
""" + _ADMIN_SHELL_HTML + """

<script>
""" + _ADMIN_I18N_JS + """let lang=localStorage.getItem('lang')||'zh';
function t(key){const v=i18n[lang][key];return v==null?key:v}
function toggleLang(){
  lang=lang==='zh'?'en':'zh';
  localStorage.setItem('lang',lang);
  applyLang();
}
// ── i18n 重渲染约定（重构锚点）─────────────────────────────────────────────
// 切换语言只需重刷标签，不应产生网络请求。为此每个动态块拆成两段：
//   loadXxx()   —— 只负责 fetch + 写内存缓存（window.__xxx / 模块级变量）
//   renderXxx() —— 纯函数，只读缓存渲染 DOM，可被反复安全调用
// applyLang() 末尾只调 renderXxx()（零网络）。存量的 loadAccounts/loadKeys
// 暂用 localOnly 单函数式（load+render 合体，localOnly=true 时跳过 fetch），
// 属"能用但风格不统一"。目标形态：
//   1) 新增动态块一律用两段式；
//   2) 后续机会性把 accounts/keys 也拆成 load+render；
//   3) 各模块把自己的 renderXxx push 到 window.__i18nRerender=[]，
//      applyLang() 改为遍历执行，从根上杜绝"新增块漏翻译"。
// ────────────────────────────────────────────────────────────────────────
function applyLang(){
  document.body.setAttribute('data-lang',lang);
  document.documentElement.lang=lang==='zh'?'zh':'en';
  const btn=document.getElementById('lang-toggle');
  if(btn)btn.title=lang==='zh'?'切换到英文':'Switch to Chinese';
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const key=el.getAttribute('data-i18n');
    if(i18n[lang][key]!=null)el.textContent=i18n[lang][key];
  });
  const vt=document.getElementById('view-title');
  if(vt){const vk=vt.getAttribute('data-i18n');if(vk&&i18n[lang][vk]!=null)vt.textContent=i18n[lang][vk]}
  const out=document.getElementById('admin-logout');if(out)out.title=lang==='zh'?'退出管理后台':'Sign out admin';
  applyTheme();applyCollapse();
  // Language switch only relocalizes labels; re-render every dynamic block from
  // its in-memory cache instead of re-fetching (no network requests here).
  try{if(typeof loadAccounts==='function')loadAccounts(true)}catch(e){}
  try{if(typeof loadKeys==='function')loadKeys(true)}catch(e){}
  try{if(typeof renderDashboard==='function')renderDashboard()}catch(e){}
  try{if(typeof renderRuntimeSettings==='function')renderRuntimeSettings(__runtimeSettings)}catch(e){}
  try{if(typeof renderTone==='function')renderTone()}catch(e){}
  try{if(typeof renderCallLog==='function'&&window.__callLogItems)renderCallLog(window.__callLogItems)}catch(e){}
  try{if(typeof renderCapture==='function'&&window.__capItems)renderCapture(window.__capItems)}catch(e){}
  try{if(typeof renderMediaProxyEvents==='function'&&window.__mediaProxyEvents)renderMediaProxyEvents(window.__mediaProxyEvents)}catch(e){}
  try{if(typeof renderStatus==='function')renderStatus()}catch(e){}
  try{if(typeof renderSessions==='function'&&__sessions)renderSessions()}catch(e){}
  try{if(typeof renderModelTest==='function')renderModelTest()}catch(e){}
  try{if(typeof renderCacheStats==='function')renderCacheStats()}catch(e){}
}
applyLang();

// Theme (dark default / soft light), persisted.
function applyTheme(){
  const th=localStorage.getItem('admin_theme')||'dark';
  document.body.setAttribute('data-theme',th);
  const btn=document.getElementById('theme-toggle');
  if(btn){btn.innerHTML=th==='light'?'&#9728;':'&#127769;';btn.title=lang==='zh'?(th==='light'?'切换到暗色主题':'切换到亮色主题'):(th==='light'?'Switch to dark theme':'Switch to light theme')}
}
function toggleTheme(){
  const th=(localStorage.getItem('admin_theme')||'dark')==='light'?'dark':'light';
  localStorage.setItem('admin_theme',th);applyTheme();
}
applyTheme();

// Collapse sidebar, persisted.
function applyCollapse(){
  const c=localStorage.getItem('admin_collapsed')==='1';
  document.body.setAttribute('data-collapsed',c?'1':'0');
  const btn=document.getElementById('collapse-toggle');
  if(btn)btn.title=lang==='zh'?(c?'展开侧边栏':'收纳侧边栏'):(c?'Expand sidebar':'Collapse sidebar');
}
function toggleCollapse(){
  const tools=document.querySelector('.side-tools');
  if(tools)tools.classList.add('switching');
  setTimeout(()=>{
    localStorage.setItem('admin_collapsed',localStorage.getItem('admin_collapsed')==='1'?'0':'1');
    applyCollapse();
    setTimeout(()=>{if(tools)tools.classList.remove('switching')},40);
  },180);
}
applyCollapse();

// Log out of the admin console (clears the admin_auth cookie, then reloads to login).
async function adminLogout(){
  try{await fetch('/admin/logout',{method:'POST',credentials:'include'})}catch(e){}
  location.reload();
}

// GRA-style sidebar: local BUILD_ID + user-triggered update check (no auto GitHub).
// Rules: only after click + success show "已最新"; never treat "local only" as latest.
window.__adminUpdateInfo=null;
window.__adminUpdateLoading=false;
function renderAdminUpdateBar(){
  const chip=document.getElementById('side-build-chip');
  const btn=document.getElementById('side-update-btn');
  if(!chip||!btn)return;
  const u=window.__adminUpdateInfo;
  const loading=!!window.__adminUpdateLoading;
  const buildId=(u&&(u.buildId||u.current))||chip.getAttribute('data-build')||chip.textContent.trim()||'…';
  chip.textContent=buildId;
  chip.setAttribute('data-build',buildId);
  const hasUpdate=!!(u&&u.hasUpdate);
  const checkedOk=!!(u&&!u.error);
  btn.classList.toggle('loading',loading);
  btn.classList.toggle('has-update',checkedOk&&hasUpdate);
  btn.classList.toggle('is-latest',checkedOk&&!hasUpdate);
  btn.disabled=loading;
  btn.removeAttribute('title');
  // aria-label only (no visual hover tooltip)
  if(loading)btn.setAttribute('aria-label',lang==='zh'?'检查中':'Checking');
  else if(checkedOk&&hasUpdate)btn.setAttribute('aria-label',(lang==='zh'?'有更新 ':'Update ')+(u.latest||''));
  else if(checkedOk)btn.setAttribute('aria-label',lang==='zh'?'已最新':'Up to date');
  else btn.setAttribute('aria-label',lang==='zh'?'检查':'Check');
  if(checkedOk&&hasUpdate){
    btn.onclick=function(){if(u.htmlUrl)window.open(u.htmlUrl,'_blank','noopener')};
  }else{
    btn.onclick=function(){checkAdminUpdate()};
  }
  const repo=document.getElementById('side-repo-btn');
  if(repo)repo.title='GitHub';
}
async function loadAdminVersion(){
  // Local only — never calls update-check / GitHub.
  try{
    const r=await fetch('/admin/system/version',{credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    const id=d.buildId||d.current||d.version;
    const chip=document.getElementById('side-build-chip');
    if(chip&&id){chip.textContent=id;chip.setAttribute('data-build',id);chip.title='BUILD_ID '+id}
    const repo=document.getElementById('side-repo-btn');
    if(repo&&d.repoUrl)repo.href=d.repoUrl;
  }catch(e){}
  renderAdminUpdateBar();
}
async function checkAdminUpdate(){
  if(window.__adminUpdateLoading)return;
  window.__adminUpdateLoading=true;
  renderAdminUpdateBar();
  try{
    const r=await fetch('/admin/system/update-check',{credentials:'include'});
    const d=r.ok?await r.json():{error:'HTTP '+r.status,current:null,latest:null,hasUpdate:false};
    window.__adminUpdateInfo=d;
  }catch(e){
    window.__adminUpdateInfo={error:String(e),current:null,latest:null,hasUpdate:false};
  }finally{
    window.__adminUpdateLoading=false;
    renderAdminUpdateBar();
  }
}
loadAdminVersion();

// Debug: toggle whether the backend accepts pushed capture payloads.
async function loadCaptureToggle(){
  const gate=document.getElementById('capture-gate');
  try{const r=await fetch('/admin/capture-toggle',{credentials:'include'});if(r.ok){const d=await r.json();if(gate)gate.classList.toggle('on',!!d.enabled)}}catch(e){}
}
async function toggleCapture(on){
  try{await fetch('/admin/capture-toggle',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!!on})})}catch(e){}
  const gate=document.getElementById('capture-gate');if(gate)gate.classList.toggle('on',!!on);
}
async function toggleCaptureGate(){
  const gate=document.getElementById('capture-gate');
  const on=!(gate&&gate.classList.contains('on'));
  await toggleCapture(on);
}

// Sidebar view switching: pure front-end, no reload. Persists last view.
""" + _GLASS_SELECT_JS + """
function switchView(view){
  document.body.setAttribute('data-view',view);
  localStorage.setItem('admin_view',view);
  document.querySelectorAll('.nav-item').forEach(el=>{el.classList.toggle('active',el.getAttribute('data-nav')===view)});
  const vt=document.getElementById('view-title');
  const map={home:'nav_home',users:'nav_users',accounts:'nav_accounts',sessions:'nav_sessions',settings:'nav_settings',debug:'nav_debug'};
  const vk=map[view]||'nav_home';
  if(vt){vt.setAttribute('data-i18n',vk);vt.textContent=(i18n[lang]&&i18n[lang][vk])||vt.textContent}
  loadViewData(view);
}
function loadViewData(view){
  if(view==='home'){loadSummary();loadTrend();loadStats();return}
  if(view==='accounts'){loadAccounts();loadStats();return}
  if(view==='users'){loadKeys();loadAccounts();return}
  if(view==='sessions'){loadSessions();return}
  if(view==='settings'){loadTone();loadRuntimeSettings();loadToolPrompt();loadSystemPrompt();return}
  if(view==='debug'){loadCaptureToggle();loadRuntimeSettings();loadModelTest();loadCallLog();loadMediaProxyEvents();loadCapture()}
}
// The first switchView() call lives at the very bottom of this script, after the
// module blocks: view loaders read module-level `let`s (__accounts, __keys,
// __sessions), and calling one before those declarations are evaluated throws a
// TDZ ReferenceError that an async loader swallows into a silent rejection --
// the view then never renders on a reload.

function showInlineLogin(){location.replace('/admin')}
function toggleInlineLang(){localStorage.setItem('lang',localStorage.getItem('lang')==='zh'?'en':'zh');showInlineLogin()}

async function doInlineLogin(){
  const pw=document.getElementById('pw').value;
  const btns=document.querySelectorAll('button');
  const btn=btns.length>1?btns[btns.length-1]:btns[0];
  const msg=document.getElementById('ilm');
  const curLang=localStorage.getItem('lang')||'zh';
  const li18n={zh:{fail:'登录失败',neterr:'网络错误'},en:{fail:'Login failed',neterr:'Network error'}};
  const lt=k=>li18n[curLang][k]||k;
  btn.disabled=true;msg.style.display='none';
  try{
    const r=await fetch('/admin/login',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
    if(r.ok){location.reload();return}
    const d=await r.json();
    msg.style.display='block';msg.style.background='#450a0a';msg.style.color='#ef4444';msg.style.border='1px solid #991b1b';
    msg.textContent=d.error?.message||lt('fail');
  }catch(e){msg.style.display='block';msg.style.background='#450a0a';msg.style.color='#ef4444';msg.style.border='1px solid #991b1b';msg.textContent=lt('neterr')}
  finally{btn.disabled=false}
}

// Merged status: fetch token status + chromium login status, render in fixed order:
// 用户名 > 登录 > 有效 > 过期时间 > 剩余 > 自动刷新 > 标题 > 页面 > 错误
async function loadStatus(){
  try{
    const tr=await fetch('/admin/token/status',{credentials:'include'});
    if(tr.status===401){showInlineLogin();return}
    const d=await tr.json();
    // /admin/chromium/login-status is only registered when the shared admin CDP
    // is on. Skip it otherwise so we don't emit a 404 on every 60s poll.
    window.__adminCdpEnabled=!!d.admin_cdp_enabled;
    let c={};
    if(d.admin_cdp_enabled){
      try{const cr=await fetch('/admin/chromium/login-status',{credentials:'include'});if(cr&&cr.ok)c=await cr.json()}catch(e){c={}}
    }
    if(d.username)window.__m365_username=d.username;
    // Cache both payloads so language switch can re-render without re-fetching.
    window.__statusData=d;window.__statusChromium=c;
    renderStatus();
    startCountdown(d.seconds_remaining||0);
  }catch(e){
    const sc=document.getElementById('legacy-status-content');if(sc)sc.innerHTML='<span class="invalid">Failed to load</span>';
  }
}
// Pure render from cached token/chromium status; safe to call on language switch (no network).
function renderStatus(){
  const d=window.__statusData;if(!d)return;
  const c=window.__statusChromium||{};
  const v=d.valid;
  const cls=v?'valid':'invalid';
  const exp=d.expires_at?new Date(d.expires_at).toLocaleString():'N/A';
  const row=(label,val,vcls)=>'<div class="status-row"><span class="status-label">'+label+'</span><span class="status-value '+(vcls||'')+'">'+val+'</span></div>';
  const warnCls=(v&&d.seconds_remaining<600)?'warn':'';
  let html='';
  // 1. 用户名
  if(d.username)html+=row(t('username_label'),d.username,'valid');
  // 2. 登录 (chromium) — 状态显示为 是/否
  if(c.chromium_running===false){
    html+=row(t('login'),t('chromium_not_running'),'invalid');
  }else if(c.chromium_running){
    html+=row(t('login'),c.logged_in?t('status_yes'):t('status_no'),c.logged_in?'valid':'warn');
  }
  const logoutBtn=document.getElementById('btn-logout');
  if(logoutBtn)logoutBtn.style.display=c.logged_in?'inline-block':'none';
  // 3. 自动刷新（紧跟登录下方）
  html+=row(t('auto_refresh_label'),d.auto_refresh?t('status_yes'):t('status_no'),d.auto_refresh?'valid':'warn');
  // 4. 有效
  html+=row(t('valid'),v?t('status_yes'):t('status_no'),cls);
  // 5. 过期时间
  html+=row(t('expires'),exp,warnCls);
  // 6. 剩余
  html+=row(t('remaining'),'<span id="remaining-sec">'+fmtSec(d.seconds_remaining)+'</span>',warnCls);
  // 7. 标题 (chromium)
  if(c.title)html+='<div class="status-row"><span class="status-label">'+t('title')+'</span><span class="status-value" style="font-size:.75rem">'+c.title+'</span></div>';
  // 8. 页面 (chromium)
  if(c.url)html+='<div class="status-row"><span class="status-label">'+t('page')+'</span><span class="status-value" style="font-size:.75rem;word-break:break-all">'+c.url+'</span></div>';
  // 9. 错误
  if(d.error)html+=row(t('error'),d.error,'invalid');
  const sc=document.getElementById('legacy-status-content');if(sc)sc.innerHTML=html;
  updateRefreshBtn(d.auto_refresh);
}

function fmtSec(s){
  if(!s&&s!==0)return'N/A';
  const h=Math.floor(s/3600),m=Math.floor(s%3600/60),sec=s%60;
  return(h?h+'h ':'')+(m?m+'m ':'')+sec+'s';
}

function updateRefreshBtn(enabled){
  const btn=document.getElementById('btn-stop-refresh');
  if(enabled){
    btn.style.display='inline-block';
    btn.style.background='linear-gradient(135deg,#ef4444,#dc2626)';
    btn.textContent=t('btn_stop_refresh');
  }else{
    btn.style.display='inline-block';
    btn.style.background='linear-gradient(135deg,#22c55e,#059669)';
    btn.textContent=t('btn_start_refresh');
  }
}

async function toggleAutoRefresh(){
  const msg=document.getElementById('update-msg');
  const btn=document.getElementById('btn-stop-refresh');
  btn.disabled=true;msg.className='msg';msg.textContent='';
  try{
    const r=await fetch('/admin/token/auto-refresh-toggle',{method:'POST',credentials:'include'});
    const d=await r.json();
    if(r.ok){
      msg.className='msg ok';msg.textContent=d.auto_refresh?t('auto_refresh_started'):t('auto_refresh_stopped');
      updateRefreshBtn(d.auto_refresh);
      loadStatus();
    }else{
      msg.className='msg err';msg.textContent=d.error?.message||d.error||'Toggle failed';
    }
  }catch(e){msg.className='msg err';msg.textContent=(lang==='zh'?'网络错误：':'Network error: ')+e}
  finally{btn.disabled=false}
}

async function updateToken(){
  const input=document.getElementById('token-input').value.trim();
  const msg=document.getElementById('update-msg');
  const btn=document.getElementById('btn-update');
  if(!input){msg.className='msg err';msg.textContent=lang==='zh'?'请粘贴 Token':'Please paste a token';return}
  btn.disabled=true;msg.className='msg';msg.textContent='';
  try{
    const r=await fetch('/admin/token/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:input})});
    const d=await r.json();
    if(r.ok){
      msg.className='msg ok';msg.textContent=(lang==='zh'?'Token 已更新！剩余：':'Token updated! Remaining: ')+fmtSec(d.token_status?.seconds_remaining);
      document.getElementById('token-input').value='';
      loadStatus();
    }else{
      msg.className='msg err';msg.textContent=d.error?.message||d.error||(lang==='zh'?'更新失败':'Update failed');
    }
  }catch(e){msg.className='msg err';msg.textContent=(lang==='zh'?'网络错误：':'Network error: ')+e}
  finally{btn.disabled=false}
}

async function autoCapture(){
  const msg=document.getElementById('update-msg');
  const btn=document.getElementById('btn-auto');
  const upd=document.getElementById('btn-update');
  btn.disabled=true;upd.disabled=true;
  msg.className='msg';msg.textContent='';
  btn.textContent=t('capturing_btn');
  try{
    const r=await fetch('/admin/token/auto-capture',{method:'POST'});
    const d=await r.json();
    if(r.ok){
      msg.className='msg ok';msg.textContent=t('auto_captured')+fmtSec(d.token_status?.seconds_remaining);
      loadStatus();
    }else{
      msg.className='msg err';msg.textContent=d.error?.message||d.error||t('auto_capture_failed');
    }
  }catch(e){msg.className='msg err';msg.textContent=(lang==='zh'?'网络错误：':'Network error: ')+e}
  finally{btn.disabled=false;upd.disabled=false;btn.textContent=t('btn_auto_capture')}
}

async function checkLogin(){
  const msg=document.getElementById('update-msg');
  if(window.__adminCdpEnabled===false){msg.className='msg err';msg.textContent=t('check_failed');return}
  msg.className='msg';msg.textContent=t('check_login');
  await new Promise(r=>setTimeout(r,1500));
  try{
    const r=await fetch('/admin/chromium/login-status',{credentials:'include'});
    const d=await r.json();
    msg.className=d.logged_in?'msg ok':'msg err';
    msg.textContent=d.logged_in?t('login_ok'):t('login_not_ok');
  }catch(e){msg.className='msg err';msg.textContent=t('check_failed')+e}
}

async function logoutUser(){
  const msg=document.getElementById('update-msg');
  const btn=document.getElementById('btn-logout');
  btn.disabled=true;msg.className='msg';msg.textContent=t('logging_out');
  try{
    const r=await fetch('/admin/chromium/logout',{method:'POST',credentials:'include'});
    const d=await r.json();
    if(r.ok){
      msg.className='msg ok';msg.textContent=t('logout_ok')+(d.message?' — '+d.message:'');
      loadStatus();
    }else{
      msg.className='msg err';msg.textContent=d.error?.message||d.error||t('logout_failed');
    }
  }catch(e){msg.className='msg err';msg.textContent=(lang==='zh'?'网络错误：':'Network error: ')+e}
  finally{btn.disabled=false}
}

// ============================ Multi-tenant admin JS ============================
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
""" + _ADMIN_DIALOGS_JS + """
// ---- home dashboard: pure-SVG KPI + donut charts, no external deps ----
function kpiCard(label,val,color){
  return '<div style="background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;padding:.7rem .8rem">'
    +'<div style="font-size:1.5rem;font-weight:700;color:'+color+'">'+val+'</div>'
    +'<div style="font-size:.72rem;color:var(--muted);margin-top:.15rem">'+label+'</div></div>';
}
function donut(parts,centerLabel,centerVal){
  // parts: [{value,color,label}] — render a glassy SVG ring + legend.
  //
  // The rings used to spin and breathe via SMIL: each segment carried three
  // indefinitely-repeating <animate> elements, on stroke-dashoffset, opacity and
  // stroke-width. On an idle dashboard that alone was 105% of a CPU core in
  // style recalculation (~1460 recalcs/s), because SMIL drives the same
  // per-frame restyle as CSS but sits outside it — `animation:none` cannot
  // reach it and `document.getAnimations()` does not report it. `stroke-width`
  // made it worse by invalidating layout each frame too.
  //
  // The spin is back, rebuilt two ways: one CSS rotation of a wrapper <g>
  // instead of nine SMIL animations (0% recalc, down from 82%), stepped rather
  // than continuous (see .donut-spin for why steps, and the measurements). The
  // opacity/stroke-width breathing is not restored — it was the part nobody
  // asked for, and static values near the old midpoints keep the glow.
  const total=parts.reduce((s,p)=>s+p.value,0);
  const R=46,C=2*Math.PI*R;let off=0;
  const uid='d'+Math.random().toString(36).slice(2,8);
  // glass defs: soft drop shadow + glossy top highlight overlay
  let defs='<defs>'
    +'<filter id="'+uid+'sh" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000" flood-opacity="0.28"/></filter>'
    +'<filter id="'+uid+'halo" x="-55%" y="-55%" width="210%" height="210%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
    +'<linearGradient id="'+uid+'gl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.5"/><stop offset="0.5" stop-color="#fff" stop-opacity="0.08"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
    +'</defs>';
  let ring='',halo='';
  // base track ring (glass groove)
  ring+='<circle cx="60" cy="60" r="'+R+'" fill="none" stroke="var(--track)" stroke-width="16" opacity=".72"/>';
  if(total>0){
    const visibleParts=parts.filter(p=>p.value>0);
    visibleParts.forEach((p,i)=>{
      if(p.value<=0)return;
      const ratio=p.value/total,len=C*ratio;
      const outerR=R+5,innerR=R-8,outerC=2*Math.PI*outerR,innerC=2*Math.PI*innerR;
      const outerLen=outerC*ratio,innerLen=innerC*ratio,outerOff=outerC*(off/C),innerOff=innerC*(off/C);
      const ringCap=8.25,outerCap=10,innerCap=1.3;
      const ringLen=Math.max(0.01,len-ringCap*2),outerDrawLen=Math.max(0.01,outerLen-outerCap*2),innerDrawLen=Math.max(0.01,innerLen-innerCap*2);
      const ringStart=off+ringCap,outerStart=outerOff+outerCap,innerStart=innerOff+innerCap;
      ring+='<circle cx="60" cy="60" r="'+R+'" fill="none" stroke="'+p.color+'" stroke-width="15" stroke-linecap="round" stroke-dasharray="'+ringLen+' '+(C-ringLen)+'" stroke-dashoffset="'+(-ringStart)+'" transform="rotate(-90 60 60)" filter="url(#'+uid+'sh)" opacity="0.96"><animate attributeName="stroke-dasharray" from="0 '+C+'" to="'+ringLen+' '+(C-ringLen)+'" dur="0.55s" fill="freeze"/></circle>';
      halo+='<circle cx="60" cy="60" r="'+outerR+'" fill="none" stroke="'+p.color+'" stroke-width="14" stroke-linecap="round" stroke-dasharray="'+outerDrawLen+' '+(outerC-outerDrawLen)+'" stroke-dashoffset="'+(-outerStart)+'" transform="rotate(-90 60 60)" filter="url(#'+uid+'halo)" opacity="0.4"/>';
      halo+='<circle cx="60" cy="60" r="'+innerR+'" fill="none" stroke="'+p.color+'" stroke-width="1.8" stroke-linecap="round" stroke-dasharray="'+innerDrawLen+' '+(innerC-innerDrawLen)+'" stroke-dashoffset="'+(-innerStart)+'" transform="rotate(-90 60 60)" filter="url(#'+uid+'halo)" opacity="0.18"/>';
      off+=len;
    });
  }
  // glossy highlight arc over the top of the ring for a glass sheen — stays put,
  // it reads as a fixed reflection on the glass rather than part of the ring.
  const sheen='<circle cx="60" cy="60" r="'+(R+3.5)+'" fill="none" stroke="url(#'+uid+'gl)" stroke-width="4" stroke-linecap="round" stroke-dasharray="'+(C*0.4)+' '+C+'" transform="rotate(-108 60 60)" pointer-events="none"/>';
  // The rings spin as one group (see .donut-spin) instead of each arc animating
  // its own stroke-dashoffset. Same look — every arc moved at the same speed
  // through a full circumference, which is a rotation — at a fraction of the cost.
  let svg='<svg viewBox="0 0 120 120" style="width:120px;height:120px;flex-shrink:0;overflow:visible;filter:drop-shadow(0 0 14px rgba(96,242,255,.38)) drop-shadow(0 0 28px rgba(140,107,255,.28)) drop-shadow(0 0 42px rgba(255,94,219,.16))">'+defs+'<g class="donut-spin">'+halo+ring+'</g>'+sheen
    +'<text x="60" y="66" text-anchor="middle" fill="var(--strong)" font-size="24" font-weight="700">'+centerVal+'</text></svg>';
  let legend='<div style="display:flex;flex-direction:column;gap:.35rem;justify-content:center">';
  parts.forEach(p=>{legend+='<div style="display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--muted)"><span style="width:10px;height:10px;border-radius:3px;background:'+p.color+';display:inline-block;box-shadow:0 1px 2px rgba(0,0,0,.25),inset 0 1px 0 rgba(255,255,255,.4)"></span>'+p.label+' <b style="color:var(--strong)">'+p.value+'</b></div>'});
  legend+='</div>';
  return '<div style="display:flex;gap:.8rem;align-items:center">'+svg+legend+'</div>';
}
function renderDashboard(){
  const kpi=document.getElementById('dash-kpi');
  if(!kpi)return;
  const keys=__keys||[],accts=__accounts||[],s=__summary||{};
  const acctTotal=s.accounts_total??accts.length;
  const acctValid=s.accounts_valid??accts.filter(a=>a.token_status&&a.token_status.valid).length;
  const acctExpired=s.accounts_expired??(acctTotal-acctValid);
  const keyTotal=s.keys_total??keys.length;
  const keyEnabled=s.keys_enabled??keys.filter(k=>k.enabled).length;
  const keyDisabled=s.keys_disabled??(keyTotal-keyEnabled);
  const keyBound=s.keys_bound??keys.filter(k=>k.account_id).length;
  const keyUnbound=s.keys_unbound??(keyTotal-keyBound);
  kpi.innerHTML=kpiCard(t('dash_kpi_users'),keyTotal,'#38bdf8')
    +kpiCard(t('dash_kpi_accounts'),acctTotal,'#a78bfa')
    +kpiCard(t('dash_kpi_active_users'),keyEnabled,'#22c55e')
    +kpiCard(t('dash_kpi_valid_accts'),acctValid,'#22c55e')
    +kpiCard(t('dash_kpi_expired_accts'),acctExpired,acctExpired?'#f59e0b':'#64748b')
    +kpiCard(t('dash_kpi_unbound'),keyUnbound,keyUnbound?'#f59e0b':'#64748b');
  const da=document.getElementById('dash-donut-acct');
  if(da)da.innerHTML=donut([{value:acctValid,color:'#22c55e',label:t('dash_valid')},{value:acctExpired,color:'#ef4444',label:t('dash_expired')}],t('dash_kpi_accounts'),acctTotal);
  const dk=document.getElementById('dash-donut-key');
  if(dk)dk.innerHTML=donut([{value:keyEnabled,color:'#22c55e',label:t('btn_enable')},{value:keyDisabled,color:'#64748b',label:t('btn_disable')}],t('dash_kpi_users'),keyTotal);
  const db=document.getElementById('dash-donut-bind');
  if(db)db.innerHTML=donut([{value:keyBound,color:'#38bdf8',label:t('dash_bound')},{value:keyUnbound,color:'#f59e0b',label:t('unbound')}],t('dash_kpi_users'),keyTotal);
}
// ---- trend line chart (multi-series SVG) ----
""" + _ADMIN_DASHBOARD_JS + """
let __summary=null;
let __runtimeSettings={};
""" + _ADMIN_TABLES_JS + """
""" + _ADMIN_ACCOUNTS_JS + """
""" + _ADMIN_COPY_JS + """
""" + _ADMIN_KEYS_JS + """
""" + _ADMIN_SESSIONS_JS + """
""" + _ADMIN_MODELTEST_JS + """
""" + _ADMIN_PKCE_JS + """
function initDetailsCards(){
  document.querySelectorAll('.view-settings,.view-debug').forEach(card=>{
    const details=[...card.querySelectorAll('details')];
    if(!details.length){card.classList.add('no-details');return}
    const sync=()=>card.classList.toggle('details-open',details.some(d=>d.open));
    details.forEach(d=>d.addEventListener('toggle',sync));sync();
  });
}
function updateAccountCountdownText(){
  if(document.body.dataset.view!=='accounts'||!__accounts.length)return;
  document.querySelectorAll('[data-token-rem]').forEach(el=>{
    const a=__accounts.find(x=>x.id===el.getAttribute('data-token-rem'));
    if(!a)return;
    const st=liveTokenStatus(a.token_status||{});
    el.textContent=st.valid?' '+fmtHMS(st.seconds_remaining||0):'';
  });
}

initDetailsCards();
loadStatus();
initGlassSelect(document);
switchView(localStorage.getItem('admin_view')||'home');
setInterval(loadStatus,60000);
setInterval(()=>{if(document.body.dataset.view==='debug')loadCallLog()},5000);
setInterval(()=>{if(document.body.dataset.view==='debug')loadMediaProxyEvents()},5000);
setInterval(()=>{if(document.body.dataset.view==='debug')loadCapture()},5000);
setInterval(()=>{if(document.body.dataset.view==='home'){loadSummary();loadTrend()}},60000);
setInterval(()=>{if(document.body.dataset.view==='home')loadStats()},30000);
setInterval(()=>{if(document.body.dataset.view==='accounts')loadAccounts()},30000);
setInterval(updateAccountCountdownText,1000);

// Client-side countdown timer
let _countdownSec=0;
let _countdownTick=0;
function startCountdown(sec){_countdownSec=sec;_countdownTick=0}
function tickCountdown(){
  if(_countdownSec<=0)return;
  _countdownSec--;_countdownTick++;
  const el=document.getElementById('remaining-sec');
  if(el)el.textContent=fmtSec(_countdownSec);
}
setInterval(tickCountdown,1000);

window.__callTexts={};
function copyCallText(key){
  const txt=window.__callTexts[key];
  if(txt==null)return;
  navigator.clipboard.writeText(txt).then(()=>{
    const b=document.getElementById('copybtn-'+key);
    if(b){const o=b.textContent;b.textContent=t('copied');setTimeout(()=>{b.textContent=o},1200)}
  }).catch(()=>{});
}
window.__capTexts={};
function formatRawText(value){
  if(value==null)return '';
  if(typeof value==='object')return JSON.stringify(value,null,2);
  const text=String(value);
  try{return JSON.stringify(JSON.parse(text),null,2)}catch(e){return text}
}
function copyCaptureText(key){
  const txt=window.__capTexts[key];
  if(txt==null)return;
  navigator.clipboard.writeText(txt).then(()=>{
    const b=document.getElementById('capcopybtn-'+key);
    if(b){const o=b.textContent;b.textContent=t('copied');setTimeout(()=>{b.textContent=o},1200)}
  }).catch(()=>{});
}
function copyJsonToButton(value,buttonId){
  navigator.clipboard.writeText(JSON.stringify(value||[],null,2)).then(()=>{
    const b=document.getElementById(buttonId);
    if(b){const o=b.textContent;b.textContent=t('copied');setTimeout(()=>{b.textContent=o},1200)}
  }).catch(()=>{});
}
function copyAllCallLog(){copyJsonToButton(window.__callLogItems||[],'copy-call-log-all')}
function copyAllMediaProxyEvents(){copyJsonToButton(window.__mediaProxyEvents||[],'copy-media-proxy-all')}
function copyAllCapturePayloads(){copyJsonToButton(window.__capItems||[],'copy-capture-all')}
function copyMediaProxyTrace(traceId){
  const items=(window.__mediaProxyEvents||[]).filter(e=>e.trace_id===traceId);
  if(!items.length)return;
  navigator.clipboard.writeText(JSON.stringify(items,null,2)).then(()=>{
    document.querySelectorAll('[data-media-trace="'+CSS.escape(traceId)+'"]').forEach(b=>{const o=b.textContent;b.textContent=t('copied');setTimeout(()=>{b.textContent=o},1200)});
  }).catch(()=>{});
}
document.addEventListener('click',e=>{
  const btn=e.target.closest('[data-media-trace]');
  if(!btn)return;
  copyMediaProxyTrace(btn.getAttribute('data-media-trace')||'');
});
function _toneOptsSource(){
  // Debug view loads runtime-settings (not /admin/tone), so prefer its tone_options;
  // fall back to the picker's __toneOpts, then empty. __runtimeSettings is a
  // script-scope `let`, NOT window.__runtimeSettings — reading it off window
  // always missed, which left the debug view with unlabelled raw tone values.
  return (__runtimeSettings&&__runtimeSettings.tone_options)||window.__toneOpts||[];
}
function _toneLabel(v){
  const o=_toneOptsSource().find(x=>x.value===v);
  if(!o)return v;
  return (lang==='en'?(o.label_en||o.label):(o.label_zh||o.label))||o.label||v;
}
function updateCallLogFilterButtons(){
  const cur=window.__callLogFilter||'';
  document.querySelectorAll('[data-api-filter]').forEach(b=>b.classList.toggle('active',b.getAttribute('data-api-filter')===cur));
  const curTone=window.__callLogToneFilter||'';
  document.querySelectorAll('[data-tone-filter]').forEach(b=>b.classList.toggle('active',b.getAttribute('data-tone-filter')===curTone));
}
function renderToneFilterButtons(logs){
  const box=document.getElementById('tone-filter-group');
  if(!box)return;
  // Distinct tones present in the current (unfiltered) log, ordered by tone_options.
  const present=new Set((logs||[]).map(l=>l.tone).filter(Boolean));
  const ordered=[];
  _toneOptsSource().forEach(o=>{if(present.has(o.value)){ordered.push(o.value);present.delete(o.value)}});
  present.forEach(v=>ordered.push(v));
  const curTone=window.__callLogToneFilter||'';
  box.innerHTML=ordered.map(v=>'<button class="call-filter-btn tone'+(v===curTone?' active':'')+'" data-tone-filter="'+encodeURIComponent(v)+'" onclick="setCallLogToneFilter(\\''+encodeURIComponent(v)+'\\')">'+_toneLabel(v).replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</button>').join('');
}
function setCallLogFilter(api){
  window.__callLogFilter=window.__callLogFilter===api?'':api;
  updateCallLogFilterButtons();
  renderCallLog(window.__callLogItems||[]);
}
function setCallLogToneFilter(v){
  const tone=decodeURIComponent(v);
  window.__callLogToneFilter=window.__callLogToneFilter===tone?'':tone;
  updateCallLogFilterButtons();
  renderCallLog(window.__callLogItems||[]);
}
function renderCallLog(logs){
    const filter=window.__callLogFilter||'';
    const toneFilter=window.__callLogToneFilter||'';
    renderToneFilterButtons(logs);
    const filtered=logs.filter(l=>(!filter||(l.api||'chat').toLowerCase()===filter)&&(!toneFilter||l.tone===toneFilter));
    document.getElementById('call-log-count').textContent=(filter||toneFilter)?(filtered.length+'/'+logs.length):logs.length;
    const el=document.getElementById('call-log-content');
    if(!logs.length){el.innerHTML='<span style="color:var(--faint)">'+t('no_calls_yet')+'</span>';updateCallLogFilterButtons();return}
    updateCallLogFilterButtons();
    window.__callTexts={};
    let html='';
    if(!filtered.length)html='<span style="color:var(--faint)">'+t('no_calls_yet')+'</span>';
    for(let i=filtered.length-1;i>=0;i--){
      const l=filtered[i];
      const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      const tc=l.tools&&l.tools.length?l.tools.join(', '):'—';
      const api=(l.api||'chat').toLowerCase();
      const apiClass=api==='responses'?'responses':(api==='anthropic'?'anthropic':'chat');
      const apiLabel=apiClass==='responses'?'responses':(apiClass==='anthropic'?'anthropic':'chat');
      const apiBadge='<span class="api-badge '+apiClass+'">'+apiLabel+'</span>';
      const toneBadge=l.tone?'<span class="tone-badge" title="'+esc(l.tone)+'">'+esc(_toneLabel(l.tone))+'</span>':'';
      const tr=l.tool_calls_result&&l.tool_calls_result.length?
        '<span style="color:#22c55e">'+t('tool_calls_parsed')+': '+l.tool_calls_result.join(', ')+'</span>':'';
      const fullKey='f'+i;
      // Full single-record text: call info + repr + text
      const fullParts=[];
      fullParts.push('time: '+l.time);
      fullParts.push('api: '+apiLabel);
      if(l.tone)fullParts.push('tone: '+l.tone+' ('+_toneLabel(l.tone)+')');
      fullParts.push('mode: '+(l.stream?'stream':'sync'));
      fullParts.push('tools: '+tc);
      if(l.tool_calls_result&&l.tool_calls_result.length)fullParts.push('tool_calls_result: '+l.tool_calls_result.join(', '));
      if(l.response_len!=null)fullParts.push('resp: '+l.response_len+' chars');
      if(l.response_repr!=null)fullParts.push('repr:\\n'+l.response_repr);
      if(l.response_text!=null)fullParts.push('text:\\n'+l.response_text);
      window.__callTexts[fullKey]=fullParts.join('\\n');
      const copyFullBtn='<button class="copybtn" id="copybtn-'+fullKey+'" data-key="'+fullKey+'" style="padding:2px 8px;font-size:.65rem">'+t('copy_record')+'</button>';
      const rawView='<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--faint);font-size:.75rem;list-style:none">'+t('view_raw')+'</summary><pre style="white-space:pre-wrap;word-break:break-all;background:var(--inner);padding:6px;border-radius:6px;color:var(--muted);margin-top:2px;font-size:.7rem;max-height:260px;overflow:auto">'+esc(formatRawText(window.__callTexts[fullKey]))+'</pre></details>';
      html+='<div style="border-bottom:1px solid #1e293b;padding:6px 0">'+
        '<div style="display:flex;justify-content:space-between;align-items:center;color:var(--muted)">'+
        '<span style="display:flex;align-items:center;gap:6px">'+apiBadge+toneBadge+'<span>'+l.time+'</span></span><span style="display:flex;align-items:center;gap:6px"><span style="color:var(--faint)">'+(l.stream?'stream':'sync')+'</span>'+copyFullBtn+'</span></div>'+
        '<div style="color:var(--strong);margin-top:2px">tools: <span style="color:#38bdf8">'+tc+'</span></div>'+
        (l.incremental!=null?'<div style="color:var(--faint);margin-top:2px">incremental: <span style="color:'+(l.incremental?'#22c55e':'#f59e0b')+'">'+(l.incremental?'yes':'no')+'</span> &nbsp; turn: '+(l.turn_count==null?'-':l.turn_count)+'</div>':'')+
        (tr?'<div style="margin-top:2px">'+tr+'</div>':'')+
        (l.response_len?'<div style="color:var(--faint);margin-top:2px">resp: '+l.response_len+' chars</div>':'')+
        rawView+
        '</div>';
    }
    el.innerHTML=html;
    el.querySelectorAll('.copybtn').forEach(function(b){
      b.addEventListener('click',function(){copyCallText(b.getAttribute('data-key'))});
    });
}
async function loadCallLog(){
  try{
    const v=window.__callLogVersion;
    const url=v==null?'/admin/call-log':'/admin/call-log?version='+encodeURIComponent(v);
    const r=await fetch(url,{credentials:'include'});
    if(r.status===401){showInlineLogin();return}
    const d=await r.json();
    document.getElementById('call-log-count').textContent=d.count||0;
    if(d.unchanged)return;
    window.__callLogVersion=d.version;
    window.__callLogItems=d.logs||[];
    renderCallLog(window.__callLogItems);
  }catch(e){}
}
function renderCapture(ps){
    document.getElementById('capture-count').textContent=ps.length;
    const el=document.getElementById('capture-content');
    if(!ps.length){el.innerHTML='<span style="color:var(--faint)">'+t('no_capture_yet')+'</span>';return}
    const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    window.__capTexts={};
    let html='';
    for(let i=0;i<ps.length;i++){
      const p=ps[i];
      const opts=(p.optionsSets||[]).join(', ');
      const gpt=p.gptId&&Object.keys(p.gptId).length?JSON.stringify(p.gptId):'-';
      const capKey='c'+i;
      window.__capTexts[capKey]=JSON.stringify(p);
      const copyCapBtn='<button class="capcopybtn" id="capcopybtn-'+capKey+'" data-key="'+capKey+'" style="padding:2px 8px;font-size:.65rem">'+t('copy_record')+'</button>';
      html+='<div style="border-bottom:1px solid #1e293b;padding:6px 0;line-height:1.5">'+
        '<div style="display:flex;justify-content:space-between;align-items:center;color:#38bdf8"><span>'+esc(p.time)+' &nbsp; tone: <b>'+esc(p.tone||'-')+'</b> &nbsp; model: <b>'+esc(p.modelId||'-')+'</b></span>'+copyCapBtn+'</div>'+
        '<div style="color:var(--muted)">gptId: '+esc(gpt)+'</div>'+
        '<div style="color:var(--faint);word-break:break-all">optionsSets: '+esc(opts)+'</div>'+
        '<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--faint);font-size:.72rem;list-style:none">'+t('view_raw')+'</summary>'+
        '<pre style="white-space:pre-wrap;word-break:break-all;background:var(--inner);padding:6px;border-radius:6px;color:var(--muted);margin-top:2px;font-size:.7rem;max-height:240px;overflow:auto">'+esc(formatRawText(p.raw))+'</pre></details>'+
        '</div>';
    }
    el.innerHTML=html;
    el.querySelectorAll('.capcopybtn').forEach(function(b){
      b.addEventListener('click',function(){copyCaptureText(b.getAttribute('data-key'))});
    });
}
async function loadCapture(){
  try{
    const v=window.__capVersion;
    const url=v==null?'/admin/capture-payload':'/admin/capture-payload?version='+encodeURIComponent(v);
    const r=await fetch(url,{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    document.getElementById('capture-count').textContent=d.count||0;
    if(d.unchanged)return;
    window.__capVersion=d.version;
    window.__capItems=d.payloads||[];
    renderCapture(window.__capItems);
  }catch(e){}
}
function renderMediaProxyEvents(items){
  const count=document.getElementById('media-proxy-event-count');if(count)count.textContent=items.length;
  const el=document.getElementById('media-proxy-event-content');if(!el)return;
  const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  if(!items.length){el.innerHTML='<span style="color:var(--faint)">'+t('no_media_proxy_yet')+'</span>';return}
  el.innerHTML=items.slice().reverse().map(e=>{
    const ts=e.ts?new Date(e.ts*1000).toLocaleTimeString():'';
    const meta={...e};delete meta.ts;delete meta.trace_id;delete meta.phase;
    const trace=String(e.trace_id||'');
    const copyBtn='<button data-media-trace="'+esc(trace)+'" style="padding:2px 8px;font-size:.65rem">'+t('copy_record')+'</button>';
    return '<div style="border-bottom:1px solid #1e293b;padding:6px 0;line-height:1.5">'+
      '<div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap"><span style="color:#38bdf8">'+esc(ts)+'</span><b style="color:var(--strong)">'+esc(e.phase)+'</b><span style="color:var(--faint)">'+esc(trace)+'</span>'+copyBtn+'</div>'+
      '<pre style="white-space:pre-wrap;word-break:break-all;color:var(--muted);margin:4px 0 0">'+esc(JSON.stringify(meta,null,2))+'</pre></div>';
  }).join('');
}
async function loadMediaProxyEvents(){
  try{
    const v=window.__mediaProxyEventsVersion;
    const url=v==null?'/admin/media-proxy/events':'/admin/media-proxy/events?version='+encodeURIComponent(v);
    const r=await fetch(url,{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    const count=document.getElementById('media-proxy-event-count');if(count)count.textContent=d.count||0;
    if(d.unchanged)return;
    window.__mediaProxyEventsVersion=d.version;
    window.__mediaProxyEvents=d.events||[];
    renderMediaProxyEvents(window.__mediaProxyEvents);
  }catch(e){}
}
""" + _ADMIN_SETTINGS_JS + """

</script>
</body>
</html>"""
