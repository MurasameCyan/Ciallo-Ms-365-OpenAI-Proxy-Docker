from __future__ import annotations

# Session management view: local session bindings merged with the M365 cloud
# conversation history (/admin/sessions). Two-stage per the template convention:
# loadSessions() fetches into __sessions, renderSessions() only reads it, so a
# language switch re-renders without a network round trip.
_ADMIN_SESSIONS_JS = """let __sessions=null;
let __sessPinned=new Set();
// A pin is a local store key, or a conversation id for a cloud-only row --
// /admin/sessions/cleanup accepts both shapes as keep_ids.
function _sessPin(row){return row.store_key||row.conversation_id||''}
// The pin arrives URI-encoded because it is spliced into an inline onclick.
function toggleSessPinned(encoded,on){
  const pin=decodeURIComponent(encoded);
  on?__sessPinned.add(pin):__sessPinned.delete(pin);
}
function _sessWhen(sec){return sec?new Date(sec*1000).toLocaleString():'-'}
function _sessOwner(row){
  if(row.source==='cloud')return '<span style="color:var(--faint)">'+t('sess_no_owner')+'</span>';
  return esc(row.username||row.key_name||row.key_id||row.tenant||'-');
}
function _sessSrcBadge(src){
  const color=src==='both'?'#22c55e':(src==='cloud'?'#a78bfa':'#38bdf8');
  return '<span style="padding:.1rem .5rem;border-radius:99px;font-size:.7rem;white-space:nowrap;border:1px solid '+color+'66;background:'+color+'22;color:'+color+'">'+t('sess_src_'+src)+'</span>';
}
function renderSessionFilter(){
  const sel=document.getElementById('sess-key-filter');
  if(!sel)return;
  const cur=sel.value||'all';
  let opts='<option value="all">'+t('sess_all_users')+'</option>';
  (__keys||[]).forEach(k=>{opts+='<option value="'+k.id+'">'+esc(k.username||k.name||k.id)+'</option>'});
  sel.innerHTML=opts;
  sel.value=cur;
  if(!sel.value)sel.value='all';
  refreshGlassSelect(sel);
}
function renderSessions(){
  const box=document.getElementById('sessions-content');
  if(!box)return;
  renderSessionFilter();
  const ttl=document.getElementById('sess-ttl');if(ttl)ttl.placeholder=t('sess_ttl_ph');
  const keep=document.getElementById('sess-keep');if(keep)keep.placeholder=t('sess_keep_ph');
  const d=__sessions;
  const warn=document.getElementById('sessions-warn');
  if(warn){
    const notes=(d&&d.warnings)||[];
    warn.classList.toggle('hide-card',!notes.length);
    // Details live in the hover tooltip, not in a banner: one line per account
    // would be a wall of text on a pool with many consumer accounts.
    warn.title=notes.length?(t('sess_cloud_warn')+'\\n'+notes.join('\\n')):'';
  }
  if(!d){box.innerHTML='<span style="color:var(--faint)">'+t('loading')+'</span>';return}
  const rows=d.data||[];
  if(!rows.length){box.innerHTML='<span style="color:var(--faint)">'+t('sess_none')+'</span>';return}
  let h='<div style="font-size:.78rem;color:var(--faint);margin-bottom:.4rem">'+t('sess_count').replace('{count}',rows.length)+(d.cloud?'':' · '+t('sess_local_only'))+'</div>'
    +'<div class="tbl-scroll"><table class="admin-tbl"><thead><tr style="color:var(--muted);text-align:left">'
    +'<th style="padding:.3rem;width:28px" title="'+t('sess_pin_title')+'">&#128204;</th>'
    +'<th style="padding:.3rem">'+t('sess_col_owner')+'</th><th style="padding:.3rem">'+t('col_account')+'</th>'
    +'<th style="padding:.3rem">'+t('sess_col_title')+'</th><th style="padding:.3rem">'+t('sess_col_source')+'</th>'
    +'<th style="padding:.3rem">'+t('sess_col_turns')+'</th><th style="padding:.3rem">'+t('sess_col_updated')+'</th>'
    +'<th style="padding:.3rem;text-align:right">'+t('col_actions')+'</th></tr></thead><tbody>';
  rows.forEach((row,i)=>{
    const pin=_sessPin(row);
    const title=row.chat_name||row.session_id||row.conversation_id||'-';
    const acct=row.account_name||row.account_email||row.account_id;
    h+='<tr style="border-top:1px solid #334155">'
      +'<td style="padding:.4rem"><input type="checkbox" '+(__sessPinned.has(pin)?'checked':'')+' onclick="toggleSessPinned(\\''+encodeURIComponent(pin)+'\\',this.checked)"></td>'
      +'<td style="padding:.4rem;font-size:.78rem">'+_sessOwner(row)+'</td>'
      +'<td style="padding:.4rem;font-size:.78rem">'+esc(acct||'-')+'</td>'
      +'<td style="padding:.4rem;font-size:.78rem;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+esc(row.conversation_id||'')+'">'+esc(title)+'</td>'
      +'<td style="padding:.4rem">'+_sessSrcBadge(row.source)+'</td>'
      +'<td style="padding:.4rem;font-size:.78rem">'+(row.turn_count||0)+'</td>'
      +'<td style="padding:.4rem;font-size:.75rem;color:var(--faint);white-space:nowrap">'+esc(_sessWhen(row.updated_at))+'</td>'
      +'<td style="padding:.4rem;text-align:right;white-space:nowrap">'
      +'<button onclick="delSession('+i+')" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('btn_delete')+'</button></td></tr>';
  });
  h+='</tbody></table></div>';
  box.innerHTML=h;
}
async function loadSessions(){
  const box=document.getElementById('sessions-content');
  if(!box)return;
  // The user filter is built from __keys; the sessions view can be the first
  // one opened, so make sure they are loaded before the first render.
  if(!(__keys||[]).length){try{await loadKeys()}catch(e){}}
  const sel=document.getElementById('sess-key-filter');
  const cloudBox=document.getElementById('sess-cloud');
  const q='?key_id='+encodeURIComponent((sel&&sel.value)||'all')+'&cloud='+((!cloudBox||cloudBox.checked)?'1':'0');
  try{
    const r=await fetch('/admin/sessions'+q,{credentials:'include'});
    if(r.status===401){showInlineLogin();return}
    if(!r.ok){const e=await r.json().catch(()=>({}));__sessions={data:[],count:0,warnings:[(e.error&&e.error.message)||('HTTP '+r.status)]}}
    else __sessions=await r.json();
  }catch(e){__sessions={data:[],count:0,warnings:[t('network_error')]}}
  renderSessions();
}
async function delSession(i){
  const row=((__sessions&&__sessions.data)||[])[i];
  if(!row)return;
  if(!await adminConfirm(t('sess_confirm_delete')))return;
  try{
    const r=await fetch('/admin/sessions/delete',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({store_key:row.store_key,conversation_id:row.conversation_id,account_id:row.account_id,cloud:true})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok){await adminAlert((d.error&&d.error.message)||'error');return}
    if((d.warnings||[]).length)await adminAlert(d.warnings.join('\\n'));
    loadSessions();
  }catch(e){await adminAlert(t('network_error'))}
}
async function cleanupSessions(){
  const sel=document.getElementById('sess-key-filter');
  const cloudBox=document.getElementById('sess-cloud');
  const ttl=Number(document.getElementById('sess-ttl').value)||0;
  const keep=Number(document.getElementById('sess-keep').value)||0;
  if(!ttl&&!keep){await adminAlert(t('sess_cleanup_need_rule'));return}
  const cloud=!cloudBox||cloudBox.checked;
  if(!await adminConfirm(cloud?t('sess_confirm_cleanup_cloud'):t('sess_confirm_cleanup')))return;
  try{
    const r=await fetch('/admin/sessions/cleanup',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key_id:(sel&&sel.value)||'all',ttl_hours:ttl,keep:keep,cloud:cloud,keep_ids:[...__sessPinned]})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok){await adminAlert((d.error&&d.error.message)||'error');return}
    const done=t('sess_cleanup_done').replace('{local}',(d.removed_local||[]).length).replace('{cloud}',(d.deleted_cloud||[]).length);
    await adminAlert((d.warnings||[]).length?done+'\\n'+d.warnings.join('\\n'):done);
    loadSessions();
  }catch(e){await adminAlert(t('network_error'))}
}
"""
