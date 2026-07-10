from __future__ import annotations

_ADMIN_ACCOUNTS_JS = """let __accounts=[];
let __selectedAccountIds=new Set();
let __selectedAccount=localStorage.getItem('admin_sel_account')||'';
function renderSelectedStatus(){
  const card=document.getElementById('status-card');
  const box=document.getElementById('status-content');
  if(!card||!box)return;
  const a=__accounts.find(x=>x.id===__selectedAccount);
  if(!a){card.classList.add('hide-card');return}
  card.classList.remove('hide-card');
  const st=liveTokenStatus(a.token_status||{});
  const v=st.valid;
  const row=(label,val,vcls)=>'<div class="status-row"><span class="status-label">'+label+'</span><span class="status-value '+(vcls||'')+'">'+val+'</span></div>';
  let html='';
  html+=row(t('col_account'),esc(a.name||a.id),'valid');
  if(a.email)html+=row('Email',esc(a.email),'');
  html+=row(t('col_token'),v?t('valid_short'):t('invalid_short'),v?'valid':'invalid');
  const cv=liveCookieValid(a);
  html+=row(t('col_cookie'),cv?t('cookie_valid_short'):t('cookie_invalid_short'),cv?'valid':'warn');
  html+=row(t('col_refresh_mode'),a.token_source==='cdp'?(cv?t('refresh_auto'):t('refresh_unavailable')):t('refresh_manual'),a.token_source==='cdp'&&cv?'valid':'warn');
  html+=row(t('cookie_updated_label'),fmtTs(a.cookie_updated_at),'');
  html+=row(t('cookie_expires_label'),fmtTs(a.cookie_expires_at),'');
  if(st.error)html+=row(t('error'),esc(st.error),'invalid');
  box.innerHTML=html;
}
function selectAccount(id){
  __selectedAccount=(__selectedAccount===id)?'':id;
  localStorage.setItem('admin_sel_account',__selectedAccount);
  loadAccounts();
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
    if(!__accounts.length){box.innerHTML='<span style="color:var(--faint)">'+t('no_accounts')+'</span>';renderSelectedStatus();renderDashboard();return}
    const __pg=_slicePage(__accounts,'accounts');
    let h='<div class="tbl-tools"><button onclick="batchRefreshAccounts()" style="font-size:.72rem;padding:3px 8px;background:var(--chip)">'+t('batch_refresh')+'</button><button onclick="batchDeleteAccounts()" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('batch_delete')+'</button></div>'
      +'<div class="tbl-scroll accounts-table-scroll"><table class="admin-tbl accounts-table"><thead><tr style="color:var(--muted);text-align:left">'
      +'<th style="padding:.3rem;width:28px"><input type="checkbox" onchange="selectAllAccounts(this.checked)"></th><th style="padding:.3rem">'+t('col_name')+'</th><th style="padding:.3rem">'+t('col_token')+'</th><th style="padding:.3rem">'+t('col_cookie')+'</th><th style="padding:.3rem">'+t('col_refresh_mode')+'</th><th style="padding:.3rem;text-align:right">'+t('col_actions')+'</th></tr></thead><tbody>';
    __pg.items.forEach(a=>{
      const st=liveTokenStatus(a.token_status||{});
      const valid=st.valid;
      const rem=valid?(' '+fmtHMS(st.seconds_remaining||0)):'';
      const badge='<span style="width:134px;display:inline-flex;justify-content:center;padding:.15rem .6rem;border-radius:99px;font-size:.72rem;background:'+(valid?'rgba(63,185,112,.16)':'rgba(224,138,138,.16)')+';color:'+(valid?'#3fb970':'#e08a8a')+';border:1px solid '+(valid?'rgba(63,185,112,.4)':'rgba(224,138,138,.4)')+'">'+(valid?t('valid_short'):t('invalid_short'))+'<span data-token-rem="'+esc(a.id)+'">'+rem+'</span></span>';
      const cookieValid=liveCookieValid(a);
      const cookieBadge='<span style="width:76px;display:inline-flex;justify-content:center;padding:.15rem .6rem;border-radius:99px;font-size:.72rem;background:'+(cookieValid?'rgba(96,242,255,.15)':'rgba(148,163,184,.12)')+';color:'+(cookieValid?'#60f2ff':'#94a3b8')+';border:1px solid '+(cookieValid?'rgba(96,242,255,.4)':'rgba(148,163,184,.25)')+'">'+(cookieValid?t('cookie_valid_short'):t('cookie_invalid_short'))+'</span>';
      const cookieMeta='<div style="display:grid;grid-template-columns:76px auto;column-gap:.55rem;row-gap:2px;align-items:center;white-space:nowrap"><div>'+cookieBadge+'</div><div style="color:var(--faint);font-size:.68rem">'+t('cookie_updated_label')+': '+fmtTs(a.cookie_updated_at)+'</div><button class="cookie-refresh-btn" data-id="'+esc(a.id)+'" style="width:76px;font-size:.72rem;padding:3px 8px">'+t('btn_cookie_refresh')+'</button><div style="color:var(--faint);font-size:.68rem">'+t('cookie_expires_label')+': '+fmtTs(a.cookie_expires_at)+'</div></div>';
      const boundNames=Array.isArray(a.bound_names)?a.bound_names.filter(Boolean):[];
      const boundMain=boundNames[0]||a.name||'name';
      const boundTitle=boundNames.length?boundNames.join(String.fromCharCode(10)):boundMain;
      const boundMore=boundNames.length>1?' +'+(boundNames.length-1):'';
      const refreshMode=a.token_source==='cdp'?(cookieValid?t('refresh_auto'):t('refresh_unavailable')):t('refresh_manual');
      const refreshColor=a.token_source==='cdp'&&cookieValid?'#a78bfa':(a.token_source==='cdp'?'#f59e0b':'var(--faint)');
      const refreshBadge='<span style="padding:.15rem .6rem;border-radius:99px;font-size:.72rem;background:rgba(167,139,250,.12);color:'+refreshColor+';border:1px solid rgba(167,139,250,.28)">'+refreshMode+'</span>';
      const sel=a.id===__selectedAccount;
      h+='<tr class="acct-row '+(sel?'selected':'')+'" onclick="selectAccount(\\''+a.id+'\\')" style="border-top:1px solid var(--inner-border);cursor:pointer">'
        +'<td style="padding:.4rem"><input class="acct-check" type="checkbox" '+(__selectedAccountIds.has(a.id)?'checked':'')+' onclick="event.stopPropagation();toggleAccountSelected(\\''+a.id+'\\',this.checked)"></td>'
        +'<td style="padding:.4rem">'+(sel?'<span style="color:#38bdf8">&#9679; </span>':'')+'<span>'+esc(a.name||a.id)+(a.email?' <span style="color:var(--faint);font-size:.72rem">'+esc(a.email)+'</span>':'')+'</span><div title="'+esc(boundTitle)+'" style="color:var(--faint);font-size:.7rem">'+esc(boundMain)+esc(boundMore)+' id: '+esc(a.id)+' · '+t('bound_count_label')+': '+a.key_count+'</div></td>'
        +'<td style="padding:.4rem;white-space:nowrap"><div>'+badge+'</div><div class="acct-token-actions" style="margin-top:2px;display:flex;gap:4px;align-items:center;width:134px"><button onclick="event.stopPropagation();refreshAccount(\\''+a.id+'\\')" style="width:46px;font-size:.7rem;padding:3px 2px;white-space:nowrap">'+t('btn_token_refresh')+'</button><button onclick="event.stopPropagation();toggleAccountToken(\\''+a.id+'\\')" style="width:42px;font-size:.72rem;padding:3px 0;background:var(--chip)">'+t('btn_push_token')+'</button><button onclick="event.stopPropagation();clearAccountToken(\\''+a.id+'\\')" style="width:42px;font-size:.72rem;padding:3px 0;background:rgba(239,68,68,.18);color:#fecaca;border:1px solid rgba(239,68,68,.35)">'+t('btn_remove_token')+'</button></div></td>'
        +'<td style="padding:.4rem;white-space:nowrap">'+cookieMeta+'</td>'
        +'<td style="padding:.4rem">'+refreshBadge+'</td>'
        +'<td style="padding:.4rem;text-align:right;white-space:nowrap">' 
        +'<button onclick="event.stopPropagation();delAccount(\\''+a.id+'\\')" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('btn_delete')+'</button>'
        +'</td></tr>'
        +'<tr id="atok-'+a.id+'" style="display:none"><td colspan="6" style="padding:.7rem .9rem;vertical-align:middle;background:linear-gradient(90deg,rgba(96,242,255,.13),rgba(140,107,255,.11),rgba(255,94,219,.07));box-shadow:inset 3px 0 0 rgba(96,242,255,.72),inset 0 1px 0 rgba(255,255,255,.08),0 0 24px rgba(96,242,255,.1);backdrop-filter:blur(10px)" onclick="event.stopPropagation()">'
        +'<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">'
        +'<textarea id="atok-val-'+a.id+'" placeholder="'+t('acct_prompt_token')+'" style="flex:1;min-width:220px;height:34px;min-height:34px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none;resize:vertical"></textarea>'
        +'<button onclick="submitAccountToken(\\''+a.id+'\\')" style="font-size:.8rem;padding:6px 14px">'+t('kf_create')+'</button>'
        +'<button onclick="toggleAccountToken(\\''+a.id+'\\')" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>'
        +'</div><div id="atok-msg-'+a.id+'" style="font-size:.78rem;color:#ef4444;margin-top:.4rem"></div>'
        +'</td></tr>';
    });
    h+='</tbody></table></div>'+_pageFoot('accounts',__pg);
    box.innerHTML=h;
    box.querySelectorAll('.cookie-refresh-btn').forEach(btn=>btn.onclick=e=>{e.stopPropagation();refreshAccountCookie(btn.dataset.id)});
    initGlassSelect(box);
    renderSelectedStatus();
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
async function refreshAccount(id){
  try{
    const r=await fetch('/admin/accounts/'+id+'/refresh',{method:'POST',credentials:'include'});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)await adminAlert((d.error&&d.error.message)||'error');
    loadAccounts();
  }catch(e){}
}
async function refreshAccountCookie(id){
  try{
    const r=await fetch('/admin/accounts/'+id+'/cookie-refresh',{method:'POST',credentials:'include'});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)await adminAlert((d.error&&d.error.message)||'error');
    loadAccounts();
  }catch(e){}
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
async function batchRefreshAccounts(){const ids=[...__selectedAccountIds];if(!ids.length)return await adminAlert(t('batch_none'));for(const id of ids){await fetch('/admin/accounts/'+id+'/refresh',{method:'POST',credentials:'include'}).catch(()=>{})}loadAccounts()}
async function batchDeleteAccounts(){const ids=[...__selectedAccountIds];if(!ids.length)return await adminAlert(t('batch_none'));if(!await adminConfirm(t('batch_confirm_delete')))return;for(const id of ids){await fetch('/admin/accounts/'+id,{method:'DELETE',credentials:'include'}).catch(()=>{})}__selectedAccountIds.clear();loadAccounts();loadKeys()}"""
