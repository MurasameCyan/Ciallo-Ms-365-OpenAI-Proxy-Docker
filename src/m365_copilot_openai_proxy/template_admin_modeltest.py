from __future__ import annotations

# Single-model connectivity probe (/admin/model-test). Which mode works is decided
# by Microsoft's rollout per account, so the only way to know is to send one real
# turn; this replaces doing that by hand with curl. Two-stage per the template
# convention: loadModelTest() only fetches what it needs, renderModelTest() reads
# the cache, so a language switch costs no network and no extra upstream turns.
_ADMIN_MODELTEST_JS = """let __modelTest=[];
let __modelTestBusy=false;
const _MT_COLORS={ok:'#22c55e',empty:'#f59e0b',refused:'#ef4444',throttled:'#a78bfa',error:'#94a3b8',running:'#38bdf8'};
function _mtBadge(v){
  const c=_MT_COLORS[v]||'#94a3b8';
  return '<span style="padding:.1rem .5rem;border-radius:99px;font-size:.7rem;white-space:nowrap;border:1px solid '+c+'66;background:'+c+'22;color:'+c+'">'+t('mt_v_'+v)+'</span>';
}
function _mtAccount(){
  const sel=document.getElementById('model-test-account');
  return (__accounts||[]).find(a=>a.id===(sel&&sel.value));
}
// The probe takes whatever a client would put in "model": a tone label/value for
// M365, a configured model id for the personal edition. __runtimeSettings is the
// script-scope cache the debug view already fetches (not a window property).
function _mtModels(acct){
  if(!acct)return [];
  if((acct.provider||'m365')==='consumer')
    return ((__runtimeSettings||{}).consumer_mode_options||[]).map(o=>({id:o.model,label:o.model+' \\u00b7 '+o.mode}));
  return _toneOptsSource().map(o=>({id:o.label||o.value,label:_toneLabel(o.value)}));
}
function renderModelTestOptions(){
  const asel=document.getElementById('model-test-account');
  if(!asel)return;
  const curA=asel.value;
  asel.innerHTML=(__accounts||[]).map(a=>'<option value="'+esc(a.id)+'">'+esc(acctLabel(a))+'</option>').join('');
  if(curA&&(__accounts||[]).some(a=>a.id===curA))asel.value=curA;
  refreshGlassSelect(asel);
  const msel=document.getElementById('model-test-model');
  if(msel){
    const curM=msel.value;
    const models=_mtModels(_mtAccount());
    msel.innerHTML=models.map(m=>'<option value="'+esc(m.id)+'">'+esc(m.label)+'</option>').join('');
    if(curM&&models.some(m=>m.id===curM))msel.value=curM;
    refreshGlassSelect(msel);
  }
  const p=document.getElementById('model-test-prompt');
  if(p)p.placeholder=t('mt_prompt_ph');
}
function renderModelTest(){
  renderModelTestOptions();
  const box=document.getElementById('model-test-result');
  if(!box)return;
  if(!__modelTest.length){box.innerHTML='<span style="color:var(--faint)">'+t('mt_none')+'</span>';return}
  let h='<table class="admin-tbl"><thead><tr style="color:var(--muted);text-align:left">'
    +'<th style="padding:.3rem">'+t('mt_col_model')+'</th><th style="padding:.3rem">'+t('mt_col_verdict')+'</th>'
    +'<th style="padding:.3rem">'+t('mt_col_latency')+'</th><th style="padding:.3rem">'+t('mt_col_detail')+'</th></tr></thead><tbody>';
  __modelTest.forEach(row=>{
    const detail=row.error||row.reply||'';
    h+='<tr style="border-top:1px solid #334155">'
      +'<td style="padding:.4rem;font-size:.78rem">'+esc(row.model)+'</td>'
      +'<td style="padding:.4rem">'+_mtBadge(row.verdict||'error')+'</td>'
      +'<td style="padding:.4rem;font-size:.75rem;color:var(--faint);white-space:nowrap">'+(row.latency_ms?(row.latency_ms+' ms'):'-')+'</td>'
      +'<td style="padding:.4rem;font-size:.75rem;max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+esc(detail)+'">'+esc(detail||'-')+'</td></tr>';
  });
  h+='</tbody></table><div style="font-size:.72rem;color:var(--faint);margin-top:.5rem">'+t('mt_legend')+'</div>';
  box.innerHTML=h;
}
async function loadModelTest(){
  // The debug view does not load accounts on its own, and the selector needs them.
  if(!(__accounts||[]).length){try{await loadAccounts()}catch(e){}}
  renderModelTest();
}
async function _mtProbe(accountId,model,prompt){
  try{
    const r=await fetch('/admin/model-test',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({account_id:accountId,model:model,prompt:prompt||''})});
    if(r.status===401){showInlineLogin();return null}
    const d=await r.json().catch(()=>({}));
    if(!r.ok)return {model:model,verdict:'error',error:(d.error&&d.error.message)||('HTTP '+r.status),latency_ms:0,reply:''};
    return d;
  }catch(e){return {model:model,verdict:'error',error:t('network_error'),latency_ms:0,reply:''}}
}
async function runModelTest(all){
  if(__modelTestBusy)return;
  const acct=_mtAccount();
  if(!acct){await adminAlert(t('mt_no_account'));return}
  const msel=document.getElementById('model-test-model');
  const pin=document.getElementById('model-test-prompt');
  const prompt=(pin&&pin.value)||'';
  const targets=all?_mtModels(acct).map(m=>m.id):[msel&&msel.value].filter(Boolean);
  if(!targets.length){await adminAlert(t('mt_no_model'));return}
  const btn=document.getElementById(all?'model-test-run-all':'model-test-run');
  const label=btn?btn.textContent:'';
  __modelTestBusy=true;__modelTest=[];
  if(btn){btn.disabled=true;btn.textContent=t('mt_running')}
  try{
    for(const model of targets){
      // Sequential on purpose: every probe is a real upstream turn on ONE account,
      // so firing them together would look like a burst and can trip the quota.
      __modelTest.push({model:model,verdict:'running'});
      renderModelTest();
      const row=await _mtProbe(acct.id,model,prompt);
      __modelTest[__modelTest.length-1]={...(row||{}),model:model};
      renderModelTest();
    }
  }finally{
    __modelTestBusy=false;
    if(btn){btn.disabled=false;btn.textContent=label}
  }
}
"""
