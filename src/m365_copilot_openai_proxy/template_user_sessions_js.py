from __future__ import annotations

# "My sessions" card on the /user page: the caller's own session bindings merged
# with the matching M365 cloud conversations. Same two-stage split as the admin
# page -- loadMySessions() fetches, renderMySessions() only reads the cache, so a
# language switch costs no request. Loaded on first expand rather than on login:
# the cloud listing is an upstream round trip nobody pays for while collapsed.
_USER_SESSIONS_JS = """let _mySessions=null;
let _mySessPinned=new Set();
function toggleMySessPinned(encoded,on){
  const pin=decodeURIComponent(encoded);
  on?_mySessPinned.add(pin):_mySessPinned.delete(pin);
}
function _mySessWhen(sec){return sec?new Date(sec*1000).toLocaleString():'-'}
function renderMySessions(){
  const box=document.getElementById('my-sessions-content');
  if(!box)return;
  const ttl=document.getElementById('my-sess-ttl');if(ttl)ttl.placeholder=t('sess_ttl_ph');
  const keep=document.getElementById('my-sess-keep');if(keep)keep.placeholder=t('sess_keep_ph');
  const warn=document.getElementById('my-sessions-warn');
  const notes=(_mySessions&&_mySessions.warnings)||[];
  if(warn){
    warn.classList.toggle('hidden',!notes.length);
    // Hover tooltip instead of a banner, same as /admin: the per-account notes
    // are detail, not something worth a paragraph above the cleanup row.
    warn.title=notes.length?(t('sess_cloud_warn')+'\\n'+notes.join('\\n')):'';
  }
  if(!_mySessions){box.innerHTML='<div class="hint">'+t('sess_loading')+'</div>';return}
  const rows=_mySessions.data||[];
  if(!rows.length){box.innerHTML='<div class="hint">'+t('sess_none')+'</div>';return}
  let h='<div class="hint">'+t('sess_count').replace('{count}',rows.length)+'</div>';
  rows.forEach((row,i)=>{
    const title=row.chat_name||row.session_id||row.conversation_id||'-';
    const pin=encodeURIComponent(row.store_key||'');
    h+='<div class="status-line" style="align-items:center;gap:.5rem">'
      +'<span style="display:flex;align-items:center;gap:.5rem;min-width:0">'
      +'<input type="checkbox" style="width:16px;height:16px;flex:0 0 auto" title="'+t('sess_pin_title')+'" '
      +(_mySessPinned.has(decodeURIComponent(pin))?'checked ':'')
      +'onclick="toggleMySessPinned(\\''+pin+'\\',this.checked)">'
      +'<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+esc(row.conversation_id||'')+'">'+esc(title)+'</span>'
      +'<span class="pill">'+t('sess_col_turns')+' '+(row.turn_count||0)+'</span>'
      +(row.source==='both'?'<span class="pill ok">'+t('sess_src_both')+'</span>':'<span class="pill">'+t('sess_src_local')+'</span>')
      +'</span>'
      +'<b style="display:flex;align-items:center;gap:.5rem;white-space:nowrap"><span style="font-size:.72rem;color:var(--faint);font-weight:400">'+esc(_mySessWhen(row.updated_at))+'</span>'
      +'<button class="btn-ghost compact-action" onclick="delMySession('+i+',this)">'+t('sess_delete')+'</button></b>'
      +'</div>';
  });
  box.innerHTML=h;
}
async function loadMySessions(){
  if(!getKey())return;
  try{
    const r=await fetch('/user/sessions',{headers:authHeaders()});
    _mySessions=r.ok?await r.json():{data:[],count:0,warnings:['HTTP '+r.status]};
  }catch(e){_mySessions={data:[],count:0,warnings:[t('network_error')]}}
  renderMySessions();
}
async function delMySession(i,btn){
  const row=((_mySessions&&_mySessions.data)||[])[i];
  if(!row||!row.store_key)return;
  if(!await userDialog(t('sess_delete'),t('sess_confirm_delete'),t('confirm_btn')))return;
  if(btn)btn.disabled=true;
  try{
    const r=await fetch('/user/sessions/delete',{method:'POST',headers:authHeaders(),body:JSON.stringify({store_key:row.store_key,cloud:true})});
    if(!r.ok)_showSessMsg(t('sess_failed'));
  }catch(e){_showSessMsg(t('network_error'))}
  loadMySessions();
}
async function cleanupMySessions(btn){
  const ttl=Number(document.getElementById('my-sess-ttl').value)||0;
  const keep=Number(document.getElementById('my-sess-keep').value)||0;
  if(!ttl&&!keep){_showSessMsg(t('sess_cleanup_need_rule'));return}
  if(!await userDialog(t('sess_cleanup_btn'),t('sess_confirm_cleanup_cloud'),t('confirm_btn')))return;
  if(btn)btn.disabled=true;
  try{
    const r=await fetch('/user/sessions/cleanup',{method:'POST',headers:authHeaders(),
      body:JSON.stringify({ttl_hours:ttl,keep:keep,cloud:true,keep_ids:[..._mySessPinned]})});
    const d=r.ok?await r.json():null;
    _showSessMsg(d?t('sess_cleanup_done').replace('{local}',(d.removed_local||[]).length).replace('{cloud}',(d.deleted_cloud||[]).length):t('sess_failed'));
  }catch(e){_showSessMsg(t('network_error'))}
  if(btn)btn.disabled=false;
  loadMySessions();
}
function _showSessMsg(text){
  const m=document.getElementById('sess-msg');
  if(!m)return;
  m.textContent=text;m.style.opacity='1';
  clearTimeout(m._sessTimer);
  m._sessTimer=setTimeout(()=>{m.style.opacity='0'},4000);
}
"""
