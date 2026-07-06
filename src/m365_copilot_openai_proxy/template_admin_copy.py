from __future__ import annotations

_ADMIN_COPY_JS = """function _fallbackCopy(text){
  try{const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();const ok=document.execCommand('copy');ta.remove();return ok}catch(e){return false}
}
function copyText(text,cb){
  // navigator.clipboard is undefined on insecure (http://ip) origins, so fall
  // back to the legacy execCommand path there.
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(()=>cb&&cb(true),()=>cb&&cb(_fallbackCopy(text)))}
  else{cb&&cb(_fallbackCopy(text))}
}
function _adminCopyFeedback(btn){if(!btn)return;if(btn._copyOldStyle===undefined)btn._copyOldStyle=btn.getAttribute('style')||'';btn.textContent=t('copied');btn.style.color='#22c55e';clearTimeout(btn._copyTimer);btn._copyTimer=setTimeout(()=>{btn.textContent=t('btn_copy');btn.setAttribute('style',btn._copyOldStyle);delete btn._copyOldStyle},1200)}
function copyKey(id,btn){
  const k=__keys.find(x=>x.id===id);if(!k)return;
  copyText(k.key,ok=>{if(ok)_adminCopyFeedback(btn)});
}
function copyPwd(id,btn){
  const k=__keys.find(x=>x.id===id);if(!k||!k.password)return;
  copyText(k.password,ok=>{if(ok)_adminCopyFeedback(btn)});
}"""
