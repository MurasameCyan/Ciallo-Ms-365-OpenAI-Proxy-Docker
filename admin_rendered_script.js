
const i18n={
  zh:{
    multi_badge:'多租户',
    nav_home:'首页总览',nav_users:'用户管理',nav_accounts:'账户管理',nav_settings:'全局设置',nav_debug:'调试模式',
    dash_title:'运行概览',dash_refresh:'刷新',btn_clear:'清空',dash_acct_valid:'账户有效 / 过期比',dash_key_status:'用户 启用 / 停用',dash_bind_status:'用户 绑定 / 未绑定',
    dash_kpi_users:'用户数',dash_kpi_accounts:'账户数',dash_kpi_active_users:'启用用户',dash_kpi_valid_accts:'有效账户',dash_kpi_expired_accts:'过期账户',dash_kpi_unbound:'未绑定用户',
    dash_valid:'有效',dash_expired:'过期',dash_bound:'已绑定',
    dash_trend_title:'趋势',dash_no_trend:'暂无趋势数据（每 5 分钟采样一次）',dash_calls_title:'调用统计',dash_tone_share:'对话模式占比',
    dash_calls_24h:'近 24h 调用',dash_calls_total:'累计调用',dash_expiry_warn:'账户「{name}」的 Token 将在 {time} 后过期，请尽快刷新。',
    title_accounts:'账户池',btn_add_account:'添加账户',
    accounts_hint:'每个账户拥有独立的 M365 Token 与 Chromium 刷新配置。刷新按需串行拉起浏览器，用完即关。',
    title_keys:'API Key 管理',btn_add_key:'新建用户',
    keys_hint:'每个 Key 绑定一个账户，可单独设置对话模式、提示词并随时启用/停用。',
    title_legacy:'全局 / 兼容 Token（高级）',
    acct_prompt_name:'账户名称（可选）：',acct_prompt_token:'可选：粘贴该账户的 access_token 或 wss:// URL（留空则稍后用 CDP 刷新）：',
    key_prompt_name:'Key 名称（可选，如用户/用途）：',
    key_prompt_username:'登录用户名（用户用它登录 / 页，可选）：',key_prompt_password:'登录密码：',
    key_prompt_password_opt:'登录密码（留空则不修改现有密码）：',
    cred_bad_user:'用户名只能包含英文字母和数字（1-32 位）',cred_bad_pass:'密码 6-64 位，仅限英文字母、数字和安全符号 !#$%&*+-.:=?@^_~',
    kf_create:'创建',kf_cancel:'取消',kf_username_ph:'用户名（选填）',kf_password_ph:'密码（选填，留空则自动生成）',
    key_form_hint:'ID 与 API Key 自动生成。M365 账户绑定由用户在「用户页」自行推送 Token 完成。',network_error:'网络错误',
    col_login:'登录名',btn_set_login:'设置账密',no_login:'未设',not_set:'未设定',
    btn_regen_key:'重置密钥',confirm_regen_key:'确定重置该 Key 的密钥吗？旧密钥立即失效，账户绑定与历史会话不受影响。',regen_ok:'新密钥已生成并复制到剪贴板',
    col_name:'名称',col_account:'账户',col_token:'Token',col_cookie:'Cookie',col_refresh_mode:'刷新方式',col_status:'状态',col_actions:'操作',col_key:'Key',col_mode:'模式',col_enabled:'启用',bound_count_label:'绑定',
    col_id:'ID',col_role:'角色',col_username:'用户名',col_password:'密码',
    btn_refresh:'刷新',btn_token_refresh:'刷新',btn_cookie_refresh:'刷新',btn_remove_token:'移除',btn_rebind:'改绑',btn_delete:'删除',btn_copy:'复制',btn_enable:'启用',btn_disable:'停用',btn_push_token:'更新',
    page_prev:'上一页',page_next:'下一页',page_info:'第 {cur}/{total} 页 · 共 {count} 条',page_size_label:'每页',page_size_unit:'条',
    batch_refresh:'批量刷新',batch_delete:'批量删除',batch_enable:'批量启用',batch_disable:'批量停用',batch_none:'请先选择项目',batch_confirm_delete:'确认批量删除所选项目？',
    confirm_del_account:'确定删除该账户？绑定它的 Key 将解绑。',confirm_del_key:'确定删除该 Key？',confirm_remove_token:'确定移除该账户 Token？',confirm_clear_stats:'确定清空这部分统计数据吗？',
    valid_short:'有效',invalid_short:'无效',cookie_valid_short:'有效',cookie_invalid_short:'无效',cookie_updated_label:'刷新时间',cookie_expires_label:'过期时间',refresh_auto:'自动',refresh_manual:'手动',refresh_unavailable:'不可用',no_accounts:'暂无账户',no_keys:'暂无 Key',unbound:'未绑定',acct_token_only:'Token',
    rebind_prompt:'输入要绑定的账户 ID（留空则解绑）：',push_token_prompt:'粘贴该账户的 access_token 或 wss:// URL：',
    rebind_title:'改绑 M365 账号',rebind_unbind:'（无）',rebind_confirm:'确定',
    title_update_token:'更新 Token',btn_update:'更新 Token',btn_check_login:'检查登录',btn_auto_capture:'自动刷新',
    title_status:'Token 与 登录状态',loading:'加载中...',
    title_quick_start:'快速开始',qs_recommended:'推荐：',qs_install_script:'安装油猴脚本（',qs_script_name:'一键脚本',
    qs_open_copilot:'打开',qs_type_trigger:'输入内容触发 WebSocket，然后在脚本面板点击',qs_push_token:'推送 Token',
    qs_alternative:'备选：',qs_manual_copy:'在 DevTools（Network → WS → wss://substrate.office.com/...）中手动复制 ',
    qs_paste_above:'然后粘贴到上方。',title_api_endpoints:'API 端点',
    api_grp_public:'公共接口',api_grp_v1:'OpenAI 兼容接口',api_grp_admin:'管理接口',
    api_chat:'OpenAI 兼容对话',api_messages:'Anthropic 兼容消息',api_models:'模型列表',api_responses:'Responses 接口',
    api_call_log:'调用记录',api_call_log_clear:'清空调用记录',api_metrics_history:'趋势数据',api_metrics_clear:'清空趋势数据',api_cap_get:'查看抓包数据',api_cap_post:'推送抓包数据',api_captgl_get:'接收开关状态',api_captgl_post:'设置接收开关',
    api_login_status:'Chromium 登录状态',api_chromium_logout:'退出 Chromium 登录',api_cookie_inject:'注入 Cookie',
    api_sys_get:'查看系统提示词',api_sys_post:'设置系统提示词',api_auto_cap:'自动抓取 Token',api_tok_status:'Token 状态',api_tok_update:'更新 Token',
    api_tone_get:'查看默认模式',api_tone_post:'设置默认模式',api_tool_get:'查看工具提示词',api_tool_post:'设置工具提示词',api_healthz:'健康检查',
    desc_paste_token:'粘贴 access_token 值或完整的 wss:// URL',
    valid:'有效',invalid:'无效',expires:'过期时间',remaining:'剩余',error:'错误',
    login:'登录',logged_in:'已登录',not_logged_in:'未登录（仅手动推送 Token）',
    btn_logout:'登出用户',logging_out:'登出中...',logout_ok:'已登出',logout_failed:'登出失败',
    page:'页面',title:'标题',chromium_not_running:'Chromium 未运行',
    capturing:'捕获中...',auto_captured:'自动刷新成功！剩余：',auto_capture_failed:'自动刷新失败',
    check_login:'检查登录中...',login_ok:'Chromium 已登录！自动刷新已启用。',
    login_not_ok:'未登录。请先使用油猴脚本推送 Cookie。',check_failed:'检查失败：',
    capturing_btn:'捕获中...',check_btn:'检查中...',
    status_yes:'是',status_no:'否',
    auto_refresh_on:'自动刷新：开',auto_refresh_off:'自动刷新：关',
    btn_stop_refresh:'停止自动刷新',btn_start_refresh:'启动自动刷新',
    auto_refresh_stopped:'自动刷新已停止',auto_refresh_started:'自动刷新已启动',
    auto_refresh_label:'自动刷新',
    username_label:'用户名',
    title_call_log:'API 调用记录',
    click_expand:'点击展开',
    no_calls_yet:'暂无调用记录',
    tool_calls_parsed:'解析出工具调用',
    view_raw:'查看原文',
    copy:'复制',copied:'已复制',copy_record:'复制整条',
    title_capture:'模式抓包对比',
    capture_hint:'在 M365 Copilot 切换不同模式（快速答复/深度思考、GPT 5.5/5.2）各发一条消息，用油猴脚本推送抓包，下方对比哪些字段控制模式。',
    no_capture_yet:'暂无抓包数据',
    dbg_guide_title:'调试指南',dbg_capture_recv:'接收抓包',dbg_gate_hint:'点击切换调试接收通道',
    dbg_capture_desc:'非必要时请勿开启，避免恶意数据写入；调试完成后请及时关闭。',
    dbg_capture_steps:'调试步骤：开启开关 → 在 M365 Copilot 切换不同模式（快速答复/深度思考、GPT 5.5/5.2）各发一条消息 → 用油猴脚本推送抓包 → 在「模式抓包对比」中比对字段。',
    title_tone:'对话模式（新用户模板）',
    tone_hint:'仅作为新建用户的默认对话模式模板。已存在用户不会跟随全局变化，用户可在自己的用户页覆盖并持久保存。',
    tone_saved:'已保存',
    title_tool_prompt:'提示词增强（全局）',
    tool_prompt_hint:'全局提示词增强：作为所有用户的公共基底，会自动拼接在每个用户自己的提示词增强「之前」（最终 = 全局基底 + 用户追加）。适合给所有人设置统一的 tool_call 行为基线。立即生效并持久保存，留空则不追加任何全局内容。',
    tool_prompt_save:'保存',
    tool_prompt_saved:'已保存',
    prompt_reset:'恢复默认',
    title_system_prompt:'系统提示词（全局）',
    system_prompt_hint:'全局系统级提示词：覆盖工具调用的基础系统提示词（定义 tool_call 格式与规则），作用于所有未单独设置系统提示词的用户。改错会导致工具调用失效，仅供高级用户调试。动态工具列表始终自动追加，不可编辑。留空则使用内置默认。',
    system_prompt_unlock:'解锁编辑（高级）',
    system_prompt_save:'保存',
    system_prompt_warn:'警告：系统级提示词定义了工具调用（tool_call）的格式与核心规则。修改不当会直接导致工具调用失效、模型无法读写文件。仅在你清楚自己在做什么时继续。\n\n确定要解锁编辑吗？',
    system_prompt_reset_confirm:'确定要将系统级提示词恢复为内置默认吗？当前自定义内容将被清空。',
  },
  en:{
    multi_badge:'Multi-tenant',
    nav_home:'Overview',nav_users:'Users',nav_accounts:'Accounts',nav_settings:'Settings',nav_debug:'Debug',
    dash_title:'Overview',dash_refresh:'Refresh',btn_clear:'Clear',dash_acct_valid:'Account valid / expired',dash_key_status:'Users enabled / disabled',dash_bind_status:'Users bound / unbound',
    dash_kpi_users:'Users',dash_kpi_accounts:'Accounts',dash_kpi_active_users:'Enabled users',dash_kpi_valid_accts:'Valid accounts',dash_kpi_expired_accts:'Expired accounts',dash_kpi_unbound:'Unbound users',
    dash_valid:'Valid',dash_expired:'Expired',dash_bound:'Bound',
    dash_trend_title:'Trend',dash_no_trend:'No trend data yet (sampled every 5 min)',dash_calls_title:'Call Stats',dash_tone_share:'Conversation mode share',
    dash_calls_24h:'Calls (24h)',dash_calls_total:'Calls total',dash_expiry_warn:'Account "{name}" token expires in {time}. Refresh it soon.',
    title_accounts:'Account Pool',btn_add_account:'Add Account',
    accounts_hint:'Each account owns an isolated M365 token and Chromium refresh profile. Refresh brings one browser up on demand (serial) and tears it down afterwards.',
    title_keys:'API Key Management',btn_add_key:'New User',
    keys_hint:'Each key is bound to one account, with its own conversation mode and prompts, and can be enabled/disabled anytime.',
    title_legacy:'Global / Legacy Token (Advanced)',
    acct_prompt_name:'Account name (optional):',acct_prompt_token:'Optional: paste this account\u0027s access_token or wss:// URL (leave empty to refresh via CDP later):',acc_form_hint:'Account name is optional. Token can be left empty and refreshed via CDP or updated later.',
    key_prompt_name:'Key name (optional, e.g. user/purpose):',
    key_prompt_username:'Login username (user logs into the / page with it, optional):',key_prompt_password:'Login password:',
    key_prompt_password_opt:'Login password (leave empty to keep the current one):',
    cred_bad_user:'Username must be 1-32 chars, letters and digits only',cred_bad_pass:'Password must be 6-64 chars: letters, digits and safe symbols !#$%&*+-.:=?@^_~',
    kf_create:'Create',kf_cancel:'Cancel',kf_username_ph:'Username (optional)',kf_password_ph:'Password (optional, auto-generated if blank)',
    key_form_hint:'ID and API Key are generated automatically. M365 account binding is done by the user pushing a token from the User page.',network_error:'Network error',
    col_login:'Login',btn_set_login:'Set credentials',no_login:'None',not_set:'Not set',
    btn_regen_key:'Reset key',confirm_regen_key:'Reset this key\u0027s secret? The old key stops working immediately; account binding and session history are unaffected.',regen_ok:'New key generated and copied to clipboard',
    col_name:'Name',col_account:'Account',col_token:'Token',col_cookie:'Cookie',col_refresh_mode:'Refresh',col_status:'Status',col_actions:'Actions',col_key:'Key',col_mode:'Mode',col_enabled:'Enabled',bound_count_label:'Bound',
    col_id:'ID',col_role:'Role',col_username:'Username',col_password:'Password',
    btn_refresh:'Refresh',btn_token_refresh:'Refresh',btn_cookie_refresh:'Refresh',btn_remove_token:'Remove',btn_rebind:'Rebind',btn_delete:'Delete',btn_copy:'Copy',btn_enable:'Enable',btn_disable:'Disable',btn_push_token:'Update',
    page_prev:'Prev',page_next:'Next',page_info:'Page {cur}/{total} · {count} total',page_size_label:'Per page',page_size_unit:'',
    batch_refresh:'Batch refresh',batch_delete:'Batch delete',batch_enable:'Batch enable',batch_disable:'Batch disable',batch_none:'Select items first',batch_confirm_delete:'Delete selected items?',
    confirm_del_account:'Delete this account? Keys bound to it will be unbound.',confirm_del_key:'Delete this key?',confirm_remove_token:'Remove this account token?',confirm_clear_stats:'Clear this statistics data?',
    valid_short:'Valid',invalid_short:'Invalid',cookie_valid_short:'Valid',cookie_invalid_short:'Invalid',cookie_updated_label:'Updated at',cookie_expires_label:'Expires at',refresh_auto:'Auto',refresh_manual:'Manual',refresh_unavailable:'Unavailable',no_accounts:'No accounts yet',no_keys:'No keys yet',unbound:'Unbound',acct_token_only:'Token',
    rebind_prompt:'Enter the account ID to bind (leave empty to unbind):',push_token_prompt:'Paste this account\u0027s access_token or wss:// URL:',
    rebind_title:'Rebind M365 account',rebind_unbind:'(None)',rebind_confirm:'Confirm',
    title_update_token:'Update Token',btn_update:'Update Token',btn_check_login:'Check Login',btn_auto_capture:'Auto Capture',
    title_status:'Token & Login Status',loading:'Loading...',
    title_quick_start:'Quick Start',qs_recommended:'Recommended:',qs_install_script:'Install the Tampermonkey script (',qs_script_name:'one-click script',
    qs_open_copilot:'open',qs_type_trigger:'type something to trigger WebSocket, then click',qs_push_token:'Push Token',
    qs_alternative:'Alternative:',qs_manual_copy:'Manually copy the ',
    qs_paste_above:'from DevTools (Network → WS → wss://substrate.office.com/...), then paste above.',title_api_endpoints:'API Endpoints',
    api_grp_public:'Public',api_grp_v1:'OpenAI-compatible',api_grp_admin:'Admin',
    api_chat:'OpenAI-compatible chat',api_messages:'Anthropic-compatible messages',api_models:'Model list',api_responses:'Responses API',
    api_call_log:'Call log',api_call_log_clear:'Clear call log',api_metrics_history:'Trend data',api_metrics_clear:'Clear trend data',api_cap_get:'View captures',api_cap_post:'Push captures',api_captgl_get:'Receive toggle state',api_captgl_post:'Set receive toggle',
    api_login_status:'Chromium login status',api_chromium_logout:'Sign out of Chromium',api_cookie_inject:'Inject cookies',
    api_sys_get:'View system prompt',api_sys_post:'Set system prompt',api_auto_cap:'Auto-capture token',api_tok_status:'Token status',api_tok_update:'Update token',
    api_tone_get:'View default mode',api_tone_post:'Set default mode',api_tool_get:'View tool prompt',api_tool_post:'Set tool prompt',api_healthz:'Health check',
    desc_paste_token:'Paste the access_token value or the full wss:// URL',
    valid:'Valid',invalid:'Invalid',expires:'Expires',remaining:'Remaining',error:'Error',
    login:'Login',logged_in:'Logged In',not_logged_in:'Not Logged In (auto-refresh only)',
    btn_logout:'Logout',logging_out:'Logging out...',logout_ok:'Logged out',logout_failed:'Logout failed',
    page:'Page',title:'Title',chromium_not_running:'Chromium Not Running',
    capturing:'Capturing...',auto_captured:'Auto-captured! Remaining: ',auto_capture_failed:'Auto-capture failed',
    check_login:'Checking...',login_ok:'Chromium is logged in! Auto-refresh is active.',
    login_not_ok:'Not logged in. Use Tampermonkey script to push cookies first.',check_failed:'Check failed: ',
    capturing_btn:'Capturing...',check_btn:'Checking...',
    status_yes:'Yes',status_no:'No',
    auto_refresh_on:'Auto Refresh: On',auto_refresh_off:'Auto Refresh: Off',
    btn_stop_refresh:'Stop Auto Refresh',btn_start_refresh:'Start Auto Refresh',
    auto_refresh_stopped:'Auto refresh stopped',auto_refresh_started:'Auto refresh started',
    auto_refresh_label:'Auto Refresh',
    username_label:'Username',
    title_call_log:'API Call Log',
    click_expand:'Click to expand',
    no_calls_yet:'No calls yet',
    tool_calls_parsed:'Parsed tool calls',
    view_raw:'View raw',
    copy:'Copy',copied:'Copied',copy_record:'Copy record',
    title_capture:'Mode Capture Compare',
    capture_hint:'In M365 Copilot switch between modes (Fast/Think, GPT 5.5/5.2) and send one message each, then push the captures via the Tampermonkey script. Compare which fields control the mode below.',
    no_capture_yet:'No captures yet',
    dbg_guide_title:'Debug Guide',dbg_capture_recv:'Receive captures',dbg_gate_hint:'Click to toggle the debug receive channel',
    dbg_capture_desc:'Do not enable unless necessary, to avoid malicious data being written; turn it off promptly after debugging.',
    dbg_capture_steps:'Steps: enable the switch → in M365 Copilot switch modes (Fast/Think, GPT 5.5/5.2) and send one message each → push the captures via the Tampermonkey script → compare fields under "Mode Capture Compare".',
    title_tone:'Conversation Mode (New User Template)',
    tone_hint:'Only used as the default conversation mode template for newly created users. Existing users will not follow global changes; users can override and persist their own mode on the user page.',
    tone_saved:'Saved',
    title_tool_prompt:'Prompt Enhancement (Global)',
    tool_prompt_hint:'Global prompt enhancement: a shared base for all users, automatically prepended before each user\u0027s own enhancement (final = global base + user addition). Ideal for setting a common tool_call baseline for everyone. Applies immediately and persists; leave empty to add nothing global.',
    tool_prompt_save:'Save',
    tool_prompt_saved:'Saved',
    prompt_reset:'Restore default',
    title_system_prompt:'System Prompt (Global)',
    system_prompt_hint:'Global system prompt: overrides the base system prompt for tool calls (defines the tool_call format and rules) for all users who have not set their own. A wrong edit will break tool calling. For advanced debugging only. The dynamic tool list is always appended and is not editable. Leave empty to use the built-in default.',
    system_prompt_unlock:'Unlock editing (Advanced)',
    system_prompt_save:'Save',
    system_prompt_warn:'WARNING: the system prompt defines the format and core rules of tool calls (tool_call). An incorrect edit will break tool calling and the model will be unable to read/write files. Continue only if you know what you are doing.\n\nUnlock editing?',
    system_prompt_reset_confirm:'Restore the system prompt to the built-in default? Your current custom content will be cleared.',
  }
};
let lang=localStorage.getItem('lang')||'zh';
function t(key){return i18n[lang][key]||key}
function toggleLang(){
  lang=lang==='zh'?'en':'zh';
  localStorage.setItem('lang',lang);
  applyLang();
}
function applyLang(){
  const btn=document.getElementById('lang-toggle');
  if(btn)btn.title=lang==='zh'?'切换到英文':'Switch to Chinese';
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const key=el.getAttribute('data-i18n');
    if(i18n[lang][key])el.textContent=i18n[lang][key];
  });
  loadStatus();loadChromiumStatus();loadTone();
  loadAccounts();loadKeys();
  const vt=document.getElementById('view-title');
  if(vt){const vk=vt.getAttribute('data-i18n');if(vk&&i18n[lang][vk])vt.textContent=i18n[lang][vk]}
  const out=document.getElementById('admin-logout');if(out)out.title=lang==='zh'?'退出管理后台':'Sign out admin';
  applyTheme();applyCollapse();
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
function initGlassSelect(root){
  const scope=root||document;
  scope.querySelectorAll('select').forEach(sel=>{
    if(sel.dataset.glassReady==='1')return;
    sel.dataset.glassReady='1';sel.classList.add('glass-native');
    const wrap=document.createElement('span');wrap.className='glass-select';
    if(sel.classList.contains('page-select'))wrap.style.minWidth='76px';
    if(sel.classList.contains('tone-select'))wrap.style.minWidth='180px';
    if(sel.id==='rebind-select')wrap.style.width='100%';
    const trigger=document.createElement('button');trigger.type='button';trigger.className='glass-select-trigger';
    const menu=document.createElement('div');menu.className='glass-select-menu';
    wrap.appendChild(trigger);wrap.appendChild(menu);sel.parentNode.insertBefore(wrap,sel.nextSibling);
    const close=()=>wrap.classList.remove('open');
    const render=()=>{
      const opt=sel.options[sel.selectedIndex];trigger.textContent=opt?opt.textContent:'';menu.innerHTML='';
      Array.from(sel.options).forEach(o=>{const b=document.createElement('button');b.type='button';b.className='glass-select-option'+(o.value===sel.value?' active':'');b.textContent=o.textContent;b.onclick=e=>{e.stopPropagation();sel.value=o.value;sel.dispatchEvent(new Event('change',{bubbles:true}));render();close()};menu.appendChild(b)});
    };
    sel._glassRender=render;
    trigger.onclick=e=>{e.stopPropagation();document.querySelectorAll('.glass-select.open').forEach(x=>{if(x!==wrap)x.classList.remove('open')});render();wrap.classList.toggle('open')};
    sel.addEventListener('change',render);render();
  });
}
function refreshGlassSelect(sel){
  if(!sel)return;
  if(sel.dataset.glassReady!=='1')initGlassSelect(sel.parentElement||document);
  if(typeof sel._glassRender==='function')sel._glassRender();
}
document.addEventListener('click',()=>document.querySelectorAll('.glass-select.open').forEach(x=>x.classList.remove('open')));
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.glass-select.open').forEach(x=>x.classList.remove('open'))});
function switchView(view){
  document.body.setAttribute('data-view',view);
  localStorage.setItem('admin_view',view);
  document.querySelectorAll('.nav-item').forEach(el=>{el.classList.toggle('active',el.getAttribute('data-nav')===view)});
  const vt=document.getElementById('view-title');
  const map={home:'nav_home',users:'nav_users',accounts:'nav_accounts',settings:'nav_settings',debug:'nav_debug'};
  const vk=map[view]||'nav_home';
  if(vt){vt.setAttribute('data-i18n',vk);vt.textContent=(i18n[lang]&&i18n[lang][vk])||vt.textContent}
  if(view==='debug')loadCaptureToggle();
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

// Kept as a thin alias so existing init/interval calls still work; loadStatus now
// renders both token and chromium status together in the required order.
async function loadChromiumStatus(){return loadStatus()}

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
  loadChromiumStatus();
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
      loadChromiumStatus();loadStatus();
    }else{
      msg.className='msg err';msg.textContent=d.error?.message||d.error||t('logout_failed');
    }
  }catch(e){msg.className='msg err';msg.textContent=(lang==='zh'?'网络错误：':'Network error: ')+e}
  finally{btn.disabled=false}
}

