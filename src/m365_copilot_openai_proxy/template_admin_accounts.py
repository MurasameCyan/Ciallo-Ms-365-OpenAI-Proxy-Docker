from __future__ import annotations

_ADMIN_ACCOUNTS_JS = """let __accounts=[];
let __selectedAccountIds=new Set();
let __refreshingAccountIds=new Set();
let __selectedAccount=localStorage.getItem('admin_sel_account')||'';
// A stored refresh token refreshes over plain HTTP, so it counts as automatic
// even for token_source==='manual' (that is what a PKCE sign-in leaves behind).
function acctRefresh(a,cookieValid){
  const auto=a.provider==='consumer'||!!a.has_refresh_token||(a.token_source==='cdp'&&cookieValid);
  return {auto:auto,available:auto||a.token_source==='cdp'};
}
function selectAccount(id){
  __selectedAccount=(__selectedAccount===id)?'':id;
  localStorage.setItem('admin_sel_account',__selectedAccount);
  loadAccounts();
}
// The accounts table is rebuilt wholesale -- by the 30s poll and by every
// mutation that ends in loadAccounts() -- while the token drawer's open state,
// its half-typed values and its result messages live only in that markup. So
// starting a PKCE sign-in and coming back from the Microsoft tab found the
// drawer collapsed, and pkceComplete's own reload ate the "signed in" line it
// had just written. Snapshot the transient state around the innerHTML swap once
// here rather than in each caller, because every caller loses it the same way.
const _DRAWER_TEXT_IDS=['atok-val-','pkce-cb-'];
const _DRAWER_MSG_IDS=['atok-msg-','pkce-msg-'];
function _grabDrawerState(box){
  const st={open:[],text:{},msg:{},focus:'',sel:null};
  __accounts.forEach(a=>{
    const row=document.getElementById('atok-'+a.id);
    if(row&&row.style.display!=='none')st.open.push(a.id);
    _DRAWER_TEXT_IDS.forEach(p=>{const el=document.getElementById(p+a.id);if(el&&el.value)st.text[p+a.id]=el.value});
    _DRAWER_MSG_IDS.forEach(p=>{const el=document.getElementById(p+a.id);if(el&&el.innerHTML)st.msg[p+a.id]=[el.innerHTML,el.style.color]});
  });
  const act=document.activeElement;
  if(act&&act.id&&box.contains&&box.contains(act)){st.focus=act.id;st.sel=[act.selectionStart,act.selectionEnd]}
  return st;
}
function _putDrawerState(st){
  st.open.forEach(id=>{const row=document.getElementById('atok-'+id);if(row)row.style.display='table-row'});
  Object.keys(st.text).forEach(id=>{const el=document.getElementById(id);if(el)el.value=st.text[id]});
  Object.keys(st.msg).forEach(id=>{const el=document.getElementById(id);if(el){el.innerHTML=st.msg[id][0];el.style.color=st.msg[id][1]}});
  const el=st.focus?document.getElementById(st.focus):null;
  if(!el)return;
  el.focus();
  // A caret only exists on text inputs; setSelectionRange throws elsewhere.
  if(st.sel&&st.sel[0]!=null)try{el.setSelectionRange(st.sel[0],st.sel[1])}catch(e){}
}
async function loadAccounts(localOnly=false){
  const box=document.getElementById('accounts-content');
  if(!box)return;
  try{
    if(!localOnly){
      const r=await fetch('/admin/accounts',{credentials:'include'});
      if(r.status===401){box.innerHTML='<span style="color:var(--faint)">'+t('loading')+'</span>';return}
      const d=await r.json();
      const loadedAt=Date.now()/1000;
      __accounts=(d.accounts||[]).map(a=>({...a,token_status:{...(a.token_status||{}),_loaded_at:loadedAt}}));
    }
    if(!__accounts.length){box.innerHTML='<span style="color:var(--faint)">'+t('no_accounts')+'</span>';renderDashboard();return}
    const __pg=_slicePage(__accounts,'accounts');
    let h='<div class="tbl-tools"><button onclick="batchRefreshAccounts()" style="font-size:.72rem;padding:3px 8px;background:var(--chip)">'+t('batch_refresh')+'</button><button onclick="batchDeleteAccounts()" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('batch_delete')+'</button></div>'
      +'<div class="tbl-scroll accounts-table-scroll"><table class="admin-tbl accounts-table"><thead><tr style="color:var(--muted);text-align:left">'
      +'<th style="padding:.3rem;width:28px"><input type="checkbox" onchange="selectAllAccounts(this.checked)"></th><th style="padding:.3rem">'+t('col_name')+'</th><th style="padding:.3rem">'+t('col_token')+'</th><th style="padding:.3rem">'+t('col_cookie')+'</th><th style="padding:.3rem">'+t('col_media')+'</th><th style="padding:.3rem">'+t('col_refresh_mode')+'</th><th class="acct-actions-head" style="padding:.3rem;text-align:right">'+t('col_actions')+'</th></tr></thead><tbody>';
    __pg.items.forEach(a=>{
      const st=liveTokenStatus(a.token_status||{});
      const valid=st.valid;
      const rem=valid&&st.expiry_known?(' '+fmtHMS(st.seconds_remaining||0)):'';
      const countdown=valid&&st.expiry_known?'<span data-token-rem="'+esc(a.id)+'">'+rem+'</span>':'';
      const badge='<span class="acct-token-status" style="padding:.15rem .25rem;border-radius:99px;font-size:.68rem;white-space:nowrap;background:'+(valid?'rgba(63,185,112,.16)':'rgba(224,138,138,.16)')+';color:'+(valid?'#3fb970':'#e08a8a')+';border:1px solid '+(valid?'rgba(63,185,112,.4)':'rgba(224,138,138,.4)')+'">'+(valid?t('valid_short'):t('invalid_short'))+countdown+'</span>';
      const cookieValid=liveCookieValid(a);
      const cookieTitle=esc(t('cookie_updated_label')+': '+fmtTs(a.cookie_updated_at))+'&#10;'+esc(t('cookie_expires_label')+': '+fmtTs(a.cookie_expires_at));
      const cookieBadge='<span class="cookie-status-tag"'+(cookieValid?' title="'+cookieTitle+'"':'')+' style="display:inline-flex;justify-content:center;padding:.15rem .6rem;border-radius:99px;font-size:.72rem;white-space:nowrap;background:'+(cookieValid?'rgba(96,242,255,.15)':'rgba(148,163,184,.12)')+';color:'+(cookieValid?'#60f2ff':'#94a3b8')+';border:1px solid '+(cookieValid?'rgba(96,242,255,.4)':'rgba(148,163,184,.25)')+'">'+(cookieValid?t('cookie_valid_short'):t('cookie_invalid_short'))+'</span>';
      const cookieMeta='<div class="cookie-meta"><div>'+cookieBadge+'</div><button class="cookie-refresh-btn" data-id="'+esc(a.id)+'" data-refresh-id="'+esc(a.id)+'" style="font-size:.7rem;padding:3px 5px">'+t('btn_cookie_refresh')+'</button></div>';
      const boundNames=Array.isArray(a.bound_names)?a.bound_names.filter(Boolean):[];
      const boundMain=boundNames[0]||a.name||'name';
      const boundTitle=boundNames.length?boundNames.join(String.fromCharCode(10)):boundMain;
      const boundMore=boundNames.length>1?' +'+(boundNames.length-1):'';
      const refreshAutomatic=acctRefresh(a,cookieValid).auto;
      const refreshAvailable=acctRefresh(a,cookieValid).available;
      const refreshMode=refreshAutomatic?t('refresh_auto'):(refreshAvailable?t('refresh_unavailable'):t('refresh_manual'));
      const refreshColor=refreshAutomatic?'#a78bfa':(refreshAvailable?'#f59e0b':'var(--faint)');
      const refreshBadge='<span class="refresh-mode-tag" style="width:63px;box-sizing:border-box;display:inline-flex;justify-content:center;padding:.15rem .25rem;border-radius:99px;font-size:.72rem;background:rgba(167,139,250,.12);color:'+refreshColor+';border:1px solid rgba(167,139,250,.28)">'+refreshMode+'</span>';
      const tokenCell='<div class="acct-token-control"><div class="acct-token-primary">'+badge+'</div><div class="acct-token-secondary"><button class="acct-token-refresh" data-refresh-id="'+esc(a.id)+'" onclick="event.stopPropagation();refreshAccount(\\''+a.id+'\\')">'+t('btn_token_refresh')+'</button><button class="acct-token-update" onclick="event.stopPropagation();toggleAccountToken(\\''+a.id+'\\')">'+t('btn_push_token')+'</button><button class="acct-token-remove" onclick="event.stopPropagation();clearAccountToken(\\''+a.id+'\\')">'+t('btn_remove_token')+'</button></div></div>';
      const mediaTag=(label,ok)=>'<span class="media-status-tag" style="display:inline-flex;align-items:center;justify-content:center;padding:.14rem .5rem;border-radius:99px;font-size:.68rem;background:'+(ok?'rgba(63,185,112,.16)':'rgba(148,163,184,.12)')+';color:'+(ok?'#3fb970':'#94a3b8')+';border:1px solid '+(ok?'rgba(63,185,112,.4)':'rgba(148,163,184,.25)')+'">'+label+'</span>';
      const mediaCell='<div class="media-status-list">'+mediaTag(t('media_image'),!!a.has_designer_auth)+mediaTag(t('media_attach'),!!a.has_media_auth)+'</div>';
      const sel=a.id===__selectedAccount;
      const provBadge=a.provider==='consumer'?'<span style="margin-left:.4rem;padding:.1rem .45rem;border-radius:99px;font-size:.66rem;vertical-align:middle;background:rgba(255,94,219,.14);color:#ff5edb;border:1px solid rgba(255,94,219,.4)">'+t('provider_consumer')+'</span>':'';
      // Only while the window upstream named is still open: it clears itself, so
      // the row never carries a stale quota claim. The exact time is the hover
      // title, matching how the cookie timestamps are surfaced.
      const throttledUntil=Number(a.throttled_until||0);
      const throttledBadge=(throttledUntil*1000>Date.now())?'<span class="acct-throttled-tag" title="'+esc(t('throttled_until_label')+': '+fmtTs(throttledUntil))+'" style="margin-left:.4rem;padding:.1rem .45rem;border-radius:99px;font-size:.66rem;vertical-align:middle;background:rgba(167,139,250,.14);color:#a78bfa;border:1px solid rgba(167,139,250,.4)">'+t('throttled_short')+'</span>':'';
      h+='<tr class="acct-row '+(sel?'selected':'')+'" onclick="selectAccount(\\''+a.id+'\\')" style="border-top:1px solid var(--inner-border);cursor:pointer">'
        +'<td style="padding:.4rem"><input class="acct-check" type="checkbox" '+(__selectedAccountIds.has(a.id)?'checked':'')+' onclick="event.stopPropagation();toggleAccountSelected(\\''+a.id+'\\',this.checked)"></td>'
        +'<td style="padding:.4rem">'+(sel?'<span style="color:#38bdf8">&#9679; </span>':'')+'<span>'+esc(a.name||a.id)+(a.email?' <span style="color:var(--faint);font-size:.72rem">'+esc(a.email)+'</span>':'')+'</span>'+provBadge+throttledBadge+'<div title="'+esc(boundTitle)+'" style="color:var(--faint);font-size:.7rem">'+esc(boundMain)+esc(boundMore)+' id: '+esc(a.id)+' · '+t('bound_count_label')+': '+a.key_count+'</div></td>'
        +'<td style="padding:.4rem;white-space:nowrap">'+tokenCell+'</td>'
        +'<td style="padding:.4rem;white-space:nowrap">'+cookieMeta+'</td>'
        +'<td style="padding:.4rem">'+mediaCell+'</td>'
        +'<td style="padding:.4rem">'+refreshBadge+'</td>'
        +'<td class="acct-actions-cell" style="padding:.4rem;text-align:right;white-space:nowrap">'
        +'<button class="acct-delete-btn" onclick="event.stopPropagation();delAccount(\\''+a.id+'\\')" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('btn_delete')+'</button>'
        +'</td></tr>'
        +'<tr id="atok-'+a.id+'" style="display:none"><td colspan="7" style="padding:.7rem .9rem;vertical-align:middle;background:linear-gradient(90deg,rgba(96,242,255,.13),rgba(140,107,255,.11),rgba(255,94,219,.07));box-shadow:inset 3px 0 0 rgba(96,242,255,.72),inset 0 1px 0 rgba(255,255,255,.08),0 0 24px rgba(96,242,255,.1);backdrop-filter:blur(10px)" onclick="event.stopPropagation()">'
        +'<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">'
        +'<textarea id="atok-val-'+a.id+'" placeholder="'+t('acct_prompt_token')+'" style="flex:1;min-width:220px;height:34px;min-height:34px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none;resize:vertical"></textarea>'
        +'<button onclick="submitAccountToken(\\''+a.id+'\\')" style="font-size:.8rem;padding:6px 14px">'+t('kf_create')+'</button>'
        +'<button onclick="toggleAccountToken(\\''+a.id+'\\')" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>'
        +'</div><div id="atok-msg-'+a.id+'" style="font-size:.78rem;color:#ef4444;margin-top:.4rem"></div>'
        +_pkcePanel(a)
        +_personalizationPanel(a)
        +'</td></tr>';
    });
    h+='</tbody></table></div>'+_pageFoot('accounts',__pg);
    const drawers=_grabDrawerState(box);
    box.innerHTML=h;
    _putDrawerState(drawers);
    box.querySelectorAll('.cookie-refresh-btn').forEach(btn=>btn.onclick=e=>{e.stopPropagation();refreshAccountCookie(btn.dataset.id)});
    __refreshingAccountIds.forEach(id=>setAccountRefreshBusy(id,true));
    initGlassSelect(box);
    renderDashboard();
  }catch(e){}
}
function toggleAccountForm(show){
  const f=document.getElementById('acc-form');if(!f)return;
  const open=(show===undefined)?(f.style.display==='none'):show;
  f.style.display=open?'block':'none';
  if(open){
    const n=document.getElementById('af-name'),tk=document.getElementById('af-token'),m=document.getElementById('af-msg');
    n.placeholder=t('acct_prompt_name');tk.placeholder=t('acct_prompt_token');
    n.value='';tk.value='';m.textContent='';n.focus();
  }
}
async function submitAccount(){
  const n=document.getElementById('af-name'),tk=document.getElementById('af-token'),m=document.getElementById('af-msg');
  const name=(n.value||'').trim();
  const token=(tk.value||'').trim();
  m.textContent='';
  try{
    const r=await fetch('/admin/accounts',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,token:token})});
    if(!r.ok){const d=await r.json().catch(()=>({}));m.textContent=(d.error&&d.error.message)||'error';return}
    toggleAccountForm(false);
    loadAccounts();loadKeys();
  }catch(e){m.textContent=t('network_error')}
}
function refreshResponseError(r,d,fallback){
  const detail=d&&d.error;
  const message=(detail&&typeof detail==='object'&&detail.message)||(typeof detail==='string'?detail:'');
  return message||fallback+' (HTTP '+r.status+')';
}
async function requestAccountRefresh(id){
  const r=await fetch('/admin/accounts/'+id+'/refresh',{method:'POST',credentials:'include'});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)return refreshResponseError(r,d,t('auto_capture_failed'));
  return d.refreshed===true?'':t('auto_capture_failed');
}
function setAccountRefreshBusy(id,busy){
  document.querySelectorAll('[data-refresh-id]').forEach(btn=>{
    if(btn.dataset.refreshId!==id)return;
    if(busy){
      if(!btn.dataset.refreshLabel)btn.dataset.refreshLabel=btn.textContent;
      btn.disabled=true;btn.textContent=t('refreshing');
    }else{
      btn.disabled=false;
      if(btn.dataset.refreshLabel){btn.textContent=btn.dataset.refreshLabel;delete btn.dataset.refreshLabel}
    }
  });
}
function beginAccountRefresh(id){
  if(__refreshingAccountIds.has(id))return false;
  __refreshingAccountIds.add(id);setAccountRefreshBusy(id,true);return true;
}
function endAccountRefresh(id,reload=true){
  __refreshingAccountIds.delete(id);setAccountRefreshBusy(id,false);if(reload)loadAccounts();
}
async function refreshAccount(id){
  if(!beginAccountRefresh(id))return;
  try{
    const message=await requestAccountRefresh(id);
    await adminAlert(message||t('refresh_ok'));
  }catch(e){await adminAlert(t('network_error'))}
  finally{endAccountRefresh(id)}
}
async function refreshAccountCookie(id){
  if(!beginAccountRefresh(id))return;
  try{
    const r=await fetch('/admin/accounts/'+id+'/cookie-refresh',{method:'POST',credentials:'include'});
    const d=await r.json().catch(()=>({}));
    const fallback=t('btn_cookie_refresh')+': '+t('cookie_invalid_short');
    if(!r.ok)await adminAlert(refreshResponseError(r,d,fallback));
    else if(d.cookie_valid!==true)await adminAlert(fallback);
    else await adminAlert(t('refresh_ok'));
  }catch(e){await adminAlert(t('network_error'))}
  finally{endAccountRefresh(id)}
}
async function clearAccountToken(id){
  if(!await adminConfirm(t('confirm_remove_token')))return;
  try{
    const r=await fetch('/admin/accounts/'+id+'/token/clear',{method:'POST',credentials:'include'});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)await adminAlert((d.error&&d.error.message)||'error');
    loadAccounts();
  }catch(e){}
}
function toggleAccountToken(id){
  const row=document.getElementById('atok-'+id);if(!row)return;
  const open=row.style.display==='none';
  row.style.display=open?'table-row':'none';
  if(open){const m=document.getElementById('atok-msg-'+id);if(m)m.textContent='';const v=document.getElementById('atok-val-'+id);if(v){v.value='';v.focus()}}
  // The personalization flags are one upstream call per read, so they are fetched
  // when the drawer opens rather than for every row of the table. No panel means
  // a consumer account, which has no such endpoint to call.
  if(open&&document.getElementById('pers-'+id))loadPersonalization(id);
}
async function submitAccountToken(id){
  const v=document.getElementById('atok-val-'+id),m=document.getElementById('atok-msg-'+id);
  const token=(v&&v.value||'').trim();
  if(m)m.textContent='';
  if(!token){if(m)m.textContent=t('acct_prompt_token');return}
  try{
    const r=await fetch('/admin/accounts/'+id+'/token',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token})});
    if(!r.ok){const d=await r.json().catch(()=>({}));if(m)m.textContent=(d.error&&d.error.message)||'error';return}
    toggleAccountToken(id);
    loadAccounts();
  }catch(e){if(m)m.textContent=t('network_error')}
}
async function delAccount(id){
  if(!await adminConfirm(t('confirm_del_account')))return;
  try{await fetch('/admin/accounts/'+id,{method:'DELETE',credentials:'include'});loadAccounts();loadKeys()}catch(e){}
}
function toggleAccountSelected(id,on){on?__selectedAccountIds.add(id):__selectedAccountIds.delete(id)}
function selectAllAccounts(on){__selectedAccountIds=new Set(on?__accounts.map(a=>a.id):[]);document.querySelectorAll('.acct-check').forEach(cb=>{cb.checked=!!on})}
async function batchRefreshAccounts(){const ids=[...__selectedAccountIds];if(!ids.length)return await adminAlert(t('batch_none'));for(const id of ids){if(!beginAccountRefresh(id))continue;let stop=false;try{const message=await requestAccountRefresh(id);if(message){await adminAlert(message);stop=true}}catch(e){await adminAlert(t('network_error'));stop=true}finally{endAccountRefresh(id,false)}if(stop)break}loadAccounts()}
async function batchDeleteAccounts(){const ids=[...__selectedAccountIds];if(!ids.length)return await adminAlert(t('batch_none'));if(!await adminConfirm(t('batch_confirm_delete')))return;for(const id of ids){await fetch('/admin/accounts/'+id,{method:'DELETE',credentials:'include'}).catch(()=>{})}__selectedAccountIds.clear();loadAccounts();loadKeys()}"""
