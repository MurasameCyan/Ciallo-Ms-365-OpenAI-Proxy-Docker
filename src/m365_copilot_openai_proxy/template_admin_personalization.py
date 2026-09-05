"""The per-account personalization panel on /admin (memory, insights, …).

It hangs inside the existing per-account drawer, under the PKCE panel: pasting a
token, signing in and deciding what this account remembers are all the same job.

Two shapes are forced by things measured upstream and by this page's own habits:

  * One GET here is one real call to substrate.office.com, so the panel loads when
    its drawer is *opened*, never for every row of the table. The accounts table
    rebuilds itself every 30 seconds and after every mutation, so the state lives
    in ``__personalization`` and each rebuild re-renders from that map instead of
    re-fetching (and instead of losing what was on screen).
  * A write is answered by the server's read-back, and the whole set is repainted
    from it -- upstream couples the flags (turning memory off also turned insights
    off), so "I only clicked one checkbox" is not what the account now says.
"""

from __future__ import annotations

_ADMIN_PERSONALIZATION_JS = r"""
// account id -> {flags:{...}, tenant_allowed:bool} | {loading:true} | {error:'...'}
let __personalization={};
const _PERS_FLAGS=[
  ['isMemoryEnabled','pers_memory'],
  ['isInsightsFromConversationHistoryEnabled','pers_insights'],
  ['isCustomInstructionEnabled','pers_custom'],
  ['isM365GraphContentEnabled','pers_graph'],
];
// Consumer accounts get nothing: personal Copilot has no such endpoint (same
// reason the PKCE panel skips them).
function _personalizationPanel(a){
  if((a.provider||'m365')!=='m365')return '';
  const id=esc(a.id);
  return '<div class="pers-panel" style="margin-top:.6rem;padding-top:.6rem;border-top:1px solid var(--inner-border)">'
    +'<div style="display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap">'
    +'<b style="font-size:.8rem;color:var(--strong)">'+t('pers_title')+'</b>'
    +'<span style="font-size:.72rem;color:#f59e0b">'+t('pers_warning')+'</span>'
    +'</div>'
    +'<div id="pers-'+id+'">'+_personalizationBody(a.id)+'</div>'
    +'</div>';
}
function _personalizationBody(id){
  const st=__personalization[id];
  const note=s=>'<div style="font-size:.76rem;color:var(--faint);margin-top:.3rem">'+s+'</div>';
  if(!st)return note(t('pers_unloaded'));
  if(st.loading)return note(t('pers_loading'));
  if(st.error&&!st.flags)return '<div style="font-size:.76rem;color:#ef4444;margin-top:.3rem">'+esc(st.error)
    +' <button onclick="loadPersonalization(\''+esc(id)+'\',true)" style="font-size:.72rem;padding:2px 8px;margin-left:.3rem">'+t('pers_retry')+'</button></div>';
  const locked=st.tenant_allowed===false||!!st.saving;
  let h='<div style="display:flex;flex-wrap:wrap;gap:.35rem 1.1rem;margin-top:.4rem">';
  _PERS_FLAGS.forEach(f=>{
    const on=!!(st.flags||{})[f[0]];
    h+='<label style="display:inline-flex;align-items:center;gap:.35rem;font-size:.78rem;color:var(--muted);cursor:'+(locked?'default':'pointer')+'">'
      +'<input type="checkbox" data-pers-flag="'+f[0]+'" '+(on?'checked ':'')+(locked?'disabled ':'')
      +'onchange="savePersonalization(\''+esc(id)+'\',\''+f[0]+'\',this.checked)">'
      +'<span>'+t(f[1])+'</span></label>';
  });
  h+='</div>';
  if(st.tenant_allowed===false)h+='<div style="font-size:.74rem;color:#f59e0b;margin-top:.3rem">'+t('pers_tenant_off')+'</div>';
  else h+=note(t('pers_coupling_hint'));
  if(st.saving)h+=note(t('pers_saving'));
  else if(st.error)h+='<div style="font-size:.76rem;color:#ef4444;margin-top:.3rem">'+esc(st.error)+'</div>';
  else if(st.saved)h+='<div style="font-size:.76rem;color:#22c55e;margin-top:.3rem">'+t('pers_saved')+'</div>';
  return h;
}
function renderPersonalization(id){
  const box=document.getElementById('pers-'+id);
  if(box)box.innerHTML=_personalizationBody(id);
}
// Called when the drawer opens. Cached afterwards: a reopen (or the 30s table
// rebuild) must not spend another upstream call. `force` is the retry button.
async function loadPersonalization(id,force){
  const st=__personalization[id];
  if(!force&&st&&(st.loading||st.flags))return;
  __personalization[id]={loading:true};
  renderPersonalization(id);
  try{
    const r=await fetch('/admin/accounts/'+id+'/personalization',{credentials:'include'});
    const d=await r.json().catch(()=>({}));
    __personalization[id]=r.ok
      ?{flags:d.flags||{},tenant_allowed:d.tenant_allowed!==false}
      :{error:(d.error&&d.error.message)||('HTTP '+r.status)};
  }catch(e){__personalization[id]={error:t('network_error')}}
  renderPersonalization(id);
}
// One checkbox posts one flag; the answer is what the account reads back, and the
// whole set is repainted from it -- upstream moves flags nobody sent.
async function savePersonalization(id,flag,on){
  const before=__personalization[id];
  if(!before||!before.flags)return;
  __personalization[id]={flags:before.flags,tenant_allowed:before.tenant_allowed,saving:true};
  renderPersonalization(id);
  try{
    const body={};body[flag]=!!on;
    const r=await fetch('/admin/accounts/'+id+'/personalization',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json().catch(()=>({}));
    __personalization[id]=r.ok
      ?{flags:d.flags||{},tenant_allowed:d.tenant_allowed!==false,saved:true}
      :{flags:before.flags,tenant_allowed:before.tenant_allowed,error:(d.error&&d.error.message)||('HTTP '+r.status)};
  }catch(e){__personalization[id]={flags:before.flags,tenant_allowed:before.tenant_allowed,error:t('network_error')}}
  renderPersonalization(id);
}
"""