// ============================ Multi-tenant admin JS ============================
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function adminDialog(message,okOnly){
  return new Promise(resolve=>{
    const ov=document.createElement('div');
    ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.3);backdrop-filter:blur(18px) saturate(145%);-webkit-backdrop-filter:blur(18px) saturate(145%);display:flex;align-items:center;justify-content:center;z-index:1000';
    ov.innerHTML='<div class="flow-box" style="position:relative;background:rgba(15,23,42,.3);border:1px solid rgba(96,242,255,.28);border-radius:12px;padding:1.25rem;width:340px;max-width:90vw;box-shadow:0 24px 70px rgba(0,0,0,.36),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(22px) saturate(150%);-webkit-backdrop-filter:blur(22px) saturate(150%)">'
      +'<div style="font-size:.86rem;color:var(--text);line-height:1.55;word-break:break-word">'+esc(message)+'</div>'
      +'<div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem">'
      +(okOnly?'':'<button id="dlg-cancel" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>')
      +'<button id="dlg-ok" style="font-size:.8rem;padding:6px 14px">'+t('rebind_confirm')+'</button>'
      +'</div></div>';
    document.body.appendChild(ov);
    const done=v=>{ov.remove();resolve(v)};
    ov.addEventListener('click',e=>{if(e.target===ov)done(false)});
    const c=ov.querySelector('#dlg-cancel');if(c)c.onclick=()=>done(false);
    ov.querySelector('#dlg-ok').onclick=()=>done(true);
  });
}
const adminAlert=message=>adminDialog(message,true);
const adminConfirm=message=>adminDialog(message,false);
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
  const keys=__keys||[],accts=__accounts||[];
  const acctValid=accts.filter(a=>a.token_status&&a.token_status.valid).length;
  const acctExpired=accts.length-acctValid;
  const keyEnabled=keys.filter(k=>k.enabled).length;
  const keyDisabled=keys.length-keyEnabled;
  const keyBound=keys.filter(k=>k.account_id).length;
  const keyUnbound=keys.length-keyBound;
  kpi.innerHTML=kpiCard(t('dash_kpi_users'),keys.length,'#38bdf8')
    +kpiCard(t('dash_kpi_accounts'),accts.length,'#a78bfa')
    +kpiCard(t('dash_kpi_active_users'),keyEnabled,'#22c55e')
    +kpiCard(t('dash_kpi_valid_accts'),acctValid,'#22c55e')
    +kpiCard(t('dash_kpi_expired_accts'),acctExpired,acctExpired?'#f59e0b':'#64748b')
    +kpiCard(t('dash_kpi_unbound'),keyUnbound,keyUnbound?'#f59e0b':'#64748b');
  const da=document.getElementById('dash-donut-acct');
  if(da)da.innerHTML=donut([{value:acctValid,color:'#22c55e',label:t('dash_valid')},{value:acctExpired,color:'#ef4444',label:t('dash_expired')}],t('dash_kpi_accounts'),accts.length);
  const dk=document.getElementById('dash-donut-key');
  if(dk)dk.innerHTML=donut([{value:keyEnabled,color:'#22c55e',label:t('btn_enable')},{value:keyDisabled,color:'#64748b',label:t('btn_disable')}],t('dash_kpi_users'),keys.length);
  const db=document.getElementById('dash-donut-bind');
  if(db)db.innerHTML=donut([{value:keyBound,color:'#38bdf8',label:t('dash_bound')},{value:keyUnbound,color:'#f59e0b',label:t('unbound')}],t('dash_kpi_users'),keys.length);
}
// ---- trend line chart (multi-series SVG) ----
function fmtClock(sec){if(sec==null)return'N/A';const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60);return(h?h+'h ':'')+m+'m'}
function fmtHMS(sec){sec=Math.max(0,Math.floor(Number(sec)||0));const h=String(Math.floor(sec/3600)).padStart(2,'0'),m=String(Math.floor(sec%3600/60)).padStart(2,'0'),s=String(sec%60).padStart(2,'0');return h+':'+m+':'+s}
function fmtTs(ts){return ts?new Date(ts*1000).toLocaleString():'N/A'}
function liveTokenStatus(st){st=st||{};const exp=Number(st.expires_at||0),now=Date.now()/1000;const rem=exp?Math.max(0,Math.floor(exp-now)):Math.max(0,Math.floor(st.seconds_remaining||0));return {...st,valid:!!st.valid&&(!exp||rem>0),seconds_remaining:rem}}
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
  // build a smooth curve path (Catmull-Rom -> cubic Bezier) through the points
  const smoothPath=pts=>{
    if(pts.length<2)return pts.length?('M'+pts[0].x.toFixed(1)+' '+pts[0].y.toFixed(1)):'';
    let dd='M'+pts[0].x.toFixed(1)+' '+pts[0].y.toFixed(1);
    for(let i=0;i<pts.length-1;i++){
      const p0=pts[i-1]||pts[i],p1=pts[i],p2=pts[i+1],p3=pts[i+2]||pts[i+1];
      const c1x=p1.x+(p2.x-p0.x)/6,c2x=p2.x-(p3.x-p1.x)/6;
      // clamp control-point Y within the segment's endpoint range to avoid overshoot on step data
      const lo=Math.min(p1.y,p2.y),hi=Math.max(p1.y,p2.y);
      const c1y=Math.max(lo,Math.min(hi,p1.y+(p2.y-p0.y)/6));
      const c2y=Math.max(lo,Math.min(hi,p2.y-(p3.y-p1.y)/6));
      dd+=' C'+c1x.toFixed(1)+' '+c1y.toFixed(1)+' '+c2x.toFixed(1)+' '+c2y.toFixed(1)+' '+p2.x.toFixed(1)+' '+p2.y.toFixed(1);
    }
    return dd;
  };
  series.forEach(s=>{
    const pts=points.map(p=>({x:X(p.ts),y:Y(p[s.key]||0)}));
    const d=smoothPath(pts);
    g+='<path d="'+d+'" fill="none" stroke="'+s.color+'" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" opacity="0.1" filter="drop-shadow(0 0 7px '+s.color+')"><animate attributeName="opacity" values="0.06;0.18;0.06" dur="3.2s" repeatCount="indefinite"/><animate attributeName="stroke-width" values="4;8;4" dur="3.2s" repeatCount="indefinite"/></path>';
    g+='<path d="'+d+'" fill="none" stroke="'+s.color+'" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" filter="drop-shadow(0 0 5px '+s.color+')"><animate attributeName="opacity" values="0.9;1;0.9" dur="3.2s" repeatCount="indefinite"/></path>';
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
        share.innerHTML=ents.map((e,i)=>{const pct=Math.round(e[1]/total*100);return '<div style="margin-bottom:.4rem"><div style="display:flex;justify-content:space-between;font-size:.76rem;color:var(--muted)"><span>'+esc(e[0])+'</span><span>'+e[1]+' ('+pct+'%)</span></div><div style="height:8px;background:var(--track);border-radius:4px;overflow:hidden;margin-top:2px"><div style="width:'+pct+'%;height:100%;background:'+pal[i%pal.length]+'"></div></div></div>'}).join('');
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
}
let __accounts=[];
let __selectedAccountIds=new Set();
let __selectedAccount=localStorage.getItem('admin_sel_account')||'';
function renderSelectedStatus(){
  const card=document.getElementById('status-card');
  const box=document.getElementById('status-content');
  const nameEl=document.getElementById('status-acct-name');
  if(!card||!box)return;
  const a=__accounts.find(x=>x.id===__selectedAccount);
  if(!a){card.classList.add('hide-card');return}
  card.classList.remove('hide-card');
  if(nameEl)nameEl.textContent=(a.name||a.id)+(a.email?' · '+a.email:'');
  const st=liveTokenStatus(a.token_status||{});
  const v=st.valid;
  const row=(label,val,vcls)=>'<div class="status-row"><span class="status-label">'+label+'</span><span class="status-value '+(vcls||'')+'">'+val+'</span></div>';
  let html='';
  html+=row(t('col_account'),esc(a.name||a.id),'valid');
  if(a.email)html+=row('Email',esc(a.email),'');
  html+=row(t('col_token'),v?t('valid_short')+' '+fmtHMS(st.seconds_remaining||0):t('invalid_short'),v?'valid':'invalid');
  const cv=liveCookieValid(a);
  html+=row(t('col_cookie'),cv?t('cookie_valid_short'):t('cookie_invalid_short'),cv?'valid':'warn');
  html+=row(t('cookie_updated_label'),fmtTs(a.cookie_updated_at),'');
  html+=row(t('cookie_expires_label'),fmtTs(a.cookie_expires_at),cv?'valid':'warn');
  html+=row(t('col_refresh_mode'),a.token_source==='cdp'?(cv?t('refresh_auto'):t('refresh_unavailable')):t('refresh_manual'),a.token_source==='cdp'&&cv?'valid':'warn');
  if(st.error)html+=row(t('error'),esc(st.error),'invalid');
  box.innerHTML=html;
}
function selectAccount(id){
  __selectedAccount=(__selectedAccount===id)?'':id;
  localStorage.setItem('admin_sel_account',__selectedAccount);
  loadAccounts();
}
const __page={keys:1,accounts:1};
const __pageSize={keys:10,accounts:10};
function _slicePage(arr,which){
  const size=__pageSize[which];
  const total=Math.max(1,Math.ceil(arr.length/size));
  if(__page[which]>total)__page[which]=total;
  if(__page[which]<1)__page[which]=1;
  const start=(__page[which]-1)*size;
  return {items:arr.slice(start,start+size),page:__page[which],total:total,count:arr.length};
}
function _setPage(which,p){__page[which]=p;which==='keys'?loadKeys():loadAccounts()}
function _setPageSize(which,s){__pageSize[which]=parseInt(s,10)||10;__page[which]=1;which==='keys'?loadKeys():loadAccounts()}
function _pageFoot(which,pg){
  const sizes=[10,20,50,100];
  let opts='';sizes.forEach(s=>{opts+='<option value="'+s+'"'+(s===__pageSize[which]?' selected':'')+'>'+s+'</option>'});
  const info=t('page_info').replace('{cur}',pg.page).replace('{total}',pg.total).replace('{count}',pg.count);
  return '<div class="tbl-foot"><div class="page-size"><span>'+t('page_size_label')+'</span><select class="page-select" onchange="_setPageSize(\''+which+'\',this.value)">'+opts+'</select><span>'+t('page_size_unit')+'</span></div>'
    +'<div class="page-nav"><button class="page-btn" '+(pg.page<=1?'disabled':'')+' onclick="_setPage(\''+which+'\','+(pg.page-1)+')">'+t('page_prev')+'</button>'
    +'<span class="page-info">'+info+'</span>'
    +'<button class="page-btn" '+(pg.page>=pg.total?'disabled':'')+' onclick="_setPage(\''+which+'\','+(pg.page+1)+')">'+t('page_next')+'</button></div></div>';
}
async function loadAccounts(localOnly=false){
  const box=document.getElementById('accounts-content');
  if(!box)return;
  try{
    if(!localOnly){
      const r=await fetch('/admin/accounts',{credentials:'include'});
      if(r.status===401){box.innerHTML='<span style="color:var(--faint)">'+t('loading')+'</span>';return}
      const d=await r.json();
      __accounts=d.accounts||[];
    }
    if(!__accounts.length){box.innerHTML='<span style="color:var(--faint)">'+t('no_accounts')+'</span>';renderSelectedStatus();renderDashboard();return}
    const __pg=_slicePage(__accounts,'accounts');
    let h='<div class="tbl-tools"><button onclick="batchRefreshAccounts()" style="font-size:.72rem;padding:3px 8px;background:var(--chip)">'+t('batch_refresh')+'</button><button onclick="batchDeleteAccounts()" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('batch_delete')+'</button></div>'
      +'<div class="tbl-scroll"><table class="admin-tbl"><thead><tr style="color:var(--muted);text-align:left">'
      +'<th style="padding:.3rem;width:28px"><input type="checkbox" onchange="selectAllAccounts(this.checked)"></th><th style="padding:.3rem">'+t('col_name')+'</th><th style="padding:.3rem">'+t('col_token')+'</th><th style="padding:.3rem">'+t('col_cookie')+'</th><th style="padding:.3rem">'+t('col_refresh_mode')+'</th><th style="padding:.3rem;text-align:right">'+t('col_actions')+'</th></tr></thead><tbody>';
    __pg.items.forEach(a=>{
      const st=liveTokenStatus(a.token_status||{});
      const valid=st.valid;
      const rem=valid?(' '+fmtHMS(st.seconds_remaining||0)):'';
      const badge='<span style="width:134px;display:inline-flex;justify-content:center;padding:.15rem .6rem;border-radius:99px;font-size:.72rem;background:'+(valid?'rgba(63,185,112,.16)':'rgba(224,138,138,.16)')+';color:'+(valid?'#3fb970':'#e08a8a')+';border:1px solid '+(valid?'rgba(63,185,112,.4)':'rgba(224,138,138,.4)')+'">'+(valid?t('valid_short'):t('invalid_short'))+rem+'</span>';
      const cookieValid=liveCookieValid(a);
      const cookieBadge='<span style="width:76px;display:inline-flex;justify-content:center;padding:.15rem .6rem;border-radius:99px;font-size:.72rem;background:'+(cookieValid?'rgba(96,242,255,.15)':'rgba(148,163,184,.12)')+';color:'+(cookieValid?'#60f2ff':'#94a3b8')+';border:1px solid '+(cookieValid?'rgba(96,242,255,.4)':'rgba(148,163,184,.25)')+'">'+(cookieValid?t('cookie_valid_short'):t('cookie_invalid_short'))+'</span>';
      const cookieMeta='<div style="display:grid;grid-template-columns:76px auto;column-gap:.55rem;row-gap:2px;align-items:center;white-space:nowrap"><div>'+cookieBadge+'</div><div style="color:var(--faint);font-size:.68rem">'+t('cookie_updated_label')+': '+fmtTs(a.cookie_updated_at)+'</div><button class="cookie-refresh-btn" data-id="'+esc(a.id)+'" style="width:76px;font-size:.72rem;padding:3px 8px">'+t('btn_cookie_refresh')+'</button><div style="color:var(--faint);font-size:.68rem">'+t('cookie_expires_label')+': '+fmtTs(a.cookie_expires_at)+'</div></div>';
      const boundNames=Array.isArray(a.bound_names)?a.bound_names.filter(Boolean):[];
      const boundMain=boundNames[0]||a.name||'name';
      const boundTitle=boundNames.length?boundNames.join(String.fromCharCode(10)):boundMain;
      const boundMore=boundNames.length>1?' +'+(boundNames.length-1):'';
      const refreshMode=a.token_source==='cdp'?(cookieValid?t('refresh_auto'):t('refresh_unavailable')):t('refresh_manual');
      const refreshColor=a.token_source==='cdp'&&cookieValid?'#a78bfa':(a.token_source==='cdp'?'#f59e0b':'var(--faint)');
      const refreshBadge='<span style="padding:.15rem .6rem;border-radius:99px;font-size:.72rem;background:rgba(167,139,250,.12);color:'+refreshColor+';border:1px solid rgba(167,139,250,.28)">'+refreshMode+'</span>';
      const sel=a.id===__selectedAccount;
      h+='<tr class="acct-row '+(sel?'selected':'')+'" onclick="selectAccount(\''+a.id+'\')" style="border-top:1px solid var(--inner-border);cursor:pointer">'
        +'<td style="padding:.4rem"><input class="acct-check" type="checkbox" '+(__selectedAccountIds.has(a.id)?'checked':'')+' onclick="event.stopPropagation();toggleAccountSelected(\''+a.id+'\',this.checked)"></td>'
        +'<td style="padding:.4rem">'+(sel?'<span style="color:#38bdf8">&#9679; </span>':'')+'<span>'+esc(a.name||a.id)+(a.email?' <span style="color:var(--faint);font-size:.72rem">'+esc(a.email)+'</span>':'')+'</span><div title="'+esc(boundTitle)+'" style="color:var(--faint);font-size:.7rem">'+esc(boundMain)+esc(boundMore)+' id: '+esc(a.id)+' · '+t('bound_count_label')+': '+a.key_count+'</div></td>'
        +'<td style="padding:.4rem;white-space:nowrap"><div>'+badge+'</div><div style="margin-top:2px;display:flex;gap:4px;align-items:center;width:134px"><button onclick="event.stopPropagation();refreshAccount(\''+a.id+'\')" style="width:42px;font-size:.72rem;padding:3px 0">'+t('btn_token_refresh')+'</button><button onclick="event.stopPropagation();toggleAccountToken(\''+a.id+'\')" style="width:42px;font-size:.72rem;padding:3px 0;background:var(--chip)">'+t('btn_push_token')+'</button><button onclick="event.stopPropagation();clearAccountToken(\''+a.id+'\')" style="width:42px;font-size:.72rem;padding:3px 0;background:rgba(239,68,68,.18);color:#fecaca;border:1px solid rgba(239,68,68,.35)">'+t('btn_remove_token')+'</button></div></td>'
        +'<td style="padding:.4rem;white-space:nowrap">'+cookieMeta+'</td>'
        +'<td style="padding:.4rem">'+refreshBadge+'</td>'
        +'<td style="padding:.4rem;text-align:right;white-space:nowrap">' 
        +'<button onclick="event.stopPropagation();delAccount(\''+a.id+'\')" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('btn_delete')+'</button>'
        +'</td></tr>'
        +'<tr id="atok-'+a.id+'" style="display:none"><td colspan="6" style="padding:.7rem .9rem;vertical-align:middle;background:linear-gradient(90deg,rgba(96,242,255,.13),rgba(140,107,255,.11),rgba(255,94,219,.07));box-shadow:inset 3px 0 0 rgba(96,242,255,.72),inset 0 1px 0 rgba(255,255,255,.08),0 0 24px rgba(96,242,255,.1);backdrop-filter:blur(10px)" onclick="event.stopPropagation()">'
        +'<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">'
        +'<textarea id="atok-val-'+a.id+'" placeholder="'+t('acct_prompt_token')+'" style="flex:1;min-width:220px;height:34px;min-height:34px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none;resize:vertical"></textarea>'
        +'<button onclick="submitAccountToken(\''+a.id+'\')" style="font-size:.8rem;padding:6px 14px">'+t('kf_create')+'</button>'
        +'<button onclick="toggleAccountToken(\''+a.id+'\')" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>'
        +'</div><div id="atok-msg-'+a.id+'" style="font-size:.78rem;color:#ef4444;margin-top:.4rem"></div>'
        +'</td></tr>';
    });
    h+='</tbody></table></div>'+_pageFoot('accounts',__pg);
    box.innerHTML=h;
    box.querySelectorAll('.cookie-refresh-btn').forEach(btn=>btn.onclick=e=>{e.stopPropagation();refreshAccountCookie(btn.dataset.id)});
    initGlassSelect(box);
    renderSelectedStatus();
    renderDashboard();
  }catch(e){}
}
function toggleAccountForm(show){
  const f=document.getElementById('acc-form');if(!f)return;
  const open=(show===undefined)?(f.style.display==='none'):show;
  f.style.display=open?'block':'none';
  if(open){
    const n=document.getElementById('af-name'),tk=document.getElementById('af-token'),m=document.getElementById('af-msg');
    n.placeholder=t('acct_prompt_name');tk.placeholder=t('acct_prompt_token');
    n.value='';tk.value='';m.textContent='';n.focus();
  }
}
async function submitAccount(){
  const n=document.getElementById('af-name'),tk=document.getElementById('af-token'),m=document.getElementById('af-msg');
  const name=(n.value||'').trim();
  const token=(tk.value||'').trim();
  m.textContent='';
  try{
    const r=await fetch('/admin/accounts',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,token:token})});
    if(!r.ok){const d=await r.json().catch(()=>({}));m.textContent=(d.error&&d.error.message)||'error';return}
    toggleAccountForm(false);
    loadAccounts();loadKeys();
  }catch(e){m.textContent=t('network_error')}
}
async function refreshAccount(id){
  try{
    const r=await fetch('/admin/accounts/'+id+'/refresh',{method:'POST',credentials:'include'});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)await adminAlert((d.error&&d.error.message)||'error');
    loadAccounts();
  }catch(e){}
}
async function refreshAccountCookie(id){
  try{
    const r=await fetch('/admin/accounts/'+id+'/cookie-refresh',{method:'POST',credentials:'include'});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)await adminAlert((d.error&&d.error.message)||'error');
    loadAccounts();
  }catch(e){}
}
async function clearAccountToken(id){
  if(!await adminConfirm(t('confirm_remove_token')))return;
  try{
    const r=await fetch('/admin/accounts/'+id+'/token/clear',{method:'POST',credentials:'include'});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)await adminAlert((d.error&&d.error.message)||'error');
    loadAccounts();
  }catch(e){}
}
function toggleAccountToken(id){
  const row=document.getElementById('atok-'+id);if(!row)return;
  const open=row.style.display==='none';
  row.style.display=open?'table-row':'none';
  if(open){const m=document.getElementById('atok-msg-'+id);if(m)m.textContent='';const v=document.getElementById('atok-val-'+id);if(v){v.value='';v.focus()}}
}
async function submitAccountToken(id){
  const v=document.getElementById('atok-val-'+id),m=document.getElementById('atok-msg-'+id);
  const token=(v&&v.value||'').trim();
  if(m)m.textContent='';
  if(!token){if(m)m.textContent=t('acct_prompt_token');return}
  try{
    const r=await fetch('/admin/accounts/'+id+'/token',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:token})});
    if(!r.ok){const d=await r.json().catch(()=>({}));if(m)m.textContent=(d.error&&d.error.message)||'error';return}
    toggleAccountToken(id);
    loadAccounts();
  }catch(e){if(m)m.textContent=t('network_error')}
}
async function delAccount(id){
  if(!await adminConfirm(t('confirm_del_account')))return;
  try{await fetch('/admin/accounts/'+id,{method:'DELETE',credentials:'include'});loadAccounts();loadKeys()}catch(e){}
}
function toggleAccountSelected(id,on){on?__selectedAccountIds.add(id):__selectedAccountIds.delete(id)}
function selectAllAccounts(on){__selectedAccountIds=new Set(on?__accounts.map(a=>a.id):[]);document.querySelectorAll('.acct-check').forEach(cb=>{cb.checked=!!on})}
async function batchRefreshAccounts(){const ids=[...__selectedAccountIds];if(!ids.length)return await adminAlert(t('batch_none'));for(const id of ids){await fetch('/admin/accounts/'+id+'/refresh',{method:'POST',credentials:'include'}).catch(()=>{})}loadAccounts()}
async function batchDeleteAccounts(){const ids=[...__selectedAccountIds];if(!ids.length)return await adminAlert(t('batch_none'));if(!await adminConfirm(t('batch_confirm_delete')))return;for(const id of ids){await fetch('/admin/accounts/'+id,{method:'DELETE',credentials:'include'}).catch(()=>{})}__selectedAccountIds.clear();loadAccounts();loadKeys()}
let __keys=[];
let __selectedKeyIds=new Set();
async function loadKeys(){
  const box=document.getElementById('keys-content');
  if(!box)return;
  try{
    const r=await fetch('/admin/keys',{credentials:'include'});
    if(r.status===401){box.innerHTML='<span style="color:var(--faint)">'+t('loading')+'</span>';return}
    const d=await r.json();
    __keys=d.keys||[];
    if(!__keys.length){box.innerHTML='<span style="color:var(--faint)">'+t('no_keys')+'</span>';renderDashboard();return}
    const __pg=_slicePage(__keys,'keys');
    let h='<div class="tbl-tools"><button onclick="batchSetKeys(true)" style="font-size:.72rem;padding:3px 8px;background:#059669">'+t('batch_enable')+'</button><button onclick="batchSetKeys(false)" style="font-size:.72rem;padding:3px 8px;background:#b45309">'+t('batch_disable')+'</button><button onclick="batchDeleteKeys()" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('batch_delete')+'</button></div>'
      +'<div class="tbl-scroll"><table class="admin-tbl"><thead><tr style="color:var(--muted);text-align:left">'
      +'<th style="padding:.3rem;width:28px"><input type="checkbox" onchange="selectAllKeys(this.checked)"></th><th style="padding:.3rem">'+t('col_id')+'</th><th style="padding:.3rem">'+t('col_role')+'</th><th style="padding:.3rem">'+t('col_username')+'</th><th style="padding:.3rem">'+t('col_password')+'</th><th style="padding:.3rem">'+t('col_key')+'</th><th style="padding:.3rem">'+t('col_account')+'</th><th style="padding:.3rem;text-align:right">'+t('col_actions')+'</th></tr></thead><tbody>';
    __pg.items.forEach(k=>{
      const acc=k.account_id?((k.account_source==='manual'?('<span style="padding:.1rem .5rem;border-radius:99px;font-size:.72rem;background:rgba(96,242,255,.16);color:#60f2ff;border:1px solid rgba(96,242,255,.4)">'+t('acct_token_only')+'</span>'):esc(k.account_name||k.account_id))+'<div style="color:var(--faint);font-size:.7rem;margin-top:.15rem">'+esc(k.account_id)+'</div>'):('<span style="color:#f59e0b">'+t('unbound')+'</span>');
      const en=k.enabled;
      const uname=k.username?esc(k.username):('<span style="color:var(--faint)">'+t('no_login')+'</span>');
      const pwd=k.password?('<div class="kv-copy"><code style="font-size:.72rem;color:#818cf8">'+esc(k.password)+'</code><button onclick="copyPwd(\''+k.id+'\',this)" style="font-size:.68rem;background:var(--chip)">'+t('btn_copy')+'</button></div>'):('<span style="color:var(--faint)">'+t('not_set')+'</span>');
      const isAdmin=k.role==='admin';
      const roleBadge='<span class="role-badge '+(isAdmin?'admin':'user')+'" title="'+(isAdmin?'admin':'user')+'">'+(isAdmin?'A':'U')+'</span>';
      h+='<tr id="krow-'+k.id+'" style="border-top:1px solid #334155;'+(en?'':'opacity:.5')+'">'
        +'<td style="padding:.4rem"><input class="key-check" type="checkbox" '+(__selectedKeyIds.has(k.id)?'checked':'')+' onclick="toggleKeySelected(\''+k.id+'\',this.checked)"></td>'
        +'<td style="padding:.4rem"><code style="font-size:.72rem;color:var(--faint)">'+esc(k.id.replace(/^key_/, 'id_'))+'</code></td>'
        +'<td style="padding:.4rem">'+roleBadge+'</td>'
        +'<td style="padding:.4rem;font-size:.78rem">'+uname+'</td>'
        +'<td style="padding:.4rem;font-size:.78rem">'+pwd+'</td>'
        +'<td style="padding:.4rem"><div class="kv-copy"><code style="font-size:.72rem;color:#818cf8">'+esc(k.key.slice(0,10))+'…</code><button onclick="copyKey(\''+k.id+'\',this)" style="font-size:.68rem;background:var(--chip)">'+t('btn_copy')+'</button></div></td>'
        +'<td style="padding:.4rem">'+acc+'</td>'
        +'<td style="padding:.4rem;text-align:right;white-space:nowrap">'
        +'<button onclick="setKeyLogin(\''+k.id+'\')" style="font-size:.72rem;padding:3px 8px;background:var(--chip)">'+t('btn_set_login')+'</button> '
        +'<button onclick="regenKey(\''+k.id+'\')" style="font-size:.72rem;padding:3px 8px;background:var(--chip)">'+t('btn_regen_key')+'</button> '
        +'<button onclick="rebindKey(\''+k.id+'\')" style="font-size:.72rem;padding:3px 8px;background:var(--chip)">'+t('btn_rebind')+'</button> '
        +'<button onclick="toggleKey(\''+k.id+'\','+(en?'false':'true')+')" style="font-size:.72rem;padding:3px 8px;background:'+(en?'#b45309':'#059669')+'">'+(en?t('btn_disable'):t('btn_enable'))+'</button> '
        +'<button onclick="delKey(\''+k.id+'\')" style="font-size:.72rem;padding:3px 8px;background:linear-gradient(135deg,#ef4444,#dc2626)">'+t('btn_delete')+'</button>'
        +'</td></tr>'
        +'<tr id="kedit-'+k.id+'" style="display:none"><td colspan="8" style="padding:.7rem .9rem;vertical-align:middle;background:linear-gradient(90deg,rgba(96,242,255,.13),rgba(140,107,255,.11),rgba(255,94,219,.07));box-shadow:inset 3px 0 0 rgba(96,242,255,.72),inset 0 1px 0 rgba(255,255,255,.08),0 0 24px rgba(96,242,255,.1);backdrop-filter:blur(10px)">'
        +'<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">'
        +'<input id="ke-user-'+k.id+'" value="'+esc(k.username||'')+'" placeholder="'+t('kf_username_ph')+'" style="flex:1;min-width:140px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none">'
        +'<input id="ke-pass-'+k.id+'" type="text" placeholder="'+t('key_prompt_password_opt')+'" style="flex:1;min-width:140px;padding:6px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:6px;color:var(--strong);font-size:.82rem;outline:none">'
        +'<label class="role-toggle" title="role"><span class="role-a">A</span><input id="ke-role-'+k.id+'" type="checkbox" '+(k.role!=='admin'?'checked':'')+'><span class="role-track"></span><span class="role-u">U</span></label>'
        +'<button onclick="submitKeyLogin(\''+k.id+'\')" style="font-size:.8rem;padding:6px 14px">'+t('rebind_confirm')+'</button>'
        +'<button onclick="setKeyLogin(\''+k.id+'\')" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>'
        +'</div><div id="ke-msg-'+k.id+'" style="font-size:.78rem;color:#ef4444;margin-top:.4rem"></div>'
        +'</td></tr>';
    });
    h+='</tbody></table></div>'+_pageFoot('keys',__pg);
    box.innerHTML=h;
    initGlassSelect(box);
    renderDashboard();
  }catch(e){}
}
// Credential rules mirror the server-side regex (letters/digits for username;
// letters/digits + safe symbols for password) so users get instant feedback.
const _USER_RE=/^[A-Za-z0-9]{1,32}$/;
const _PASS_RE=/^[A-Za-z0-9!#$%&*+\-.:=?@^_~]{6,64}$/;
async function badCred(username,password){
  if(username&&!_USER_RE.test(username)){await adminAlert(t('cred_bad_user'));return true}
  if(password&&!_PASS_RE.test(password)){await adminAlert(t('cred_bad_pass'));return true}
  return false;
}
async function addKey(){
  const name=prompt(t('key_prompt_name'));
  if(name===null)return;
  const username=prompt(t('key_prompt_username'))||'';
  const password=username?(prompt(t('key_prompt_password'))||''):'';
  if(await badCred(username,password))return;
  let account_id='';
  if(__accounts.length){account_id=prompt(t('rebind_prompt')+'\n'+__accounts.map(a=>a.id+' = '+(a.name||'')).join('\n'))||''}
  try{
    const r=await fetch('/admin/keys',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,account_id:account_id,username:username,password:password})});
    if(!r.ok){const d=await r.json().catch(()=>({}));await adminAlert((d.error&&d.error.message)||'error');return}
    loadKeys();loadAccounts();
  }catch(e){}
}
function toggleKeyForm(show){
  const f=document.getElementById('key-form');if(!f)return;
  const open=(show===undefined)?(f.style.display==='none'):show;
  f.style.display=open?'block':'none';
  if(open){
    const u=document.getElementById('kf-username'),p=document.getElementById('kf-password'),r=document.getElementById('kf-role'),m=document.getElementById('kf-msg');
    u.placeholder=t('kf_username_ph');p.placeholder=t('kf_password_ph');
    u.value='';p.value='';if(r)r.checked=true;m.textContent='';u.focus();
  }
}
async function submitKey(){
  const u=document.getElementById('kf-username'),p=document.getElementById('kf-password'),r=document.getElementById('kf-role'),m=document.getElementById('kf-msg');
  const username=(u.value||'').trim();
  const password=p.value||'';
  const role=(r&&r.checked)?'user':'admin';
  m.textContent='';
  if(username&&!_USER_RE.test(username)){m.textContent=t('cred_bad_user');return}
  if(password&&!_PASS_RE.test(password)){m.textContent=t('cred_bad_pass');return}
  try{
    const r=await fetch('/admin/keys',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:username,username:username,password:password,role:role})});
    if(!r.ok){const d=await r.json().catch(()=>({}));m.textContent=(d.error&&d.error.message)||'error';return}
    toggleKeyForm(false);
    loadKeys();
  }catch(e){m.textContent=t('network_error')}
}
function setKeyLogin(id){
  const row=document.getElementById('kedit-'+id);if(!row)return;
  const open=row.style.display==='none';
  row.style.display=open?'table-row':'none';
  if(open){const m=document.getElementById('ke-msg-'+id);if(m)m.textContent='';const p=document.getElementById('ke-pass-'+id);if(p)p.value='';const u=document.getElementById('ke-user-'+id);if(u)u.focus()}
}
async function submitKeyLogin(id){
  const u=document.getElementById('ke-user-'+id),p=document.getElementById('ke-pass-'+id),r=document.getElementById('ke-role-'+id),m=document.getElementById('ke-msg-'+id);
  const username=(u.value||'').trim();
  const password=p.value||'';
  const role=(r&&r.checked)?'user':'admin';
  m.textContent='';
  if(username&&!_USER_RE.test(username)){m.textContent=t('cred_bad_user');return}
  if(password&&!_PASS_RE.test(password)){m.textContent=t('cred_bad_pass');return}
  const body={username:username,role:role};
  if(password)body.password=password;
  try{
    const r=await fetch('/admin/keys/'+id,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok){const d=await r.json().catch(()=>({}));m.textContent=(d.error&&d.error.message)||'error';return}
    loadKeys();
  }catch(e){m.textContent=t('network_error')}
}
async function regenKey(id){
  if(!await adminConfirm(t('confirm_regen_key')))return;
  try{
    const r=await fetch('/admin/keys/'+id+'/regenerate',{method:'POST',credentials:'include'});
    if(!r.ok){const d=await r.json().catch(()=>({}));await adminAlert((d.error&&d.error.message)||'error');return}
    const d=await r.json();
    if(d.key&&d.key.key){try{await navigator.clipboard.writeText(d.key.key)}catch(e){}}
    await adminAlert(t('regen_ok'));
    loadKeys();
  }catch(e){}
}
function _fallbackCopy(text){
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
}
function acctLabel(a){
  const name=a.name||a.id;
  return a.email?(name+' ('+a.email+')'):name;
}
function rebindKey(id){
  const k=__keys.find(x=>x.id===id);
  const cur=k?k.account_id:'';
  let opts='<option value="">'+t('rebind_unbind')+'</option>';
  __accounts.forEach(a=>{opts+='<option value="'+a.id+'"'+(a.id===cur?' selected':'')+'>'+esc(acctLabel(a))+'</option>'});
  const ov=document.createElement('div');
  ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.3);backdrop-filter:blur(18px) saturate(145%);-webkit-backdrop-filter:blur(18px) saturate(145%);display:flex;align-items:center;justify-content:center;z-index:1000';
  ov.innerHTML='<div class="flow-box" style="position:relative;background:rgba(15,23,42,.3);border:1px solid rgba(96,242,255,.28);border-radius:12px;padding:1.25rem;width:340px;max-width:90vw;box-shadow:0 24px 70px rgba(0,0,0,.36),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(22px) saturate(150%);-webkit-backdrop-filter:blur(22px) saturate(150%)">'
    +'<div style="font-weight:600;margin-bottom:.75rem">'+t('rebind_title')+'</div>'
    +'<div class="flow-box" style="position:relative;border-radius:8px"><select id="rebind-select" style="width:100%;padding:8px 10px;background:var(--inner);border:1px solid var(--inner-border);border-radius:8px;color:var(--strong);font-size:.85rem;outline:none">'+opts+'</select></div>'
    +'<div style="display:flex;gap:.5rem;justify-content:flex-end;margin-top:1rem">'
    +'<button id="rebind-cancel" style="font-size:.8rem;padding:6px 14px;background:var(--chip)">'+t('kf_cancel')+'</button>'
    +'<button id="rebind-ok" style="font-size:.8rem;padding:6px 14px">'+t('rebind_confirm')+'</button>'
    +'</div></div>';
  document.body.appendChild(ov);
  initGlassSelect(ov);
  const close=()=>ov.remove();
  ov.addEventListener('click',e=>{if(e.target===ov)close()});
  ov.querySelector('#rebind-cancel').onclick=close;
  ov.querySelector('#rebind-ok').onclick=async()=>{
    const account_id=ov.querySelector('#rebind-select').value;
    try{
      const r=await fetch('/admin/keys/'+id,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id:account_id})});
      if(!r.ok){const d=await r.json().catch(()=>({}));await adminAlert((d.error&&d.error.message)||'error');return}
      close();loadKeys();loadAccounts();
    }catch(e){}
  };
}
async function toggleKey(id,enabled){
  try{await fetch('/admin/keys/'+id,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:enabled})});loadKeys()}catch(e){}
}
async function delKey(id){
  if(!await adminConfirm(t('confirm_del_key')))return;
  try{await fetch('/admin/keys/'+id,{method:'DELETE',credentials:'include'});loadKeys();loadAccounts()}catch(e){}
}
function toggleKeySelected(id,on){on?__selectedKeyIds.add(id):__selectedKeyIds.delete(id)}
function selectAllKeys(on){__selectedKeyIds=new Set(on?__keys.map(k=>k.id):[]);document.querySelectorAll('.key-check').forEach(cb=>{cb.checked=!!on})}
async function batchSetKeys(enabled){const ids=[...__selectedKeyIds];if(!ids.length)return await adminAlert(t('batch_none'));for(const id of ids){await fetch('/admin/keys/'+id,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:enabled})}).catch(()=>{})}loadKeys()}
async function batchDeleteKeys(){const ids=[...__selectedKeyIds];if(!ids.length)return await adminAlert(t('batch_none'));if(!await adminConfirm(t('batch_confirm_delete')))return;for(const id of ids){await fetch('/admin/keys/'+id,{method:'DELETE',credentials:'include'}).catch(()=>{})}__selectedKeyIds.clear();loadKeys();loadAccounts()}

