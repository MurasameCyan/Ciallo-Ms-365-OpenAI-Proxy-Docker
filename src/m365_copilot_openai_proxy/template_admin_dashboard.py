from __future__ import annotations

_ADMIN_DASHBOARD_JS = """function fmtClock(sec){if(sec==null)return'N/A';const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60);return(h?h+'h ':'')+m+'m'}
function fmtHMS(sec){sec=Math.max(0,Math.floor(Number(sec)||0));const h=String(Math.floor(sec/3600)).padStart(2,'0'),m=String(Math.floor(sec%3600/60)).padStart(2,'0'),s=String(sec%60).padStart(2,'0');return h+':'+m+':'+s}
function fmtTs(ts){const n=Number(ts);if(!Number.isFinite(n)||n<=0)return'N/A';const d=new Date(n*1000);if(Number.isNaN(d.getTime()))return'N/A';const yy=String(d.getFullYear()%100).padStart(2,'0'),mo=String(d.getMonth()+1).padStart(2,'0'),day=String(d.getDate()).padStart(2,'0'),h=String(d.getHours()).padStart(2,'0'),m=String(d.getMinutes()).padStart(2,'0'),s=String(d.getSeconds()).padStart(2,'0');return yy+'-'+mo+'-'+day+' '+h+':'+m+':'+s}
function liveTokenStatus(st){st=st||{};const raw=st.expires_at,numeric=Number(raw),parsed=raw&&Number.isFinite(numeric)?numeric:(raw?Date.parse(raw)/1000:0),exp=Number.isFinite(parsed)&&parsed>0?parsed:0,now=Date.now()/1000,base=Number(st.seconds_remaining||0),loaded=Number(st._loaded_at||now);const rem=exp?Math.max(0,Math.floor(exp-now)):Math.max(0,Math.floor(base-(now-loaded)));return {...st,valid:!!st.valid&&(!exp||rem>0),seconds_remaining:rem,expiry_known:exp>0}}
function liveCookieValid(a){const exp=Number(a.cookie_expires_at||0);return !!a.cookie_valid&&(!exp||exp>Date.now()/1000)}
function lineChart(points,series){
  // points: [{ts,...}]; series: [{key,color,label}]. Returns responsive SVG.
  if(!points||points.length<2)return '<span style="color:var(--faint)">'+t('dash_no_trend')+'</span>';
  const W=760,H=200,pl=36,pr=12,pt=12,pb=24;
  const xs=points.map(p=>p.ts);
  const xmin=Math.min.apply(null,xs),xmax=Math.max.apply(null,xs);
  let ymax=1;series.forEach(s=>points.forEach(p=>{if((p[s.key]||0)>ymax)ymax=p[s.key]}));
  const X=t=>pl+(xmax===xmin?0:(t-xmin)/(xmax-xmin))*(W-pl-pr);
  const Y=v=>pt+(1-v/ymax)*(H-pt-pb);
  let g='';
  // horizontal gridlines + y labels (0, mid, max)
  [0,0.5,1].forEach(f=>{const v=Math.round(ymax*f);const y=Y(v);g+='<line x1="'+pl+'" y1="'+y+'" x2="'+(W-pr)+'" y2="'+y+'" stroke="var(--grid)"/><text x="'+(pl-6)+'" y="'+(y+3)+'" text-anchor="end" fill="var(--faint)" font-size="10">'+v+'</text>'});
  series.forEach(s=>{
    const pts=points.map(p=>({x:X(p.ts),y:Y(p[s.key]||0)}));
    const poly=pts.map(p=>p.x.toFixed(1)+','+p.y.toFixed(1)).join(' ');
    g+='<polyline points="'+poly+'" fill="none" stroke="'+s.color+'" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" opacity="0.16"/>';
    g+='<polyline points="'+poly+'" fill="none" stroke="'+s.color+'" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" opacity="0.95"/>';
    pts.forEach((p,i)=>{if(i===0||i===pts.length-1)g+='<circle cx="'+p.x.toFixed(1)+'" cy="'+p.y.toFixed(1)+'" r="2.6" fill="var(--inner)" stroke="'+s.color+'" stroke-width="1.6"/>'});
  });
  // x labels: first + last time
  const tf=ts=>new Date(ts*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
  g+='<text x="'+pl+'" y="'+(H-6)+'" fill="var(--faint)" font-size="10">'+tf(xmin)+'</text>';
  g+='<text x="'+(W-pr)+'" y="'+(H-6)+'" text-anchor="end" fill="var(--faint)" font-size="10">'+tf(xmax)+'</text>';
  let legend='<div style="display:flex;gap:1rem;flex-wrap:wrap;margin-top:.5rem">';
  series.forEach(s=>{legend+='<span style="display:flex;align-items:center;gap:.35rem;font-size:.78rem;color:var(--muted)"><span style="width:14px;height:3px;background:'+s.color+';display:inline-block;border-radius:2px"></span>'+s.label+'</span>'});
  legend+='</div>';
  return '<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">'+g+'</svg>'+legend;
}
async function loadSummary(){
  try{const r=await fetch('/admin/summary',{credentials:'include'});if(!r.ok)return;__summary=await r.json();renderDashboard()}catch(e){}
}
async function loadTrend(){
  const box=document.getElementById('dash-trend');if(!box)return;
  try{
    const r=await fetch('/admin/metrics-history',{credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    const h=(d.history||[]).map(p=>({ts:p.ts,users:p.users,accounts:p.accounts,valid_accounts:p.valid_accounts}));
    box.innerHTML=lineChart(h,[
      {key:'users',color:'#38bdf8',label:t('dash_kpi_users')},
      {key:'accounts',color:'#a78bfa',label:t('dash_kpi_accounts')},
      {key:'valid_accounts',color:'#22c55e',label:t('dash_kpi_valid_accts')}
    ]);
  }catch(e){}
}
async function clearTrendStats(){
  if(!await adminConfirm(t('confirm_clear_stats')))return;
  await fetch('/admin/metrics-history/clear',{method:'POST',credentials:'include'}).catch(()=>{});
  loadTrend();
}
async function clearCallStats(){
  if(!await adminConfirm(t('confirm_clear_call_log')))return;
  await fetch('/admin/call-log/clear',{method:'POST',credentials:'include'}).catch(()=>{});
  loadStats();loadCallLog();
}
async function clearUsageStats(){
  if(!await adminConfirm(t('confirm_clear_usage')))return;
  await fetch('/admin/usage/clear',{method:'POST',credentials:'include'}).catch(()=>{});
  loadStats();
}
async function clearCapturePayloads(){
  if(!await adminConfirm(t('confirm_clear_stats')))return;
  await fetch('/admin/capture-payload/clear',{method:'POST',credentials:'include'}).catch(()=>{});
  loadCapture();
}
async function loadProtocolProfileAccounts(){
  const select=document.getElementById('protocol-profile-account');
  if(!select)return;
  const previous=select.value;
  try{
    const r=await fetch('/admin/accounts',{credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    const accounts=(d.accounts||[]).filter(a=>a.provider!=='consumer');
    select.innerHTML=accounts.map(a=>'<option value="'+esc(a.id)+'">'+esc(a.name||a.email||a.id)+'</option>').join('');
    if(accounts.some(a=>a.id===previous))select.value=previous;
  }catch(e){}
}
function protocolProfileSelection(){
  const accountId=(document.getElementById('protocol-profile-account')||{}).value||'';
  const scope=(document.getElementById('protocol-profile-scope')||{}).value||'account';
  if(accountId)return {accountId,scope};
  const el=document.getElementById('protocol-profile-status');
  if(el)el.textContent=t('mt_no_account');
  return null;
}
async function showProtocolCandidate(){
  try{
    const r=await fetch('/admin/protocol-profile/candidate',{credentials:'include'});
    const d=await r.json();
    const el=document.getElementById('protocol-profile-status');
    if(el)el.textContent=JSON.stringify(d);
  }catch(e){}
}
async function applyProtocolCandidate(){
  if(!await adminConfirm(t('confirm_protocol_profile_apply')))return;
  const selected=protocolProfileSelection();if(!selected)return;
  const accountId=selected.accountId,scope=selected.scope;
  try{
    const r=await fetch('/admin/protocol-profile/apply',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id:accountId,scope:scope})});
    const d=await r.json();
    const el=document.getElementById('protocol-profile-status');
    if(el)el.textContent=JSON.stringify(d);
  }catch(e){}
}
async function rollbackProtocolProfile(){
  if(!await adminConfirm(t('confirm_protocol_profile_rollback')))return;
  const selected=protocolProfileSelection();if(!selected)return;
  const accountId=selected.accountId,scope=selected.scope;
  try{
    const r=await fetch('/admin/protocol-profile/rollback',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id:accountId,scope:scope})});
    const d=await r.json();
    const el=document.getElementById('protocol-profile-status');
    if(el)el.textContent=JSON.stringify(d);
  }catch(e){}
}
async function clearMediaProxyEvents(){
  if(!await adminConfirm(t('confirm_clear_stats')))return;
  await fetch('/admin/media-proxy/events/clear',{method:'POST',credentials:'include'}).catch(()=>{});
  loadMediaProxyEvents();
}
let __expiryWarnTimer=null;
// What the caches are buying. The headline is the incremental rate: a turn that
// continued a remembered upstream conversation sent only the new message, a fresh
// start resent the whole transcript. The rest is the two in-memory caches behind
// it plus how many disk writes the coalescing window saved.
function _cachePct(v){return v==null?'—':Math.round(v*100)+'%'}
function renderCacheStats(){
  const box=document.getElementById('dash-cache');
  if(!box)return;
  const c=window.__cacheStats;
  if(!c){box.innerHTML='<span style="color:var(--faint)">'+t('dash_cache_none')+'</span>';return}
  const s=c.sessions||{},hi=c.history_index||{},tok=c.cloud_token||{};
  box.innerHTML='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.6rem">'
    +kpiCard(t('dash_cache_reuse'),_cachePct(c.incremental_hit_rate),'#22c55e')
    +kpiCard(t('dash_cache_index'),_cachePct(hi.hit_rate),'#38bdf8')
    +kpiCard(t('dash_cache_token'),_cachePct(tok.hit_rate),'#a78bfa')
    +kpiCard(t('dash_cache_saved'),s.coalesced==null?'—':s.coalesced,'#f59e0b')
    +'</div>';
}
function _fmtCompactNumber(value){
  const number=Math.max(0,Number(value)||0);
  const scales=[[1e9,'B'],[1e6,'M'],[1e3,'K']];
  for(const [size,unit] of scales){
    if(number>=size){
      const scaled=number/size;
      return {value:(scaled>=100?Math.round(scaled):Math.round(scaled*10)/10).toString(),unit};
    }
  }
  return {value:new Intl.NumberFormat().format(number),unit:''};
}
function renderUsageOverview(){
  const box=document.getElementById('dash-model-share');
  if(!box)return;
  const usage=window.__usageStats;
  if(!usage){box.innerHTML='<span style="color:var(--faint)">'+t('no_calls_yet')+'</span>';return}
  // The ring shares calls per model, the centre stays the token total. Fold the
  // tail into one grey slice when a model can earn neither a row nor an arc: the
  // legend box is a fixed 120px (six rows, and its scrollbar is styled
  // invisible), and an arc under donut()'s 16.5px threshold is shorter than the
  // ring is thick, so it draws as a block rather than an arc whatever caps it
  // gets -- 3% of 331 calls is 8.7px of a 289px ring. Three names survive the
  // arc rule regardless, or a flat spread would collapse into one grey circle.
  const counts=usage.model_counts||{};
  const pal=['#38bdf8','#a78bfa','#22c55e','#f59e0b','#ef4444','#06b6d4','#e879f9'];
  const otherLabel='other',otherColor='#94a3b8',maxSlices=6,minShare=16.5/(2*Math.PI*46);
  const ranked=Object.entries(counts).map(e=>[e[0],Number(e[1])||0]).filter(e=>e[1]>0).sort((a,b)=>b[1]-a[1]);
  const sum=ranked.reduce((s,e)=>s+e[1],0)||1;
  let keep=ranked.length>maxSlices?maxSlices-1:ranked.length;
  while(keep>3&&ranked[keep-1][1]/sum<minShare)keep--;
  // The store has an "other" bucket of its own past 25 models; merge into it
  // rather than drawing a second slice under the same name.
  const rest=ranked.splice(keep).reduce((s,e)=>s+e[1],0),seen=ranked.find(e=>e[0]===otherLabel);
  if(rest>0){if(seen)seen[1]+=rest;else ranked.push([otherLabel,rest])}
  // The share is the whole point of the ring; the raw count would cost the model
  // name the width it needs to stay readable, and it is still in /admin/stats.
  const parts=ranked.map((entry,index)=>({
    value:entry[1],color:entry[0]===otherLabel?otherColor:pal[index%pal.length],label:esc(entry[0]),
    text:Math.round(entry[1]/sum*100)+'%'
  }));
  const total=_fmtCompactNumber(usage.total_tokens);
  box.innerHTML=donut(parts,t('dash_token_total'),total.value,total.unit);
}
async function loadStats(){
  const kpi=document.getElementById('dash-stat-kpi');
  try{
    const r=await fetch('/admin/stats',{credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    if(kpi)kpi.innerHTML=kpiCard(t('dash_calls_24h'),d.calls_24h||0,'#38bdf8')+kpiCard(t('dash_calls_total'),d.calls_total||0,'#a78bfa');
    window.__cacheStats=d.cache||null;
    window.__usageStats=d.usage||null;
    renderCacheStats();
    renderUsageOverview();
    // tone share as horizontal bars
    const tc=d.tone_counts||{};const total=Object.values(tc).reduce((s,v)=>s+v,0);
    const share=document.getElementById('dash-tone-share');
    if(share){
      if(!total){share.innerHTML='<span style="color:var(--faint)">'+t('no_calls_yet')+'</span>'}
      else{
        const pal=['#38bdf8','#a78bfa','#22c55e','#f59e0b','#ef4444','#06b6d4','#e879f9'];
        const ents=Object.entries(tc).sort((a,b)=>b[1]-a[1]);
        share.innerHTML=ents.map((e,i)=>{const pct=Math.round(e[1]/total*100);return '<div style="margin-bottom:.4rem"><div style="display:flex;justify-content:space-between;font-size:.76rem;color:var(--muted)"><span>'+esc(e[0])+'</span><span>'+e[1]+' ('+pct+'%)</span></div><div style="height:8px;background:var(--track);border-radius:4px;overflow:hidden;margin-top:2px"><div class="tone-share-fill" style="width:'+pct+'%;height:100%;background:'+pal[i%pal.length]+';color:'+pal[i%pal.length]+'"></div></div></div>'}).join('');
      }
    }
    // Expiry warnings on Accounts page: show all accounts expiring within 10 minutes; rotate when multiple.
    const warn=document.getElementById('accounts-warn');
    if(warn){
      if(__expiryWarnTimer){clearInterval(__expiryWarnTimer);__expiryWarnTimer=null}
      const items=(d.expiring_accounts||[]).filter(s=>s&&s.seconds_remaining<=600).sort((a,b)=>a.seconds_remaining-b.seconds_remaining);
      if(items.length){
        let idx=0;
        const show=()=>{
          const s=items[idx%items.length];
          warn.classList.remove('hide-card');
          warn.classList.remove('expiry-warn-rotate');
          void warn.offsetWidth;
          warn.innerHTML='&#9888; '+(items.length>1?'['+(idx%items.length+1)+'/'+items.length+'] ':'')+t('dash_expiry_warn').replace('{name}',esc(s.name)).replace('{time}',fmtClock(Math.max(0,s.seconds_remaining)));
          if(items.length>1)warn.classList.add('expiry-warn-rotate');
          idx++;
        };
        show();
        if(items.length>1)__expiryWarnTimer=setInterval(show,3000);
      }else{warn.classList.remove('expiry-warn-rotate');warn.classList.add('hide-card')}
    }
  }catch(e){}
}"""
