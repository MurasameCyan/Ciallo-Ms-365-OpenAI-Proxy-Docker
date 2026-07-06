from __future__ import annotations

_ADMIN_DIALOGS_JS = """function adminDialog(message,okOnly){
  return new Promise(resolve=>{
    const ov=document.createElement('div');
    ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.3);backdrop-filter:blur(18px) saturate(145%);-webkit-backdrop-filter:blur(18px) saturate(145%);display:flex;align-items:center;justify-content:center;z-index:1000';
    ov.innerHTML='<div class="flow-box" style="position:relative;background:rgba(15,23,42,.3);border:1px solid rgba(96,242,255,.28);border-radius:12px;padding:1.25rem;width:340px;max-width:90vw;box-shadow:0 24px 70px rgba(0,0,0,.36),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(22px) saturate(150%);-webkit-backdrop-filter:blur(22px) saturate(150%)">'
      +'<div style="font-size:.86rem;color:var(--text);line-height:1.55;word-break:break-word">'+esc(message)+'</div>'
      +'<div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem">'
      +(okOnly?'':'<button id="dlg-cancel" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>')
      +'<button id="dlg-ok" style="font-size:.8rem;padding:6px 14px">'+t('rebind_confirm')+'</button>'
      +'</div></div>';
    document.body.appendChild(ov);
    const done=v=>{ov.remove();resolve(v)};
    ov.addEventListener('click',e=>{if(e.target===ov)done(false)});
    const c=ov.querySelector('#dlg-cancel');if(c)c.onclick=()=>done(false);
    ov.querySelector('#dlg-ok').onclick=()=>done(true);
  });
}
const adminAlert=message=>adminDialog(message,true);
const adminConfirm=message=>adminDialog(message,false);"""
