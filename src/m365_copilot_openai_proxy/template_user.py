from __future__ import annotations

from .template_assets import _GLASS_SELECT_CSS, _GLASS_SELECT_JS

_USER_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ciallo Ms-365 Copilot 代理 · 用户</title>
<style>
:root{--cyan:#60f2ff;--violet:#8c6bff;--pink:#ff5edb;--gold:#ffd76f;--muted:#9aa7d1;--line:rgba(108,137,255,.24);--strong:#eaf0ff;--faint:#8a97c4;--inner:rgba(9,14,34,.66);--inner-border:rgba(108,137,255,.2);--text:#f3f6ff;--card:linear-gradient(180deg,rgba(13,19,45,.82),rgba(7,10,24,.76));--bg:radial-gradient(circle at 18% 12%,rgba(96,242,255,.16),transparent 26%),radial-gradient(circle at 84% 10%,rgba(140,107,255,.2),transparent 24%),radial-gradient(circle at 50% 92%,rgba(255,94,219,.14),transparent 26%),linear-gradient(135deg,#040612 0%,#090d1f 45%,#03050d 100%);--chip:rgba(255,255,255,.06);--chip-border:rgba(255,255,255,.14)}
body[data-theme="light"]{--muted:#5b6785;--line:rgba(99,102,180,.22);--strong:#243049;--faint:#7581a3;--inner:rgba(255,255,255,.72);--inner-border:rgba(99,102,180,.22);--text:#1f2740;--card:linear-gradient(180deg,rgba(255,255,255,.9),rgba(244,247,253,.84));--bg:radial-gradient(circle at 18% 12%,rgba(96,180,242,.16),transparent 28%),radial-gradient(circle at 84% 10%,rgba(140,107,255,.14),transparent 26%),radial-gradient(circle at 50% 92%,rgba(255,150,220,.12),transparent 28%),linear-gradient(135deg,#edf3fb 0%,#e4ebf6 48%,#eef2f8 100%);--chip:rgba(99,102,180,.08);--chip-border:rgba(99,102,180,.22)}
*{box-sizing:border-box}
html{scrollbar-gutter:stable;scrollbar-color:rgba(96,242,255,.45) rgba(8,13,32,.22);scrollbar-width:thin}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:rgba(8,13,32,.22);border-radius:999px}
::-webkit-scrollbar-thumb{background:linear-gradient(180deg,rgba(96,242,255,.58),rgba(140,107,255,.48));border-radius:999px;border:2px solid rgba(8,13,32,.4)}
::-webkit-scrollbar-thumb:hover{background:linear-gradient(180deg,rgba(96,242,255,.78),rgba(255,94,219,.58))}
body{margin:0;font-family:"Segoe UI","PingFang SC","Microsoft YaHei",-apple-system,sans-serif;color:var(--text);line-height:1.5;min-height:100vh;background:var(--bg);position:relative;transition:background .25s,color .25s}
body::before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(rgba(255,255,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 1px);background-size:44px 44px;mask-image:radial-gradient(circle at center,black 45%,transparent 92%);z-index:0}
.orb{position:fixed;width:380px;height:380px;border-radius:50%;filter:blur(16px);background:conic-gradient(from 160deg,var(--cyan),var(--pink),var(--violet),var(--cyan));top:50%;left:50%;transform:translate(-50%,-50%);animation:loginSpin 11s linear infinite,loginPulse 3.8s ease-in-out infinite;opacity:.32;z-index:0;pointer-events:none}
.wrap{position:relative;z-index:1;max-width:900px;margin:0 auto;padding:1.5rem 1rem 3rem}
h1{font-size:1.4rem;margin:0;background:linear-gradient(135deg,#fff,#8deef7 44%,#ffc6f1 78%,#ffe598);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.card{position:relative;background:var(--card);border:1px solid var(--line);border-radius:24px;padding:1.5rem;margin-bottom:10px;backdrop-filter:blur(20px);box-shadow:0 24px 70px rgba(0,0,0,.38);overflow:hidden}
.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.3);backdrop-filter:blur(18px) saturate(145%);-webkit-backdrop-filter:blur(18px) saturate(145%);display:flex;align-items:center;justify-content:center;z-index:1000;padding:1rem}
.modal-card{position:relative;width:360px;max-width:92vw;border-radius:14px;padding:1.25rem;background:rgba(15,23,42,.3);border:1px solid rgba(96,242,255,.28);box-shadow:0 24px 70px rgba(0,0,0,.36),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(22px) saturate(150%);-webkit-backdrop-filter:blur(22px) saturate(150%)}
body[data-theme="light"] .modal-card{background:rgba(255,255,255,.3);border-color:rgba(99,102,180,.22)}
.card::before{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;background:linear-gradient(135deg,rgba(96,242,255,.42),transparent 30%,rgba(255,94,219,.32),rgba(255,215,111,.24));-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;opacity:.75;pointer-events:none}
.card:has(details[open])::after{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,transparent,rgba(96,242,255,.85),rgba(255,94,219,.58),transparent);background-size:240% 100%;animation:flowBorder 2.4s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
details summary{min-height:42px;display:flex;align-items:center;position:relative;border-radius:14px;padding:.15rem .25rem;transition:background .2s}
details[open] summary{background:linear-gradient(135deg,rgba(96,242,255,.04),rgba(140,107,255,.04))}
@keyframes flowBorder{to{background-position:240% 0}}
.card h2{font-size:1rem;margin:0 0 .8rem;color:var(--strong)}
#login-card{width:380px;max-width:calc(100vw - 32px);margin:8vh auto 1.5rem;text-align:center;padding:2.6rem;border-radius:28px}
#login-card .brand-mark{width:56px;height:56px;margin:0 auto 1rem;border-radius:18px;position:relative;background:linear-gradient(135deg,rgba(96,242,255,.9),rgba(140,107,255,.92));box-shadow:0 0 30px rgba(96,242,255,.4),inset 0 0 22px rgba(255,255,255,.22);overflow:hidden}
#login-card .brand-mark:before,#login-card .brand-mark:after{content:"";position:absolute;inset:12px;border-radius:12px;border:1px solid rgba(255,255,255,.34);animation:userMarkSpin 4.8s linear infinite}
#login-card .brand-mark:after{inset:8px;opacity:.58;animation:userMarkSpinReverse 6.2s linear infinite}
#login-card input{background:rgba(10,16,36,.46)!important;border:1px solid rgba(255,255,255,.14);backdrop-filter:blur(14px);box-shadow:inset 0 1px 0 rgba(255,255,255,.08);-webkit-text-fill-color:#e2e8f0;-webkit-box-shadow:0 0 0 1000px rgba(10,16,36,.46) inset;transition:background-color 0s,color 0s}
#login-card input:focus{border:1px solid transparent!important;background-image:linear-gradient(rgba(10,16,36,.58),rgba(10,16,36,.58)),linear-gradient(90deg,var(--cyan),var(--violet),var(--pink),var(--gold),var(--cyan))!important;background-origin:border-box!important;background-clip:padding-box,border-box!important;background-size:100% 100%,300% 100%!important;animation:fieldFlow 2.2s linear infinite!important}
#login-card input:-webkit-autofill,#login-card input:-webkit-autofill:focus,#login-card input:-webkit-autofill:hover{-webkit-text-fill-color:#e2e8f0!important;background-color:rgba(18,24,48,.72)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.08)!important;-webkit-box-shadow:0 0 0 1000px rgba(18,24,48,.72) inset,inset 0 1px 0 rgba(255,255,255,.08)!important;caret-color:#e2e8f0}
@keyframes userMarkSpin{from{transform:rotate(16deg)}to{transform:rotate(376deg)}}
@keyframes userMarkSpinReverse{from{transform:rotate(-12deg)}to{transform:rotate(-372deg)}}
label{display:block;font-size:.85rem;color:var(--muted);margin:.6rem 0 .3rem}
input,select,textarea{width:100%;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--text);padding:.6rem .7rem;font-size:.9rem;font-family:inherit;transition:border-color .2s,box-shadow .2s}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--cyan);box-shadow:0 0 0 3px rgba(96,242,255,.16)}
select:focus{transition:none!important;animation:none!important;box-shadow:0 0 0 2px rgba(96,242,255,.12),inset 0 1px 0 rgba(255,255,255,.08)!important}
textarea{resize:vertical;min-height:70px;font-family:monospace}
#acct-token{height:75px;min-height:75px;max-height:75px;resize:none;overflow:hidden;line-height:1.45;box-sizing:border-box;display:block}
button{color:#050815;border:none;border-radius:10px;padding:.55rem 1rem;font-size:.85rem;font-weight:800;cursor:pointer;margin-top:.6rem;background:linear-gradient(135deg,var(--cyan),#d6fbff 52%,var(--gold));box-shadow:0 10px 24px rgba(96,242,255,.22);transition:transform .18s ease,box-shadow .18s ease;text-shadow:none}
button:hover{transform:translateY(-2px);box-shadow:0 16px 32px rgba(96,242,255,.34)}
button:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn-ghost{background:var(--chip);background-image:none;color:var(--strong);border:1px solid var(--chip-border);box-shadow:none}
.compact-action{width:58px;margin:0;padding:.2rem .55rem!important;font-size:.75rem!important;text-align:center;display:inline-flex;align-items:center;justify-content:center}
.call-param-box{background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--text);padding:.6rem .7rem;font-size:.9rem;box-shadow:inset 0 1px 0 rgba(255,255,255,.08)}
.call-param-row{display:grid;grid-template-columns:72px minmax(0,1fr) 58px;align-items:center;gap:.5rem;font-size:.8rem;color:var(--muted);margin-bottom:.4rem}
.call-param-row:last-child{margin-bottom:0}
.call-param-row code{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#a5b4fc}
.account-main>.row button,.account-main .action-row button,.account-action{width:180px;justify-content:center}
.account-main select{width:180px!important;min-height:38px;background-color:var(--inner);border:1px solid var(--inner-border);color:var(--text);box-shadow:inset 0 1px 0 rgba(255,255,255,.08);transition:border-color .2s,box-shadow .2s}
.account-main select:focus{border-color:var(--cyan);box-shadow:0 0 0 2px rgba(96,242,255,.12),inset 0 1px 0 rgba(255,255,255,.1)!important;animation:none!important;transition:none!important}
select option{transition:none!important}
select option:checked{background:#1e40af;color:#fff}
@keyframes userSelectGlow{50%{box-shadow:0 0 0 3px rgba(96,242,255,.22),0 0 30px rgba(255,94,219,.2),inset 0 1px 0 rgba(255,255,255,.14)}}
.account-main select option{background:#10162f;color:#f3f6ff}
body[data-theme="light"] .account-main select option{background:#fff;color:#243049}
""" + _GLASS_SELECT_CSS + """
.account-main .glass-select.open{z-index:2000}
.account-main .tone-select+.glass-select .glass-select-menu{left:0;right:auto;width:100%;max-width:100%;min-width:100%;overflow-x:hidden;overflow-y:auto}
.account-main textarea{margin-top:.65rem}
.action-row{margin-top:.8rem;margin-bottom:.15rem}
.row{display:flex;gap:.5rem;align-items:center}
.login-row{align-items:stretch;margin-top:.6rem}
.login-row #login-btn{width:100%;margin:0}
.login-row #login-msg{position:absolute;left:2.6rem;right:2.6rem;bottom:1.15rem;text-align:center}
.row>*{margin-top:0}
.pill{display:inline-block;font-size:.75rem;padding:.15rem .5rem;border-radius:99px;background:rgba(255,255,255,.08);color:#cbd5e1}
.pill.ok{background:rgba(6,95,70,.6);color:#d1fae5}
.pill.bad{background:rgba(127,29,29,.6);color:#fee2e2}
.msg{font-size:.8rem;margin-left:.5rem;opacity:0;transition:opacity .2s;color:#86efac}
#tone-msg{display:inline-flex;align-items:center;justify-content:center;min-width:42px;height:18px;margin-left:0;padding:0 .45rem;border-radius:999px;background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.18);font-size:.72rem;font-weight:700;line-height:1;color:#86efac;box-shadow:inset 0 1px 0 rgba(255,255,255,.08);transform:translateY(1px);transition:opacity .22s ease}
.hint{font-size:.8rem;color:var(--muted);margin-bottom:.4rem}
.section-title{display:flex;flex-direction:column;align-items:flex-start;gap:.35rem;margin:1rem 0 .45rem;font-size:1rem;color:var(--strong);font-weight:700;letter-spacing:.01em}
.section-title:before{content:"";display:block;width:46px;height:1px;border-radius:99px;background:linear-gradient(90deg,var(--cyan),var(--violet),transparent);box-shadow:0 0 10px rgba(96,242,255,.35)}
input:focus,textarea:focus{border:1px solid transparent!important;background-image:linear-gradient(var(--inner),var(--inner)),linear-gradient(90deg,var(--cyan),var(--violet),var(--pink),var(--gold),var(--cyan))!important;background-origin:border-box!important;background-clip:padding-box,border-box!important;background-size:100% 100%,300% 100%!important;background-position:0 0,0 0!important;box-shadow:0 0 0 3px rgba(96,242,255,.12),0 0 24px rgba(96,242,255,.2),inset 0 1px 0 rgba(255,255,255,.08)!important;animation:fieldFlow 2.2s linear infinite!important;outline:none}
select:focus{border-color:var(--cyan)!important;background-image:none!important;animation:none!important;transition:none!important;box-shadow:0 0 0 2px rgba(96,242,255,.12),inset 0 1px 0 rgba(255,255,255,.08)!important;outline:none}
@keyframes fieldFlow{to{background-position:0 0,300% 0}}
.qs-link{color:var(--cyan);font-weight:700;text-decoration:none;padding:.02rem .28rem;border-radius:6px;background:linear-gradient(135deg,rgba(96,242,255,.12),rgba(140,107,255,.12));border:1px solid rgba(96,242,255,.28);transition:box-shadow .18s,background .18s}
.qs-link:hover{text-decoration:none;background:linear-gradient(135deg,rgba(96,242,255,.22),rgba(255,94,219,.18));box-shadow:0 0 14px rgba(96,242,255,.28)}
body[data-theme="light"] .qs-link{color:#0e7490;border-color:rgba(14,116,144,.3);background:linear-gradient(135deg,rgba(14,116,144,.1),rgba(124,58,237,.1))}
body[data-theme="light"] .hint,body[data-theme="light"] label,body[data-theme="light"] .call-param-row,body[data-theme="light"] .status-line{color:#4b5878}
body[data-theme="light"] code,body[data-theme="light"] .call-param-row code{color:#4f46e5}
body[data-theme="light"] .pill{background:rgba(99,102,180,.12);color:#334155}
body[data-theme="light"] .pill.ok{background:rgba(220,252,231,.88);color:#166534}
body[data-theme="light"] .pill.bad{background:rgba(254,226,226,.9);color:#991b1b}
body[data-theme="light"] .msg{color:#15803d}
body[data-theme="light"] .api-row>span:first-child{color:var(--text)}
body[data-theme="light"] .account-side{background:linear-gradient(180deg,rgba(255,255,255,.72),rgba(240,245,255,.62));border-color:rgba(99,102,180,.24);box-shadow:inset 0 1px 0 rgba(255,255,255,.86),0 12px 32px rgba(80,100,160,.12)}
body[data-theme="light"] .status-line,body[data-theme="light"] .status-line:first-child{border-color:rgba(99,102,180,.18)}
.api-info{margin-top:.75rem;padding:.75rem;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;font-family:monospace;font-size:.8rem;line-height:1.6}
.api-grp{font-weight:700;color:var(--strong);margin:.5rem 0 .25rem;font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:.78rem}
.api-grp:first-child{margin-top:0}
.api-row{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.12rem 0}
.api-row>span:first-child{color:#f3f6ff;white-space:pre}
.api-row>span:last-child{color:var(--faint);text-align:right;font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:.74rem}
.account-card{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:10px;align-items:start;min-height:600px;overflow:visible}
.account-card:has(.glass-select.open){z-index:2000}
.user-default-grid{display:grid;grid-template-columns:repeat(4,minmax(0,180px));gap:1rem;align-items:end;margin-top:.25rem}
.user-config-field{display:flex;flex-direction:column;gap:.35rem;color:var(--strong);font-size:.86rem;font-weight:800;min-width:0}
.user-config-field input{width:100%;height:38px;box-sizing:border-box;padding:9px 14px;background:rgba(96,242,255,.08);border:1px solid rgba(96,242,255,.45);border-radius:14px;color:var(--strong);font-size:.86rem;font-weight:700;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 8px 20px rgba(0,0,0,.16)}
.user-default-grid .glass-select{width:100%!important;min-width:0!important;height:38px!important;margin-left:0!important}
.user-default-grid .glass-select-trigger{height:38px!important;width:100%!important;box-sizing:border-box!important;padding:9px 34px 9px 14px!important;border-radius:14px!important;font-size:.86rem!important;font-weight:700!important}
.account-side{position:sticky;top:10px;background:linear-gradient(180deg,rgba(96,242,255,.09),rgba(140,107,255,.08));border:1px solid rgba(96,242,255,.22);border-radius:18px;padding:1rem;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 12px 32px rgba(0,0,0,.22);overflow:hidden}
.account-side:before{content:"";position:absolute;inset:-40%;background:conic-gradient(from 180deg,transparent,rgba(96,242,255,.22),transparent,rgba(255,94,219,.16),transparent);animation:spin 8s linear infinite;opacity:.55;pointer-events:none}
.account-side>*{position:relative;z-index:1}
.status-grid{display:grid;gap:0;margin-top:.1rem}
.status-line{display:flex;justify-content:space-between;gap:.8rem;font-size:.78rem;color:var(--muted);border-bottom:1px solid rgba(255,255,255,.08);padding:.5rem 0}
.status-line:first-child{border-top:1px solid rgba(255,255,255,.08)}
.status-line b{color:var(--strong);font-weight:700;text-align:right;word-break:break-word}
.status-mark{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;padding:0;border-radius:50%;font-size:.55rem;font-weight:900;color:#050815;border:none;background:linear-gradient(135deg,var(--cyan),#d6fbff 52%,var(--gold));box-shadow:0 4px 10px rgba(96,242,255,.24),inset 0 1px 0 rgba(255,255,255,.4);line-height:1;position:relative;overflow:hidden}
.status-mark:before{content:"";position:absolute;inset:0;border-radius:inherit;background:linear-gradient(180deg,rgba(255,255,255,.32),transparent 55%);pointer-events:none}
.status-mark:after{display:none}
.status-mark.ok{background:linear-gradient(135deg,var(--cyan),#d6fbff 52%,var(--gold));color:#050815}
.status-mark.bad{background:linear-gradient(135deg,#64748b,#475569);color:#f8fafc;box-shadow:0 4px 10px rgba(0,0,0,.22),inset 0 1px 0 rgba(255,255,255,.18)}
@keyframes statusBreath{50%{box-shadow:inset 0 1px 0 rgba(255,255,255,.55),inset 0 -9px 16px rgba(0,0,0,.14),0 0 26px rgba(255,255,255,.16)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes loginSpin{to{transform:translate(-50%,-50%) rotate(360deg)}}
@keyframes loginPulse{50%{scale:1.08;opacity:.48}}
@media(max-width:760px){.account-card{grid-template-columns:1fr;min-height:auto}.account-side{position:relative;top:auto}}
.hidden{display:none}
a{color:var(--cyan);text-decoration:none}
a:hover{text-decoration:underline}
code{color:#a5b4fc}
</style>
</head>
<body>
<div class="orb" aria-hidden="true"></div>
<div class="wrap">
  <div class="top">
    <h1 data-i18n="title">Ciallo Ms-365 Copilot 代理 · 用户</h1>
    <div style="display:flex;gap:.5rem;align-items:center">
      <button class="btn-ghost" id="theme-toggle" onclick="toggleTheme()">&#127769;</button>
      <button class="btn-ghost" id="lang-toggle" onclick="toggleLang()">&#127760; EN</button>
    </div>
  </div>

  <div id="login-card" class="card">
    <div class="brand-mark" aria-hidden="true"></div>
    <h2 data-i18n="login_title">登录</h2>
    <div class="hint" data-i18n="login_hint">输入管理员分配给你的用户名与密码，管理自己的对话模式、提示词与账户 Token。</div>
    <input id="username" type="text" autocomplete="off" data-i18n-ph="username_ph" placeholder="用户名" onkeydown="if(event.key==='Enter')doLogin()">
    <input id="password" type="password" autocomplete="off" data-i18n-ph="password_ph" placeholder="密码" style="margin-top:.5rem" onkeydown="if(event.key==='Enter')doLogin()">
    <div class="row login-row"><button id="login-btn" onclick="doLogin()" data-i18n="login_btn">登录</button><span id="login-msg" class="msg"></span></div>
  </div>

  <div id="app" class="hidden">
    <div class="card">
      <h2 data-i18n="qs_title">快速使用指南</h2>
      <div class="hint" style="line-height:1.7" data-i18n-html="qs_body">1. 安装 <a href="https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/multi/get_token.user.js" target="_blank" rel="noopener" class="qs-link">油猴脚本</a> 并打开 <a href="https://m365.cloud.microsoft/chat" target="_blank" rel="noopener" class="qs-link">M365 Copilot</a>，随意发一条消息触发 WebSocket。<br>2. 在脚本面板点击「一键推送」或 手动「推送/复制 Token」，「推送 Cookie」均可。<br>3. 在账户卡片中复制 Base URL 与 API Key，填入 OpenAI 兼容客户端即可使用。</div>
      <details style="margin-top:.75rem;cursor:pointer">
        <summary style="font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
          <span data-i18n="endpoints_title">OpenAI 兼容接口</span>
          <span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
        </summary>
        <div class="api-info">
          <div class="api-grp" data-i18n="api_grp_public">公共接口</div>
          <div class="api-row"><span>GET&nbsp; /healthz</span><span data-i18n="api_healthz">健康检查</span></div>
          <div class="api-grp" data-i18n="api_grp_v1">OpenAI 兼容接口</div>
          <div class="api-row"><span>POST /v1/chat/completions</span><span data-i18n="api_chat">OpenAI 兼容对话</span></div>
          <div class="api-row"><span>POST /v1/messages</span><span data-i18n="api_messages">Anthropic 兼容消息</span></div>
          <div class="api-row"><span>GET&nbsp; /v1/models</span><span data-i18n="api_models">模型列表</span></div>
          <div class="api-row"><span>POST /v1/responses</span><span data-i18n="api_responses">Responses 接口</span></div>
        </div>
      </details>
    </div>
    <div class="card account-card">
      <div class="account-main">
        <div style="display:flex;align-items:center;gap:20px;margin-bottom:.75rem">
          <h2 data-i18n="account_title" style="margin:0;height:32px;display:flex;align-items:center;line-height:1">账户控制台</h2>
          <span id="account-console-actions"></span>
        </div>
        <div id="account-info"></div>
        <label class="section-title" data-i18n="call_params_title">调用参数</label>
        <div class="call-param-box">
          <div class="call-param-row"><span>Base URL:</span><code id="base-url"></code><button onclick="copyBaseUrl(this)" class="btn-ghost compact-action" data-i18n="copy_base">复制</button></div>
          <div class="call-param-row"><span>API Key:</span><code id="my-key"></code><button onclick="copyMyKey(this)" class="btn-ghost compact-action" data-i18n="copy_key">复制</button></div>
        </div>
        <div class="row" style="margin-top:.6rem"><button onclick="regenMyKey(this)" data-i18n="regen_my_key">重置 API Key</button><span id="regen-msg" class="msg"></span></div>
        <div style="display:flex;align-items:center;gap:20px;margin:1rem 0 .45rem"><label class="section-title" data-i18n="mode_profile_title" style="margin:0">默认配置</label><span id="tone-msg" class="msg"></span></div>
        <div class="user-default-grid">
          <label class="user-config-field"><span data-i18n="tone_title">对话模式</span><select id="tone" class="tone-select" onchange="saveTone()"></select></label>
          <label class="user-config-field"><span data-i18n="run_permission_label">运行权限</span><select id="user-run-permission" class="tone-select" onchange="saveTone()"></select></label>
          <label class="user-config-field"><span data-i18n="model_alias_label">模型别名</span><input id="user-model-alias" onchange="saveTone()"></label>
          <label class="user-config-field"><span data-i18n="user_time_zone_label">更改时区</span><input id="user-time-zone" onchange="saveTone()"></label>
        </div>
        <label class="section-title" data-i18n="manual_update_title">手动更新</label>
        <div class="row action-row"><button onclick="pushToken(this)" data-i18n="push_token_btn">更新 Token</button><span id="token-msg" class="msg"></span></div>
        <textarea id="acct-token" data-i18n-ph="push_token_ph" placeholder="粘贴 access_token 值或完整 wss:// URL。若尚未绑定账户，将自动创建并绑定。&#10;access_token / wss://substrate.office.com/..."></textarea>
      </div>
      <div class="account-side" id="account-status-panel"></div>
    </div>

    <div class="card">
      <details id="tool-prompt-details" style="cursor:pointer">
      <summary style="font-size:1rem;font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
      <span data-i18n="tool_prompt_title">提示词增强</span>
      <span style="font-size:.7rem;color:#475569;margin-left:auto" data-i18n="click_expand">点击展开</span>
      </summary>
      <div style="margin-top:.75rem">
      <div class="hint" data-i18n="tool_prompt_hint">追加到工具调用提示词后的自定义指令，仅作用于你自己的 Key。留空则不追加。</div>
      <textarea id="tool-prompt"></textarea>
      <div class="row"><button onclick="saveToolPrompt()" data-i18n="save">保存</button><span id="tool-msg" class="msg"></span></div>
      </div>
      </details>
      <hr style="border:none;border-top:1px solid #334155;margin:1.1rem 0">
      <details id="sys-prompt-details" style="cursor:pointer">
      <summary style="font-size:1rem;font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
      <span data-i18n="sys_prompt_title">系统提示词（高级）</span>
      <span style="font-size:.7rem;color:#475569;margin-left:auto" data-i18n="click_expand">点击展开</span>
      </summary>
      <div style="margin-top:.75rem">
      <div class="hint" data-i18n="sys_prompt_hint">覆盖工具调用的基础系统提示词（定义 tool_call 格式与规则）。改错会导致工具调用失效，仅供高级用户调试。留空则使用内置默认。</div>
      <div id="sys-prompt-locked">
      <button onclick="unlockSysPrompt()" style="background:linear-gradient(135deg,#ef4444,#dc2626)" data-i18n="system_prompt_unlock">解锁编辑</button>
      </div>
      <div id="sys-prompt-editor" style="display:none">
      <textarea id="sys-prompt" style="border-color:#7f1d1d"></textarea>
      <div class="row"><button onclick="saveSysPrompt()" data-i18n="save">保存</button><button class="btn-ghost" onclick="resetSysPrompt()" data-i18n="reset">恢复默认</button><span id="sys-msg" class="msg"></span></div>
      </div>
      </div>
      </details>
    </div>
  </div>
</div>

<script>
const i18n={
  zh:{
    title:'Ciallo Ms-365 Copilot 代理 · 用户',
    login_title:'登录',login_hint:'输入管理员分配给你的用户名与密码，管理自己的对话模式、提示词与账户 Token。',
    qs_title:'快速使用指南',qs_body:'1. 安装 <a href="https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/multi/get_token.user.js" target="_blank" rel="noopener" class="qs-link">油猴脚本</a> 并打开 <a href="https://m365.cloud.microsoft/chat" target="_blank" rel="noopener" class="qs-link">M365 Copilot</a>，随意发一条消息触发 WebSocket。<br>2. 在脚本面板点击「一键推送」或 手动「推送/复制 Token」，「推送 Cookie」均可。<br>3. 在账户卡片中复制 Base URL 与 API Key，填入 OpenAI 兼容客户端即可使用。',
    username_ph:'用户名',password_ph:'密码',login_btn:'登录',login_failed:'用户名或密码错误',network_error:'网络错误',
    account_title:'账户控制台',push_token_label:'推送 / 更新账户 Token',
    push_token_hint:'粘贴 access_token 值或完整 wss:// URL。若尚未绑定账户，将自动创建并绑定。',push_token_ph:'粘贴 access_token 值或完整 wss:// URL。若尚未绑定账户，将自动创建并绑定。\\naccess_token / wss://substrate.office.com/...',
    push_token_btn:'更新 Token',updating_token:'更新中...',saved:'已保存',push_ok:'已更新',token_update_failed:'更新失败',
    mode_profile_title:'默认配置',user_tone_hint:'保存后仅影响当前用户，不再跟随全局模板变化。',call_params_title:'调用参数',manual_update_title:'手动更新',status_panel_title:'账户状态',status_account:'账户',status_login:'登录',status_refresh:'刷新',status_valid:'有效',status_expire:'过期',status_remaining:'剩余',status_yes:'是',status_no:'否',status_unknown:'未知',
    tone_title:'对话模式',run_permission_label:'运行权限',run_permission_inherit:'继承全局',run_permission_read_only:'只读',run_permission_full:'完全',user_time_zone_label:'更改时区',tool_prompt_title:'提示词增强',system_prompt_title:'系统提示词',prompt_card_title:'提示词',click_expand:'点击展开',
    tool_prompt_hint:'追加到工具调用提示词后的自定义指令，仅作用于你自己的 Key。留空则不追加。',
    save:'保存',reset:'恢复默认',
    sys_prompt_title:'系统提示词（高级）',
    sys_prompt_hint:'覆盖工具调用的基础系统提示词。改错会导致工具调用失效，仅供高级用户调试。留空则使用内置默认。',
    sys_prompt_reset_confirm:'确定要将系统提示词恢复为内置默认吗？当前自定义内容将被清空。',
    system_prompt_unlock:'解锁编辑',
    system_prompt_warn:'警告：系统级提示词定义了工具调用（tool_call）的格式与核心规则。修改不当会直接导致工具调用失效、模型无法读写文件。仅在你清楚自己在做什么时继续。\\n\\n确定要解锁编辑吗？',
    endpoints_title:'OpenAI 兼容接口',endpoints_hint:'在你的 OpenAI 兼容客户端里填入上面的 Base URL 和你的 API Key。',
    api_grp_public:'公共接口',api_grp_v1:'OpenAI 兼容接口',api_chat:'OpenAI 兼容对话',api_messages:'Anthropic 兼容消息',api_models:'模型列表',api_responses:'Responses 接口',api_healthz:'健康检查',
    copy_base:'复制',copy_key:'复制',key_copied:'已复制',kf_cancel:'取消',confirm_btn:'确认',regen_my_key:'重置 API Key',regen_my_key_hint:'重置后旧密钥立即失效，需要在客户端换成新密钥。账户绑定与历史会话不受影响。',confirm_regen_my_key:'确定重置你的 API Key 吗？旧密钥立即失效，你需要在客户端换成新密钥。',regen_done:'新密钥已生效',regen_running:'重置中...',regen_failed:'重置失败',
    logout:'登出 Microsoft',console_logout:'登出 控制台',change_password:'修改 登录密码',old_password:'当前密码',new_password:'新密码',password_changed:'密码已修改',password_change_failed:'修改失败',logging_out_ms:'登出中...',logout_ok_ms:'已登出',logout_failed_ms:'登出失败',unbind_account:'解绑 Microsoft',unbinding_ms:'解绑中...',unbind_ok_ms:'已解绑',unbind_failed_ms:'解绑失败',unbind_confirm:'确认解绑当前 Microsoft 账户？将同时清除该账户 Token 和 Cookie 状态，之后需要重新推送 Token 才能使用。',unbind_confirm_btn:'确认解绑',displaced_notice:'你的账户绑定已被同一 Microsoft 账号的其他用户推送接管，当前账户已解绑。请重新推送 Token 或联系管理员。',no_account:'尚未绑定账户，推送 Token 后将自动创建。',
    key_name:'名称',bound_account:'绑定账户',token_valid:'有效',token_invalid:'无效/缺失',remaining:'剩余',
  },
  en:{
    title:'Ciallo Ms-365 Copilot Proxy · User',
    login_title:'Login',login_hint:'Enter the username and password assigned by the admin to manage your own conversation mode, prompts and account token.',
    qs_title:'Quick Start',qs_body:'1. Install the <a href="https://gh-proxy.com/https://raw.githubusercontent.com/MurasameCyan/Ciallo-Ms-365-OpenAI-Proxy-Docker/multi/get_token.user.js" target="_blank" rel="noopener" class="qs-link">Tampermonkey script</a> and open <a href="https://m365.cloud.microsoft/chat" target="_blank" rel="noopener" class="qs-link">M365 Copilot</a>, then send any message to trigger the WebSocket.<br>2. Click "One-click Push" / "Push Token" in the script panel, or manually copy the access_token and paste it below to update.<br>3. Copy the Base URL and API Key from the account card into your OpenAI-compatible client.',
    username_ph:'Username',password_ph:'Password',login_btn:'Login',login_failed:'Wrong username or password',network_error:'Network error',
    account_title:'Account Console',push_token_label:'Push / update account token',
    push_token_hint:'Paste the access_token value or the full wss:// URL. If no account is bound yet, one will be created and bound automatically.',push_token_ph:'Paste the access_token value or the full wss:// URL. If no account is bound yet, one will be created and bound automatically.\\naccess_token / wss://substrate.office.com/...',
    push_token_btn:'Update Token',updating_token:'Updating...',saved:'Saved',push_ok:'Updated',token_update_failed:'Update failed',
    mode_profile_title:'Default Config',user_tone_hint:'After saving, this only affects the current user and will no longer follow the global template.',call_params_title:'Call Parameters',manual_update_title:'Manual Update',status_panel_title:'Account Status',status_account:'Account',status_login:'Login',status_refresh:'Refresh',status_valid:'Valid',status_expire:'Expires',status_remaining:'Remaining',status_yes:'Yes',status_no:'No',status_unknown:'Unknown',
    tone_title:'Conversation Mode',run_permission_label:'Run permission',run_permission_inherit:'Inherit global',run_permission_read_only:'Read-only',run_permission_full:'Full',user_time_zone_label:'Change Time Zone',tool_prompt_title:'Prompt Enhancement',system_prompt_title:'System Prompt',prompt_card_title:'Prompts',click_expand:'Click to expand',
    tool_prompt_hint:'Custom instruction appended after the tool-call prompt, applies only to your own key. Leave empty to append nothing.',
    save:'Save',reset:'Restore default',
    sys_prompt_title:'System Prompt (Advanced)',
    sys_prompt_hint:'Overrides the base system prompt for tool calls (defines tool_call format and rules). A wrong edit will break tool calling. For advanced debugging only. Leave empty to use the built-in default.',
    sys_prompt_reset_confirm:'Restore the system prompt to the built-in default? Your current custom content will be cleared.',
    system_prompt_unlock:'Unlock editing',
    system_prompt_warn:'WARNING: the system prompt defines the format and core rules of tool calls (tool_call). An incorrect edit will break tool calling and the model will be unable to read/write files. Continue only if you know what you are doing.\\n\\nUnlock editing?',
    endpoints_title:'OpenAI-compatible',endpoints_hint:'Point your OpenAI-compatible client at the Base URL above with your API key.',
    api_grp_public:'Public',api_grp_v1:'OpenAI-compatible',api_chat:'OpenAI-compatible chat',api_messages:'Anthropic-compatible messages',api_models:'Model list',api_responses:'Responses API',api_healthz:'Health check',
    copy_base:'Copy',copy_key:'Copy',key_copied:'Copied',kf_cancel:'Cancel',confirm_btn:'Confirm',regen_my_key:'Reset API key',regen_my_key_hint:'After reset the old key stops working immediately; update your client with the new key. Account binding and session history are unaffected.',confirm_regen_my_key:'Reset your API key? The old key stops working immediately and you must update your client with the new one.',regen_done:'New key is now active',regen_running:'Resetting...',regen_failed:'Reset failed',
    logout:'Sign out of Microsoft',console_logout:'Sign out Console',change_password:'Change Login Password',old_password:'Current password',new_password:'New password',password_changed:'Password changed',password_change_failed:'Change failed',logging_out_ms:'Signing out...',logout_ok_ms:'Signed out',logout_failed_ms:'Sign out failed',unbind_account:'Unbind Microsoft',unbinding_ms:'Unbinding...',unbind_ok_ms:'Unbound',unbind_failed_ms:'Unbind failed',unbind_confirm:'Unbind the current Microsoft account? This will clear this account token and cookie state. You will need to push a token again before using it.',unbind_confirm_btn:'Unbind',displaced_notice:'Your account binding was taken over by another user pushing the same Microsoft account. This key is now unbound. Push your token again or contact the admin.',no_account:'No account bound yet. Pushing a token will create one automatically.',
    key_name:'Name',bound_account:'Bound account',token_valid:'Valid',token_invalid:'Invalid/Missing',remaining:'Remaining',
  }
};
let lang=localStorage.getItem('lang')||'zh';
let toneOptions=[];
let sysDefault='';
let userTimeZone='';
function t(k){return i18n[lang][k]||k}
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function getKey(){return sessionStorage.getItem('user_api_key')||''}
function authHeaders(){return {'Content-Type':'application/json','Authorization':'Bearer '+getKey()}}
function applyLang(){
  const btn=document.getElementById('lang-toggle');
  btn.innerHTML=lang==='zh'?'&#127760; EN':'&#127760; 中文';
  document.querySelectorAll('[data-i18n]').forEach(el=>{const k=el.getAttribute('data-i18n');if(i18n[lang][k])el.textContent=i18n[lang][k]});
  document.querySelectorAll('[data-i18n-ph]').forEach(el=>{const k=el.getAttribute('data-i18n-ph');if(i18n[lang][k])el.placeholder=i18n[lang][k]});
  document.querySelectorAll('[data-i18n-html]').forEach(el=>{const k=el.getAttribute('data-i18n-html');if(i18n[lang][k])el.innerHTML=i18n[lang][k]});
  renderToneOptions();
}
function toggleLang(){lang=lang==='zh'?'en':'zh';localStorage.setItem('lang',lang);applyLang()}
""" + _GLASS_SELECT_JS + """
function applyTheme(){const theme=localStorage.getItem('user_theme')||'dark';document.body.setAttribute('data-theme',theme);const b=document.getElementById('theme-toggle');if(b)b.innerHTML=theme==='light'?'&#9728;':'&#127769;'}
function toggleTheme(){localStorage.setItem('user_theme',(localStorage.getItem('user_theme')||'dark')==='dark'?'light':'dark');applyTheme()}
function renderToneOptions(){
  const sel=document.getElementById('tone');if(!sel||!toneOptions.length)return;
  const cur=sel.value;
  sel.innerHTML='';
  toneOptions.forEach(o=>{
    const opt=document.createElement('option');
    opt.value=o.value;
    opt.textContent=lang==='zh'?(o.label_zh||o.label):(o.label_en||o.label);
    sel.appendChild(opt);
  });
  if(cur)sel.value=cur;
  initGlassSelect(sel.parentElement);
  refreshGlassSelect(sel);
  renderRunPermissionOptions();
}
function renderRunPermissionOptions(){
  const sel=document.getElementById('user-run-permission');if(!sel)return;
  const cur=sel.value;
  sel.innerHTML='<option value="read_only">'+t('run_permission_read_only')+'</option><option value="full">'+t('run_permission_full')+'</option>';
  sel.value=cur==='read_only'||cur==='full'?cur:'full';
  sel.dataset.glassReady='';
  const old=sel.nextElementSibling;if(old&&old.classList.contains('glass-select'))old.remove();
  initGlassSelect(sel.parentElement);
  refreshGlassSelect(sel);
}
function flash(id){const s=document.getElementById(id);if(!s)return;s.textContent=t('saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
async function doLogin(){
  const username=document.getElementById('username').value.trim();
  const password=document.getElementById('password').value;
  const msg=document.getElementById('login-msg');
  if(!username||!password)return;
  const fail=()=>{msg.className='msg';msg.style.color='#fca5a5';msg.style.opacity='1';msg.textContent=t('login_failed')};
  try{
    const r=await fetch('/user/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username,password:password})});
    if(!r.ok){fail();return}
    const d=await r.json();
    sessionStorage.setItem('user_api_key',d.key);
    const ok=await loadMe();
    if(!ok){fail();sessionStorage.removeItem('user_api_key')}
  }catch(e){msg.className='msg';msg.style.color='#fca5a5';msg.style.opacity='1';msg.textContent=t('network_error')}
}
function userPasswordDialog(){
  return new Promise(resolve=>{
    const ov=document.createElement('div');ov.className='modal-backdrop';
    ov.innerHTML='<div class="modal-card flow-box"><div style="font-weight:700;color:var(--strong);margin-bottom:.55rem">'+t('change_password')+'</div><div style="display:grid;gap:.55rem"><input id="rp-old" type="password" placeholder="'+t('old_password')+'"><input id="rp-new" type="password" placeholder="'+t('new_password')+'"></div><div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem"><button id="rp-cancel" class="btn-ghost" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button><button id="rp-ok" style="font-size:.8rem;padding:6px 14px">'+t('confirm_btn')+'</button></div></div>';
    document.body.appendChild(ov);
    const oldEl=ov.querySelector('#rp-old'),newEl=ov.querySelector('#rp-new');
    const done=v=>{ov.remove();resolve(v)};
    const submit=()=>{const oldPassword=oldEl.value,newPassword=newEl.value;if(!oldPassword||!newPassword)return;done({oldPassword,newPassword})};
    ov.addEventListener('click',e=>{if(e.target===ov)done(null)});
    ov.querySelector('#rp-cancel').onclick=()=>done(null);
    ov.querySelector('#rp-ok').onclick=submit;
    ov.addEventListener('keydown',e=>{if(e.key==='Enter')submit();if(e.key==='Escape')done(null)});
    setTimeout(()=>oldEl.focus(),30);
  });
}
async function changeLoginPassword(btn){
  const form=await userPasswordDialog();
  if(!form)return;
  if(btn){btn.disabled=true}
  let ok=false,msg='';
  try{
    const r=await fetch('/user/repassword',{method:'POST',headers:{...authHeaders(),'Content-Type':'application/json'},body:JSON.stringify({old_password:form.oldPassword,new_password:form.newPassword})});
    const d=await r.json().catch(()=>({}));ok=r.ok;msg=(d.error&&d.error.message)||'';
  }catch(e){msg=t('network_error')}
  if(btn){btn.textContent=ok?t('password_changed'):(msg||t('password_change_failed'));btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(()=>{btn.textContent=t('change_password');btn.style.color='';btn.disabled=false},2500)}
}
async function logout(btn){if(btn){btn.disabled=true;btn.textContent=t('logging_out_ms')}let ok=false;try{const r=await fetch('/user/account/logout',{method:'POST',headers:authHeaders()});ok=r.ok}catch(e){}if(btn){btn.textContent=ok?t('logout_ok_ms'):t('logout_failed_ms');btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(async()=>{btn.textContent=t('logout');btn.style.color='';btn.disabled=false;await loadMe()},3000)}else{await loadMe()}}
function logoutConsole(){_userRemainSec=0;sessionStorage.removeItem('user_api_key');document.getElementById('app').classList.add('hidden');document.getElementById('login-card').classList.remove('hidden');const p=document.getElementById('password');if(p)p.value='';const m=document.getElementById('login-msg');if(m)m.textContent=''}
function userDialog(title,message,okText){
  return new Promise(resolve=>{
    const ov=document.createElement('div');ov.className='modal-backdrop';
    ov.innerHTML='<div class="modal-card flow-box"><div style="font-weight:700;color:var(--strong);margin-bottom:.55rem">'+title+'</div><div style="font-size:.84rem;color:var(--muted);line-height:1.55">'+message+'</div><div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem"><button id="dlg-cancel" class="btn-ghost" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button><button id="dlg-ok" style="font-size:.8rem;padding:6px 14px">'+okText+'</button></div></div>';
    document.body.appendChild(ov);const done=v=>{ov.remove();resolve(v)};ov.addEventListener('click',e=>{if(e.target===ov)done(false)});ov.querySelector('#dlg-cancel').onclick=()=>done(false);ov.querySelector('#dlg-ok').onclick=()=>done(true);
  });
}
function confirmUnbindAccount(){
  return new Promise(resolve=>{
    const ov=document.createElement('div');
    ov.className='modal-backdrop';
    ov.innerHTML='<div class="modal-card flow-box">'
      +'<div style="font-weight:700;color:var(--strong);margin-bottom:.55rem">'+t('unbind_account')+'</div>'
      +'<div style="font-size:.84rem;color:var(--muted);line-height:1.55">'+t('unbind_confirm')+'</div>'
      +'<div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem">'
      +'<button id="unbind-cancel" class="btn-ghost" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>'
      +'<button id="unbind-ok" style="font-size:.8rem;padding:6px 14px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('unbind_confirm_btn')+'</button>'
      +'</div></div>';
    document.body.appendChild(ov);
    const done=v=>{ov.remove();resolve(v)};
    ov.addEventListener('click',e=>{if(e.target===ov)done(false)});
    ov.querySelector('#unbind-cancel').onclick=()=>done(false);
    ov.querySelector('#unbind-ok').onclick=()=>done(true);
  });
}
async function unbindAccount(btn){
  if(!await confirmUnbindAccount())return;
  if(btn){btn.disabled=true;btn.textContent=t('unbinding_ms')}
  let ok=false;try{const r=await fetch('/user/account/unbind',{method:'POST',headers:authHeaders()});ok=r.ok}catch(e){}
  if(btn){btn.textContent=ok?t('unbind_ok_ms'):t('unbind_failed_ms');btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(async()=>{btn.textContent=t('unbind_account');btn.style.color='';btn.disabled=false;await loadMe()},3000)}else{await loadMe()}
}
function fmtExpire(iso){
  if(!iso)return t('status_unknown');
  try{return new Date(iso).toLocaleString(undefined,userTimeZone?{timeZone:userTimeZone}:undefined)}catch(e){return iso}
}
function fmtRemaining(sec){
  sec=Math.max(0,Math.floor(sec||0));
  const h=String(Math.floor(sec/3600)).padStart(2,'0');
  const m=String(Math.floor((sec%3600)/60)).padStart(2,'0');
  const s=String(sec%60).padStart(2,'0');
  return h+':'+m+':'+s;
}
let _userRemainSec=0;
function startUserCountdown(sec){_userRemainSec=Math.max(0,Math.floor(sec||0));renderUserCountdown()}
function renderUserCountdown(){
  const text=fmtRemaining(_userRemainSec);
  document.querySelectorAll('[data-user-remaining]').forEach(el=>{el.textContent=text});
}
function tickUserCountdown(){if(_userRemainSec>0){_userRemainSec--;renderUserCountdown()}}
function renderAccountStatus(d){
  const box=document.getElementById('account-status-panel');if(!box)return;
  const a=d.account||null,st=a?(a.token_status||{}):{};
  const valid=!!st.valid;
  const login=!!(a&&a.cookie_valid);
  const refresh=!!(a&&a.token_source==='cdp');
  const name=a?(a.name||a.email||a.id):t('status_unknown');
  const mark=(ok)=>'<span class="status-mark '+(ok?'ok':'bad')+'"></span>';
  box.innerHTML='<h3 style="margin:0;color:var(--strong);font-size:1rem;display:none">'+t('status_panel_title')+'</h3>'
    +'<div class="status-grid">'
    +'<div class="status-line status-first"><span>'+t('status_account')+'</span><b>'+esc(name)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_login')+'</span><b>'+mark(login)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_refresh')+'</span><b>'+mark(refresh)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_valid')+'</span><b>'+mark(valid)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_remaining')+'</span><b data-user-remaining>'+fmtRemaining(st.seconds_remaining)+'</b></div>'
    +'<div class="status-line"><span>'+t('status_expire')+'</span><b>'+fmtExpire(st.expires_at)+'</b></div>'
    +'</div>';
}
async function loadMe(){
  if(!getKey())return false;
  try{
    const r=await fetch('/user/me',{headers:authHeaders()});
    if(!r.ok)return false;
    const d=await r.json();
    toneOptions=d.tone_options||[];
    sysDefault=d.default_system_prompt||'';
    document.getElementById('login-card').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    document.getElementById('base-url').textContent=location.origin+'/v1';
    const mk=document.getElementById('my-key');if(mk)mk.textContent=getKey();
    renderToneOptions();
    document.getElementById('tone').value=d.tone||'Magic';
    refreshGlassSelect(document.getElementById('tone'));
    renderRunPermissionOptions();
    document.getElementById('user-run-permission').value=d.run_permission||'';
    refreshGlassSelect(document.getElementById('user-run-permission'));
    document.getElementById('user-model-alias').value=d.model_alias||'';
    userTimeZone=d.time_zone||'';
    document.getElementById('user-time-zone').value=userTimeZone;
    document.getElementById('tool-prompt').value=d.tool_prompt||'';
    document.getElementById('sys-prompt').value=d.system_prompt||'';
    let acc='';
    if(d.displaced){
      acc+='<div class="msg err" style="display:block;margin-bottom:.6rem">'+t('displaced_notice')+'</div>';
    }
    const keyIcon='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7.5" cy="14.5" r="3.5"></circle><path d="M10.2 12L21 1.2M15.5 6.7l2.8 2.8M18.2 4l2.6 2.6"></path></svg>';
    const doorIcon='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5.5A1.5 1.5 0 0 1 4 19.5v-15A1.5 1.5 0 0 1 5.5 3H9"></path><path d="M14 8l4 4-4 4"></path><path d="M18 12H8"></path><path d="M10 3h7a1.5 1.5 0 0 1 1.5 1.5v4"></path></svg>';
    const consoleActions='<span style="height:32px;display:inline-flex;align-items:center;gap:.35rem"><button class="btn-ghost account-action" title="'+t('change_password')+'" onclick="changeLoginPassword(this)" style="width:32px;height:32px;padding:0;display:inline-flex;align-items:center;justify-content:center;color:#facc15;background:rgba(250,204,21,.14);border-color:rgba(250,204,21,.38)">'+keyIcon+'</button><button class="btn-ghost account-action" title="'+t('console_logout')+'" onclick="logoutConsole()" style="width:32px;height:32px;padding:0;display:inline-flex;align-items:center;justify-content:center;color:#38bdf8;background:rgba(56,189,248,.14);border-color:rgba(56,189,248,.38)">'+doorIcon+'</button></span>';
    const actionBox=document.getElementById('account-console-actions');if(actionBox)actionBox.innerHTML=consoleActions;
    if(d.account){
      const st=d.account.token_status||{};
      const valid=st.valid;
      const rem=valid?(' · '+t('remaining')+' <span data-user-remaining>'+fmtRemaining(st.seconds_remaining)+'</span>'):'';
      acc+='<div class="row" style="flex-wrap:wrap;gap:.4rem;align-items:center"><span class="pill">'+t('bound_account')+': '+(d.account.name||d.account.id)+'</span>'
        +'<span class="pill '+(valid?'ok':'bad')+'">'+(valid?t('token_valid'):t('token_invalid'))+rem+'</span></div>';
    }else{
      acc+='<div class="row" style="flex-wrap:wrap;gap:.4rem;align-items:center"><span class="pill">'+t('no_account')+'</span></div>';
    }
    acc+='<div style="margin-top:.6rem;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center"><button class="btn-ghost account-action" onclick="logout(this)">'+t('logout')+'</button><button class="btn-ghost account-action" onclick="unbindAccount(this)">'+t('unbind_account')+'</button></div>';
    document.getElementById('account-info').innerHTML=acc;
    renderAccountStatus(d);
    startUserCountdown(d.account?.token_status?.seconds_remaining||0);
    return true;
  }catch(e){return false}
}
function _userFallbackCopy(text){try{const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();const ok=document.execCommand('copy');document.body.removeChild(ta);return ok}catch(e){return false}}
function _userCopy(text,cb){if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(()=>cb(true),()=>cb(_userFallbackCopy(text)))}else{cb(_userFallbackCopy(text))}}
function _copyFeedback(btn,defKey){if(!btn)return;btn.textContent=t('key_copied');btn.style.color='#22c55e';clearTimeout(btn._copyTimer);btn._copyTimer=setTimeout(()=>{btn.textContent=t(defKey);btn.style.color=''},1200)}
function copyMyKey(btn){
  const k=getKey();if(!k)return;
  _userCopy(k,ok=>{if(ok)_copyFeedback(btn,'copy_key')});
}
function copyBaseUrl(btn){
  const v=document.getElementById('base-url')?.textContent||'';if(!v)return;
  _userCopy(v,ok=>{if(ok)_copyFeedback(btn,'copy_base')});
}
async function regenMyKey(btn){
  if(!await userDialog(t('regen_my_key'),t('confirm_regen_my_key'),t('confirm_btn')))return;
  if(btn){btn.disabled=true;btn.textContent=t('regen_running')}
  let ok=false;
  try{
    const r=await fetch('/user/regenerate-key',{method:'POST',headers:authHeaders()});
    if(r.ok){
      const d=await r.json();
      if(d.key){sessionStorage.setItem('user_api_key',d.key);const mk=document.getElementById('my-key');if(mk)mk.textContent=d.key;ok=true}
    }
  }catch(e){}
  if(btn){btn.textContent=ok?t('regen_done'):t('regen_failed');btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(()=>{btn.textContent=t('regen_my_key');btn.style.color='';btn.disabled=false},3000)}
}

function autoGrowTokenBox(){const el=document.getElementById('acct-token');if(!el)return;el.style.height='75px';el.style.height=Math.min(Math.max(el.scrollHeight,75),180)+'px'}
async function pushToken(btn){
  const token=document.getElementById('acct-token').value.trim();
  if(!token)return;
  if(btn){btn.disabled=true;btn.textContent=t('updating_token')}
  let ok=false;
  try{const r=await fetch('/user/account/token',{method:'POST',headers:authHeaders(),body:JSON.stringify({token:token})});ok=r.ok}catch(e){}
  if(ok)document.getElementById('acct-token').value='';
  if(btn){btn.textContent=ok?t('push_ok'):t('token_update_failed');btn.style.color=ok?'#22c55e':'#ef4444';clearTimeout(btn._rTimer);btn._rTimer=setTimeout(async()=>{btn.textContent=t('push_token_btn');btn.style.color='';btn.disabled=false;if(ok)await loadMe()},3000)}
}
async function saveTone(){
  const tone=document.getElementById('tone').value;
  const model_alias=document.getElementById('user-model-alias')?.value||'';
  const time_zone=document.getElementById('user-time-zone')?.value||'';
  const run_permission=document.getElementById('user-run-permission')?.value||'full';
  userTimeZone=time_zone;
  try{
    const r=await fetch('/user/tone',{method:'POST',headers:authHeaders(),body:JSON.stringify({tone:tone,model_alias:model_alias,time_zone:time_zone,run_permission:run_permission})});
    if(r.ok){const d=await r.json();document.getElementById('user-model-alias').value=d.model_alias||'';userTimeZone=d.time_zone||'';document.getElementById('user-time-zone').value=userTimeZone;const rp=document.getElementById('user-run-permission');if(rp){rp.value=d.run_permission||d.effective_run_permission||'full';refreshGlassSelect(rp)}flash('tone-msg')}
  }catch(e){}
}
async function saveToolPrompt(){
  const p=document.getElementById('tool-prompt').value;
  try{await fetch('/user/tool-prompt',{method:'POST',headers:authHeaders(),body:JSON.stringify({tool_prompt:p})});flash('tool-msg')}catch(e){}
}
async function unlockSysPrompt(){
  if(!await userDialog(t('system_prompt_title'),t('system_prompt_warn'),t('confirm_btn')))return;
  const l=document.getElementById('sys-prompt-locked');
  const e=document.getElementById('sys-prompt-editor');
  if(l)l.style.display='none';
  if(e)e.style.display='block';
}
async function saveSysPrompt(){
  const p=document.getElementById('sys-prompt').value;
  try{await fetch('/user/system-prompt',{method:'POST',headers:authHeaders(),body:JSON.stringify({system_prompt:p})});flash('sys-msg')}catch(e){}
}
async function resetSysPrompt(){
  if(!await userDialog(t('system_prompt_title'),t('sys_prompt_reset_confirm'),t('confirm_btn')))return;
  document.getElementById('sys-prompt').value='';
  try{await fetch('/user/system-prompt',{method:'POST',headers:authHeaders(),body:JSON.stringify({system_prompt:''})});flash('sys-msg')}catch(e){}
}
applyTheme();
applyLang();
setInterval(tickUserCountdown,1000);
loadMe();
</script>
</body>
</html>"""
