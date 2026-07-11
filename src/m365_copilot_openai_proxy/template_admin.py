from __future__ import annotations

from .template_admin_accounts import _ADMIN_ACCOUNTS_JS
from .template_admin_copy import _ADMIN_COPY_JS
from .template_admin_dashboard import _ADMIN_DASHBOARD_JS
from .template_admin_dialogs import _ADMIN_DIALOGS_JS
from .template_admin_i18n import _ADMIN_I18N_JS
from .template_admin_keys import _ADMIN_KEYS_JS
from .template_admin_settings_js import _ADMIN_SETTINGS_JS
from .template_admin_tables import _ADMIN_TABLES_JS
from .template_admin_css import _ADMIN_CSS
from .template_assets import _GLASS_SELECT_JS

_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ciallo Ms-365 OpenAI Proxy</title>
<style>
""" + _ADMIN_CSS + """
</style>
</head>
<body>
<div class="orb" aria-hidden="true"></div>
<div class="layout">
<aside class="sidebar">
<div class="brand"><span class="brand-short">Ciallo</span><span class="brand-rest"> Ms-365</span> <span class="tenant-pill" data-i18n="multi_badge">多租户</span></div>
<nav class="nav">
<a class="nav-item active" data-nav="home" onclick="switchView('home')"><span class="nav-ico">&#128202;</span><span data-i18n="nav_home">首页总览</span></a>
<a class="nav-item" data-nav="users" onclick="switchView('users')"><span class="nav-ico">&#128100;</span><span data-i18n="nav_users">用户管理</span></a>
<a class="nav-item" data-nav="accounts" onclick="switchView('accounts')"><span class="nav-ico">&#128273;</span><span data-i18n="nav_accounts">账户管理</span></a>
<a class="nav-item" data-nav="settings" onclick="switchView('settings')"><span class="nav-ico">&#9881;&#65039;</span><span data-i18n="nav_settings">全局设置</span></a>
<a class="nav-item" data-nav="debug" onclick="switchView('debug')"><span class="nav-ico">&#128295;</span><span data-i18n="nav_debug">调试</span></a>
</nav>
<div class="side-tools">
<button class="icon-btn" id="collapse-toggle" onclick="toggleCollapse()" title="Collapse">&#9776;</button>
<button class="icon-btn" id="theme-toggle" onclick="toggleTheme()" title="Theme">&#127769;</button>
<button class="icon-btn" id="lang-toggle" onclick="toggleLang()" title="Language">&#127760;</button>
<button class="icon-btn" id="admin-logout" onclick="adminLogout()" title="Logout">&#9211;</button>
</div>
</aside>
<main class="main">
<div class="container">
<h1 id="view-title" data-i18n="nav_home" style="display:none">首页总览</h1>

<div class="card view-home">
<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.9rem">
<h2 data-i18n="dash_title" style="margin:0">运行概览</h2>
<button onclick="loadKeys();loadAccounts()" style="margin-left:auto;font-size:.8rem;padding:5px 12px" data-i18n="dash_refresh">刷新</button>
</div>
<div id="dash-kpi" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.6rem;margin-bottom:1.1rem"></div>
<div style="display:flex;gap:1.2rem;flex-wrap:wrap">
<div style="flex:1;min-width:230px"><div style="font-size:.8rem;color:var(--muted);margin-bottom:.5rem" data-i18n="dash_acct_valid">账户有效 / 过期比</div><div id="dash-donut-acct"></div></div>
<div style="flex:1;min-width:230px"><div style="font-size:.8rem;color:var(--muted);margin-bottom:.5rem" data-i18n="dash_key_status">用户 启用 / 停用</div><div id="dash-donut-key"></div></div>
<div style="flex:1;min-width:230px"><div style="font-size:.8rem;color:var(--muted);margin-bottom:.5rem" data-i18n="dash_bind_status">用户 绑定 / 未绑定</div><div id="dash-donut-bind"></div></div>
</div>
</div>

<div class="card view-home">
<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.9rem"><h2 data-i18n="dash_trend_title" style="margin:0">趋势</h2><button onclick="clearTrendStats()" style="margin-left:auto;font-size:.8rem;padding:5px 12px" data-i18n="btn_clear">清空</button></div>
<div id="dash-trend"><span style="color:var(--faint)" data-i18n="dash_no_trend">暂无趋势数据（每 5 分钟采样一次）</span></div>
</div>

<div class="card view-home">
<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.9rem"><h2 data-i18n="dash_calls_title" style="margin:0">调用统计</h2><button onclick="clearCallStats()" style="margin-left:auto;font-size:.8rem;padding:5px 12px" data-i18n="btn_clear">清空</button></div>
<div id="dash-stat-kpi" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.6rem;margin-bottom:1rem"></div>
<div style="font-size:.8rem;color:var(--muted);margin-bottom:.5rem" data-i18n="dash_tone_share">对话模式占比</div>
<div id="dash-tone-share"></div>
</div>

<div class="card view-accounts accounts-main-card">
<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.75rem">
<button onclick="toggleAccountForm()" style="margin-left:auto;font-size:.8rem;padding:5px 12px" data-i18n="btn_add_account">添加账户</button>
<button onclick="loadAccounts();loadStats()" style="font-size:.8rem;padding:5px 12px" data-i18n="dash_refresh">刷新</button>
</div>
<div id="accounts-warn" class="hide-card" style="margin-bottom:.75rem;padding:.6rem .9rem;border-radius:10px;background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.45);color:#fbbf24;font-size:.85rem;box-shadow:0 0 22px rgba(245,158,11,.12)"></div>
<div style="font-size:.8rem;color:var(--faint);margin-bottom:.5rem" data-i18n="accounts_hint">每个账户拥有独立的 M365 Token 与 Chromium 刷新配置。刷新按需串行拉起浏览器，用完即关。</div>
<div id="acc-form" class="flow-box" style="display:none;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;padding:.75rem;margin-bottom:.75rem;position:relative">
<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
<input id="af-name" style="flex:1;min-width:140px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none">
<button onclick="submitAccount()" style="font-size:.8rem;padding:6px 14px" data-i18n="kf_create">创建</button>
<button onclick="toggleAccountForm(false)" style="font-size:.8rem;padding:6px 14px;background:var(--chip)" data-i18n="kf_cancel">取消</button>
</div>
<textarea id="af-token" style="width:100%;margin-top:.5rem;min-height:64px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none;resize:vertical"></textarea>
<div style="font-size:.75rem;color:var(--faint);margin-top:.5rem" data-i18n="acc_form_hint">账户名可选。Token 可留空，稍后用 CDP 刷新或单独更新。</div>
<div id="af-msg" style="font-size:.78rem;color:#ef4444;margin-top:.4rem"></div>
</div>
<div id="accounts-content"><span style="color:var(--faint)" data-i18n="loading">加载中...</span></div>
</div>

<div class="card view-users">
<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.75rem">
<button onclick="toggleKeyForm()" style="margin-left:auto;font-size:.8rem;padding:5px 12px" data-i18n="btn_add_key">新建用户</button>
<button onclick="loadKeys();loadAccounts()" style="font-size:.8rem;padding:5px 12px" data-i18n="dash_refresh">刷新</button>
</div>
<div style="font-size:.8rem;color:var(--faint);margin-bottom:.5rem" data-i18n="keys_hint">每个 Key 绑定一个账户，可单独设置对话模式、提示词并随时启用/停用。</div>
<div id="key-form" class="flow-box" style="display:none;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;padding:.75rem;margin-bottom:.75rem;position:relative">
<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
<input id="kf-username" style="flex:1;min-width:140px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none">
<input id="kf-password" type="text" style="flex:1;min-width:140px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none">
<label class="role-toggle" title="role"><span class="role-a">A</span><input id="kf-role" type="checkbox" checked><span class="role-track"></span><span class="role-u">U</span></label>
<button onclick="submitKey()" style="font-size:.8rem;padding:6px 14px" data-i18n="kf_create">创建</button>
<button onclick="toggleKeyForm(false)" style="font-size:.8rem;padding:6px 14px;background:var(--chip)" data-i18n="kf_cancel">取消</button>
</div>
<div style="font-size:.75rem;color:var(--faint);margin-top:.5rem" data-i18n="key_form_hint">ID 与 API Key 自动生成。M365 账户绑定由用户在「用户页」自行推送 Token 完成。</div>
<div id="kf-msg" style="font-size:.78rem;color:#ef4444;margin-top:.4rem"></div>
</div>
<div id="keys-content"><span style="color:var(--faint)" data-i18n="loading">加载中...</span></div>
</div>

<div id="status-card" class="card view-accounts hide-card">
<h2 style="margin:0 0 .5rem"><span data-i18n="title_status">Token 与 登录状态</span></h2>
<div id="status-content"><span style="color:var(--faint)" data-i18n="loading">加载中...</span></div>
</div>

