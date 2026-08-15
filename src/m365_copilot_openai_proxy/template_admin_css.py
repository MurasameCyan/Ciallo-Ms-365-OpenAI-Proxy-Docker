from __future__ import annotations

from .template_assets import _GLASS_SELECT_CSS, _NO_SPIN_CSS, _STILL_DECOR_CSS

_ADMIN_CSS = """:root{--cyan:#60f2ff;--violet:#8c6bff;--pink:#ff5edb;--gold:#ffd76f;--muted:#9aa7d1;--line:rgba(108,137,255,.24);
--bg:radial-gradient(circle at 18% 12%,rgba(96,242,255,.16),transparent 26%),radial-gradient(circle at 84% 10%,rgba(140,107,255,.2),transparent 24%),radial-gradient(circle at 50% 92%,rgba(255,94,219,.14),transparent 26%),linear-gradient(135deg,#040612 0%,#090d1f 45%,#03050d 100%);
--text:#f3f6ff;--card:linear-gradient(180deg,rgba(13,19,45,.78),rgba(7,10,24,.7));--surface:rgba(7,11,27,.7);--surface-border:rgba(255,255,255,.12);
--sidebar:rgba(6,10,24,.62);--nav-hover:rgba(255,255,255,.06);--h1grad:linear-gradient(135deg,#fff,#8deef7 44%,#ffc6f1 78%,#ffe598);--shadow:0 18px 48px rgba(0,0,0,.36);--chip:rgba(255,255,255,.06);--chip-border:rgba(255,255,255,.14);
--inner:rgba(9,14,34,.66);--inner-border:rgba(108,137,255,.2);--track:rgba(255,255,255,.08);--grid:rgba(148,163,220,.16);--strong:#eaf0ff;--faint:#8a97c4}
/* iOS26 Liquid Glass light theme — neutral system palette, soft glass, no neon.
   Accent vars (--cyan/--violet/--pink/--gold) are remapped to iOS system colors
   so shared button/focus/badge rules pick up the new look automatically. */
body[data-theme="light"]{
--cyan:#007aff;--violet:#5856d6;--pink:#ff2d55;--gold:#ff9f0a;
--muted:#6b6b70;--line:rgba(60,60,67,.12);
--bg:radial-gradient(circle at 16% 10%,rgba(0,122,255,.05),transparent 30%),radial-gradient(circle at 84% 8%,rgba(88,86,214,.04),transparent 28%),radial-gradient(circle at 50% 92%,rgba(0,0,0,.02),transparent 32%),linear-gradient(160deg,#f2f3f7 0%,#e9ebf0 48%,#f4f5f8 100%);
--text:#1c1c1e;--card:linear-gradient(180deg,rgba(255,255,255,.72),rgba(255,255,255,.52));--surface:rgba(255,255,255,.62);--surface-border:rgba(255,255,255,.7);
--sidebar:rgba(255,255,255,.52);--nav-hover:rgba(0,122,255,.07);--h1grad:linear-gradient(135deg,#1d1d1f,#3a3a3c 70%,#636366);--shadow:0 8px 28px rgba(0,0,0,.07);--chip:rgba(120,120,128,.1);--chip-border:rgba(120,120,128,.16);
--inner:rgba(255,255,255,.62);--inner-border:rgba(120,120,128,.18);--track:rgba(120,120,128,.14);--grid:rgba(120,120,128,.1);--strong:#000000;--faint:#8e8e93}
*{box-sizing:border-box;margin:0;padding:0}
html{scrollbar-gutter:stable;scrollbar-color:rgba(96,242,255,.45) rgba(8,13,32,.22);scrollbar-width:thin}
body{font-family:"Segoe UI","PingFang SC","Microsoft YaHei",-apple-system,sans-serif;color:var(--text);min-height:100vh;padding:2rem;background:var(--bg);transition:color .25s,background .25s;position:relative}
body::before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(rgba(255,255,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.03) 1px,transparent 1px);background-size:44px 44px;mask-image:radial-gradient(circle at center,black 45%,transparent 92%);z-index:0}
.orb{position:fixed;width:420px;height:420px;border-radius:50%;filter:blur(18px);background:conic-gradient(from 160deg,var(--cyan),var(--pink),var(--violet),var(--cyan));top:50%;left:50%;transform:translate(-50%,-50%);animation:loginSpin 12s linear infinite,loginPulse 4s ease-in-out infinite;opacity:.28;z-index:0;pointer-events:none}
.layout{position:relative;z-index:1}
.container{max-width:1000px;margin:0 auto}
h1{font-size:1.5rem;margin-bottom:1.5rem;background:var(--h1grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.card{position:relative;width:100%;background:var(--card);border-radius:24px;padding:1.5rem;margin-bottom:10px;border:1px solid var(--line);backdrop-filter:blur(20px);box-shadow:var(--shadow);overflow:hidden}
.card::before{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;background:linear-gradient(135deg,rgba(96,242,255,.38),transparent 30%,rgba(255,94,219,.28),rgba(255,215,111,.22));-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;opacity:.7;pointer-events:none}
details summary{min-height:42px;display:flex;align-items:center;position:relative;border-radius:14px;padding:.15rem .25rem;transition:background .2s}
details[open] summary{background:linear-gradient(135deg,rgba(96,242,255,.04),rgba(140,107,255,.04))}
details[open] summary:after{display:none}
.card:has(details[open])::after{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,transparent,rgba(96,242,255,.85),rgba(255,94,219,.58),transparent);background-size:240% 100%;animation:flowBorder 2.4s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
.flow-box{scrollbar-gutter:stable}
.flow-box::after{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,transparent,rgba(96,242,255,.85),rgba(255,94,219,.58),transparent);background-size:240% 100%;animation:flowBorder 2.4s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
@keyframes flowBorder{to{background-position:220% 0}}
.card h2{font-size:1.1rem;margin-bottom:1rem;color:var(--text)}
.status-row{display:flex;justify-content:space-between;align-items:center;padding:.5rem 0;border-bottom:1px solid var(--line)}
.status-row:last-child{border:none}
.status-label{color:var(--muted);font-size:.9rem}
.status-value{font-weight:600;font-size:.9rem}
.valid{color:#3fb970}.invalid{color:#e08a8a}.warn{color:#c99a3a}
textarea{width:100%;height:120px;background:var(--surface);border:1px solid var(--surface-border);border-radius:10px;color:var(--text);padding:.75rem;font-family:monospace;font-size:.8rem;resize:vertical;margin-bottom:.75rem}
#media-suffix-input::-webkit-scrollbar{display:none}
input[type="checkbox"]{appearance:none;-webkit-appearance:none;width:18px;height:18px;border-radius:999px;border:1px solid rgba(96,242,255,.34);background:linear-gradient(135deg,rgba(255,255,255,.18),rgba(96,242,255,.08));box-shadow:inset 0 1px 0 rgba(255,255,255,.35),0 0 12px rgba(96,242,255,.08);cursor:pointer;position:relative;vertical-align:middle;transition:box-shadow .18s,background .18s,border-color .18s}
input[type="checkbox"]:checked{background:linear-gradient(135deg,rgba(96,242,255,.85),rgba(140,107,255,.62));border-color:rgba(96,242,255,.78);box-shadow:0 0 16px rgba(96,242,255,.34),inset 0 1px 0 rgba(255,255,255,.5)}
input[type="checkbox"]:checked:after{content:"";position:absolute;inset:5px;border-radius:inherit;background:#fff;box-shadow:0 0 8px rgba(255,255,255,.8)}
body[data-theme="light"] input[type="checkbox"]{border-color:rgba(60,60,67,.22);background:linear-gradient(135deg,rgba(255,255,255,.92),rgba(0,122,255,.06))}
textarea:focus{outline:none;border-color:var(--cyan);box-shadow:0 0 0 3px rgba(96,242,255,.14)}
button{color:#050815;border:none;border-radius:10px;padding:.55rem .9rem;font-size:.8rem;font-weight:800;cursor:pointer;transition:transform .18s ease,box-shadow .18s ease;white-space:nowrap;flex-shrink:0;background:linear-gradient(135deg,var(--cyan),#d6fbff 52%,var(--gold));box-shadow:0 10px 24px rgba(96,242,255,.22);text-shadow:none}
button[style*="background:#ef4444"],button[style*="background:linear-gradient(135deg,#ef4444"],button[style*="background:#b91c1c"],button[style*="background:#059669"],button[style*="background:#b45309"],button[style*="background:#0f172a"],button[style*="background:#334155"]{color:#fff!important}
button[style*="background:var(--chip)"]{color:var(--strong)!important;border:1px solid var(--chip-border)!important;box-shadow:none!important}
.kv-copy{display:grid;grid-template-rows:1.1rem 1.35rem;align-items:center;gap:.12rem;min-width:86px;max-width:112px}
.kv-copy code{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.1rem}
.kv-copy button{width:50px;margin:0;padding:2px 6px!important;justify-self:start}
.acct-row{transition:background .18s,box-shadow .18s,transform .18s}
.acct-row.selected{background:linear-gradient(90deg,rgba(96,242,255,.13),rgba(140,107,255,.11),rgba(255,94,219,.07));box-shadow:inset 3px 0 0 rgba(96,242,255,.72),inset 0 1px 0 rgba(255,255,255,.08),0 0 24px rgba(96,242,255,.1);backdrop-filter:blur(10px)}
.tbl-tools{display:flex;gap:.4rem;justify-content:flex-end;margin-bottom:.5rem;flex-wrap:wrap;position:sticky;top:0;z-index:4;background:var(--card);padding:.1rem 0}
.view-users{height:800px;display:none;position:relative;padding-bottom:64px}
body[data-view="users"] .view-users{display:block}
.view-users .tbl-scroll{max-height:605px}
body[data-view="users"] .view-users,body[data-view="accounts"] .view-accounts,body[data-view="settings"] .view-settings,body[data-view="debug"] .view-debug{position:relative;top:auto}
.view-home,.view-users,.view-accounts,.view-settings,.view-debug{margin-top:0;margin-bottom:10px}
body[data-view="debug"] .debug-gate-card{height:250px;min-height:250px;display:flex;align-items:center;justify-content:center}
body[data-view="debug"] .debug-guide-card{height:200px!important;min-height:200px!important;overflow:hidden}
body[data-view="debug"] .debug-guide-card:has(details[open]){height:auto!important;min-height:200px!important;overflow:visible}
.accounts-main-card{position:relative;padding-bottom:64px;height:450px}
.accounts-main-card .accounts-table-scroll{height:260px;max-height:260px;overflow-y:auto;overflow-x:hidden;border-radius:8px;scrollbar-width:none;-ms-overflow-style:none;scrollbar-gutter:auto}
.accounts-main-card .accounts-table-scroll::-webkit-scrollbar{width:0;height:0;display:none}
.accounts-main-card .accounts-table thead th{position:sticky;top:0;z-index:5;background:var(--card)}
body[data-view="accounts"] .view-accounts{animation:none!important}
.view-accounts + .view-accounts,.view-settings + .view-settings,.view-debug + .view-debug{margin-top:0}
#status-card{position:relative!important;top:auto!important;margin-top:0!important;margin-bottom:10px!important;transform:none!important;animation:none!important;height:330px}
.view-settings{height:90px;min-height:90px}
.view-settings.details-open,.view-settings:has(details[open]){height:auto;min-height:90px;overflow:visible}
.view-debug{height:90px;min-height:90px}
.view-debug.details-open,.view-debug:has(details[open]){height:auto;min-height:90px;overflow:visible}
body[data-view="debug"] .view-debug.details-card:not(.details-open){height:auto;min-height:0;overflow:hidden}
body[data-view="debug"] .view-debug.details-card:not(.details-open) details:not([open])>*:not(summary){display:none!important}
body[data-view="debug"] .view-debug.no-details,body[data-view="debug"] .view-debug:not(.debug-gate-card):not(:has(details)){height:auto;min-height:260px;overflow:visible}
body[data-view="debug"] .view-debug.ports-logs-card{height:100px;min-height:100px;padding:18px 20px!important}
body[data-view="debug"] .view-debug.ports-logs-card summary{min-height:58px}
body[data-view="debug"] .view-debug.ports-logs-card.details-open{height:auto;min-height:250px;overflow:visible}
.debug-gate-card .debug-gate{height:100%;min-height:0}
.debug-gate{min-height:280px}
.tbl-scroll{max-height:595px;overflow:auto;border-radius:8px;scrollbar-gutter:stable}
.admin-tbl{width:100%;border-collapse:collapse;font-size:.82rem}
.admin-tbl thead th{position:sticky;top:0;z-index:3;background:var(--card)}
.role-toggle{display:inline-flex;align-items:center;gap:.35rem;min-height:30px;padding:3px 8px;border-radius:999px;background:linear-gradient(135deg,rgba(245,158,11,.14),rgba(251,146,60,.08));border:1px solid rgba(245,158,11,.34);box-shadow:inset 0 1px 0 rgba(255,255,255,.1),0 0 14px rgba(245,158,11,.14);color:var(--faint);font-size:.72rem;font-weight:800;user-select:none;transition:background .2s ease,border-color .2s ease,box-shadow .2s ease}
.role-toggle:has(input:checked){background:linear-gradient(135deg,rgba(96,242,255,.16),rgba(59,130,246,.1));border-color:rgba(96,242,255,.42);box-shadow:inset 0 1px 0 rgba(255,255,255,.1),0 0 14px rgba(96,242,255,.16)}
.role-toggle input{position:absolute;opacity:0;pointer-events:none}
.role-toggle .role-track{position:relative;width:34px;height:18px;border-radius:999px;background:linear-gradient(135deg,rgba(245,158,11,.58),rgba(251,146,60,.38));border:1px solid rgba(245,158,11,.58);box-shadow:inset 0 1px 3px rgba(0,0,0,.35),0 0 10px rgba(245,158,11,.22);transition:background .2s ease,border-color .2s ease,box-shadow .2s ease}
.role-toggle .role-track:before{content:"";position:absolute;width:14px;height:14px;left:2px;top:2px;border-radius:50%;background:linear-gradient(135deg,#fde68a,#f59e0b);box-shadow:0 0 10px rgba(245,158,11,.58);transition:transform .2s ease,background .2s ease,box-shadow .2s ease}
.role-toggle input:checked+.role-track{background:linear-gradient(135deg,rgba(96,242,255,.6),rgba(59,130,246,.4));border-color:rgba(96,242,255,.62);box-shadow:inset 0 1px 3px rgba(0,0,0,.35),0 0 10px rgba(96,242,255,.28)}
.role-toggle input:checked+.role-track:before{transform:translateX(16px);background:linear-gradient(135deg,#d6fbff,#60f2ff);box-shadow:0 0 10px rgba(96,242,255,.62)}
.role-toggle .role-a{color:var(--gold)}
.role-toggle .role-u{color:var(--faint)}
.role-toggle:has(input:checked) .role-a{color:var(--faint)}
.role-toggle:has(input:checked) .role-u{color:var(--cyan)}
.auto-toggle{display:inline-flex;align-items:center;gap:.45rem;min-height:30px;padding:3px 8px;border-radius:999px;background:linear-gradient(135deg,rgba(245,158,11,.14),rgba(251,146,60,.08));border:1px solid rgba(245,158,11,.34);box-shadow:inset 0 1px 0 rgba(255,255,255,.1),0 0 14px rgba(245,158,11,.14);color:var(--faint);font-size:.75rem;font-weight:800;user-select:none;transition:background .2s ease,border-color .2s ease,box-shadow .2s ease}
.auto-toggle:has(input:checked){background:linear-gradient(135deg,rgba(96,242,255,.16),rgba(59,130,246,.1));border-color:rgba(96,242,255,.42);box-shadow:inset 0 1px 0 rgba(255,255,255,.1),0 0 14px rgba(96,242,255,.16)}
.auto-toggle input{position:absolute;opacity:0;pointer-events:none}
.auto-toggle .role-track{position:relative;width:34px;height:18px;border-radius:999px;background:linear-gradient(135deg,rgba(245,158,11,.58),rgba(251,146,60,.38));border:1px solid rgba(245,158,11,.58);box-shadow:inset 0 1px 3px rgba(0,0,0,.35),0 0 10px rgba(245,158,11,.22);transition:background .2s ease,border-color .2s ease,box-shadow .2s ease}
.auto-toggle .role-track:before{content:"";position:absolute;width:14px;height:14px;left:2px;top:2px;border-radius:50%;background:linear-gradient(135deg,#fde68a,#f59e0b);box-shadow:0 0 10px rgba(245,158,11,.58);transition:transform .2s ease,background .2s ease,box-shadow .2s ease}
.auto-toggle input:checked+.role-track{background:linear-gradient(135deg,rgba(96,242,255,.6),rgba(59,130,246,.4));border-color:rgba(96,242,255,.62);box-shadow:inset 0 1px 3px rgba(0,0,0,.35),0 0 10px rgba(96,242,255,.28)}
.auto-toggle input:checked+.role-track:before{transform:translateX(16px);background:linear-gradient(135deg,#d6fbff,#60f2ff);box-shadow:0 0 10px rgba(96,242,255,.62)}
.role-badge{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:999px;font-size:.74rem;font-weight:900;letter-spacing:.02em;border:1px solid var(--inner-border);box-shadow:inset 0 1px 0 rgba(255,255,255,.12)}
.role-badge.admin{color:#fde68a;background:linear-gradient(135deg,rgba(245,158,11,.28),rgba(255,94,219,.18));border-color:rgba(245,158,11,.42);box-shadow:0 0 14px rgba(245,158,11,.22),inset 0 1px 0 rgba(255,255,255,.12)}
.role-badge.user{color:var(--cyan);background:linear-gradient(135deg,rgba(96,242,255,.16),rgba(140,107,255,.12));border-color:rgba(96,242,255,.38);box-shadow:0 0 14px rgba(96,242,255,.18),inset 0 1px 0 rgba(255,255,255,.12)}
.api-badge{display:inline-flex;align-items:center;justify-content:center;min-width:52px;padding:.12rem .48rem;border-radius:999px;font-size:.66rem;font-weight:900;letter-spacing:.03em;text-transform:uppercase;border:1px solid var(--inner-border);box-shadow:inset 0 1px 0 rgba(255,255,255,.12)}
.api-badge.chat{color:var(--cyan);background:linear-gradient(135deg,rgba(96,242,255,.16),rgba(140,107,255,.12));border-color:rgba(96,242,255,.36);box-shadow:0 0 12px rgba(96,242,255,.14),inset 0 1px 0 rgba(255,255,255,.12)}
.api-badge.responses{color:#fde68a;background:linear-gradient(135deg,rgba(245,158,11,.2),rgba(255,215,111,.12));border-color:rgba(245,158,11,.36);box-shadow:0 0 12px rgba(245,158,11,.14),inset 0 1px 0 rgba(255,255,255,.12)}
.api-badge.anthropic{color:#f0abfc;background:linear-gradient(135deg,rgba(217,70,239,.18),rgba(140,107,255,.12));border-color:rgba(217,70,239,.36);box-shadow:0 0 12px rgba(217,70,239,.14),inset 0 1px 0 rgba(255,255,255,.12)}
.call-filter-bar{display:flex;align-items:center;justify-content:space-between;gap:.6rem;flex-wrap:wrap;margin-top:20px}
.call-filter-group{display:flex;align-items:center;gap:.45rem;flex-wrap:wrap}
.debug-actions{display:flex;align-items:center;gap:.6rem;margin-left:auto;flex-wrap:wrap}
.call-filter-btn{min-width:74px;padding:5px 10px!important;border-radius:999px!important;font-size:.68rem!important;font-weight:900!important;letter-spacing:.03em;text-transform:uppercase;background:var(--chip)!important;color:var(--faint)!important;border:1px solid var(--chip-border)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.08)!important}
.call-filter-btn.active.chat{color:var(--cyan)!important;background:linear-gradient(135deg,rgba(96,242,255,.18),rgba(140,107,255,.12))!important;border-color:rgba(96,242,255,.42)!important;box-shadow:0 0 14px rgba(96,242,255,.18),inset 0 1px 0 rgba(255,255,255,.12)!important}
.call-filter-btn.active.responses{color:#fde68a!important;background:linear-gradient(135deg,rgba(245,158,11,.22),rgba(255,215,111,.12))!important;border-color:rgba(245,158,11,.4)!important;box-shadow:0 0 14px rgba(245,158,11,.16),inset 0 1px 0 rgba(255,255,255,.12)!important}
.call-filter-btn.active.anthropic{color:#f0abfc!important;background:linear-gradient(135deg,rgba(217,70,239,.2),rgba(140,107,255,.12))!important;border-color:rgba(217,70,239,.4)!important;box-shadow:0 0 14px rgba(217,70,239,.16),inset 0 1px 0 rgba(255,255,255,.12)!important}
.tone-badge{display:inline-flex;align-items:center;justify-content:center;padding:.12rem .5rem;border-radius:999px;font-size:.64rem;font-weight:900;letter-spacing:.02em;color:#a7f3d0;background:linear-gradient(135deg,rgba(16,185,129,.18),rgba(45,212,191,.12));border:1px solid rgba(16,185,129,.36);box-shadow:0 0 12px rgba(16,185,129,.14),inset 0 1px 0 rgba(255,255,255,.12)}
.call-filter-btn.tone{min-width:0;text-transform:none;letter-spacing:0}
.call-filter-btn.active.tone{color:#a7f3d0!important;background:linear-gradient(135deg,rgba(16,185,129,.2),rgba(45,212,191,.12))!important;border-color:rgba(16,185,129,.42)!important;box-shadow:0 0 14px rgba(16,185,129,.16),inset 0 1px 0 rgba(255,255,255,.12)!important}
body[data-theme="light"] .tone-badge{color:#047857;background:linear-gradient(135deg,rgba(16,185,129,.14),rgba(45,212,191,.1));border-color:rgba(4,120,87,.3);box-shadow:0 0 10px rgba(4,120,87,.1),inset 0 1px 0 rgba(255,255,255,.82)}
body[data-theme="light"] .call-filter-btn.active.tone{color:#047857!important;background:linear-gradient(135deg,rgba(16,185,129,.16),rgba(45,212,191,.1))!important;border-color:rgba(4,120,87,.3)!important}
.tbl-foot{position:absolute;left:1.5rem;right:1.5rem;bottom:1rem;display:flex;align-items:center;justify-content:space-between;gap:.6rem;flex-wrap:wrap;font-size:.78rem;color:var(--muted);z-index:6;background:linear-gradient(180deg,rgba(8,13,32,.78),rgba(8,13,32,.9));border:1px solid rgba(96,242,255,.12);border-radius:14px;padding:.45rem .6rem;backdrop-filter:blur(14px)}
.page-size{display:flex;align-items:center;gap:.4rem}
.page-nav{display:flex;align-items:center;gap:.5rem}
.page-info{color:var(--faint);min-width:150px;text-align:center;display:inline-flex;align-items:center;justify-content:center}
.page-btn{font-size:.74rem;padding:5px 12px;color:#050815;background:linear-gradient(135deg,var(--cyan),#d6fbff 52%,var(--gold));border:none;box-shadow:0 10px 24px rgba(96,242,255,.22);font-weight:800}
.page-btn:hover:not(:disabled){box-shadow:0 0 20px rgba(96,242,255,.28),inset 0 1px 0 rgba(255,255,255,.2)}
.page-btn:disabled{opacity:.45;cursor:not-allowed;background:var(--chip);color:var(--faint)}
.page-select{min-height:30px;padding:4px 28px 4px 10px;background-color:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--text);font-size:.76rem;font-weight:700;outline:none;-webkit-appearance:none;-moz-appearance:none;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2360f2ff' stroke-width='2.5'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 8px 22px rgba(0,0,0,.12);transition:border-color .2s,box-shadow .2s;cursor:pointer}
.page-select:focus{border:1px solid transparent!important;background-image:linear-gradient(var(--inner),var(--inner)),linear-gradient(90deg,var(--cyan),var(--violet),var(--pink),var(--gold),var(--cyan))!important;background-origin:border-box!important;background-clip:padding-box,border-box!important;background-size:100% 100%,300% 100%!important;background-position:0 0,0 0!important;animation:fieldFlow 2.2s linear infinite!important}
.page-select option{background:#10162f;color:#f3f6ff}
body[data-theme="light"] .page-select{color:#1c1c1e;background-color:rgba(255,255,255,.78);border-color:rgba(60,60,67,.16)}
body[data-theme="light"] .page-select option{background:#fff;color:#1c1c1e}
.runtime-field-label{font-size:.8125rem;color:var(--strong);font-weight:800}
.runtime-field-label.auto{display:flex;align-items:center;gap:.6rem;margin-top:1.35rem}
.tone-select{margin-left:auto;width:180px;max-width:50%;min-height:38px;padding:7px 34px 7px 12px;background-color:var(--inner);border:1px solid var(--inner-border);border-radius:12px;color:var(--text);font-size:.82rem;font-weight:700;outline:none;-webkit-appearance:none;-moz-appearance:none;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2360f2ff' stroke-width='2.5'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 12px center;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 8px 22px rgba(0,0,0,.12);transition:border-color .2s,box-shadow .2s}
input:focus,textarea:focus,select:focus{border:1px solid transparent!important;background-image:linear-gradient(var(--inner),var(--inner)),linear-gradient(90deg,var(--cyan),var(--violet),var(--pink),var(--gold),var(--cyan))!important;background-origin:border-box!important;background-clip:padding-box,border-box!important;background-size:100% 100%,300% 100%!important;background-position:0 0,0 0!important;box-shadow:0 0 0 3px rgba(96,242,255,.12),0 0 24px rgba(96,242,255,.2),inset 0 1px 0 rgba(255,255,255,.08)!important;animation:fieldFlow 2.2s linear infinite!important;outline:none}
.tone-select:focus{animation:none!important}
select:focus,.page-select:focus,.tone-select:focus{animation:none!important;transition:none!important;box-shadow:0 0 0 2px rgba(96,242,255,.12),inset 0 1px 0 rgba(255,255,255,.08)!important;background-position:0 0,0 0!important}
select option{transition:none!important}
select option:checked{background:#1e40af;color:#fff}
@keyframes fieldFlow{to{background-position:0 0,300% 0}}
@keyframes selectGlow{50%{box-shadow:0 0 0 3px rgba(96,242,255,.2),0 0 30px rgba(140,107,255,.28),inset 0 1px 0 rgba(255,255,255,.12)}}
.tone-select option{background:#10162f;color:#f3f6ff}
body[data-theme="light"] .tone-select{color:#1c1c1e;background-color:rgba(255,255,255,.78);border-color:rgba(60,60,67,.16);box-shadow:inset 0 1px 0 rgba(255,255,255,.9),0 6px 16px rgba(0,0,0,.05)}
body[data-theme="light"] .tone-select option{background:#fff;color:#1c1c1e}
""" + _GLASS_SELECT_CSS + _NO_SPIN_CSS + """
.view-settings .tone-select+.glass-select{margin-left:auto}
.runtime-settings-grid{display:grid!important;grid-template-columns:repeat(3,minmax(180px,1fr))!important;gap:1rem 1.1rem!important;margin-top:.75rem!important;align-items:start!important;max-width:1080px!important}
.runtime-settings-grid>div{display:grid!important;gap:1rem!important}
.runtime-settings-grid .runtime-field-label{display:flex!important;flex-direction:column!important;gap:.55rem!important;min-width:0!important;font-size:.95rem!important;font-weight:800!important;color:var(--strong)!important}
.runtime-settings-grid input{min-height:44px!important;margin-top:0!important;padding:11px 13px!important;border-radius:10px!important;font-size:.95rem!important;font-weight:700!important;background:var(--inner)!important;border:1px solid var(--inner-border)!important;color:var(--strong)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 8px 22px rgba(0,0,0,.12)!important}
.runtime-settings-grid .glass-select{display:block!important;width:100%!important;min-width:0!important;margin-left:0!important}
.runtime-settings-grid .glass-select-trigger{min-height:44px!important;padding:11px 36px 11px 13px!important;border-radius:10px!important;font-size:.95rem!important;font-weight:700!important}
.ports-logs-card{overflow:visible!important;z-index:10}
.ports-logs-card:has(.glass-select.open){z-index:3000!important}
.ports-logs-card label{font-size:.875rem!important;font-weight:800!important;color:var(--strong)!important}
.ports-logs-grid{align-items:start!important}
.ports-logs-card input{min-height:38px!important;margin-top:.5rem!important;padding:9px 12px!important;border-radius:10px!important;font-size:.875rem!important;font-weight:700!important}
.ports-log-level{display:flex!important;flex-direction:column!important;align-items:stretch!important;gap:.5rem!important;position:relative;z-index:20}
.ports-logs-grid .glass-select{display:block!important;width:100%!important;min-width:0!important;margin-left:0!important}
.ports-logs-grid .glass-select-trigger{height:38px!important;min-height:38px!important;padding:9px 36px 9px 12px!important;border-radius:10px!important;font-size:.875rem!important;font-weight:700!important}
.ports-logs-grid .glass-select.open{z-index:3100!important}
.ports-logs-grid .glass-select-menu{z-index:3200!important}
.layout .glass-select.open{z-index:2000}
.layout .glass-select-menu{left:0;right:auto;width:100%;max-width:100%;min-width:100%;overflow-x:hidden;overflow-y:auto}
.view-settings:has(.glass-select.open){z-index:2000;overflow:visible}
.tbl-foot:has(.glass-select.open),.modal-card:has(.glass-select.open){z-index:2000}
#rebind-select+.glass-select.open{z-index:2000}
#rebind-select+.glass-select .glass-select-menu{left:0;right:auto;width:100%;max-width:100%;min-width:100%;overflow-x:hidden;overflow-y:auto}
body[data-theme="light"] button[style*="background:var(--chip)"]{color:#1c1c1e!important;background:rgba(120,120,128,.12)!important;box-shadow:none!important}
body[data-theme="light"] .tbl-foot{color:#6b6b70;background:linear-gradient(180deg,rgba(255,255,255,.82),rgba(242,243,247,.92));border-color:rgba(60,60,67,.12);box-shadow:inset 0 1px 0 rgba(255,255,255,.9),0 8px 20px rgba(0,0,0,.04)}
body[data-theme="light"] .role-toggle{background:linear-gradient(135deg,rgba(255,255,255,.78),rgba(0,122,255,.08),rgba(88,86,214,.06));border-color:rgba(60,60,67,.14);box-shadow:inset 0 1px 0 rgba(255,255,255,.9),0 6px 14px rgba(0,0,0,.04)}
body[data-theme="light"] .role-toggle .role-track{background:rgba(120,120,128,.14);border-color:rgba(60,60,67,.18);box-shadow:inset 0 1px 3px rgba(0,0,0,.06)}
body[data-theme="light"] .role-toggle .role-a{color:#b45309}
body[data-theme="light"] .role-toggle .role-u{color:#7581a3}
body[data-theme="light"] .role-badge.admin{color:#92400e;background:linear-gradient(135deg,rgba(245,158,11,.2),rgba(255,94,219,.1));border-color:rgba(217,119,6,.34);box-shadow:0 0 12px rgba(245,158,11,.14),inset 0 1px 0 rgba(255,255,255,.82)}
body[data-theme="light"] .role-badge.user{color:#007aff;background:linear-gradient(135deg,rgba(0,122,255,.12),rgba(88,86,214,.08));border-color:rgba(0,122,255,.22);box-shadow:0 0 10px rgba(0,122,255,.08),inset 0 1px 0 rgba(255,255,255,.88)}
body[data-theme="light"] .api-badge.chat{color:#007aff;background:linear-gradient(135deg,rgba(0,122,255,.12),rgba(88,86,214,.08));border-color:rgba(0,122,255,.22);box-shadow:0 0 10px rgba(0,122,255,.08),inset 0 1px 0 rgba(255,255,255,.88)}
body[data-theme="light"] .api-badge.responses{color:#92400e;background:linear-gradient(135deg,rgba(245,158,11,.18),rgba(255,215,111,.12));border-color:rgba(217,119,6,.3);box-shadow:0 0 12px rgba(245,158,11,.12),inset 0 1px 0 rgba(255,255,255,.82)}
body[data-theme="light"] .api-badge.anthropic{color:#a21caf;background:linear-gradient(135deg,rgba(217,70,239,.13),rgba(124,58,237,.08));border-color:rgba(162,28,175,.28);box-shadow:0 0 12px rgba(162,28,175,.1),inset 0 1px 0 rgba(255,255,255,.82)}
body[data-theme="light"] .call-filter-btn{color:#6b6b70!important;background:rgba(120,120,128,.08)!important;border-color:rgba(60,60,67,.14)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.88)!important}
body[data-theme="light"] .call-filter-btn.active.chat{color:#007aff!important;background:linear-gradient(135deg,rgba(0,122,255,.12),rgba(88,86,214,.08))!important;border-color:rgba(0,122,255,.24)!important;box-shadow:0 0 10px rgba(0,122,255,.08),inset 0 1px 0 rgba(255,255,255,.88)!important}
body[data-theme="light"] .call-filter-btn.active.responses{color:#92400e!important;background:linear-gradient(135deg,rgba(245,158,11,.18),rgba(255,215,111,.12))!important;border-color:rgba(217,119,6,.3)!important;box-shadow:0 0 12px rgba(245,158,11,.12),inset 0 1px 0 rgba(255,255,255,.82)!important}
body[data-theme="light"] .call-filter-btn.active.anthropic{color:#a21caf!important;background:linear-gradient(135deg,rgba(217,70,239,.13),rgba(124,58,237,.08))!important;border-color:rgba(162,28,175,.28)!important;box-shadow:0 0 12px rgba(162,28,175,.1),inset 0 1px 0 rgba(255,255,255,.82)!important}
body[data-theme="light"] .debug-gate{background:radial-gradient(circle at 50% 38%,rgba(0,122,255,.1),transparent 30%),linear-gradient(135deg,rgba(255,255,255,.86),rgba(242,243,247,.78));color:var(--text);box-shadow:inset 0 1px 0 rgba(255,255,255,.9),0 16px 36px rgba(0,0,0,.06)}
body[data-theme="light"] .debug-gate:after{background:linear-gradient(135deg,rgba(255,255,255,.84),rgba(239,245,255,.76))}
body[data-theme="light"] .debug-gate:before{opacity:.34}
body[data-theme="light"] .debug-gate.on{box-shadow:0 0 28px rgba(0,122,255,.18),0 0 60px rgba(88,86,214,.1),inset 0 1px 0 rgba(255,255,255,.92)}
button:hover{transform:translateY(-2px);box-shadow:0 16px 32px rgba(96,242,255,.34)}
button:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn-bar{display:flex;gap:.5rem;margin-bottom:.25rem;flex-wrap:wrap}
.msg{padding:.6rem 1rem;border-radius:10px;font-size:.85rem;margin-top:.5rem;display:none}
.msg.ok{display:block;background:rgba(5,46,22,.6);color:#4ade80;border:1px solid rgba(34,197,94,.4)}
.msg.err{display:block;background:rgba(69,10,10,.6);color:#fecaca;border:1px solid rgba(239,68,68,.5)}
body[data-theme="light"] .msg.ok{background:rgba(220,252,231,.8);color:#15803d;border-color:rgba(34,197,94,.35)}
body[data-theme="light"] .msg.err{background:rgba(254,226,226,.8);color:#b91c1c;border-color:rgba(239,68,68,.35)}
.api-info{margin-top:1rem;padding:.75rem;background:var(--surface);border-radius:10px;font-family:monospace;font-size:.8rem;color:var(--muted);line-height:1.6}
.api-grp{font-weight:700;color:var(--strong);margin:.5rem 0 .25rem;font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:.78rem}
.api-grp:first-child{margin-top:0}
.api-row{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.12rem 0}
.api-row>span:first-child{color:var(--text);white-space:pre}
.api-row>span:last-child{color:var(--faint);text-align:right;font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:.74rem}
a{color:var(--cyan);text-decoration:none}
body[data-theme="light"] a{color:#007aff}
a:hover{text-decoration:underline}
/* ---- multi-tenant sidebar layout ---- */
body{padding:.85rem 0 .85rem .85rem}
.layout{display:flex;min-height:calc(100vh - 1.7rem);gap:.85rem}
.sidebar{width:210px;flex-shrink:0;background:linear-gradient(180deg,rgba(8,13,32,.46),rgba(8,12,28,.3));border:1px solid rgba(96,242,255,.2);border-radius:26px;display:flex;flex-direction:column;padding:1.2rem .85rem;position:sticky;top:.85rem;height:calc(100vh - 1.7rem);backdrop-filter:blur(26px) saturate(1.32);-webkit-backdrop-filter:blur(26px) saturate(1.32);transition:width .22s ease,padding .22s ease;will-change:width;contain:layout paint;box-shadow:inset 0 1px 0 rgba(255,255,255,.12),18px 0 60px rgba(0,0,0,.12),0 0 28px rgba(96,242,255,.08)}
.brand{font-size:1.02rem;font-weight:800;padding:.4rem .4rem 1.2rem;white-space:nowrap;overflow:hidden;background:var(--h1grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;text-align:left}
.brand .brand-short,.brand .brand-rest{display:inline-block;min-width:0}
.brand .tenant-pill{position:relative;display:inline-flex;align-items:center;justify-content:center;margin-left:0;padding:.16rem .52rem;border-radius:999px;font-size:.62rem;line-height:1;color:var(--strong);-webkit-text-fill-color:currentColor;background:linear-gradient(135deg,rgba(255,255,255,.18),rgba(96,242,255,.12),rgba(140,107,255,.12));border:1px solid transparent;box-shadow:inset 0 1px 0 rgba(255,255,255,.36),0 0 16px rgba(96,242,255,.16),0 0 26px rgba(140,107,255,.1);backdrop-filter:blur(12px);overflow:hidden;vertical-align:middle;letter-spacing:.04em}
.brand .tenant-pill:before{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,var(--cyan),var(--violet),var(--pink),var(--gold),var(--cyan));background-size:300% 100%;animation:tenantFlow 2.2s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
.brand .tenant-pill:after{content:"";position:absolute;inset:2px;border-radius:inherit;background:linear-gradient(135deg,rgba(255,255,255,.1),transparent 58%,rgba(96,242,255,.12));pointer-events:none}
@keyframes tenantFlow{to{background-position:300% 0}}
.nav{display:flex;flex-direction:column;gap:.25rem}
.nav-item{position:relative;display:grid;grid-template-columns:1.4rem 1fr 1.4rem;align-items:center;gap:.45rem;padding:.6rem .7rem;border-radius:12px;color:var(--muted);cursor:pointer;font-size:.9rem;font-weight:500;transition:background .16s ease,color .16s ease;user-select:none;white-space:nowrap;overflow:hidden;text-align:center}
.nav-item:hover{background:var(--nav-hover);color:var(--text);text-decoration:none}
.nav-item.active{background:linear-gradient(135deg,rgba(96,242,255,.18),rgba(140,107,255,.16));color:var(--text);box-shadow:inset 0 1px 0 rgba(255,255,255,.22),inset 0 0 18px rgba(96,242,255,.12),0 0 24px rgba(96,242,255,.13);border:1px solid rgba(96,242,255,.28);backdrop-filter:blur(14px)}
.nav-item:hover::after,.nav-item.active::after{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,transparent,rgba(96,242,255,.9),rgba(255,94,219,.6),transparent);background-size:240% 100%;animation:flowBorder 2.4s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
.nav-ico{font-size:1.05rem;width:1.4rem;text-align:center;flex-shrink:0;grid-column:1}
.nav-item span:not(.nav-ico){transition:opacity .16s ease;grid-column:2;text-align:center;justify-self:center}
/* Footer: two full-width rows, same gap/height; top = hash + 2 icon squares; bottom = 4 equal icons. */
.side-footer{margin-top:auto;display:flex;flex-direction:column;gap:.35rem;padding-top:.15rem;width:100%}
.side-update-bar,.side-tools{display:flex;align-items:center;gap:.35rem;width:100%;min-width:0;box-sizing:border-box}
.side-build-chip,.side-update-btn,.side-repo-btn{box-sizing:border-box;height:36px;min-width:0;border-radius:12px;border:1px solid rgba(96,242,255,.22);background:linear-gradient(135deg,rgba(96,242,255,.1),rgba(140,107,255,.1));color:var(--muted);box-shadow:inset 0 1px 0 rgba(255,255,255,.16);transition:background .16s ease,color .16s ease,border-color .16s ease,opacity .16s ease}
/* Version chip fills remaining width so top row spans same outer length as bottom. */
.side-build-chip{display:inline-flex;align-items:center;justify-content:center;flex:1 1 auto;min-width:0;padding:0 .45rem;font-size:.7rem;font-weight:700;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums;letter-spacing:.04em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* Check / GitHub: equal square icon buttons (icon only). */
.side-update-btn,.side-repo-btn{display:inline-flex;align-items:center;justify-content:center;flex:0 0 36px;width:36px;padding:0;cursor:pointer;text-decoration:none;color:var(--muted)}
.side-update-btn:hover,.side-repo-btn:hover{color:var(--text);background:linear-gradient(135deg,rgba(96,242,255,.22),rgba(255,94,219,.12));border-color:rgba(96,242,255,.4);text-decoration:none}
.side-update-btn:disabled{opacity:.6;cursor:wait}
.side-update-btn.has-update{color:#4ade80;background:rgba(74,222,128,.14);border-color:rgba(74,222,128,.4)}
.side-update-btn.has-update:hover{background:rgba(74,222,128,.22)}
.side-update-btn.is-latest{color:#4ade80;border-color:rgba(74,222,128,.28)}
.side-update-ico{flex:0 0 auto;display:block}
.side-update-btn.loading .side-update-ico{animation:sideSpin .8s linear infinite}
.side-gh-ico{flex:0 0 auto;display:block;opacity:.92}
@keyframes sideSpin{to{transform:rotate(360deg)}}
.side-tools{position:relative;height:auto;padding-top:0}
.side-tools .icon-btn{position:relative;left:auto;margin:0;transform:none;flex:1 1 0;width:auto;height:36px;min-width:0}
body[data-theme="light"] .side-build-chip,body[data-theme="light"] .side-update-btn,body[data-theme="light"] .side-repo-btn{color:var(--muted);background:linear-gradient(135deg,rgba(255,255,255,.78),rgba(0,122,255,.08));border-color:rgba(0,122,255,.16);box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}
body[data-theme="light"] .side-update-btn:hover,body[data-theme="light"] .side-repo-btn:hover{color:var(--text);border-color:rgba(0,122,255,.28)}
body[data-theme="light"] .side-update-btn.has-update,body[data-theme="light"] .side-update-btn.is-latest{color:#15803d;background:rgba(34,197,94,.12);border-color:rgba(22,163,74,.35)}
.icon-btn{position:relative;width:auto;height:36px;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,rgba(96,242,255,.18),rgba(140,107,255,.16));border:1px solid rgba(96,242,255,.28);color:var(--text);border-radius:12px;padding:0;font-size:1.05rem;line-height:1;cursor:pointer;box-shadow:inset 0 1px 0 rgba(255,255,255,.22),inset 0 0 18px rgba(96,242,255,.12),0 0 20px rgba(96,242,255,.12);backdrop-filter:blur(14px);transition:background .16s ease,opacity .18s ease,filter .18s ease,box-shadow .16s ease;will-change:opacity;overflow:hidden}
.icon-btn:hover{background:linear-gradient(135deg,rgba(96,242,255,.28),rgba(255,94,219,.18));box-shadow:inset 0 1px 0 rgba(255,255,255,.3),0 0 24px rgba(96,242,255,.24)}
.icon-btn:hover::after{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,transparent,rgba(96,242,255,.95),rgba(255,94,219,.65),transparent);background-size:220% 100%;animation:flowBorder 1.6s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
.side-tools.switching .icon-btn{opacity:0;filter:blur(4px);pointer-events:none}
body[data-theme="light"] .sidebar{background:linear-gradient(180deg,rgba(255,255,255,.62),rgba(242,243,247,.42));border-color:rgba(60,60,67,.1);box-shadow:inset 0 1px 0 rgba(255,255,255,.86),12px 0 36px rgba(0,0,0,.04),0 0 18px rgba(0,0,0,.03)}
body[data-theme="light"] .brand .tenant-pill{color:#1c1c1e;background:linear-gradient(135deg,rgba(255,255,255,.82),rgba(0,122,255,.1),rgba(88,86,214,.08));border-color:rgba(0,122,255,.2);box-shadow:inset 0 1px 0 rgba(255,255,255,.9),0 0 12px rgba(0,122,255,.08)}
/* ---- glass toggle switch ---- */
.switch{position:relative;display:inline-block;width:44px;height:24px;flex-shrink:0}
.switch input{opacity:0;width:0;height:0}
.switch .slider{position:absolute;inset:0;cursor:pointer;background:var(--track);border:1px solid var(--inner-border);border-radius:99px;transition:.25s;box-shadow:inset 0 1px 3px rgba(0,0,0,.25)}
.switch .slider:before{content:"";position:absolute;height:18px;width:18px;left:2px;top:2px;border-radius:50%;background:linear-gradient(180deg,#fff,#dfe6ff);box-shadow:0 2px 5px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.7);transition:.25s}
.switch input:checked+.slider{background:linear-gradient(135deg,var(--cyan),var(--violet));border-color:transparent;box-shadow:0 0 12px rgba(96,242,255,.5),inset 0 1px 2px rgba(255,255,255,.25)}
.switch input:checked+.slider:before{transform:translateX(20px)}
/* ---- debug receive gate ---- */
.debug-gate-card{padding:20px;overflow:hidden}
.debug-gate{position:relative;width:100%;height:200px;min-height:200px;padding:20px;border:none;border-radius:28px;background:radial-gradient(circle at 50% 38%,rgba(96,242,255,.12),transparent 28%),linear-gradient(135deg,rgba(8,13,32,.9),rgba(18,25,56,.8));color:var(--text);cursor:pointer;overflow:hidden;display:flex;align-items:center;justify-content:center;isolation:isolate;font-weight:800;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 20px 58px rgba(0,0,0,.28)}
.debug-gate:before{content:"";position:absolute;inset:-2px;background:conic-gradient(from 0deg,transparent,rgba(96,242,255,.55),transparent,rgba(140,107,255,.52),transparent);animation:spin 4s linear infinite;opacity:.42;z-index:-2}
.debug-gate:after{content:"";position:absolute;inset:20px;border-radius:20px;background:linear-gradient(135deg,rgba(7,11,27,.92),rgba(13,19,45,.86));z-index:-1}
.debug-gate-core{display:flex;align-items:center;justify-content:center;text-align:center;letter-spacing:.02em}
.data-globe{position:relative;width:170px;height:170px;border-radius:50%;margin:0;background:radial-gradient(circle at 34% 24%,rgba(255,255,255,.78),rgba(96,242,255,.35) 17%,rgba(34,98,180,.42) 48%,rgba(16,24,64,.9) 74%);border:1px solid rgba(96,242,255,.45);box-shadow:0 0 48px rgba(96,242,255,.3),inset 0 0 44px rgba(96,242,255,.2);overflow:visible;transform-style:preserve-3d}
.debug-gate.on .data-globe{animation:globeSpin 9s linear infinite,globeBreath 3.2s ease-in-out infinite}
.data-globe:before{content:"";position:absolute;inset:6px;border-radius:50%;background:radial-gradient(circle at 24% 30%,rgba(255,255,255,.95) 0 1.4px,transparent 2.2px),radial-gradient(circle at 66% 22%,rgba(96,242,255,.9) 0 1.6px,transparent 2.4px),radial-gradient(circle at 40% 58%,rgba(255,255,255,.72) 0 1.1px,transparent 1.8px),radial-gradient(circle at 74% 64%,rgba(140,107,255,.82) 0 1.5px,transparent 2.2px),radial-gradient(circle at 30% 78%,rgba(96,242,255,.7) 0 1.2px,transparent 1.9px);opacity:.85;animation:globeDotA 6.5s ease-in-out infinite}
.data-globe:after{content:"";position:absolute;inset:6px;border-radius:50%;background:radial-gradient(circle at 52% 20%,rgba(255,255,255,.85) 0 1.3px,transparent 2px),radial-gradient(circle at 18% 54%,rgba(96,242,255,.8) 0 1.5px,transparent 2.2px),radial-gradient(circle at 60% 48%,rgba(255,215,111,.75) 0 1.3px,transparent 2px),radial-gradient(circle at 82% 40%,rgba(255,255,255,.7) 0 1.1px,transparent 1.7px),radial-gradient(circle at 46% 82%,rgba(140,107,255,.7) 0 1.4px,transparent 2.1px);opacity:.7;animation:globeDotB 5.2s ease-in-out infinite}
.data-globe .orbit{position:absolute;inset:-14px;border-radius:50%;border:1px solid rgba(96,242,255,.38);transform:rotateX(var(--x)) rotateY(var(--y)) rotateZ(var(--r));box-shadow:0 0 20px rgba(96,242,255,.16);opacity:0;transition:opacity .35s ease;transform-style:preserve-3d}
.data-globe .orbit:after{content:"";position:absolute;width:8px;height:8px;border-radius:50%;background:var(--cyan);top:50%;left:-4px;box-shadow:0 0 12px var(--cyan)}
.data-globe .orbit.o1{--x:68deg;--y:18deg;--r:18deg}
.data-globe .orbit.o2{inset:-24px;--x:28deg;--y:72deg;--r:64deg;border-color:rgba(140,107,255,.45)}.data-globe .orbit.o2:after{background:var(--violet);box-shadow:0 0 14px var(--violet)}
.data-globe .orbit.o3{inset:-30px;--x:78deg;--y:-36deg;--r:-34deg;border-color:rgba(255,215,111,.42)}.data-globe .orbit.o3:after{background:var(--gold);box-shadow:0 0 14px var(--gold)}
.debug-gate b,.debug-gate small{display:none}
.debug-gate.on{box-shadow:0 0 42px rgba(96,242,255,.34),0 0 110px rgba(140,107,255,.24),inset 0 1px 0 rgba(255,255,255,.1)}
.debug-gate.on:before{opacity:1;animation-duration:1.8s}.debug-gate.on .data-globe:before{animation-duration:3.4s}.debug-gate.on .data-globe:after{animation-duration:2.8s}.debug-gate.on .data-globe{box-shadow:0 0 52px rgba(96,242,255,.52),0 0 86px rgba(140,107,255,.3),0 0 118px rgba(255,94,219,.16),inset 0 0 34px rgba(96,242,255,.22)}
.debug-gate.on .orbit{opacity:1;animation:orbitSpin 2.4s linear infinite}.debug-gate.on .orbit.o2{animation-duration:3.2s;animation-direction:reverse}.debug-gate.on .orbit.o3{animation-duration:4.1s}
.gate-flow{position:absolute;inset:6px;border-radius:24px;pointer-events:none;opacity:0;z-index:0}
.debug-gate.on .gate-flow{opacity:1;border:1px solid transparent;background:linear-gradient(90deg,transparent,rgba(96,242,255,.5),rgba(140,107,255,.4),rgba(255,94,219,.3),transparent);background-size:300% 100%;animation:gateFlow 2.6s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;padding:1px}
.debug-gate-card{display:flex;align-items:center;justify-content:center}
.debug-gate-card .debug-gate{background:transparent;box-shadow:none;border:none;border-radius:inherit;padding:0;overflow:visible}
.debug-gate-card .debug-gate-core{transform:translateY(14px)}
.debug-gate-card .debug-gate:before,.debug-gate-card .debug-gate:after,.debug-gate-card .gate-flow{display:none}
.debug-gate-card .debug-gate:hover{transform:none;box-shadow:none}
.debug-gate-card .debug-gate.on{box-shadow:none}
.debug-gate-card:has(.debug-gate.on)::after{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,transparent,rgba(96,242,255,.85),rgba(255,94,219,.58),transparent);background-size:240% 100%;animation:flowBorder 2.4s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
body[data-theme="light"] .debug-gate-card .debug-gate{background:transparent;box-shadow:none}
@keyframes gateFlow{to{background-position:300% 0}}
@keyframes globeSpin{to{transform:rotate(360deg)}}
@keyframes globeBreath{0%,100%{scale:1;filter:drop-shadow(0 0 14px rgba(96,242,255,.32)) drop-shadow(0 0 24px rgba(140,107,255,.2))}50%{scale:1.08;filter:drop-shadow(0 0 24px rgba(96,242,255,.62)) drop-shadow(0 0 44px rgba(140,107,255,.38)) drop-shadow(0 0 62px rgba(255,94,219,.2))}}
@keyframes globeDotA{0%{transform:translate(0,0)}25%{transform:translate(2px,-3px)}50%{transform:translate(-3px,2px)}75%{transform:translate(1px,3px)}100%{transform:translate(0,0)}}
@keyframes globeDotB{0%{transform:translate(0,0)}30%{transform:translate(-2px,-2px)}60%{transform:translate(3px,1px)}100%{transform:translate(0,0)}}
@keyframes orbitSpin{to{transform:rotateX(var(--x)) rotateY(var(--y)) rotateZ(calc(var(--r) + 360deg))}}
@keyframes flow{to{background-position:64px 0}}
/* ---- collapsed sidebar ---- */
body[data-collapsed="1"] .sidebar{width:60px;padding:1.2rem .5rem}
body[data-collapsed="1"] .brand .brand-rest,body[data-collapsed="1"] .brand .tenant-pill,body[data-collapsed="1"] .nav-item span:not(.nav-ico){opacity:0;pointer-events:none;width:0;margin:0;display:none}
body[data-collapsed="1"] .brand{font-size:.76rem;width:100%;padding:.4rem 0 1.2rem;text-align:center;letter-spacing:.01em;display:flex;justify-content:center;align-items:center;background:none;-webkit-text-fill-color:initial;color:var(--strong)}
body[data-collapsed="1"] .brand .brand-short{opacity:1;display:block;width:100%;margin:0;text-align:center;background:var(--h1grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;transform:scale(.92);transform-origin:center}
body[data-collapsed="1"] .nav-item{display:flex;justify-content:center;align-items:center;padding:.6rem 0;gap:0}
body[data-collapsed="1"] .nav-ico{width:100%;text-align:center;grid-column:auto}
/* Collapsed: hide update bar; stack 4 tool icons centered. */
body[data-collapsed="1"] .side-update-bar{display:none!important}
body[data-collapsed="1"] .side-footer{gap:0}
body[data-collapsed="1"] .side-tools{flex-direction:column;align-items:center;justify-content:flex-start;gap:.45rem;height:auto;padding-top:.25rem}
body[data-collapsed="1"] .side-tools .icon-btn{position:relative;left:auto;margin:0;transform:none;flex:0 0 auto;width:38px;height:38px}
.main{flex:1;padding:2rem;overflow-x:hidden}
.main .container{max-width:1000px}
.main h1{font-size:1.4rem}
body[data-lang="en"] .nav-item{font-size:.78rem;letter-spacing:0}
body[data-lang="en"] .nav-item span:not(.nav-ico){font-size:.78rem;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
body[data-lang="en"] .runtime-field-label,body[data-lang="en"] .ports-logs-card label{font-size:.72rem!important;line-height:1.2;font-weight:700!important}
body[data-lang="en"] button,body[data-lang="en"] .page-btn,body[data-lang="en"] .call-filter-btn{font-size:.72rem!important;letter-spacing:0}
body[data-lang="en"] .admin-tbl{font-size:.76rem}
body[data-lang="en"] .admin-tbl th,body[data-lang="en"] .admin-tbl td{line-height:1.2}
body[data-lang="en"] .role-toggle,body[data-lang="en"] .auto-toggle{font-size:.72rem}
body[data-lang="en"] .api-badge,body[data-lang="en"] .tone-badge{font-size:.68rem;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body[data-lang="en"] .brand .tenant-pill{font-size:.62rem;padding:.16rem .48rem;letter-spacing:0;line-height:1}
body[data-lang="en"] .btn-ghost{font-size:.72rem!important}
body[data-lang="en"] .acct-token-actions{width:auto!important;min-width:148px}
body[data-lang="en"] .acct-token-actions button{width:auto!important;min-width:46px;padding:3px 6px!important;font-size:.68rem!important}
body[data-lang="en"] .cookie-refresh-btn{width:auto!important;min-width:46px;font-size:.68rem!important}
body[data-lang="en"] .admin-tbl button{font-size:.68rem!important;padding:3px 7px!important;white-space:nowrap}
.page-size-unit:empty{display:none}
body[data-lang="en"] .page-size-unit{font-size:.72rem}
body[data-lang="en"] .tbl-foot .page-size{gap:.35rem}

/* view switching: hide all view cards, show active group with fade-in */
.view-home,.view-users,.view-accounts,.view-settings,.view-debug{display:none}
body[data-view="home"] .view-home,body[data-view="users"] .view-users,body[data-view="accounts"] .view-accounts,body[data-view="settings"] .view-settings,body[data-view="debug"] .view-debug{display:block;animation:fadeUp .35s ease}
.hide-card{display:none !important}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@keyframes warnFade{0%{opacity:0;transform:translateY(4px)}18%,82%{opacity:1;transform:translateY(0)}100%{opacity:0;transform:translateY(-4px)}}
.expiry-warn-rotate{animation:warnFade 3s ease-in-out both}
.tone-share-fill{box-shadow:0 0 12px currentColor;animation:toneShareBreath 3.2s ease-in-out infinite}
@keyframes toneShareBreath{0%,100%{opacity:.82;filter:saturate(1)}50%{opacity:1;filter:saturate(1.35) brightness(1.12)}}
@keyframes loginSpin{to{transform:translate(-50%,-50%) rotate(360deg)}}
@keyframes loginPulse{50%{scale:1.08;opacity:.42}}
@media(max-width:680px){.sidebar{width:60px;padding:1rem .4rem}.brand,.nav-item span:not(.nav-ico){display:none}.nav-item{justify-content:center}.main{padding:1rem}.ports-logs-card>div{grid-template-columns:1fr!important}}

/* iOS26 light — component overrides (system blue, soft glass, no neon rainbow) */
body[data-theme="light"]{scrollbar-color:rgba(0,122,255,.28) rgba(120,120,128,.08)}
body[data-theme="light"]::before{background:linear-gradient(rgba(60,60,67,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(60,60,67,.05) 1px,transparent 1px);background-size:44px 44px;opacity:.55}
body[data-theme="light"] .orb{opacity:.1;filter:blur(28px);background:conic-gradient(from 160deg,rgba(0,122,255,.55),rgba(88,86,214,.45),rgba(255,45,85,.28),rgba(0,122,255,.55))}
body[data-theme="light"] .card{border-radius:22px;backdrop-filter:blur(28px) saturate(160%);-webkit-backdrop-filter:blur(28px) saturate(160%)}
body[data-theme="light"] .card::before{background:linear-gradient(135deg,rgba(255,255,255,.75),transparent 42%,rgba(0,122,255,.12),rgba(88,86,214,.08));opacity:.55}
body[data-theme="light"] .card:has(details[open])::after{background:linear-gradient(90deg,transparent,rgba(0,122,255,.45),rgba(88,86,214,.28),transparent);animation:none;opacity:.7}
body[data-theme="light"] details[open] summary{background:linear-gradient(135deg,rgba(0,122,255,.05),rgba(88,86,214,.04))}
body[data-theme="light"] button,body[data-theme="light"] .page-btn{color:#fff;background:linear-gradient(180deg,#0a84ff 0%,#007aff 100%);box-shadow:0 4px 14px rgba(0,122,255,.28),inset 0 1px 0 rgba(255,255,255,.28);text-shadow:none;border-radius:12px;font-weight:700}
body[data-theme="light"] button:hover,body[data-theme="light"] .page-btn:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(0,122,255,.32),inset 0 1px 0 rgba(255,255,255,.32)}
body[data-theme="light"] button:active,body[data-theme="light"] .page-btn:active{transform:translateY(0);filter:brightness(.96)}
body[data-theme="light"] .btn-ghost,body[data-theme="light"] button.btn-ghost{color:#1c1c1e!important;background:rgba(120,120,128,.12)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.7)!important}
body[data-theme="light"] input:focus,body[data-theme="light"] textarea:focus,body[data-theme="light"] select:focus{border:1px solid rgba(0,122,255,.45)!important;background-image:none!important;background:var(--inner)!important;box-shadow:0 0 0 4px rgba(0,122,255,.14)!important;animation:none!important;outline:none}
body[data-theme="light"] .page-select:focus,body[data-theme="light"] .tone-select:focus{border:1px solid rgba(0,122,255,.45)!important;background-image:none!important;box-shadow:0 0 0 4px rgba(0,122,255,.14)!important;animation:none!important}
body[data-theme="light"] .nav-item.active{background:linear-gradient(135deg,rgba(0,122,255,.12),rgba(88,86,214,.08));color:var(--text);box-shadow:inset 0 1px 0 rgba(255,255,255,.7),0 0 0 1px rgba(0,122,255,.14);border:1px solid rgba(0,122,255,.18);backdrop-filter:blur(16px)}
body[data-theme="light"] .icon-btn{background:linear-gradient(135deg,rgba(255,255,255,.7),rgba(0,122,255,.1));border:1px solid rgba(0,122,255,.16);color:var(--text);box-shadow:inset 0 1px 0 rgba(255,255,255,.8),0 4px 12px rgba(0,0,0,.05);backdrop-filter:blur(16px)}
body[data-theme="light"] .switch input:checked+.slider{background:linear-gradient(135deg,#0a84ff,#007aff);border-color:transparent;box-shadow:0 0 10px rgba(0,122,255,.28),inset 0 1px 2px rgba(255,255,255,.35)}
body[data-theme="light"] .glass-select-trigger{color:#1c1c1e!important;background:linear-gradient(135deg,rgba(255,255,255,.88),rgba(0,122,255,.06))!important;border-color:rgba(60,60,67,.14)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.92),0 4px 12px rgba(0,0,0,.04)!important}
body[data-theme="light"] .glass-select.open .glass-select-trigger{border-color:rgba(0,122,255,.4)!important;box-shadow:0 0 0 3px rgba(0,122,255,.12),0 4px 14px rgba(0,0,0,.05)!important}
body[data-theme="light"] .glass-select-menu{background:linear-gradient(180deg,rgba(255,255,255,.94),rgba(242,243,247,.9));border-color:rgba(60,60,67,.12);box-shadow:0 16px 36px rgba(0,0,0,.1),inset 0 1px 0 rgba(255,255,255,.92);backdrop-filter:blur(28px) saturate(160%)}
body[data-theme="light"] .glass-select-menu:before{background:linear-gradient(90deg,rgba(0,122,255,.35),rgba(88,86,214,.25),rgba(0,122,255,.35));animation:none;opacity:.45}
body[data-theme="light"] .glass-select-option{color:#6b6b70!important}
body[data-theme="light"] .glass-select-option:hover{background:rgba(0,122,255,.08)!important;color:#1c1c1e!important}
body[data-theme="light"] .glass-select-option.active{color:#007aff!important;background:rgba(0,122,255,.12)!important;box-shadow:inset 3px 0 0 #007aff!important}
body[data-theme="light"] .role-toggle .role-u{color:#8e8e93}
body[data-theme="light"] .role-toggle:has(input:checked) .role-u{color:#007aff}
body[data-theme="light"] .data-globe .orbit:after{background:#007aff;box-shadow:0 0 8px rgba(0,122,255,.45)}
""" + _STILL_DECOR_CSS
