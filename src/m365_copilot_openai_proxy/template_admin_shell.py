from __future__ import annotations

_ADMIN_SHELL_HTML = """<div class="orb" aria-hidden="true"></div>
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
<div style="font-size:.8rem;color:var(--faint);margin-bottom:.5rem" data-i18n="tone_options_hint">每行一个模式，格式：底层tone值 | 显示名（显示名可省略，默认用tone值）。显示名会作为 /v1/models 里的模型名，其中的空格会自动转为下划线；每个模式会生成普通与「-持续」两个模型。底层值即发送给 M365 的 tone，可填任意字符串。保存后立即生效。</div>
<textarea id="tone-options-input" rows="7" style="width:100%;box-sizing:border-box;padding:8px 12px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong);font-size:.85rem;font-family:monospace;outline:none;resize:vertical;scrollbar-width:none;-ms-overflow-style:none" placeholder="Gpt_5_2_Reasoning | GPT 5.5 快速响应"></textarea>
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
<label style="font-size:.95rem;font-weight:800;color:var(--strong)" title="为多用户分配的 CDP 端口起始点"><span data-i18n="account_cdp_port_base_label">CDP 用户端口</span><input id="runtime-account-cdp-port-base" type="number" min="1" style="margin-top:.6rem;width:100%;box-sizing:border-box;padding:11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></label>
<label style="font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="refresh_before_label">提前刷新秒数</span><input id="runtime-refresh-before" type="number" min="0" style="margin-top:.6rem;width:100%;box-sizing:border-box;padding:11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></label>
<label style="font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="ws_idle_timeout_label">对话响应超时分钟</span><input id="runtime-ws-idle-timeout" type="number" min="1" style="margin-top:.6rem;width:100%;box-sizing:border-box;padding:11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></label>
<label class="ports-log-level" style="display:flex;flex-direction:column;gap:.6rem;font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="log_level_label">日志等级</span><select id="runtime-log-level" style="width:100%;box-sizing:border-box;padding:11px 36px 11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"><option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option><option>CRITICAL</option></select></label>
<label style="display:flex;flex-direction:column;gap:.6rem;font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="user_log_verbose_label">用户运行日志</span><select id="runtime-user-log-verbose" style="width:100%;box-sizing:border-box;padding:11px 36px 11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></select></label>
<label style="display:flex;flex-direction:column;gap:.6rem;font-size:.95rem;font-weight:800;color:var(--strong)"><span data-i18n="user_log_errors_label">用户错误日志</span><select id="runtime-user-log-errors" style="width:100%;box-sizing:border-box;padding:11px 36px 11px 13px;background:var(--inner);border:1px solid var(--inner-border);border-radius:10px;color:var(--strong);font-size:.95rem;font-weight:700"></select></label>
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
</div>"""
