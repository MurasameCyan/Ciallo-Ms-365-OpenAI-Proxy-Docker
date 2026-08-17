"""Admin JS for the interactive PKCE sign-in and RT-derived media tokens.

Lives inside the existing per-account "push token" drawer rather than as a new
card: pasting a token, signing in, and minting media keys are the same job --
give this account credentials -- and the drawer is already the place for it.
"""

_ADMIN_PKCE_JS = r"""
// Panel markup injected into the account drawer. Consumer accounts get nothing:
// personal Copilot is MSA + Cloudflare, not an AAD OAuth client.
function _pkcePanel(a){
  if((a.provider||'m365')!=='m365')return '';
  const id=esc(a.id);
  const btn='font-size:.78rem;padding:5px 12px';
  return '<div style="margin-top:.6rem;padding-top:.6rem;border-top:1px solid var(--inner-border)">'
    +'<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">'
    +'<button onclick="pkceStart(\''+id+'\')" style="'+btn+'">'+t('pkce_start')+'</button>'
    +'<input id="pkce-cb-'+id+'" placeholder="'+t('pkce_paste_ph')+'" style="flex:1;min-width:240px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none">'
    +'<button onclick="pkceComplete(\''+id+'\')" style="'+btn+'">'+t('pkce_finish')+'</button>'
    +'<span style="color:var(--faint);font-size:.72rem">|</span>'
    +'<button onclick="pkceMint(\''+id+'\',\'media\')" style="'+btn+';background:var(--chip)">'+t('pkce_mint_media')+'</button>'
    +'<button onclick="pkceMint(\''+id+'\',\'designer\')" style="'+btn+';background:var(--chip)">'+t('pkce_mint_designer')+'</button>'
    +'</div>'
    +'<div style="color:var(--faint);font-size:.72rem;margin-top:.4rem">'+t('pkce_hint')+'</div>'
    +'<div id="pkce-msg-'+id+'" style="font-size:.78rem;margin-top:.4rem;word-break:break-all"></div>'
    +'</div>';
}
function _pkceMsg(id,text,color){
  const box=document.getElementById('pkce-msg-'+id);
  if(box){box.style.color=color||'var(--muted)';box.textContent=text}
}
async function _pkcePost(path,body){
  const r=await fetch(path,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error((d.error&&d.error.message)||('HTTP '+r.status));
  return d;
}
async function pkceStart(id){
  _pkceMsg(id,t('pkce_starting'));
  try{
    const d=await _pkcePost('/admin/pkce/start',{account_id:id});
    // Opened rather than shown as a link: the operator has to sign in anyway, and
    // the URL is long enough that copying it by hand invites truncation.
    window.open(d.auth_url,'_blank','noopener');
    const box=document.getElementById('pkce-msg-'+id);
    if(box){
      box.style.color='var(--muted)';
      box.innerHTML=esc(t('pkce_started'))+' <a href="'+esc(d.auth_url)+'" target="_blank" rel="noopener" style="color:#38bdf8">'+esc(t('pkce_open_manually'))+'</a>';
    }
  }catch(e){_pkceMsg(id,String(e.message||e),'#ef4444')}
}
async function pkceComplete(id){
  const input=document.getElementById('pkce-cb-'+id);
  const pasted=(input&&input.value||'').trim();
  if(!pasted){_pkceMsg(id,t('pkce_need_paste'),'#f59e0b');return}
  _pkceMsg(id,t('pkce_finishing'));
  try{
    const d=await _pkcePost('/admin/pkce/complete',{callback_url:pasted});
    if(input)input.value='';
    _pkceMsg(id,t('pkce_done').replace('{email}',d.email||'-'),'#22c55e');
    loadAccounts();
  }catch(e){_pkceMsg(id,String(e.message||e),'#ef4444')}
}
async function pkceMint(id,kind){
  _pkceMsg(id,t('pkce_minting'));
  try{
    const d=await _pkcePost('/admin/pkce/mint',{account_id:id,kind:kind});
    const shape=d.format==='jwt'?(d.aud||''):t('pkce_opaque');
    _pkceMsg(id,t('pkce_minted').replace('{kind}',kind).replace('{shape}',shape),'#22c55e');
    loadAccounts();
  }catch(e){_pkceMsg(id,String(e.message||e),'#ef4444')}
}
"""
