from __future__ import annotations

_ADMIN_DASHBOARD_JS = """function fmtClock(sec){if(sec==null)return'N/A';const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60);return(h?h+'h ':'')+m+'m'}
function fmtHMS(sec){sec=Math.max(0,Math.floor(Number(sec)||0));const h=String(Math.floor(sec/3600)).padStart(2,'0'),m=String(Math.floor(sec%3600/60)).padStart(2,'0'),s=String(sec%60).padStart(2,'0');return h+':'+m+':'+s}
function fmtTs(ts){return ts?new Date(ts*1000).toLocaleString():'N/A'}
function liveTokenStatus(st){st=st||{};const exp=Number(st.expires_at||0),now=Date.now()/1000,base=Number(st.seconds_remaining||0),loaded=Number(st._loaded_at||now);const rem=exp?Math.max(0,Math.floor(exp-now)):Math.max(0,Math.floor(base-(now-loaded)));return {...st,valid:!!st.valid&&(!exp||rem>0),seconds_remaining:rem}}
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
    g+='<polyline points="'+poly+'" fill="none" stroke="'+s.color+'" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" opacity="0.1"><animate attributeName="opacity" values="0.08;0.24;0.08" dur="3.2s" repeatCount="indefinite"/></polyline>';
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
  if(!await adminConfirm(t('confirm_clear_stats')))return;
  await fetch('/admin/call-log/clear',{method:'POST',credentials:'include'}).catch(()=>{});
  loadStats();loadCallLog();
}
async function clearCapturePayloads(){
  if(!await adminConfirm(t('confirm_clear_stats')))return;
  await fetch('/admin/capture-payload/clear',{method:'POST',credentials:'include'}).catch(()=>{});
  loadCapture();
}
async function clearImageProxyEvents(){
  if(!await adminConfirm(t('confirm_clear_stats')))return;
  await fetch('/admin/image-proxy/events/clear',{method:'POST',credentials:'include'}).catch(()=>{});
  loadImageProxyEvents();
}
let __expiryWarnTimer=null;
async function loadStats(){
  const kpi=document.getElementById('dash-stat-kpi');
  try{
    const r=await fetch('/admin/stats',{credentials:'include'});
    if(!r.ok)return;
    const d=await r.json();
    if(kpi)kpi.innerHTML=kpiCard(t('dash_calls_24h'),d.calls_24h||0,'#38bdf8')+kpiCard(t('dash_calls_total'),d.calls_total||0,'#a78bfa');
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