<div class="card view-settings">
<details id="runtime-settings-details" style="cursor:pointer">
<summary style="font-size:1.1rem;font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
<span data-i18n="runtime_title">运行设置（全局模板）</span><span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div style="font-size:.82rem;color:var(--faint);line-height:1.65;margin-top:1rem;margin-bottom:1rem;max-width:760px" data-i18n="tone_hint"></div>
<div class="runtime-settings-grid" style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem .8rem;margin-top:.2rem;align-items:start">
<div style="display:grid;gap:.7rem">
<label class="runtime-field-label"><span data-i18n="title_tone">对话模式</span><select id="tone-select" class="tone-select" style="margin-top:.4rem;width:100%"></select></label>
<label class="runtime-field-label"><span data-i18n="auto_refresh_label">自动刷新</span><select id="runtime-auto-refresh" class="tone-select" style="margin-top:.4rem;width:100%"></select></label>
<label class="runtime-field-label"><span data-i18n="run_permission_label">运行权限</span><select id="runtime-run-permission" class="tone-select" style="margin-top:.4rem;width:100%"></select></label>
</div>
<div style="display:grid;gap:.7rem">
<label class="runtime-field-label"><span data-i18n="idle_timeout_label">空闲超时分钟</span><input id="runtime-idle-timeout" type="number" min="1" style="margin-top:.4rem;width:100%;box-sizing:border-box;padding:8px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong)"></label>
<label class="runtime-field-label"><span data-i18n="keepalive_check_label">保活检查间隔（分钟）</span><input id="runtime-keepalive-check" type="number" min="1" style="margin-top:.4rem;width:100%;box-sizing:border-box;padding:8px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong)"></label>
<label class="runtime-field-label"><span data-i18n="cookie_keepalive_before_label">Cookie 提前保活（小时）</span><input id="runtime-cookie-keepalive-before" type="number" min="1" style="margin-top:.4rem;width:100%;box-sizing:border-box;padding:8px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong)"></label>
</div>
<div style="display:grid;gap:.7rem">
<label class="runtime-field-label"><span data-i18n="model_alias_label">模型别名</span><input id="runtime-model-alias" style="margin-top:.4rem;width:100%;box-sizing:border-box;padding:8px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong)"></label>
<label class="runtime-field-label"><span data-i18n="time_zone_label">时区</span><input id="runtime-time-zone" style="margin-top:.4rem;width:100%;box-sizing:border-box;padding:8px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong)"></label>
<label class="runtime-field-label"><span data-i18n="media_ttl_label">媒体超时时间（天）</span><input id="media-proxy-ttl-input" type="number" min="1" style="margin-top:.4rem;width:100%;box-sizing:border-box;padding:8px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong)"></label>
</div>
</div>
<div style="display:flex;align-items:center;gap:.5rem;margin-top:.85rem"><button id="runtime-settings-save" onclick="saveTone(document.getElementById('tone-select')?.value);saveRuntimeSettings('runtime-settings-save')" data-i18n="save">保存</button><span id="tone-saved" style="display:none"></span><span id="runtime-settings-saved" style="display:none"></span></div>
</details>
</div>

<div class="card view-settings">
<details id="tone-options-details" style="cursor:pointer">
<summary style="font-size:1.1rem;font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
<span data-i18n="tone_options_title">对话模式列表（全局）</span><span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div style="margin-top:.75rem">
<div style="font-size:.8rem;color:var(--faint);margin-bottom:.5rem" data-i18n="tone_options_hint">每行一个模式，格式：底层tone值 | 显示名 | 英文名（英文名可省略）。底层值即发送给 M365 的 tone，可填任意字符串。保存后立即生效。</div>
<textarea id="tone-options-input" rows="7" style="width:100%;box-sizing:border-box;padding:8px 12px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong);font-size:.85rem;font-family:monospace;outline:none;resize:vertical;scrollbar-width:none;-ms-overflow-style:none" placeholder="Gpt_5_2_Reasoning | GPT 5.5 快速响应 | GPT 5.5 Fast"></textarea>
<div style="display:flex;align-items:center;gap:.5rem;margin-top:.5rem">
<button id="tone-options-save" onclick="saveToneOptions()" data-i18n="media_suffix_save">保存</button>
<button id="tone-options-reset" onclick="resetToneOptions()" style="background:linear-gradient(135deg,#64748b,#475569)" data-i18n="prompt_reset">恢复默认</button>
<span id="tone-options-saved" style="font-size:.75rem;color:#22c55e;opacity:0;transition:opacity .3s"></span>
</div>
</div>
</details>
</div>

<div class="card view-settings">
<details id="media-suffix-details" style="cursor:pointer">
<summary style="font-size:1.1rem;font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
<span data-i18n="media_suffix_title">媒体后缀名（全局）</span><span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div style="margin-top:.75rem">
<div style="font-size:.8rem;color:var(--faint);margin-bottom:.5rem" data-i18n="media_suffix_hint">控制 /v1/m365-media 允许代理的文件后缀名。用逗号、空格或换行分隔，保存后立即生效。</div>
<textarea id="media-suffix-input" rows="6" style="width:100%;box-sizing:border-box;padding:8px 12px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong);font-size:.85rem;font-family:monospace;outline:none;resize:vertical;scrollbar-width:none;-ms-overflow-style:none" placeholder="png jpg wav mp4 py tsx"></textarea>
<div style="display:flex;align-items:center;gap:.5rem;margin-top:.5rem">
<button id="media-suffix-save" onclick="saveMediaSuffixes()" data-i18n="media_suffix_save">保存</button>
<button id="media-suffix-reset" onclick="resetMediaSuffixes()" style="background:linear-gradient(135deg,#64748b,#475569)" data-i18n="prompt_reset">恢复默认</button>
<span id="media-suffix-saved" style="font-size:.75rem;color:#22c55e;opacity:0;transition:opacity .3s"></span>
</div>
</div>
</details>
</div>

<div class="card view-settings">
<details id="tool-prompt-details" style="cursor:pointer">
<summary style="font-size:1.1rem;font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
<span data-i18n="title_tool_prompt">提示词微调</span>
<span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div style="margin-top:.75rem">
<div style="font-size:.8rem;color:var(--faint);margin-bottom:.5rem" data-i18n="tool_prompt_hint">追加到工具调用提示词后的自定义指令，用于调教模型的 tool_call 行为。立即生效并持久保存，留空则不追加。</div>
<textarea id="tool-prompt-input" rows="4" style="width:100%;box-sizing:border-box;padding:8px 12px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong);font-size:.85rem;font-family:monospace;outline:none;resize:vertical" placeholder=""></textarea>
<div style="display:flex;align-items:center;gap:.5rem;margin-top:.5rem">
<button id="tool-prompt-save" onclick="saveToolPrompt()" data-i18n="tool_prompt_save">保存</button>
<button id="tool-prompt-reset" onclick="resetToolPrompt()" style="background:linear-gradient(135deg,#64748b,#475569)" data-i18n="prompt_reset">恢复默认</button>
<span id="tool-prompt-saved" style="font-size:.75rem;color:#22c55e;opacity:0;transition:opacity .3s"></span>
</div>
</div>
</details>
</div>

<div class="card view-settings">
<details id="system-prompt-details" style="cursor:pointer">
<summary style="font-size:1.1rem;font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
<span data-i18n="title_system_prompt">系统级提示词（高级）</span>
<span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div style="margin-top:.75rem">
<div style="font-size:.8rem;color:var(--faint);margin-bottom:.5rem" data-i18n="system_prompt_hint">覆盖工具调用的基础系统提示词（定义 tool_call 格式与规则）。改错会导致工具调用失效，仅供高级用户调试。动态工具列表始终自动追加，不可编辑。留空则使用内置默认。</div>
<div id="system-prompt-locked">
<button id="system-prompt-unlock" onclick="unlockSystemPrompt()" style="background:linear-gradient(135deg,#ef4444,#dc2626)" data-i18n="system_prompt_unlock">解锁编辑</button>
</div>
<div id="system-prompt-editor" style="display:none">
<textarea id="system-prompt-input" rows="10" style="width:100%;box-sizing:border-box;padding:8px 12px;background:var(--inner);border:1px solid #7f1d1d;border-radius:8px;color:var(--strong);font-size:.8rem;font-family:monospace;outline:none;resize:vertical" placeholder=""></textarea>
<div style="display:flex;align-items:center;gap:.5rem;margin-top:.5rem">
<button id="system-prompt-save" onclick="saveSystemPrompt()" data-i18n="system_prompt_save">保存</button>
<button id="system-prompt-reset" onclick="resetSystemPrompt()" style="background:linear-gradient(135deg,#64748b,#475569)" data-i18n="prompt_reset">恢复默认</button>
<span id="system-prompt-saved" style="font-size:.75rem;color:#22c55e;opacity:0;transition:opacity .3s"></span>
</div>
</div>
</div>
</details>
</div>