loadStatus();
loadChromiumStatus();
loadCallLog();
loadCapture();
loadTone();
loadToolPrompt();
loadSystemPrompt();
loadAccounts();
loadKeys();
loadTrend();
loadStats();
initGlassSelect(document);
setInterval(loadStatus,60000);
setInterval(loadChromiumStatus,60000);
setInterval(loadCallLog,5000);
setInterval(loadCapture,5000);
setInterval(loadTrend,60000);
setInterval(loadStats,30000);
setInterval(()=>{if(document.body.dataset.view==='accounts')loadAccounts()},30000);
setInterval(()=>{if(document.body.dataset.view==='accounts'&&__accounts.length&&!document.querySelector('tr[id^="atok-"][style*="table-row"]'))loadAccounts(true)},1000);

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
async function loadCallLog(){
  try{
    const r=await fetch('/admin/call-log',{credentials:'include'});
    if(r.status===401){showInlineLogin();return}
    const d=await r.json();
    const logs=d.logs||[];
    document.getElementById('call-log-count').textContent=logs.length;
    const el=document.getElementById('call-log-content');
    if(!logs.length){el.innerHTML='<span style="color:var(--faint)">'+t('no_calls_yet')+'</span>';window.__callLogSig='';return}
    // Skip re-render if nothing changed — prevents open <details> from collapsing every 5s
    const sig=JSON.stringify(logs);
    if(sig===window.__callLogSig)return;
    window.__callLogSig=sig;
    window.__callTexts={};
    let html='';
    for(let i=logs.length-1;i>=0;i--){
      const l=logs[i];
      const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      const tc=l.tools&&l.tools.length?l.tools.join(', '):'—';
      const tr=l.tool_calls_result&&l.tool_calls_result.length?
        '<span style="color:#22c55e">'+t('tool_calls_parsed')+': '+l.tool_calls_result.join(', ')+'</span>':'';
      const fullKey='f'+i;
      // Full single-record text: call info + repr + text
      const fullParts=[];
      fullParts.push('time: '+l.time);
      fullParts.push('mode: '+(l.stream?'stream':'sync'));
      fullParts.push('tools: '+tc);
      if(l.tool_calls_result&&l.tool_calls_result.length)fullParts.push('tool_calls_result: '+l.tool_calls_result.join(', '));
      if(l.response_len!=null)fullParts.push('resp: '+l.response_len+' chars');
      if(l.response_repr!=null)fullParts.push('repr:\n'+l.response_repr);
      if(l.response_text!=null)fullParts.push('text:\n'+l.response_text);
      window.__callTexts[fullKey]=fullParts.join('\n');
      const copyFullBtn='<button class="copybtn" id="copybtn-'+fullKey+'" data-key="'+fullKey+'" style="padding:2px 8px;font-size:.65rem">'+t('copy_record')+'</button>';
      const rawView='<details style="margin-top:4px"><summary style="cursor:pointer;color:var(--faint);font-size:.75rem;list-style:none">'+t('view_raw')+'</summary><pre style="white-space:pre-wrap;word-break:break-all;background:var(--inner);padding:6px;border-radius:6px;color:var(--muted);margin-top:2px;font-size:.7rem;max-height:260px;overflow:auto">'+esc(formatRawText(window.__callTexts[fullKey]))+'</pre></details>';
      html+='<div style="border-bottom:1px solid #1e293b;padding:6px 0">'+
        '<div style="display:flex;justify-content:space-between;align-items:center;color:var(--muted)">'+
        '<span>'+l.time+'</span><span style="display:flex;align-items:center;gap:6px"><span style="color:var(--faint)">'+(l.stream?'stream':'sync')+'</span>'+copyFullBtn+'</span></div>'+
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
  }catch(e){}
}
async function loadCapture(){
  try{
    const r=await fetch('/admin/capture-payload',{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    const ps=d.payloads||[];
    document.getElementById('capture-count').textContent=ps.length;
    const el=document.getElementById('capture-content');
    if(!ps.length){el.innerHTML='<span style="color:var(--faint)">'+t('no_capture_yet')+'</span>';window.__capSig='';return}
    const sig=JSON.stringify(ps);
    if(sig===window.__capSig)return;
    window.__capSig=sig;
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
  }catch(e){}
}
async function loadTone(){
  try{
    const r=await fetch('/admin/tone',{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    const sel=document.getElementById('tone-select');
    if(!sel)return;
    const cur=d.tone||'Magic';
    const opts=d.options||[];
    window.__toneOpts=opts;
    // Skip re-render if unchanged (avoids resetting an open dropdown). Signature
    // includes lang so switching language re-renders the localized labels.
    const sig=JSON.stringify(opts)+'|'+cur+'|'+lang;
    if(sig===window.__toneSig)return;
    window.__toneSig=sig;
    const lbl=o=>(lang==='en'?(o.label_en||o.label):(o.label_zh||o.label))||o.label;
    sel.innerHTML=opts.map(o=>'<option value="'+o.value+'">'+lbl(o)+'</option>').join('');
    sel.value=opts.some(o=>o.value===cur)?cur:(opts[0]?opts[0].value:'');
    initGlassSelect(sel.parentElement);
    refreshGlassSelect(sel);
    sel.onchange=()=>saveTone(sel.value);
  }catch(e){}
}
async function saveTone(tone){
  try{
    const r=await fetch('/admin/tone',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({tone})});
    if(!r.ok)return;
    window.__toneSig='';
    const s=document.getElementById('tone-saved');
    if(s){s.textContent=t('tone_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
async function loadToolPrompt(){
  try{
    const r=await fetch('/admin/tool-prompt',{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    const ta=document.getElementById('tool-prompt-input');
    if(!ta)return;
    if(document.activeElement!==ta)ta.value=d.tool_prompt||'';
  }catch(e){}
}
async function saveToolPrompt(){
  try{
    const ta=document.getElementById('tool-prompt-input');
    if(!ta)return;
    const r=await fetch('/admin/tool-prompt',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({tool_prompt:ta.value})});
    if(!r.ok)return;
    const s=document.getElementById('tool-prompt-saved');
    if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
async function resetToolPrompt(){
  // Extra instruction default is empty.
  const ta=document.getElementById('tool-prompt-input');
  if(ta)ta.value='';
  await saveToolPrompt();
}

let __systemPromptDefault='';
async function loadSystemPrompt(){
  try{
    const r=await fetch('/admin/system-prompt',{credentials:'include'});
    if(r.status===401){return}
    const d=await r.json();
    __systemPromptDefault=d.default||'';
    const ta=document.getElementById('system-prompt-input');
    if(!ta)return;
    // Show the saved override, or fall back to the default text for reference.
    if(document.activeElement!==ta)ta.value=(d.system_prompt&&d.system_prompt.length)?d.system_prompt:__systemPromptDefault;
  }catch(e){}
}
async function unlockSystemPrompt(){
  if(!await adminConfirm(t('system_prompt_warn')))return;
  const locked=document.getElementById('system-prompt-locked');
  const editor=document.getElementById('system-prompt-editor');
  if(locked)locked.style.display='none';
  if(editor)editor.style.display='block';
}
async function saveSystemPrompt(){
  try{
    const ta=document.getElementById('system-prompt-input');
    if(!ta)return;
    const r=await fetch('/admin/system-prompt',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({system_prompt:ta.value})});
    if(!r.ok)return;
    const s=document.getElementById('system-prompt-saved');
    if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}
async function resetSystemPrompt(){
  if(!await adminConfirm(t('system_prompt_reset_confirm')))return;
  const ta=document.getElementById('system-prompt-input');
  // Saving an empty override makes the backend fall back to the built-in default.
  if(ta)ta.value=__systemPromptDefault;
  try{
    const r=await fetch('/admin/system-prompt',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({system_prompt:''})});
    if(!r.ok)return;
    const s=document.getElementById('system-prompt-saved');
    if(s){s.textContent=t('tool_prompt_saved');s.style.opacity='1';setTimeout(()=>{s.style.opacity='0'},1500)}
  }catch(e){}
}

