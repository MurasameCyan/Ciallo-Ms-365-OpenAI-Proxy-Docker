from __future__ import annotations

_ADMIN_KEYS_JS = """let __keys=[];
let __selectedKeyIds=new Set();
async function loadKeys(){
  const box=document.getElementById('keys-content');
  if(!box)return;
  try{
    const r=await fetch('/admin/keys',{credentials:'include'});
    if(r.status===401){box.innerHTML='<span style="color:var(--faint)">'+t('loading')+'</span>';return}
    const d=await r.json();
    __keys=d.keys||[];
    if(!__keys.length){box.innerHTML='<span style="color:var(--faint)">'+t('no_keys')+'</span>';renderDashboard();return}
    const __pg=_slicePage(__keys,'keys');
    let h='<div class="tbl-tools"><button onclick="batchSetKeys(true)" style="font-size:.72rem;padding:3px 8px;background:#059669">'+t('batch_enable')+'</button><button onclick="batchSetKeys(false)" style="font-size:.72rem;padding:3px 8px;background:#b45309">'+t('batch_disable')+'</button><button onclick="batchDeleteKeys()" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('batch_delete')+'</button></div>'
      +'<div class="tbl-scroll"><table class="admin-tbl"><thead><tr style="color:var(--muted);text-align:left">'
      +'<th style="padding:.3rem;width:28px"><input type="checkbox" onchange="selectAllKeys(this.checked)"></th><th style="padding:.3rem">'+t('col_id')+'</th><th style="padding:.3rem">'+t('col_role')+'</th><th style="padding:.3rem">'+t('col_username')+'</th><th style="padding:.3rem">'+t('col_password')+'</th><th style="padding:.3rem">'+t('col_key')+'</th><th style="padding:.3rem">'+t('col_account')+'</th><th style="padding:.3rem;text-align:right">'+t('col_actions')+'</th></tr></thead><tbody>';
    __pg.items.forEach(k=>{
      const acc=k.account_id?((k.account_source==='manual'?('<span style="padding:.1rem .5rem;border-radius:99px;font-size:.72rem;background:rgba(96,242,255,.16);color:#60f2ff;border:1px solid rgba(96,242,255,.4)">'+t('acct_token_only')+'</span>'):esc(k.account_name||k.account_id))+'<div style="color:var(--faint);font-size:.7rem;margin-top:.15rem">'+esc(k.account_id)+'</div>'):('<span style="color:#f59e0b">'+t('unbound')+'</span>');
      const en=k.enabled;
      const uname=k.username?esc(k.username):('<span style="color:var(--faint)">'+t('no_login')+'</span>');
      const pwd=k.password?('<div class="kv-copy"><code style="font-size:.72rem;color:#818cf8">'+esc(k.password)+'</code><button onclick="copyPwd(\\''+k.id+'\\',this)" style="font-size:.68rem;background:var(--chip)">'+t('btn_copy')+'</button></div>'):('<span style="color:var(--faint)">'+t('not_set')+'</span>');
      const isAdmin=k.role==='admin';
      const roleBadge='<span class="role-badge '+(isAdmin?'admin':'user')+'" title="'+(isAdmin?'admin':'user')+'">'+(isAdmin?'A':'U')+'</span>';
      h+='<tr id="krow-'+k.id+'" style="border-top:1px solid #334155;'+(en?'':'opacity:.5')+'">'
        +'<td style="padding:.4rem"><input class="key-check" type="checkbox" '+(__selectedKeyIds.has(k.id)?'checked':'')+' onclick="toggleKeySelected(\\''+k.id+'\\',this.checked)"></td>'
        +'<td style="padding:.4rem"><code style="font-size:.72rem;color:var(--faint)">'+esc(k.id.replace(/^key_/, 'id_'))+'</code></td>'
        +'<td style="padding:.4rem">'+roleBadge+'</td>'
        +'<td style="padding:.4rem;font-size:.78rem">'+uname+'</td>'
        +'<td style="padding:.4rem;font-size:.78rem">'+pwd+'</td>'
        +'<td style="padding:.4rem"><div class="kv-copy"><code style="font-size:.72rem;color:#818cf8">'+esc(k.key.slice(0,10))+'…</code><button onclick="copyKey(\\''+k.id+'\\',this)" style="font-size:.68rem;background:var(--chip)">'+t('btn_copy')+'</button></div></td>'
        +'<td style="padding:.4rem">'+acc+'</td>'
        +'<td style="padding:.4rem;text-align:right;white-space:nowrap">'
        +'<button onclick="setKeyLogin(\\''+k.id+'\\')" style="font-size:.72rem;padding:3px 8px;background:var(--chip)">'+t('btn_set_login')+'</button> '
        +'<button onclick="regenKey(\\''+k.id+'\\')" style="font-size:.72rem;padding:3px 8px;background:var(--chip)">'+t('btn_regen_key')+'</button> '
        +'<button onclick="rebindKey(\\''+k.id+'\\')" style="font-size:.72rem;padding:3px 8px;background:var(--chip)">'+t('btn_rebind')+'</button> '
        +'<button onclick="toggleKey(\\''+k.id+'\\','+(en?'false':'true')+')" style="font-size:.72rem;padding:3px 8px;background:'+(en?'#b45309':'#059669')+'">'+(en?t('btn_disable'):t('btn_enable'))+'</button> '
        +'<button onclick="delKey(\\''+k.id+'\\')" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('btn_delete')+'</button>'
        +'</td></tr>'
        +'<tr id="kedit-'+k.id+'" style="display:none"><td colspan="8" style="padding:.7rem .9rem;vertical-align:middle;background:linear-gradient(90deg,rgba(96,242,255,.13),rgba(140,107,255,.11),rgba(255,94,219,.07));box-shadow:inset 3px 0 0 rgba(96,242,255,.72),inset 0 1px 0 rgba(255,255,255,.08),0 0 24px rgba(96,242,255,.1);backdrop-filter:blur(10px)">'
        +'<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">'
        +'<input id="ke-user-'+k.id+'" value="'+esc(k.username||'')+'" placeholder="'+t('kf_username_ph')+'" style="flex:1;min-width:140px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none">'
        +'<input id="ke-pass-'+k.id+'" type="text" placeholder="'+t('key_prompt_password_opt')+'" style="flex:1;min-width:140px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none">'
        +'<label class="role-toggle" title="role"><span class="role-a">A</span><input id="ke-role-'+k.id+'" type="checkbox" '+(k.role!=='admin'?'checked':'')+'><span class="role-track"></span><span class="role-u">U</span></label>'
        +'<button onclick="submitKeyLogin(\\''+k.id+'\\')" style="font-size:.8rem;padding:6px 14px">'+t('rebind_confirm')+'</button>'
        +'<button onclick="setKeyLogin(\\''+k.id+'\\')" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>'
        +'</div><div id="ke-msg-'+k.id+'" style="font-size:.78rem;color:#ef4444;margin-top:.4rem"></div>'
        +'</td></tr>';
    });
    h+='</tbody></table></div>'+_pageFoot('keys',__pg);
    box.innerHTML=h;
    initGlassSelect(box);
    renderDashboard();
  }catch(e){}
}
// Credential rules mirror the server-side regex (letters/digits for username;
// letters/digits + safe symbols for password) so users get instant feedback.
const _USER_RE=/^[A-Za-z0-9]{1,32}$/;
const _PASS_RE=/^[A-Za-z0-9!#$%&*+\\-.:=?@^_~]{6,64}$/;
async function badCred(username,password){
  if(username&&!_USER_RE.test(username)){await adminAlert(t('cred_bad_user'));return true}
  if(password&&!_PASS_RE.test(password)){await adminAlert(t('cred_bad_pass'));return true}
  return false;
}
async function addKey(){
  const name=prompt(t('key_prompt_name'));
  if(name===null)return;
  const username=prompt(t('key_prompt_username'))||'';
  const password=username?(prompt(t('key_prompt_password'))||''):'';
  if(await badCred(username,password))return;
  let account_id='';
  if(__accounts.length){account_id=prompt(t('rebind_prompt')+'\\n'+__accounts.map(a=>a.id+' = '+(a.name||'')).join('\\n'))||''}
  try{
    const r=await fetch('/admin/keys',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,account_id:account_id,username:username,password:password})});
    if(!r.ok){const d=await r.json().catch(()=>({}));await adminAlert((d.error&&d.error.message)||'error');return}
    loadKeys();loadAccounts();
  }catch(e){}
}
function toggleKeyForm(show){
  const f=document.getElementById('key-form');if(!f)return;
  const open=(show===undefined)?(f.style.display==='none'):show;
  f.style.display=open?'block':'none';
  if(open){
    const u=document.getElementById('kf-username'),p=document.getElementById('kf-password'),r=document.getElementById('kf-role'),m=document.getElementById('kf-msg');
    u.placeholder=t('kf_username_ph');p.placeholder=t('kf_password_ph');
    u.value='';p.value='';if(r)r.checked=true;m.textContent='';u.focus();
  }
}
async function submitKey(){
  const u=document.getElementById('kf-username'),p=document.getElementById('kf-password'),r=document.getElementById('kf-role'),m=document.getElementById('kf-msg');
  const username=(u.value||'').trim();
  const password=p.value||'';
  const role=(r&&r.checked)?'user':'admin';
  m.textContent='';
  if(username&&!_USER_RE.test(username)){m.textContent=t('cred_bad_user');return}
  if(password&&!_PASS_RE.test(password)){m.textContent=t('cred_bad_pass');return}
  try{
    const r=await fetch('/admin/keys',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:username,username:username,password:password,role:role})});
    if(!r.ok){const d=await r.json().catch(()=>({}));m.textContent=(d.error&&d.error.message)||'error';return}
    toggleKeyForm(false);
    loadKeys();
  }catch(e){m.textContent=t('network_error')}
}
function setKeyLogin(id){
  const row=document.getElementById('kedit-'+id);if(!row)return;
  const open=row.style.display==='none';
  row.style.display=open?'table-row':'none';
  if(open){const m=document.getElementById('ke-msg-'+id);if(m)m.textContent='';const p=document.getElementById('ke-pass-'+id);if(p)p.value='';const u=document.getElementById('ke-user-'+id);if(u)u.focus()}
}
async function submitKeyLogin(id){
  const u=document.getElementById('ke-user-'+id),p=document.getElementById('ke-pass-'+id),r=document.getElementById('ke-role-'+id),m=document.getElementById('ke-msg-'+id);
  const username=(u.value||'').trim();
  const password=p.value||'';
  const role=(r&&r.checked)?'user':'admin';
  m.textContent='';
  if(username&&!_USER_RE.test(username)){m.textContent=t('cred_bad_user');return}
  if(password&&!_PASS_RE.test(password)){m.textContent=t('cred_bad_pass');return}
  const body={username:username,role:role};
  if(password)body.password=password;
  try{
    const r=await fetch('/admin/keys/'+id,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok){const d=await r.json().catch(()=>({}));m.textContent=(d.error&&d.error.message)||'error';return}
    loadKeys();
  }catch(e){m.textContent=t('network_error')}
}
async function regenKey(id){
  if(!await adminConfirm(t('confirm_regen_key')))return;
  try{
    const r=await fetch('/admin/keys/'+id+'/regenerate',{method:'POST',credentials:'include'});
    if(!r.ok){const d=await r.json().catch(()=>({}));await adminAlert((d.error&&d.error.message)||'error');return}
    const d=await r.json();
    if(d.key&&d.key.key){try{await navigator.clipboard.writeText(d.key.key)}catch(e){}}
    await adminAlert(t('regen_ok'));
    loadKeys();
  }catch(e){}
}
function acctLabel(a){
  const name=a.name||a.id;
  return a.email?(name+' ('+a.email+')'):name;
}
function rebindKey(id){
  const k=__keys.find(x=>x.id===id);
  const cur=k?k.account_id:'';
  let opts='<option value="">'+t('rebind_unbind')+'</option>';
  __accounts.forEach(a=>{opts+='<option value="'+a.id+'"'+(a.id===cur?' selected':'')+'>'+esc(acctLabel(a))+'</option>'});
  const ov=document.createElement('div');
  ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.3);backdrop-filter:blur(18px) saturate(145%);-webkit-backdrop-filter:blur(18px) saturate(145%);display:flex;align-items:center;justify-content:center;z-index:1000';
  ov.innerHTML='<div class="flow-box" style="position:relative;background:rgba(15,23,42,.3);border:1px solid rgba(96,242,255,.28);border-radius:12px;padding:1.25rem;width:340px;max-width:90vw;box-shadow:0 24px 70px rgba(0,0,0,.36),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(22px) saturate(150%);-webkit-backdrop-filter:blur(22px) saturate(150%)">'
    +'<div style="font-weight:600;margin-bottom:.75rem">'+t('rebind_title')+'</div>'
    +'<div class="flow-box" style="position:relative;border-radius:8px"><select id="rebind-select" style="width:100%;padding:8px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong);font-size:.85rem;outline:none">'+opts+'</select></div>'
    +'<div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem">'
    +'<button id="rebind-cancel" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>'
    +'<button id="rebind-ok" style="font-size:.8rem;padding:6px 14px">'+t('rebind_confirm')+'</button>'
    +'</div></div>';
  document.body.appendChild(ov);
  initGlassSelect(ov);
  const close=()=>ov.remove();
  ov.addEventListener('click',e=>{if(e.target===ov)close()});
  ov.querySelector('#rebind-cancel').onclick=close;
  ov.querySelector('#rebind-ok').onclick=async()=>{
    const account_id=ov.querySelector('#rebind-select').value;
    try{
      const r=await fetch('/admin/keys/'+id,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id:account_id})});
      if(!r.ok){const d=await r.json().catch(()=>({}));await adminAlert((d.error&&d.error.message)||'error');return}
      close();loadKeys();loadAccounts();
    }catch(e){}
  };
}
async function toggleKey(id,enabled){
  try{await fetch('/admin/keys/'+id,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:enabled})});loadKeys()}catch(e){}
}
async function delKey(id){
  if(!await adminConfirm(t('confirm_del_key')))return;
  try{await fetch('/admin/keys/'+id,{method:'DELETE',credentials:'include'});loadKeys();loadAccounts()}catch(e){}
}
function toggleKeySelected(id,on){on?__selectedKeyIds.add(id):__selectedKeyIds.delete(id)}
function selectAllKeys(on){__selectedKeyIds=new Set(on?__keys.map(k=>k.id):[]);document.querySelectorAll('.key-check').forEach(cb=>{cb.checked=!!on})}
async function batchSetKeys(enabled){const ids=[...__selectedKeyIds];if(!ids.length)return await adminAlert(t('batch_none'));for(const id of ids){await fetch('/admin/keys/'+id,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:enabled})}).catch(()=>{})}loadKeys()}
async function batchDeleteKeys(){const ids=[...__selectedKeyIds];if(!ids.length)return await adminAlert(t('batch_none'));if(!await adminConfirm(t('batch_confirm_delete')))return;for(const id of ids){await fetch('/admin/keys/'+id,{method:'DELETE',credentials:'include'}).catch(()=>{})}__selectedKeyIds.clear();loadKeys();loadAccounts()}
"""