<div class="card view-debug debug-gate-card">
<button class="debug-gate" id="capture-gate" onclick="toggleCaptureGate()">
<div class="gate-flow"></div>

<span class="debug-gate-core"><span class="data-globe"><i class="orbit o1"></i><i class="orbit o2"></i><i class="orbit o3"></i></span></span>
</button>
</div>

<div class="card view-debug ports-logs-card" style="padding:20px">
<details id="ports-logs-details" style="cursor:pointer">
<summary style="font-size:1.1rem;font-weight:700;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem;padding:20px;border-radius:12px;background:var(--inner);border:1px solid var(--inner-border)">
<span data-i18n="ports_logs_title">端口与日志</span>
<span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div class="ports-logs-grid" style="display:grid;grid-template-columns:repeat(3,minmax(160px,1fr));gap:1rem 1.1rem;align-items:start;margin-top:20px">
<label style="font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="cdp_port_label">CDP 主端口</span><input id="runtime-cdp-port" type="number" min="1" style="margin-top:.6rem;width:100%;box-sizing:border-box;padding:11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></label>
<label style="font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="ws_idle_timeout_label">对话响应超时分钟</span><input id="runtime-ws-idle-timeout" type="number" min="1" style="margin-top:.6rem;width:100%;box-sizing:border-box;padding:11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></label>
<label class="ports-log-level" style="display:flex;flex-direction:column;gap:.6rem;font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="log_level_label">日志等级</span><select id="runtime-log-level" style="width:100%;box-sizing:border-box;padding:11px 36px 11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"><option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option><option>CRITICAL</option></select></label>
<label style="font-size:.95rem;font-weight:800;color:var(--strong)" title="为多用户分配的设定起始点"><span data-i18n="account_cdp_port_base_label">CDP 从端口</span><input id="runtime-account-cdp-port-base" type="number" min="1" style="margin-top:.6rem;width:100%;box-sizing:border-box;padding:11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></label>
<label style="font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="refresh_before_label">提前刷新秒数</span><input id="runtime-refresh-before" type="number" min="0" style="margin-top:.6rem;width:100%;box-sizing:border-box;padding:11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></label>
<label style="font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="call_log_limit_label">调用记录上限</span><input id="runtime-call-log-limit" type="number" min="1" style="margin-top:.6rem;width:100%;box-sizing:border-box;padding:11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></label>
</div>
<div style="display:flex;align-items:center;gap:.5rem;margin-top:20px"><button id="debug-runtime-save" onclick="saveRuntimeSettings('debug-runtime-save')" data-i18n="save">保存</button><span id="debug-runtime-saved" style="display:none"></span></div>
</details>
</div>

<div class="card view-debug details-card" style="padding:20px">
<details id="call-log-details" style="cursor:pointer;margin-bottom:20px">
<summary style="font-size:1.1rem;font-weight:700;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem;padding:20px;border-radius:12px;background:var(--inner);border:1px solid var(--inner-border)">
<span data-i18n="title_call_log">API 调用日志</span>
<span id="call-log-count" style="font-size:.75rem;color:var(--faint);background:rgba(255,255,255,.06);padding:2px 8px;border-radius:8px">0</span>
<span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div class="call-filter-bar"><div class="call-filter-group"><button class="call-filter-btn chat" data-api-filter="chat" onclick="setCallLogFilter('chat')">chat</button><button class="call-filter-btn responses" data-api-filter="responses" onclick="setCallLogFilter('responses')">responses</button><button class="call-filter-btn anthropic" data-api-filter="anthropic" onclick="setCallLogFilter('anthropic')">anthropic</button></div><div class="call-filter-group" id="tone-filter-group"></div><div class="debug-actions"><button id="copy-call-log-all" onclick="copyAllCallLog()" style="font-size:.8rem;padding:5px 12px" data-i18n="copy_all">复制全部</button><button onclick="clearCallStats()" style="font-size:.8rem;padding:5px 12px" data-i18n="btn_clear">清空</button></div></div>
<div id="call-log-content" style="margin-top:.6rem;padding:20px;border-radius:12px;background:var(--inner);border:1px solid var(--inner-border);max-height:400px;overflow-y:auto;font-family:monospace;font-size:.8rem">
<span style="color:var(--faint)" data-i18n="no_calls_yet">暂无调用记录</span>
</div>
</details>
<details id="media-proxy-details" style="cursor:pointer;margin-bottom:20px">
<summary style="font-size:1.1rem;font-weight:700;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem;padding:20px;border-radius:12px;background:var(--inner);border:1px solid var(--inner-border)">
<span data-i18n="title_media_proxy">媒体代理日志</span>
<span id="media-proxy-event-count" style="font-size:.75rem;color:var(--faint);background:rgba(255,255,255,.06);padding:2px 8px;border-radius:8px">0</span>
<span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div style="display:flex;align-items:center;gap:.75rem;margin-top:20px"><div style="font-size:.75rem;color:var(--faint);line-height:1.5;flex:1" data-i18n="media_proxy_hint">记录媒体代理请求的签名、直连 HTTP、Chromium fallback、超时和最终状态；当前覆盖 /v1/m365-media，后续可扩展到视频、音频和文件。</div><div class="debug-actions"><button id="copy-media-proxy-all" onclick="copyAllMediaProxyEvents()" style="font-size:.8rem;padding:5px 12px" data-i18n="copy_all">复制全部</button><button onclick="clearMediaProxyEvents()" style="font-size:.8rem;padding:5px 12px" data-i18n="btn_clear">清空</button></div></div>
<div id="media-proxy-event-content" style="margin-top:.6rem;padding:20px;border-radius:12px;background:var(--inner);border:1px solid var(--inner-border);max-height:400px;overflow-y:auto;font-family:monospace;font-size:.78rem">
<span style="color:var(--faint)" data-i18n="no_media_proxy_yet">暂无媒体代理日志</span>
</div>
</details>
<details id="capture-details" style="cursor:pointer">
<summary style="font-size:1.1rem;font-weight:700;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem;padding:20px;border-radius:12px;background:var(--inner);border:1px solid var(--inner-border)">
<span data-i18n="title_capture">抓包调试日志</span>
<span id="capture-count" style="font-size:.75rem;color:var(--faint);background:rgba(255,255,255,.06);padding:2px 8px;border-radius:8px">0</span>
<span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div style="display:flex;align-items:center;gap:.75rem;margin-top:20px"><div style="font-size:.75rem;color:var(--faint);line-height:1.5;flex:1" data-i18n="capture_hint">在 M365 Copilot 切换不同模式（快速答复/深度思考、GPT 5.5/5.2）各发一条消息，用油猴脚本推送抓包，下方对比哪些字段控制模式。</div><div class="debug-actions"><button id="copy-capture-all" onclick="copyAllCapturePayloads()" style="font-size:.8rem;padding:5px 12px" data-i18n="copy_all">复制全部</button><button onclick="clearCapturePayloads()" style="font-size:.8rem;padding:5px 12px" data-i18n="btn_clear">清空</button></div></div>
<div id="capture-content" style="margin-top:.6rem;padding:20px;border-radius:12px;background:var(--inner);border:1px solid var(--inner-border);max-height:400px;overflow-y:auto;font-family:monospace;font-size:.78rem">
<span style="color:var(--faint)" data-i18n="no_capture_yet">暂无抓包数据</span>
</div>
</details>
</div>

