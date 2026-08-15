from __future__ import annotations

from .template_assets import _STILL_DECOR_CSS

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ciallo Ms-365 OpenAI Proxy</title>
<style>
:root{--cyan:#60f2ff;--violet:#8c6bff;--pink:#ff5edb;--gold:#ffd76f;--text:#f3f6ff;--muted:#9aa7d1;--line:rgba(108,137,255,.24)}
*{box-sizing:border-box;margin:0;padding:0}
html{scrollbar-gutter:stable;scrollbar-color:rgba(96,242,255,.45) rgba(8,13,32,.22);scrollbar-width:thin}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:rgba(8,13,32,.22);border-radius:999px}
::-webkit-scrollbar-thumb{background:linear-gradient(180deg,rgba(96,242,255,.58),rgba(140,107,255,.48));border-radius:999px;border:2px solid rgba(8,13,32,.4)}
::-webkit-scrollbar-thumb:hover{background:linear-gradient(180deg,rgba(96,242,255,.78),rgba(255,94,219,.58))}
body{font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;overflow:hidden;background:radial-gradient(circle at 20% 20%,rgba(96,242,255,.18),transparent 28%),radial-gradient(circle at 80% 18%,rgba(140,107,255,.22),transparent 24%),radial-gradient(circle at 50% 85%,rgba(255,94,219,.16),transparent 26%),linear-gradient(135deg,#040612 0%,#090d1f 45%,#03050d 100%)}
body::before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(rgba(255,255,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 1px);background-size:44px 44px;mask-image:radial-gradient(circle at center,black 45%,transparent 92%)}
.orb{position:fixed;width:340px;height:340px;border-radius:50%;filter:blur(14px);background:conic-gradient(from 160deg,var(--cyan),var(--pink),var(--violet),var(--cyan));top:50%;left:50%;transform:translate(-50%,-50%);animation:spin 9s linear infinite,pulse 3.4s ease-in-out infinite;opacity:.5;z-index:0}
.login-box{position:relative;z-index:2;width:380px;max-width:calc(100vw - 32px);padding:2.6rem;text-align:center;border-radius:28px;border:1px solid var(--line);background:linear-gradient(180deg,rgba(13,19,45,.82),rgba(7,10,24,.76));backdrop-filter:blur(20px);box-shadow:0 24px 70px rgba(0,0,0,.5)}
.login-box::before{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;background:linear-gradient(135deg,rgba(96,242,255,.55),transparent 30%,rgba(255,94,219,.45),rgba(255,215,111,.4));-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;opacity:.9;pointer-events:none}
.brand-mark{width:56px;height:56px;margin:0 auto 1rem;border-radius:18px;position:relative;background:linear-gradient(135deg,rgba(96,242,255,.9),rgba(140,107,255,.92));box-shadow:0 0 30px rgba(96,242,255,.4),inset 0 0 22px rgba(255,255,255,.22);overflow:hidden}
.brand-mark::before,.brand-mark::after{content:"";position:absolute;inset:12px;border-radius:12px;border:1px solid rgba(255,255,255,.34);animation:markSpin 4.8s linear infinite}
.brand-mark::after{inset:8px;opacity:.58;animation:markSpinReverse 6.2s linear infinite}
@keyframes markSpin{from{transform:rotate(16deg)}to{transform:rotate(376deg)}}
@keyframes markSpinReverse{from{transform:rotate(-12deg)}to{transform:rotate(-372deg)}}
.login-box h1{font-size:1.3rem;margin-bottom:.5rem;letter-spacing:.04em;background:linear-gradient(135deg,#fff,#8deef7 44%,#ffc6f1 78%,#ffe598);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.login-box p{color:var(--muted);font-size:.85rem;margin-bottom:1.6rem;letter-spacing:.02em}
input{width:100%;padding:.8rem 1rem;background:rgba(7,11,27,.46);border:1px solid rgba(255,255,255,.14);border-radius:12px;color:var(--text);font-size:.9rem;outline:none;margin-bottom:1rem;transition:border-color .2s,box-shadow .2s;backdrop-filter:blur(14px);box-shadow:inset 0 1px 0 rgba(255,255,255,.08)}
input:-webkit-autofill,input:-webkit-autofill:focus,input:-webkit-autofill:hover{-webkit-text-fill-color:var(--text)!important;background-color:rgba(18,24,48,.72)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.08)!important;-webkit-box-shadow:0 0 0 1000px rgba(18,24,48,.72) inset,inset 0 1px 0 rgba(255,255,255,.08)!important;caret-color:var(--text)}
input:focus{border:1px solid transparent;background-image:linear-gradient(rgba(7,11,27,.58),rgba(7,11,27,.58)),linear-gradient(90deg,var(--cyan),var(--violet),var(--pink),var(--gold),var(--cyan));background-origin:border-box;background-clip:padding-box,border-box;background-size:100% 100%,300% 100%;animation:loginFieldFlow 2.2s linear infinite;box-shadow:0 0 0 3px rgba(96,242,255,.14),0 0 24px rgba(96,242,255,.22),inset 0 1px 0 rgba(255,255,255,.12)}
@keyframes loginFieldFlow{to{background-position:0 0,300% 0}}
button{width:100%;color:#050815;border:none;border-radius:12px;padding:.8rem;font-size:.95rem;font-weight:700;cursor:pointer;background:linear-gradient(135deg,var(--cyan),#d6fbff 52%,var(--gold));box-shadow:0 18px 36px rgba(96,242,255,.28);transition:transform .18s ease,box-shadow .18s ease}
button:hover{transform:translateY(-2px);box-shadow:0 22px 44px rgba(96,242,255,.4)}
button:disabled{opacity:.5;cursor:not-allowed;transform:none}
.msg{padding:.5rem .75rem;border-radius:10px;font-size:.8rem;margin-top:.75rem;display:none}
.msg.err{display:block;background:rgba(127,29,29,.5);color:#fecaca;border:1px solid rgba(239,68,68,.5)}
.top-tools{position:absolute;top:14px;right:14px;display:flex;align-items:center;gap:8px;z-index:3}
.lang-btn,.theme-btn{position:static;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14);color:var(--text);font-size:12px;padding:5px 12px;border-radius:999px;cursor:pointer;font-weight:600;width:auto;min-width:0;box-shadow:none;line-height:1.2}
.theme-btn{padding:5px 10px;font-size:14px}
.lang-btn:hover,.theme-btn:hover{transform:translateY(-1px);box-shadow:none}
@keyframes spin{to{transform:translate(-50%,-50%) rotate(360deg)}}
@keyframes pulse{50%{scale:1.08;opacity:.68}}


/* iOS26 light — admin login follows localStorage admin_theme; dark defaults untouched */
body[data-theme="light"]{--cyan:#007aff;--violet:#5856d6;--pink:#ff2d55;--gold:#ff9f0a;--text:#1c1c1e;--muted:#6b6b70;--line:rgba(60,60,67,.12);--strong:#000000;--faint:#8e8e93;--inner:rgba(255,255,255,.72);scrollbar-color:rgba(0,122,255,.28) rgba(120,120,128,.08);background:radial-gradient(circle at 16% 10%,rgba(0,122,255,.05),transparent 30%),radial-gradient(circle at 84% 8%,rgba(88,86,214,.04),transparent 28%),radial-gradient(circle at 50% 92%,rgba(0,0,0,.02),transparent 32%),linear-gradient(160deg,#f2f3f7 0%,#e9ebf0 48%,#f4f5f8 100%)}
body[data-theme="light"]::before{background:linear-gradient(rgba(60,60,67,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(60,60,67,.05) 1px,transparent 1px);background-size:44px 44px;opacity:.55}
body[data-theme="light"] .orb{opacity:.1;filter:blur(28px);background:conic-gradient(from 160deg,rgba(0,122,255,.55),rgba(88,86,214,.45),rgba(255,45,85,.28),rgba(0,122,255,.55))}
body[data-theme="light"] .login-box{background:linear-gradient(180deg,rgba(255,255,255,.78),rgba(255,255,255,.58));border-color:rgba(60,60,67,.12);box-shadow:0 16px 40px rgba(0,0,0,.08);backdrop-filter:blur(28px) saturate(160%);-webkit-backdrop-filter:blur(28px) saturate(160%)}
body[data-theme="light"] .login-box::before{background:linear-gradient(135deg,rgba(255,255,255,.8),transparent 42%,rgba(0,122,255,.14),rgba(88,86,214,.1));opacity:.55}
body[data-theme="light"] .brand-mark{background:linear-gradient(135deg,#0a84ff,#007aff);box-shadow:0 4px 18px rgba(0,122,255,.28),inset 0 1px 0 rgba(255,255,255,.35)}
body[data-theme="light"] .login-box h1{background:linear-gradient(135deg,#1d1d1f,#3a3a3c 70%,#636366);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
body[data-theme="light"] input{background:rgba(255,255,255,.72);border:1px solid rgba(60,60,67,.14);color:#1c1c1e;-webkit-text-fill-color:#1c1c1e;box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}
body[data-theme="light"] input:focus{border:1px solid rgba(0,122,255,.45);background-image:none;background:rgba(255,255,255,.86);box-shadow:0 0 0 4px rgba(0,122,255,.14);animation:none}
body[data-theme="light"] input:-webkit-autofill,body[data-theme="light"] input:-webkit-autofill:focus,body[data-theme="light"] input:-webkit-autofill:hover{-webkit-text-fill-color:#1c1c1e!important;box-shadow:0 0 0 1000px rgba(255,255,255,.86) inset!important}
body[data-theme="light"] button{color:#fff;background:linear-gradient(180deg,#0a84ff 0%,#007aff 100%);box-shadow:0 4px 14px rgba(0,122,255,.28),inset 0 1px 0 rgba(255,255,255,.28)}
body[data-theme="light"] button:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(0,122,255,.32),inset 0 1px 0 rgba(255,255,255,.32)}
body[data-theme="light"] .lang-btn,body[data-theme="light"] .theme-btn{background:rgba(120,120,128,.12);border-color:rgba(60,60,67,.14);color:#1c1c1e;box-shadow:none}
body[data-theme="light"] .msg.err{background:rgba(254,226,226,.85);color:#b91c1c;border-color:rgba(239,68,68,.35)}
body[data-theme="light"]::-webkit-scrollbar-track{background:rgba(120,120,128,.08)}
body[data-theme="light"]::-webkit-scrollbar-thumb{background:linear-gradient(180deg,rgba(0,122,255,.4),rgba(88,86,214,.32));border-color:rgba(255,255,255,.5)}
""" + _STILL_DECOR_CSS + """
</style>
</head>
<body>
<div class="orb"></div>
<div class="login-box">
<div class="top-tools">
<button type="button" class="theme-btn" id="theme-toggle" onclick="toggleTheme()" title="Theme" aria-label="Theme">&#127769;</button>
<button type="button" class="lang-btn" id="lang-toggle" onclick="toggleLang()">&#127760; EN</button>
</div>
<div class="brand-mark" aria-hidden="true"></div>
<h1>Ciallo Ms-365 OpenAI Proxy</h1>
<p id="login-desc" data-i18n="login_desc">输入管理员密码以继续</p>
<input id="pw" type="password" autocomplete="off" placeholder="API Key / 密码" autofocus onkeydown="if(event.key==='Enter')doLogin()">
<button id="btn" onclick="doLogin()" data-i18n="login_btn">登录</button>
<div id="msg" class="msg"></div>
</div>
<script>
const i18n={
  zh:{login_desc:'输入管理员密码以继续',login_btn:'登录',placeholder:'API Key / 密码',login_failed:'登录失败',network_error:'网络错误',wrong_password:'密码错误'},
  en:{login_desc:'Enter admin password to continue',login_btn:'Login',placeholder:'API Key / Password',login_failed:'Login failed',network_error:'Network error',wrong_password:'Wrong password'}
};
let lang=localStorage.getItem('lang')||'zh';
function t(k){return i18n[lang][k]||k}
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function applyLang(){
  const btn=document.getElementById('lang-toggle');
  btn.innerHTML=lang==='zh'?'&#127760; EN':'&#127760; 中文';
  document.querySelectorAll('[data-i18n]').forEach(el=>{const k=el.getAttribute('data-i18n');if(i18n[lang][k])el.textContent=i18n[lang][k]});
  document.getElementById('pw').placeholder=t('placeholder');
}
function toggleLang(){lang=lang==='zh'?'en':'zh';localStorage.setItem('lang',lang);applyLang()}

function applyTheme(){
  const th=localStorage.getItem('admin_theme')||'dark';
  document.body.setAttribute('data-theme',th);
  const b=document.getElementById('theme-toggle');
  if(b){
    b.innerHTML=th==='light'?'&#9728;':'&#127769;';
    b.title=th==='light'?'Light':'Dark';
  }
}
function toggleTheme(){
  const th=(localStorage.getItem('admin_theme')||'dark')==='light'?'dark':'light';
  localStorage.setItem('admin_theme',th);
  applyTheme();
}
applyTheme();
applyLang();
async function doLogin(){
  const pw=document.getElementById('pw').value;
  const btn=document.getElementById('btn');
  const msg=document.getElementById('msg');
  btn.disabled=true;msg.className='msg';msg.textContent='';
  try{
    const r=await fetch('/admin/login',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
    const d=await r.json();
    if(r.ok){location.reload()}else{msg.className='msg err';msg.textContent=d.error?.message||t('login_failed')}
  }catch(e){msg.className='msg err';msg.textContent=t('network_error')}
  finally{btn.disabled=false}
}
</script>
</body>
</html>"""
