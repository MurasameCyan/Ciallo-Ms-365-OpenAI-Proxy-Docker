from __future__ import annotations

from .template_assets import _GLASS_SELECT_CSS, _GLASS_SELECT_JS, _NO_SPIN_CSS
from .template_user_account_js import _USER_ACCOUNT_JS
from .template_user_config_js import _USER_CONFIG_JS
from .template_user_i18n import _USER_I18N_JS

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
.account-icon-btn{width:34px!important;height:34px!important;min-width:34px!important;padding:0!important;display:inline-flex!important;align-items:center;justify-content:center;border-radius:12px;border:1px solid transparent;box-shadow:inset 0 1px 0 rgba(255,255,255,.16);cursor:pointer}
.account-icon-btn svg{width:17px;height:17px;display:block;flex:0 0 auto;stroke-width:2.4}
.account-icon-btn-pass{color:#fde047!important;background:rgba(250,204,21,.22)!important;border-color:rgba(250,204,21,.55)!important}
.account-icon-btn-out{color:#7dd3fc!important;background:rgba(56,189,248,.22)!important;border-color:rgba(56,189,248,.55)!important}
.account-icon-btn:hover{filter:brightness(1.12)}
body[data-theme="light"] .account-icon-btn-pass{color:#a16207!important;background:rgba(250,204,21,.28)!important;border-color:rgba(202,138,4,.55)!important}
body[data-theme="light"] .account-icon-btn-out{color:#0369a1!important;background:rgba(14,165,233,.2)!important;border-color:rgba(2,132,199,.5)!important}
.account-main select{width:180px!important;min-height:38px;background-color:var(--inner);border:1px solid var(--inner-border);color:var(--text);box-shadow:inset 0 1px 0 rgba(255,255,255,.08);transition:border-color .2s,box-shadow .2s}
.account-main select:focus{border-color:var(--cyan);box-shadow:0 0 0 2px rgba(96,242,255,.12),inset 0 1px 0 rgba(255,255,255,.1)!important;animation:none!important;transition:none!important}
select option{transition:none!important}
select option:checked{background:#1e40af;color:#fff}
@keyframes userSelectGlow{50%{box-shadow:0 0 0 3px rgba(96,242,255,.22),0 0 30px rgba(255,94,219,.2),inset 0 1px 0 rgba(255,255,255,.14)}}
.account-main select option{background:#10162f;color:#f3f6ff}
body[data-theme="light"] .account-main select option{background:#fff;color:#243049}
""" + _GLASS_SELECT_CSS + _NO_SPIN_CSS + """
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
body[data-lang="en"] .user-config-field,body[data-lang="en"] .user-media-suffix .user-config-label{font-size:.72rem;line-height:1.2;font-weight:700}
body[data-lang="en"] .user-config-field>span,body[data-lang="en"] .user-config-label{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body[data-lang="en"] .user-default-grid{grid-template-columns:repeat(4,minmax(0,1fr));gap:.75rem}
body[data-lang="en"] .user-config-field input,body[data-lang="en"] .user-default-grid .glass-select-trigger{font-size:.78rem!important}
body[data-lang="en"] button{font-size:.72rem!important;letter-spacing:0}
body[data-lang="en"] .compact-action{font-size:.7rem!important}
body[data-lang="en"] .section-title{font-size:.9rem}
body[data-lang="en"] .account-action{font-size:.72rem!important;min-width:0}
body[data-lang="en"] .account-icon-btn{width:34px!important;height:34px!important;min-width:34px!important;padding:0!important;font-size:0!important}
body[data-lang="en"] .account-main .account-action{font-size:.78rem!important;padding:.45rem .8rem!important;white-space:nowrap}
body[data-lang="en"] .pill{max-width:100%;overflow:hidden;text-overflow:ellipsis}
body[data-lang="en"] .status-line{font-size:.72rem}
body[data-lang="en"] .pill{font-size:.7rem}
body[data-lang="en"] h1{font-size:1.15rem}
body[data-lang="en"] .card h2{font-size:.95rem}

.user-config-field input{width:100%;height:38px;box-sizing:border-box;padding:9px 14px;background:rgba(96,242,255,.08);border:1px solid rgba(96,242,255,.45);border-radius:14px;color:var(--strong);font-size:.86rem;font-weight:700;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 8px 20px rgba(0,0,0,.16)}
.user-default-grid .glass-select{width:100%!important;min-width:0!important;height:38px!important;margin-left:0!important}
.user-default-grid .glass-select-trigger{height:38px!important;width:100%!important;box-sizing:border-box!important;padding:9px 34px 9px 14px!important;border-radius:14px!important;font-size:.86rem!important;font-weight:700!important}
.mode-profile-card:has(.glass-select.open){overflow:visible;z-index:2000}
.mode-profile-card .user-default-grid .glass-select-menu{left:0;right:auto;width:100%;min-width:100%;max-width:100%}
.user-media-suffix{margin-top:1.1rem}
.user-media-suffix .user-config-label{font-size:.86rem;font-weight:800;color:var(--strong)}
.user-media-suffix textarea{width:100%;box-sizing:border-box;min-height:60px;padding:9px 14px;background:rgba(96,242,255,.08);border:1px solid rgba(96,242,255,.45);border-radius:14px;color:var(--strong);font-size:.85rem;font-family:monospace;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 8px 20px rgba(0,0,0,.16);resize:vertical;scrollbar-width:none;-ms-overflow-style:none}
.user-media-suffix textarea::-webkit-scrollbar{display:none}
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
        <label class="section-title" data-i18n="manual_update_title">手动更新</label>
        <div class="row action-row"><button onclick="pushToken(this)" data-i18n="push_token_btn">更新 Token</button><span id="token-msg" class="msg"></span></div>
        <textarea id="acct-token" data-i18n-ph="push_token_ph" placeholder="粘贴 access_token 值或完整 wss:// URL。仅推送 Token 可临时使用，推送 Cookie 后才算绑定 Microsoft 账户。&#10;access_token / wss://substrate.office.com/..."></textarea>
      </div>
      <div class="account-side" id="account-status-panel"></div>
    </div>

    <div class="card mode-profile-card">
      <details id="mode-profile-details" style="cursor:pointer">
      <summary style="font-size:1rem;font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
      <span data-i18n="mode_profile_title">默认配置</span>
      <span id="tone-msg" class="msg"></span>
      <span style="font-size:.7rem;color:#475569;margin-left:auto" data-i18n="click_expand">点击展开</span>
      </summary>
      <div style="margin-top:.75rem">
      <div class="hint" data-i18n="user_tone_hint">保存后仅影响当前用户，不再跟随全局模板变化。</div>
      <div class="user-default-grid">
        <label class="user-config-field" style="display:none"><span data-i18n="tone_title">对话模式</span><select id="tone" class="tone-select" onchange="saveTone()"></select></label>
        <label class="user-config-field"><span data-i18n="run_permission_label">运行权限</span><select id="user-run-permission" class="tone-select" onchange="saveTone()"></select></label>
        <label class="user-config-field" style="display:none"><span data-i18n="model_alias_label">模型别名</span><input id="user-model-alias" onchange="saveTone()"></label>
        <label class="user-config-field"><span data-i18n="user_time_zone_label">更改时区</span><input id="user-time-zone" onchange="saveTone()"></label>
        <label class="user-config-field"><span data-i18n="ws_idle_timeout_label">对话响应超时分钟</span><input id="user-ws-idle-timeout" type="number" min="0" onchange="saveTone()"></label>
      </div>
      <div class="user-media-suffix">
        <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.35rem"><span class="user-config-label" data-i18n="user_media_suffix_label">媒体后缀名</span></div>
        <div class="hint" data-i18n="user_media_suffix_hint">填写后将强制覆盖全局媒体后缀，仅作用于你自己的 Key。用逗号、空格或换行分隔。留空则跟随全局。</div>
        <textarea id="user-media-suffix" rows="3" onchange="saveTone()" placeholder=""></textarea>
      </div>
      </div>
      </details>
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
""" + _USER_I18N_JS + """let lang=localStorage.getItem('lang')||'zh';
let toneOptions=[];
let sysDefault='';
let userTimeZone='';
function t(k){const v=i18n[lang][k];return v==null?k:v}
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function getKey(){return sessionStorage.getItem('user_api_key')||''}
function authHeaders(){return {'Content-Type':'application/json','Authorization':'Bearer '+getKey()}}
function applyLang(){
  document.body.setAttribute('data-lang',lang);
  document.documentElement.lang=lang==='zh'?'zh':'en';
  document.title=t('title');
  const btn=document.getElementById('lang-toggle');
  btn.innerHTML=lang==='zh'?'&#127760; EN':'&#127760; 中文';
  document.querySelectorAll('[data-i18n]').forEach(el=>{const k=el.getAttribute('data-i18n');if(i18n[lang][k]!=null)el.textContent=i18n[lang][k]});
  document.querySelectorAll('[data-i18n-ph]').forEach(el=>{const k=el.getAttribute('data-i18n-ph');if(i18n[lang][k]!=null)el.placeholder=i18n[lang][k]});
  document.querySelectorAll('[data-i18n-html]').forEach(el=>{const k=el.getAttribute('data-i18n-html');if(i18n[lang][k]!=null)el.innerHTML=i18n[lang][k]});
  renderToneOptions();
  try{
    if(typeof applyUserLangDynamic==='function' && _userMeCache){applyUserLangDynamic()}
    else if(getKey()){loadMe()}
  }catch(e){}
}
function toggleLang(){lang=lang==='zh'?'en':'zh';localStorage.setItem('lang',lang);applyLang()}
""" + _GLASS_SELECT_JS + """
function applyTheme(){const theme=localStorage.getItem('user_theme')||'dark';document.body.setAttribute('data-theme',theme);const b=document.getElementById('theme-toggle');if(b)b.innerHTML=theme==='light'?'&#9728;':'&#127769;'}
function toggleTheme(){localStorage.setItem('user_theme',(localStorage.getItem('user_theme')||'dark')==='dark'?'light':'dark');applyTheme()}
""" + _USER_CONFIG_JS + """
""" + _USER_ACCOUNT_JS + """
applyTheme();
applyLang();
setInterval(tickUserCountdown,1000);
loadMe();
</script>
</body>
</html>"""