<div class="card view-debug debug-guide-card">
<div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.75rem;flex-wrap:wrap">
<h2 data-i18n="dbg_guide_title" style="margin:0">调试指南</h2>
</div>
<p style="color:var(--muted);font-size:.85rem;line-height:1.6;margin-bottom:.75rem">
<span data-i18n="dbg_capture_desc">非必要时请勿开启，避免恶意数据写入；调试完成后请及时关闭。</span><br>
<span data-i18n="dbg_capture_steps">调试步骤：开启开关 → 在 M365 Copilot 切换不同模式（快速答复/深度思考、GPT 5.5/5.2）各发一条消息 → 用油猴脚本推送抓包 → 在「抓包调试日志」中比对字段。</span>
</p>
<details style="cursor:pointer">
<summary style="font-weight:600;color:var(--strong);list-style:none;display:flex;align-items:center;gap:.5rem">
<span data-i18n="title_api_endpoints">API 端点</span>
<span style="font-size:.7rem;color:var(--faint);margin-left:auto" data-i18n="click_expand">点击展开</span>
</summary>
<div class="api-info" style="margin-top:.5rem">
<div class="api-grp" data-i18n="api_grp_public">公共接口</div>
<div class="api-row"><span>GET&nbsp; /healthz</span><span data-i18n="api_healthz">健康检查</span></div>
<div class="api-grp" data-i18n="api_grp_v1">OpenAI 兼容接口</div>
<div class="api-row"><span>POST /v1/chat/completions</span><span data-i18n="api_chat">OpenAI 兼容对话</span></div>
<div class="api-row"><span>POST /v1/messages</span><span data-i18n="api_messages">Anthropic 兼容消息</span></div>
<div class="api-row"><span>GET&nbsp; /v1/models</span><span data-i18n="api_models">模型列表</span></div>
<div class="api-row"><span>POST /v1/responses</span><span data-i18n="api_responses">Responses 接口</span></div>
<div class="api-grp" data-i18n="api_grp_admin">管理接口</div>
<div class="api-row"><span>GET&nbsp; /admin/call-log</span><span data-i18n="api_call_log">调用记录</span></div>
<div class="api-row"><span>POST /admin/call-log/clear</span><span data-i18n="api_call_log_clear">清空调用记录</span></div>
<div class="api-row"><span>GET&nbsp; /admin/metrics-history</span><span data-i18n="api_metrics_history">趋势数据</span></div>
<div class="api-row"><span>POST /admin/metrics-history/clear</span><span data-i18n="api_metrics_clear">清空趋势数据</span></div>
<div class="api-row"><span>GET&nbsp; /admin/capture-payload</span><span data-i18n="api_cap_get">查看抓包数据</span></div>
<div class="api-row"><span>POST /admin/capture-payload</span><span data-i18n="api_cap_post">推送抓包数据</span></div>
<div class="api-row"><span>POST /admin/capture-payload/clear</span><span data-i18n="api_cap_clear">清空抓包数据</span></div>
<div class="api-row"><span>GET&nbsp; /admin/capture-toggle</span><span data-i18n="api_captgl_get">接收开关状态</span></div>
<div class="api-row"><span>POST /admin/capture-toggle</span><span data-i18n="api_captgl_post">设置接收开关</span></div>
<div class="api-row"><span>GET&nbsp; /admin/chromium/login-status</span><span data-i18n="api_login_status">Chromium 登录状态</span></div>
<div class="api-row"><span>POST /admin/chromium/logout</span><span data-i18n="api_chromium_logout">退出 Chromium 登录</span></div>
<div class="api-row"><span>POST /admin/cookie/inject</span><span data-i18n="api_cookie_inject">注入 Cookie</span></div>
<div class="api-row"><span>GET&nbsp; /admin/system-prompt</span><span data-i18n="api_sys_get">查看系统提示词</span></div>
<div class="api-row"><span>POST /admin/system-prompt</span><span data-i18n="api_sys_post">设置系统提示词</span></div>
<div class="api-row"><span>POST /admin/token/auto-capture</span><span data-i18n="api_auto_cap">自动抓取 Token</span></div>
<div class="api-row"><span>GET&nbsp; /admin/token/status</span><span data-i18n="api_tok_status">Token 状态</span></div>
<div class="api-row"><span>POST /admin/token/update</span><span data-i18n="api_tok_update">更新 Token</span></div>
<div class="api-row"><span>GET&nbsp; /admin/tone</span><span data-i18n="api_tone_get">查看默认模式</span></div>
<div class="api-row"><span>POST /admin/tone</span><span data-i18n="api_tone_post">设置默认模式</span></div>
<div class="api-row"><span>GET&nbsp; /admin/tool-prompt</span><span data-i18n="api_tool_get">查看工具提示词</span></div>
<div class="api-row"><span>POST /admin/tool-prompt</span><span data-i18n="api_tool_post">设置工具提示词</span></div>
</div>
</details>
</div>

</div>
</main>
</div>

<script>
""" + _ADMIN_I18N_JS + """let lang=localStorage.getItem('lang')||'zh';
function t(key){const v=i18n[lang][key];return v==null?key:v}
function toggleLang(){
  lang=lang==='zh'?'en':'zh';
  localStorage.setItem('lang',lang);
  applyLang();
}
function applyLang(){
  document.body.setAttribute('data-lang',lang);
  document.documentElement.lang=lang==='zh'?'zh':'en';
  const btn=document.getElementById('lang-toggle');
  if(btn)btn.title=lang==='zh'?'切换到英文':'Switch to Chinese';
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const key=el.getAttribute('data-i18n');
    if(i18n[lang][key]!=null)el.textContent=i18n[lang][key];
  });
  const vt=document.getElementById('view-title');
  if(vt){const vk=vt.getAttribute('data-i18n');if(vk&&i18n[lang][vk]!=null)vt.textContent=i18n[lang][vk]}
  const out=document.getElementById('admin-logout');if(out)out.title=lang==='zh'?'退出管理后台':'Sign out admin';
  applyTheme();applyCollapse();
  try{if(typeof loadAccounts==='function')loadAccounts()}catch(e){}
  try{if(typeof loadKeys==='function')loadKeys()}catch(e){}
  try{if(typeof renderDashboard==='function')renderDashboard()}catch(e){}
  try{if(typeof loadCallLog==='function')loadCallLog()}catch(e){}
  try{if(typeof loadCapture==='function')loadCapture()}catch(e){}
  try{if(typeof loadMediaProxyEvents==='function')loadMediaProxyEvents()}catch(e){}
  try{if(typeof loadStatus==='function')loadStatus()}catch(e){}
}
applyLang();

// Theme (dark default / soft light), persisted.
function applyTheme(){
  const th=localStorage.getItem('admin_theme')||'dark';
  document.body.setAttribute('data-theme',th);
  const btn=document.getElementById('theme-toggle');
  if(btn){btn.innerHTML=th==='light'?'&#9728;':'&#127769;';btn.title=lang==='zh'?(th==='light'?'切换到暗色主题':'切换到亮色主题'):(th==='light'?'Switch to dark theme':'Switch to light theme')}
}
function toggleTheme(){
  const th=(localStorage.getItem('admin_theme')||'dark')==='light'?'dark':'light';
  localStorage.setItem('admin_theme',th);applyTheme();
}
applyTheme();

// Collapse sidebar, persisted.
function applyCollapse(){
  const c=localStorage.getItem('admin_collapsed')==='1';
  document.body.setAttribute('data-collapsed',c?'1':'0');
  const btn=document.getElementById('collapse-toggle');
  if(btn)btn.title=lang==='zh'?(c?'展开侧边栏':'收纳侧边栏'):(c?'Expand sidebar':'Collapse sidebar');
}
function toggleCollapse(){
  const tools=document.querySelector('.side-tools');
  if(tools)tools.classList.add('switching');
  setTimeout(()=>{
    localStorage.setItem('admin_collapsed',localStorage.getItem('admin_collapsed')==='1'?'0':'1');
    applyCollapse();
    setTimeout(()=>{if(tools)tools.classList.remove('switching')},40);
  },180);
}
applyCollapse();

// Log out of the admin console (clears the admin_auth cookie, then reloads to login).
async function adminLogout(){
  try{await fetch('/admin/logout',{method:'POST',credentials:'include'})}catch(e){}
  location.reload();
}

// Debug: toggle whether the backend accepts pushed capture payloads.
async function loadCaptureToggle(){
  const gate=document.getElementById('capture-gate');
  try{const r=await fetch('/admin/capture-toggle',{credentials:'include'});if(r.ok){const d=await r.json();if(gate)gate.classList.toggle('on',!!d.enabled)}}catch(e){}
}
async function toggleCapture(on){
  try{await fetch('/admin/capture-toggle',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!!on})})}catch(e){}
  const gate=document.getElementById('capture-gate');if(gate)gate.classList.toggle('on',!!on);
}
async function toggleCaptureGate(){
  const gate=document.getElementById('capture-gate');
  const on=!(gate&&gate.classList.contains('on'));
  await toggleCapture(on);
}

// Sidebar view switching: pure front-end, no reload. Persists last view.
""" + _GLASS_SELECT_JS + """
function switchView(view){
  document.body.setAttribute('data-view',view);
  localStorage.setItem('admin_view',view);
  document.querySelectorAll('.nav-item').forEach(el=>{el.classList.toggle('active',el.getAttribute('data-nav')===view)});
  const vt=document.getElementById('view-title');
  const map={home:'nav_home',users:'nav_users',accounts:'nav_accounts',settings:'nav_settings',debug:'nav_debug'};
  const vk=map[view]||'nav_home';
  if(vt){vt.setAttribute('data-i18n',vk);vt.textContent=(i18n[lang]&&i18n[lang][vk])||vt.textContent}
  loadViewData(view);
}
function loadViewData(view){
  if(view==='home'){loadSummary();loadTrend();loadStats();return}
  if(view==='accounts'){loadAccounts();loadStats();return}
  if(view==='users'){loadKeys();loadAccounts();return}
  if(view==='settings'){loadTone();loadRuntimeSettings();loadToolPrompt();loadSystemPrompt();return}
  if(view==='debug'){loadCaptureToggle();loadRuntimeSettings();loadCallLog();loadMediaProxyEvents();loadCapture()}
}
switchView(localStorage.getItem('admin_view')||'home');

