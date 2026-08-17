"""Shared JS for the interactive PKCE sign-in.

The same two steps -- open the Microsoft sign-in, paste the redirect URL back --
are offered on both consoles, so the flow lives here once and each page supplies
three bindings:

  ``_PKCE_BASE``    where to post ("/admin/pkce" vs "/user/pkce")
  ``_pkceInit()``   how the request is authorised (admin cookie vs API key)
  ``_pkceReload()`` what to refresh afterwards (accounts table vs user card)

There are no "mint media key" buttons: completing a sign-in mints both media keys
server-side, and the keepalive renews them off the same refresh token, so the
manual ``/pkce/mint`` endpoints are only a debugging escape hatch now.

On /admin the panel is injected into the existing per-account "push token"
drawer rather than a new card: pasting a token and signing in are the same job --
give this account credentials.
"""

_PKCE_JS = r"""
// Panel markup, identical on both consoles. Consumer accounts get nothing:
// personal Copilot is MSA + Cloudflare, not an AAD OAuth client.
function _pkcePanel(a){
  if((a.provider||'m365')!=='m365')return '';
  const id=esc(a.id);
  const btn='font-size:.78rem;padding:5px 12px';
  return '<div class="pkce-panel" style="margin-top:.6rem;padding-top:.6rem;border-top:1px solid var(--inner-border)">'
    +'<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">'
    +'<button onclick="pkceStart(\''+id+'\')" style="'+btn+'">'+t('pkce_start')+'</button>'
    +'<input id="pkce-cb-'+id+'" placeholder="'+t('pkce_paste_ph')+'" style="flex:1;min-width:240px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none">'
    +'<button onclick="pkceComplete(\''+id+'\')" style="'+btn+'">'+t('pkce_finish')+'</button>'
    +'</div>'
    +'<div id="pkce-msg-'+id+'" style="font-size:.78rem;margin-top:.4rem;word-break:break-all"></div>'
    +'</div>';
}
function _pkceMsg(id,text,color){
  const box=document.getElementById('pkce-msg-'+id);
  if(box){box.style.color=color||'var(--muted)';box.textContent=text}
}
async function _pkcePost(path,body){
  const init={method:'POST',body:JSON.stringify(body),..._pkceInit()};
  init.headers={'Content-Type':'application/json',...(init.headers||{})};
  const r=await fetch(_PKCE_BASE+path,init);
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error((d.error&&d.error.message)||('HTTP '+r.status));
  return d;
}
async function pkceStart(id){
  _pkceMsg(id,t('pkce_starting'));
  try{
    const d=await _pkcePost('/start',{account_id:id});
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
    const d=await _pkcePost('/complete',{callback_url:pasted});
    if(input)input.value='';
    // The server mints both media keys as part of the sign-in; report the ones
    // that failed, because chat still works without them and the gap is silent.
    const keys=d.media_keys||{};
    const bad=Object.keys(keys).filter(k=>!keys[k]||keys[k].status!=='ok');
    let text=t('pkce_done').replace('{email}',d.email||'-');
    text+=' '+(bad.length?t('pkce_keys_failed').replace('{kinds}',bad.join(', ')):t('pkce_keys_ok'));
    _pkceMsg(id,text,bad.length?'#f59e0b':'#22c55e');
    _pkceReload();
  }catch(e){_pkceMsg(id,String(e.message||e),'#ef4444')}
}
"""

_ADMIN_PKCE_JS = (
    r"""
const _PKCE_BASE='/admin/pkce';
function _pkceInit(){return {credentials:'include'}}
function _pkceReload(){loadAccounts()}
"""
    + _PKCE_JS
)

_USER_PKCE_JS = (
    r"""
const _PKCE_BASE='/user/pkce';
// The user surface takes the account from the API key, so the account_id the
// shared code sends along is ignored server-side.
function _pkceInit(){return {headers:authHeaders()}}
function _pkceReload(){loadMe()}
function renderUserPkce(a){
  const box=document.getElementById('pkce-panel');if(!box)return;
  const id=(a&&(a.provider||'m365')==='m365')?String(a.id||''):'';
  // loadMe() runs after every credential change, and re-rendering would wipe the
  // URL being pasted plus the result message -- so only rebuild when the account
  // or the language actually changed.
  const sig=id+'|'+lang;
  if(box.dataset.pkceSig===sig&&box.innerHTML)return;
  box.dataset.pkceSig=sig;
  box.innerHTML=id?_pkcePanel({id:id,provider:'m365'}):('<div class="hint">'+t('pkce_no_account')+'</div>');
}
"""
    + _PKCE_JS
)