function showInlineLogin(){location.replace('/admin')}
function toggleInlineLang(){localStorage.setItem('lang',localStorage.getItem('lang')==='zh'?'en':'zh');showInlineLogin()}

async function doInlineLogin(){
  const pw=document.getElementById('pw').value;
  const btns=document.querySelectorAll('button');
  const btn=btns.length>1?btns[btns.length-1]:btns[0];
  const msg=document.getElementById('ilm');
  const curLang=localStorage.getItem('lang')||'zh';
  const li18n={zh:{fail:'登录失败',neterr:'网络错误'},en:{fail:'Login failed',neterr:'Network error'}};
  const lt=k=>li18n[curLang][k]||k;
  btn.disabled=true;msg.style.display='none';
  try{
    const r=await fetch('/admin/login',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
    if(r.ok){location.reload();return}
    const d=await r.json();
    msg.style.display='block';msg.style.background='#450a0a';msg.style.color='#ef4444';msg.style.border='1px solid #991b1b';
    msg.textContent=d.error?.message||lt('fail');
  }catch(e){msg.style.display='block';msg.style.background='#450a0a';msg.style.color='#ef4444';msg.style.border='1px solid #991b1b';msg.textContent=lt('neterr')}
  finally{btn.disabled=false}
}

// Merged status: fetch token status + chromium login status, render in fixed order:
// 用户名 > 登录 > 有效 > 过期时间 > 剩余 > 自动刷新 > 标题 > 页面 > 错误
async function loadStatus(){
  try{
    const [tr,cr]=await Promise.all([
      fetch('/admin/token/status',{credentials:'include'}),
      fetch('/admin/chromium/login-status',{credentials:'include'}).catch(()=>null),
    ]);
    if(tr.status===401){showInlineLogin();return}
    const d=await tr.json();
    let c={};
    if(cr&&cr.ok){try{c=await cr.json()}catch(e){c={}}}
    const v=d.valid;
    const cls=v?'valid':'invalid';
    const exp=d.expires_at?new Date(d.expires_at).toLocaleString():'N/A';
    if(d.username)window.__m365_username=d.username;
    const row=(label,val,vcls)=>'<div class="status-row"><span class="status-label">'+label+'</span><span class="status-value '+(vcls||'')+'">'+val+'</span></div>';
    const warnCls=(v&&d.seconds_remaining<600)?'warn':'';
    let html='';
    // 1. 用户名
    if(d.username)html+=row(t('username_label'),d.username,'valid');
    // 2. 登录 (chromium) — 状态显示为 是/否
    if(c.chromium_running===false){
      html+=row(t('login'),t('chromium_not_running'),'invalid');
    }else if(c.chromium_running){
      html+=row(t('login'),c.logged_in?t('status_yes'):t('status_no'),c.logged_in?'valid':'warn');
    }
    const logoutBtn=document.getElementById('btn-logout');
    if(logoutBtn)logoutBtn.style.display=c.logged_in?'inline-block':'none';
    // 3. 自动刷新（紧跟登录下方）
    html+=row(t('auto_refresh_label'),d.auto_refresh?t('status_yes'):t('status_no'),d.auto_refresh?'valid':'warn');
    // 4. 有效
    html+=row(t('valid'),v?t('status_yes'):t('status_no'),cls);
    // 5. 过期时间
    html+=row(t('expires'),exp,warnCls);
    // 6. 剩余
    html+=row(t('remaining'),'<span id="remaining-sec">'+fmtSec(d.seconds_remaining)+'</span>',warnCls);
    // 7. 标题 (chromium)
    if(c.title)html+='<div class="status-row"><span class="status-label">'+t('title')+'</span><span class="status-value" style="font-size:.75rem">'+c.title+'</span></div>';
    // 8. 页面 (chromium)
    if(c.url)html+='<div class="status-row"><span class="status-label">'+t('page')+'</span><span class="status-value" style="font-size:.75rem;word-break:break-all">'+c.url+'</span></div>';
    // 9. 错误
    if(d.error)html+=row(t('error'),d.error,'invalid');
    const sc=document.getElementById('legacy-status-content');if(sc)sc.innerHTML=html;
    startCountdown(d.seconds_remaining||0);
    updateRefreshBtn(d.auto_refresh);
  }catch(e){
    const sc=document.getElementById('legacy-status-content');if(sc)sc.innerHTML='<span class="invalid">Failed to load</span>';
  }
}

function fmtSec(s){
  if(!s&&s!==0)return'N/A';
  const h=Math.floor(s/3600),m=Math.floor(s%3600/60),sec=s%60;
  return(h?h+'h ':'')+(m?m+'m ':'')+sec+'s';
}

function updateRefreshBtn(enabled){
  const btn=document.getElementById('btn-stop-refresh');
  if(enabled){
    btn.style.display='inline-block';
    btn.style.background='linear-gradient(135deg,#ef4444,#dc2626)';
    btn.textContent=t('btn_stop_refresh');
  }else{
    btn.style.display='inline-block';
    btn.style.background='linear-gradient(135deg,#22c55e,#059669)';
    btn.textContent=t('btn_start_refresh');
  }
}

async function toggleAutoRefresh(){
  const msg=document.getElementById('update-msg');
  const btn=document.getElementById('btn-stop-refresh');
  btn.disabled=true;msg.className='msg';msg.textContent='';
  try{
    const r=await fetch('/admin/token/auto-refresh-toggle',{method:'POST',credentials:'include'});
    const d=await r.json();
    if(r.ok){
      msg.className='msg ok';msg.textContent=d.auto_refresh?t('auto_refresh_started'):t('auto_refresh_stopped');
      updateRefreshBtn(d.auto_refresh);
      loadStatus();
    }else{
      msg.className='msg err';msg.textContent=d.error?.message||d.error||'Toggle failed';
    }
  }catch(e){msg.className='msg err';msg.textContent=(lang==='zh'?'网络错误：':'Network error: ')+e}
  finally{btn.disabled=false}
}

async function updateToken(){
  const input=document.getElementById('token-input').value.trim();
  const msg=document.getElementById('update-msg');
  const btn=document.getElementById('btn-update');
  if(!input){msg.className='msg err';msg.textContent=lang==='zh'?'请粘贴 Token':'Please paste a token';return}
  btn.disabled=true;msg.className='msg';msg.textContent='';
  try{
    const r=await fetch('/admin/token/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:input})});
    const d=await r.json();
    if(r.ok){
      msg.className='msg ok';msg.textContent=(lang==='zh'?'Token 已更新！剩余：':'Token updated! Remaining: ')+fmtSec(d.token_status?.seconds_remaining);
      document.getElementById('token-input').value='';
      loadStatus();
    }else{
      msg.className='msg err';msg.textContent=d.error?.message||d.error||(lang==='zh'?'更新失败':'Update failed');
    }
  }catch(e){msg.className='msg err';msg.textContent=(lang==='zh'?'网络错误：':'Network error: ')+e}
  finally{btn.disabled=false}
}

async function autoCapture(){
  const msg=document.getElementById('update-msg');
  const btn=document.getElementById('btn-auto');
  const upd=document.getElementById('btn-update');
  btn.disabled=true;upd.disabled=true;
  msg.className='msg';msg.textContent='';
  btn.textContent=t('capturing_btn');
  try{
    const r=await fetch('/admin/token/auto-capture',{method:'POST'});
    const d=await r.json();
    if(r.ok){
      msg.className='msg ok';msg.textContent=t('auto_captured')+fmtSec(d.token_status?.seconds_remaining);
      loadStatus();
    }else{
      msg.className='msg err';msg.textContent=d.error?.message||d.error||t('auto_capture_failed');
    }
  }catch(e){msg.className='msg err';msg.textContent=(lang==='zh'?'网络错误：':'Network error: ')+e}
  finally{btn.disabled=false;upd.disabled=false;btn.textContent=t('btn_auto_capture')}
}

async function checkLogin(){
  const msg=document.getElementById('update-msg');
  msg.className='msg';msg.textContent=t('check_login');
  await new Promise(r=>setTimeout(r,1500));
  try{
    const r=await fetch('/admin/chromium/login-status',{credentials:'include'});
    const d=await r.json();
    msg.className=d.logged_in?'msg ok':'msg err';
    msg.textContent=d.logged_in?t('login_ok'):t('login_not_ok');
  }catch(e){msg.className='msg err';msg.textContent=t('check_failed')+e}
}

async function logoutUser(){
  const msg=document.getElementById('update-msg');
  const btn=document.getElementById('btn-logout');
  btn.disabled=true;msg.className='msg';msg.textContent=t('logging_out');
  try{
    const r=await fetch('/admin/chromium/logout',{method:'POST',credentials:'include'});
    const d=await r.json();
    if(r.ok){
      msg.className='msg ok';msg.textContent=t('logout_ok')+(d.message?' — '+d.message:'');
      loadStatus();
    }else{
      msg.className='msg err';msg.textContent=d.error?.message||d.error||t('logout_failed');
    }
  }catch(e){msg.className='msg err';msg.textContent=(lang==='zh'?'网络错误：':'Network error: ')+e}
  finally{btn.disabled=false}
}

// ============================ Multi-tenant admin JS ============================
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
""" + _ADMIN_DIALOGS_JS + """
// ---- home dashboard: pure-SVG KPI + donut charts, no external deps ----
function kpiCard(label,val,color){
  return '<div style="background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;padding:.7rem .8rem">'
    +'<div style="font-size:1.5rem;font-weight:700;color:'+color+'">'+val+'</div>'
    +'<div style="font-size:.72rem;color:var(--muted);margin-top:.15rem">'+label+'</div></div>';
}
function donut(parts,centerLabel,centerVal){
  // parts: [{value,color,label}] — render a glassy SVG ring + legend.
  const total=parts.reduce((s,p)=>s+p.value,0);
  const R=46,C=2*Math.PI*R;let off=0;
  const uid='d'+Math.random().toString(36).slice(2,8);
  // glass defs: soft drop shadow + glossy top highlight overlay
  let defs='<defs>'
    +'<filter id="'+uid+'sh" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000" flood-opacity="0.28"/></filter>'
    +'<filter id="'+uid+'halo" x="-55%" y="-55%" width="210%" height="210%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
    +'<linearGradient id="'+uid+'gl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.5"/><stop offset="0.5" stop-color="#fff" stop-opacity="0.08"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
    +'</defs>';
  let ring='',halo='';
  // base track ring (glass groove)
  ring+='<circle cx="60" cy="60" r="'+R+'" fill="none" stroke="var(--track)" stroke-width="16" opacity=".72"/>';
  if(total>0){
    const visibleParts=parts.filter(p=>p.value>0);
    visibleParts.forEach((p,i)=>{
      if(p.value<=0)return;
      const ratio=p.value/total,len=C*ratio;
      const outerR=R+5,innerR=R-8,outerC=2*Math.PI*outerR,innerC=2*Math.PI*innerR;
      const outerLen=outerC*ratio,innerLen=innerC*ratio,outerOff=outerC*(off/C),innerOff=innerC*(off/C);
      const ringCap=8.25,outerCap=10,innerCap=1.3;
      const ringLen=Math.max(0.01,len-ringCap*2),outerDrawLen=Math.max(0.01,outerLen-outerCap*2),innerDrawLen=Math.max(0.01,innerLen-innerCap*2);
      const ringStart=off+ringCap,outerStart=outerOff+outerCap,innerStart=innerOff+innerCap;
      ring+='<circle cx="60" cy="60" r="'+R+'" fill="none" stroke="'+p.color+'" stroke-width="15" stroke-linecap="round" stroke-dasharray="'+ringLen+' '+(C-ringLen)+'" stroke-dashoffset="'+(-ringStart)+'" transform="rotate(-90 60 60)" filter="url(#'+uid+'sh)" opacity="0.96"><animate attributeName="stroke-dasharray" from="0 '+C+'" to="'+ringLen+' '+(C-ringLen)+'" dur="0.55s" fill="freeze"/><animate attributeName="stroke-dashoffset" values="'+(-ringStart)+';'+(-ringStart-C)+'" dur="5.5s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.84;1;0.84" dur="5.5s" repeatCount="indefinite"/><animate attributeName="stroke-width" values="14;16.5;14" dur="5.5s" repeatCount="indefinite"/></circle>';
      halo+='<circle cx="60" cy="60" r="'+outerR+'" fill="none" stroke="'+p.color+'" stroke-width="14" stroke-linecap="round" stroke-dasharray="'+outerDrawLen+' '+(outerC-outerDrawLen)+'" stroke-dashoffset="'+(-outerStart)+'" transform="rotate(-90 60 60)" filter="url(#'+uid+'halo)" opacity="0.2"><animate attributeName="stroke-dashoffset" values="'+(-outerStart)+';'+(-outerStart-outerC)+'" dur="5.5s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.16;0.62;0.16" dur="5.5s" repeatCount="indefinite"/><animate attributeName="stroke-width" values="9;20;9" dur="5.5s" repeatCount="indefinite"/></circle>';
      halo+='<circle cx="60" cy="60" r="'+innerR+'" fill="none" stroke="'+p.color+'" stroke-width="1.6" stroke-linecap="round" stroke-dasharray="'+innerDrawLen+' '+(innerC-innerDrawLen)+'" stroke-dashoffset="'+(-innerStart)+'" transform="rotate(-90 60 60)" filter="url(#'+uid+'halo)" opacity="0.16"><animate attributeName="stroke-dashoffset" values="'+(-innerStart)+';'+(-innerStart-innerC)+'" dur="5.5s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.08;0.28;0.08" dur="5.5s" repeatCount="indefinite"/><animate attributeName="stroke-width" values="1;2.6;1" dur="5.5s" repeatCount="indefinite"/></circle>';
      off+=len;
    });
  }
  // glossy highlight arc over the top of the ring for a glass sheen
  const sheen='<circle cx="60" cy="60" r="'+(R+3.5)+'" fill="none" stroke="url(#'+uid+'gl)" stroke-width="4" stroke-linecap="round" stroke-dasharray="'+(C*0.4)+' '+C+'" transform="rotate(-108 60 60)" pointer-events="none"/>';
  let svg='<svg viewBox="0 0 120 120" style="width:120px;height:120px;flex-shrink:0;overflow:visible;filter:drop-shadow(0 0 14px rgba(96,242,255,.38)) drop-shadow(0 0 28px rgba(140,107,255,.28)) drop-shadow(0 0 42px rgba(255,94,219,.16))">'+defs+halo+ring+sheen
    +'<text x="60" y="66" text-anchor="middle" fill="var(--strong)" font-size="24" font-weight="700">'+centerVal+'</text></svg>';
  let legend='<div style="display:flex;flex-direction:column;gap:.35rem;justify-content:center">';
  parts.forEach(p=>{legend+='<div style="display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--muted)"><span style="width:10px;height:10px;border-radius:3px;background:'+p.color+';display:inline-block;box-shadow:0 1px 2px rgba(0,0,0,.25),inset 0 1px 0 rgba(255,255,255,.4)"></span>'+p.label+' <b style="color:var(--strong)">'+p.value+'</b></div>'});
  legend+='</div>';
  return '<div style="display:flex;gap:.8rem;align-items:center">'+svg+legend+'</div>';
}
function renderDashboard(){
  const kpi=document.getElementById('dash-kpi');
  if(!kpi)return;
  const keys=__keys||[],accts=__accounts||[],s=__summary||{};
  const acctTotal=s.accounts_total??accts.length;
  const acctValid=s.accounts_valid??accts.filter(a=>a.token_status&&a.token_status.valid).length;
  const acctExpired=s.accounts_expired??(acctTotal-acctValid);
  const keyTotal=s.keys_total??keys.length;
  const keyEnabled=s.keys_enabled??keys.filter(k=>k.enabled).length;
  const keyDisabled=s.keys_disabled??(keyTotal-keyEnabled);
  const keyBound=s.keys_bound??keys.filter(k=>k.account_id).length;
  const keyUnbound=s.keys_unbound??(keyTotal-keyBound);
  kpi.innerHTML=kpiCard(t('dash_kpi_users'),keyTotal,'#38bdf8')
    +kpiCard(t('dash_kpi_accounts'),acctTotal,'#a78bfa')
    +kpiCard(t('dash_kpi_active_users'),keyEnabled,'#22c55e')
    +kpiCard(t('dash_kpi_valid_accts'),acctValid,'#22c55e')
    +kpiCard(t('dash_kpi_expired_accts'),acctExpired,acctExpired?'#f59e0b':'#64748b')
    +kpiCard(t('dash_kpi_unbound'),keyUnbound,keyUnbound?'#f59e0b':'#64748b');
  const da=document.getElementById('dash-donut-acct');
  if(da)da.innerHTML=donut([{value:acctValid,color:'#22c55e',label:t('dash_valid')},{value:acctExpired,color:'#ef4444',label:t('dash_expired')}],t('dash_kpi_accounts'),acctTotal);
  const dk=document.getElementById('dash-donut-key');
  if(dk)dk.innerHTML=donut([{value:keyEnabled,color:'#22c55e',label:t('btn_enable')},{value:keyDisabled,color:'#64748b',label:t('btn_disable')}],t('dash_kpi_users'),keyTotal);
  const db=document.getElementById('dash-donut-bind');
  if(db)db.innerHTML=donut([{value:keyBound,color:'#38bdf8',label:t('dash_bound')},{value:keyUnbound,color:'#f59e0b',label:t('unbound')}],t('dash_kpi_users'),keyTotal);
}
// ---- trend line chart (multi-series SVG) ----
""" + _ADMIN_DASHBOARD_JS + """
let __summary=null;
let __runtimeSettings={};
""" + _ADMIN_TABLES_JS + """
""" + _ADMIN_ACCOUNTS_JS + """
""" + _ADMIN_COPY_JS + """
""" + _ADMIN_KEYS_JS + """
function initDetailsCards(){
  document.querySelectorAll('.view-settings,.view-debug').forEach(card=>{
    const details=[...card.querySelectorAll('details')];
    if(!details.length){card.classList.add('no-details');return}
    const sync=()=>card.classList.toggle('details-open',details.some(d=>d.open));
    details.forEach(d=>d.addEventListener('toggle',sync));sync();
  });
}
function updateAccountCountdownText(){
  if(document.body.dataset.view!=='accounts'||!__accounts.length)return;
  document.querySelectorAll('[data-token-rem]').forEach(el=>{
    const a=__accounts.find(x=>x.id===el.getAttribute('data-token-rem'));
    if(!a)return;
    const st=liveTokenStatus(a.token_status||{});
    el.textContent=st.valid?' '+fmtHMS(st.seconds_remaining||0):'';
  });
}

initDetailsCards();
loadStatus();
initGlassSelect(document);
setInterval(loadStatus,60000);
setInterval(()=>{if(document.body.dataset.view==='debug')loadCallLog()},5000);
setInterval(()=>{if(document.body.dataset.view==='debug')loadMediaProxyEvents()},5000);
setInterval(()=>{if(document.body.dataset.view==='debug')loadCapture()},5000);
setInterval(()=>{if(document.body.dataset.view==='home'){loadSummary();loadTrend()}},60000);
setInterval(()=>{if(document.body.dataset.view==='home')loadStats()},30000);
setInterval(()=>{if(document.body.dataset.view==='accounts')loadAccounts()},30000);
setInterval(updateAccountCountdownText,1000);

// Client-side countdown timer
let _countdownSec=0;
let _countdownTick=0;
function startCountdown(sec){_countdownSec=sec;_countdownTick=0}
function tickCountdown(){
  if(_countdownSec<=0)return;
  _countdownSec--;_countdownTick++;
  const el=document.getElementById('remaining-sec');
  if(el)el.textContent=fmtSec(_countdownSec);
}
setInterval(tickCountdown,1000);

window.__callTexts={};
function copyCallText(key){
  const txt=window.__callTexts[key];
  if(txt==null)return;
  navigator.clipboard.writeText(txt).then(()=>{
    const b=document.getElementById('copybtn-'+key);
    if(b){const o=b.textContent;b.textContent=t('copied');setTimeout(()=>{b.textContent=o},1200)}
  }).catch(()=>{});
}
window.__capTexts={};
function formatRawText(value){
  if(value==null)return '';
  if(typeof value==='object')return JSON.stringify(value,null,2);
  const text=String(value);
  try{return JSON.stringify(JSON.parse(text),null,2)}catch(e){return text}
}
function copyCaptureText(key){
  const txt=window.__capTexts[key];
  if(txt==null)return;
  navigator.clipboard.writeText(txt).then(()=>{
    const b=document.getElementById('capcopybtn-'+key);
    if(b){const o=b.textContent;b.textContent=t('copied');setTimeout(()=>{b.textContent=o},1200)}
  }).catch(()=>{});
}
function copyJsonToButton(value,buttonId){
  navigator.clipboard.writeText(JSON.stringify(value||[],null,2)).then(()=>{
    const b=document.getElementById(buttonId);
    if(b){const o=b.textContent;b.textContent=t('copied');setTimeout(()=>{b.textContent=o},1200)}
  }).catch(()=>{});
}
function copyAllCallLog(){copyJsonToButton(window.__callLogItems||[],'copy-call-log-all')}
function copyAllMediaProxyEvents(){copyJsonToButton(window.__mediaProxyEvents||[],'copy-media-proxy-all')}
function copyAllCapturePayloads(){copyJsonToButton(window.__capItems||[],'copy-capture-all')}
function copyMediaProxyTrace(traceId){
  const items=(window.__mediaProxyEvents||[]).filter(e=>e.trace_id===traceId);
  if(!items.length)return;
  navigator.clipboard.writeText(JSON.stringify(items,null,2)).then(()=>{
    document.querySelectorAll('[data-media-trace="'+CSS.escape(traceId)+'"]').forEach(b=>{const o=b.textContent;b.textContent=t('copied');setTimeout(()=>{b.textContent=o},1200)});
  }).catch(()=>{});
}
document.addEventListener('click',e=>{
  const btn=e.target.closest('[data-media-trace]');
  if(!btn)return;
  copyMediaProxyTrace(btn.getAttribute('data-media-trace')||'');
});
function _toneOptsSource(){
  // Debug view loads runtime-settings (not /admin/tone), so prefer its tone_options;
  // fall back to the picker's __toneOpts, then empty.
  return (window.__runtimeSettings&&window.__runtimeSettings.tone_options)||window.__toneOpts||[];
}
function _toneLabel(v){
  const o=_toneOptsSource().find(x=>x.value===v);
  if(!o)return v;
  return (lang==='en'?(o.label_en||o.label):(o.label_zh||o.label))||o.label||v;
}
function updateCallLogFilterButtons(){
  const cur=window.__callLogFilter||'';
  document.querySelectorAll('[data-api-filter]').forEach(b=>b.classList.toggle('active',b.getAttribute('data-api-filter')===cur));
  const curTone=window.__callLogToneFilter||'';
  document.querySelectorAll('[data-tone-filter]').forEach(b=>b.classList.toggle('active',b.getAttribute('data-tone-filter')===curTone));
}
function renderToneFilterButtons(logs){
  const box=document.getElementById('tone-filter-group');
  if(!box)return;
  // Distinct tones present in the current (unfiltered) log, ordered by tone_options.
  const present=new Set((logs||[]).map(l=>l.tone).filter(Boolean));
  const ordered=[];
  _toneOptsSource().forEach(o=>{if(present.has(o.value)){ordered.push(o.value);present.delete(o.value)}});
  present.forEach(v=>ordered.push(v));
  const curTone=window.__callLogToneFilter||'';
  box.innerHTML=ordered.map(v=>'<button class="call-filter-btn tone'+(v===curTone?' active':'')+'" data-tone-filter="'+encodeURIComponent(v)+'" onclick="setCallLogToneFilter(\\''+encodeURIComponent(v)+'\\')">'+_toneLabel(v).replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</button>').join('');
}
function setCallLogFilter(api){
  window.__callLogFilter=window.__callLogFilter===api?'':api;
  updateCallLogFilterButtons();
  renderCallLog(window.__callLogItems||[]);
}
function setCallLogToneFilter(v){
  const tone=decodeURIComponent(v);
  window.__callLogToneFilter=window.__callLogToneFilter===tone?'':tone;
  updateCallLogFilterButtons();
  renderCallLog(window.__callLogItems||[]);
}
function renderCallLog(logs){
    const filter=window.__callLogFilter||'';
    const toneFilter=window.__callLogToneFilter||'';
    renderToneFilterButtons(logs);
    const filtered=logs.filter(l=>(!filter||(l.api||'chat').toLowerCase()===filter)&&(!toneFilter||l.tone===toneFilter));
    document.getElementById('call-log-count').textContent=(filter||toneFilter)?(filtered.length+'/'+logs.length):logs.length;
    const el=document.getElementById('call-log-content');
    if(!logs.length){el.innerHTML='<span style="color:var(--faint)">'+t('no_calls_yet')+'</span>';updateCallLogFilterButtons();return}
    updateCallLogFilterButtons();
    window.__callTexts={};
    let html='';
    if(!filtered.length)html='<span style="color:var(--faint)">'+t('no_calls_yet')+'</span>';
    for(let i=filtered.length-1;i>=0;i--){
      const l=filtered[i];
      const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      const tc=l.tools&&l.tools.length?l.tools.join(', '):'—';
      const api=(l.api||'chat').toLowerCase();
      const apiClass=api==='responses'?'responses':(api==='anthropic'?'anthropic':'chat');
      const apiLabel=apiClass==='responses'?'responses':(apiClass==='anthropic'?'anthropic':'chat');
      const apiBadge='<span class="api-badge '+apiClass+'">'+apiLabel+'</span>';
      const toneBadge=l.tone?'<span class="tone-badge" title="'+esc(l.tone)+'">'+esc(_toneLabel(l.tone))+'</span>':'';
      const tr=l.tool_calls_result&&l.tool_calls_result.length?
        '<span style="color:#22c55e">'+t('tool_calls_parsed')+': '+l.tool_calls_result.join(', ')+'</span>':'';
      const fullKey='f'+i;
      // Full single-record text: call info + repr + text
      const fullParts=[];
      fullParts.push('time: '+l.time);
      fullParts.push('api: '+apiLabel);
      if(l.tone)fullParts.push('tone: '+l.tone+' ('+_toneLabel(l.tone)+')');
      fullParts.push('mode: '+(l.stream?'stream':'sync'));
      fullParts.push('tools: '+tc);
      if(l.tool_calls_result&&l.tool_calls_result.length)fullParts.push('tool_calls_result: '+l.tool_calls_result.join(', '));
      if(l.response_len!=null)fullParts.push('resp: '+l.response_len+' chars');
      if(l.response_repr!=null)fullParts.push('repr:\\n'+l.response_repr);
      if(l.response_text!=null)fullParts.push('text:\\n'+l.response_text);
      window.__callTexts[fullKey]=fullParts.join('\\n');
      const copyFullBtn='<button class="copybtn" id="copybtn-'+fullKey+'" data-key="'+fullKey+'" style="padding:2px 8px;font-size:.65rem">'+t('copy_record')+'</button>';
      const rawView='<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--faint);font-size:.75rem;list-style:none">'+t('view_raw')+'</summary><pre style="white-space:pre-wrap;word-break:break-all;background:var(--inner);padding:6px;border-radius:6px;color:var(--muted);margin-top:2px;font-size:.7rem;max-height:260px;overflow:auto">'+esc(formatRawText(window.__callTexts[fullKey]))+'</pre></details>';
      html+='<div style="border-bottom:1px solid #1e293b;padding:6px 0">'+
        '<div style="display:flex;justify-content:space-between;align-items:center;color:var(--muted)">'+
        '<span style="display:flex;align-items:center;gap:6px">'+apiBadge+toneBadge+'<span>'+l.time+'</span></span><span style="display:flex;align-items:center;gap:6px"><span style="color:var(--faint)">'+(l.stream?'stream':'sync')+'</span>'+copyFullBtn+'</span></div>'+
        '<div style="color:var(--strong);margin-top:2px">tools: <span style="color:#38bdf8">'+tc+'</span></div>'+
        (l.incremental!=null?'<div style="color:var(--faint);margin-top:2px">incremental: <span style="color:'+(l.incremental?'#22c55e':'#f59e0b')+'">'+(l.incremental?'yes':'no')+'</span> &nbsp; turn: '+(l.turn_count==null?'-':l.turn_count)+'</div>':'')+
        (tr?'<div style="margin-top:2px">'+tr+'</div>':'')+
        (l.response_len?'<div style="color:var(--faint);margin-top:2px">resp: '+l.response_len+' chars</div>':'')+
        rawView+
        '</div>';
    }
    el.innerHTML=html;
    el.querySelectorAll('.copybtn').forEach(function(b){
      b.addEventListener('click',function(){copyCallText(b.getAttribute('data-key'))});
    });
}
async function loadCallLog(){
  try{
    const v=window.__callLogVersion;
    const url=v==null?'/admin/call-log':'/admin/call-log?version='+encodeURIComponent(v);
    const r=await fetch(url,{credentials:'include'});
    if(r.status===401){showInlineLogin();return}
    const d=await r.json();
    document.getElementById('call-log-count').textContent=d.count||0;
    if(d.unchanged)return;
    window.__callLogVersion=d.version;
    window.__callLogItems=d.logs||[];
    renderCallLog(window.__callLogItems);
  }catch(e){}
}
function renderCapture(ps){
    document.getElementById('capture-count').textContent=ps.length;
    const el=document.getElementById('capture-content');
    if(!ps.length){el.innerHTML='<span style="color:var(--faint)">'+t('no_capture_yet')+'</span>';return}
    const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    window.__capTexts={};
    let html='';
    for(let i=0;i<ps.length;i++){
      const p=ps[i];
      const opts=(p.optionsSets||[]).join(', ');
      const gpt=p.gptId&&Object.keys(p.gptId).length?JSON.stringify(p.gptId):'-';
      const capKey='c'+i;
      window.__capTexts[capKey]=JSON.stringify(p);
      const copyCapBtn='<button class="capcopybtn" id="capcopybtn-'+capKey+'" data-key="'+capKey+'" style="padding:2px 8px;font-size:.65rem">'+t('copy_record')+'</button>';
      html+='<div style="border-bottom:1px solid #1e293b;padding:6px 0;line-height:1.5">'+
        '<div style="display:flex;justify-content:space-between;align-items:center;color:#38bdf8"><span>'+esc(p.time)+' &nbsp; tone: <b>'+esc(p.tone||'-')+'</b> &nbsp; model: <b>'+esc(p.modelId||'-')+'</b></span>'+copyCapBtn+'</div>'+
        '<div style="color:var(--muted)">gptId: '+esc(gpt)+'</div>'+
        '<div style="color:var(--faint);word-break:break-all">optionsSets: '+esc(opts)+'</div>'+
        '<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--faint);font-size:.72rem;list-style:none">'+t('view_raw')+'</summary>'+
        '<pre style="white-space:pre-wrap;word-break:break-all;background:var(--inner);padding:6px;border-radius:6px;color:var(--muted);margin-top:2px;font-size:.7rem;max-height:240px;overflow:auto">'+esc(formatRawText(p.raw))+'</pre></details>'+
        '</div>';
    }
    el.innerHTML=html;
    el.querySelectorAll('.capcopybtn').forEach(function(b){
      b.addEventListener('click',function(){copyCaptureText(b.getAttribute('data-key'))});
    });
}
async function loadCapture(){
  try{
    const v=window.__capVersion;
    const url=v==null?'/admin/capture-payload':'/admin/capture-payload?version='+encodeURIComponent(v);
    const r=await fetch(url,{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    document.getElementById('capture-count').textContent=d.count||0;
    if(d.unchanged)return;
    window.__capVersion=d.version;
    window.__capItems=d.payloads||[];
    renderCapture(window.__capItems);
  }catch(e){}
}
function renderMediaProxyEvents(items){
  const count=document.getElementById('media-proxy-event-count');if(count)count.textContent=items.length;
  const el=document.getElementById('media-proxy-event-content');if(!el)return;
  const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  if(!items.length){el.innerHTML='<span style="color:var(--faint)">'+t('no_media_proxy_yet')+'</span>';return}
  el.innerHTML=items.slice().reverse().map(e=>{
    const ts=e.ts?new Date(e.ts*1000).toLocaleTimeString():'';
    const meta={...e};delete meta.ts;delete meta.trace_id;delete meta.phase;
    const trace=String(e.trace_id||'');
    const copyBtn='<button data-media-trace="'+esc(trace)+'" style="padding:2px 8px;font-size:.65rem">'+t('copy_record')+'</button>';
    return '<div style="border-bottom:1px solid #1e293b;padding:6px 0;line-height:1.5">'+
      '<div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap"><span style="color:#38bdf8">'+esc(ts)+'</span><b style="color:var(--strong)">'+esc(e.phase)+'</b><span style="color:var(--faint)">'+esc(trace)+'</span>'+copyBtn+'</div>'+
      '<pre style="white-space:pre-wrap;word-break:break-all;color:var(--muted);margin:4px 0 0">'+esc(JSON.stringify(meta,null,2))+'</pre></div>';
  }).join('');
}
async function loadMediaProxyEvents(){
  try{
    const v=window.__mediaProxyEventsVersion;
    const url=v==null?'/admin/media-proxy/events':'/admin/media-proxy/events?version='+encodeURIComponent(v);
    const r=await fetch(url,{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    const count=document.getElementById('media-proxy-event-count');if(count)count.textContent=d.count||0;
    if(d.unchanged)return;
    window.__mediaProxyEventsVersion=d.version;
    window.__mediaProxyEvents=d.events||[];
    renderMediaProxyEvents(window.__mediaProxyEvents);
  }catch(e){}
}
""" + _ADMIN_SETTINGS_JS + """

</script>
</body>
</html>"""
