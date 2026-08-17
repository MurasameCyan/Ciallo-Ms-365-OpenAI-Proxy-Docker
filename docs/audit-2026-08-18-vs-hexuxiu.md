# 对照 HEXUXIU 三份审计报告的自查清单（2026-08-18）

对照对象：`HEXUXIU/M365-Copilot2API` 的 `docs/audit-2026-08-07-{security,robustness,performance}.md`（Go 实现，单账号架构为主）。

做法：把他们报告里的**每一条**拿到本仓库（`fox` 分支）逐一核对，给出对我方的结论与证据。不搬他们的修法，只搬「该检查什么」。

结论栏含义：

| 标记 | 含义 |
|------|------|
| ✅ 无此问题 | 我方代码结构上不会发生，附证据位置 |
| ✅ 已修 | 曾经存在，已修，附 commit |
| ➖ 不适用 | 我方没有对应功能/代码（不是「没查」） |
| ⚠️ 取舍 | 存在但是有意为之，附理由 |
| ❗ 待办 | 真的有，本轮新发现，见文末待办清单 |

核对方式为读码 + 已有测试，未在生产上做攻击性验证。

---

## 一、安全（audit-2026-08-07-security.md）

| 他们的条目 | 我方结论 | 证据 / 说明 |
|-----------|---------|------------|
| **S-1** 默认口令 `admin123`，未配置即接管 | ✅ 无此问题（另有取舍） | 我方没有任何内置口令：`config.py:18` 的 `ADMIN_PASSWORD` 默认空串，`admin_auth.py:34` 的 secret 取 `admin_password or api_key`。口令只来自环境变量，从不落盘，因此也不需要 hash。取舍：两者都为空时 admin 页**开放无鉴权**（而不是拒绝启动），`startup_warnings.py:11` 打印警告——生产 compose 一直有 `ADMIN_PASSWORD`。登录用 `secrets.compare_digest`（`routes_web.py:67`），失败按 IP 限流（`login_guard.py`，5 次 / 60 秒） |
| **S-2** 图片 URL 任意下载（SSRF） | ✅ 已修 | `6eabf04`：`substrate_upload.py` 下载前逐跳校验，只允许 http(s)，解析出的每个地址必须 `is_global`，手动跟随重定向且每跳重校验（`_MAX_REDIRECT_HOPS = 3`）。`tests/test_remote_image_ssrf.py` 14 项（含「被拒地址一个请求都不许发出」） |
| **S-3** 跨请求状态无租户隔离 | ✅ 无此问题 | 会话 store 的每个 key 都以租户前缀（api key id，回落 account id）开头：`session_helpers.py:22` `_request_tenant`，`:179/:204-210` 的 `f"{tenant}:..."`，`:142` 显式归属校验。`previous_response_id` 不是可猜的 ID 而是 **HMAC 签名**的 `resp_` 串（`session_helpers.py:41-90`，`hmac.compare_digest`），另有 latest/consumed 校验（`routes_api_responses.py:276-330`）。历史索引也按租户分桶（`history_index.py` 文档段） |
| **H-1** API key 明文落盘 + 管理接口明文返回 | ⚠️ 取舍 | `keys.json` 里 `key`/`password`/`password_hash`/`password_salt` 全部 AES-256-GCM 加密（`key_store.py:20-25`），密钥同 `accounts.json`；登录口令另存 PBKDF2-SHA256 10 万轮 + 每 key salt（`key_store.py:29`）。但 raw key 与明文口令**确实保留**并在 admin UI 显示——这是产品要求（管理员要把 key/口令发给用户），不是遗漏。前提是数据卷与 `.enc_key` 不外泄 |
| **H-2** M365 token 明文落盘（他们标记「未做」） | ✅ 无此问题 | 我方 `accounts.json` 的 token 字段加密落盘（`account_crypto.py`，AES-256-GCM，密钥 `/home/app/token/.enc_key`）。注意：**容器内探针必须用 `/app/.venv/bin/python`**，系统 python 缺 `cryptography` 会把加密字段静默读成空 |
| **H-4** 匿名可读 `/api/stats`、匿名可 reset | ✅ 无此问题 | `/admin/stats` 与所有 capture 端点开头即 `require_admin(request)`（`routes_admin_debug.py:47-49, 104-130`）；没有任何匿名 reset 端点。唯一匿名端点 `/healthz` 只报 `accounts.total/valid`，且带缓存（`routes_web.py:30-53`）——见文末取舍 6 |
| **H-5** 无速率限制；key 校验每次全量写盘 | ✅ 无此问题 | 限流：per-key token bucket（`ratelimit.py`，rpm + burst，可按 key 覆盖 `rate_limit_rpm`）；本轮另加 per-account 并发上限（`45afeb3`，默认 8）。写盘：`key_store.resolve()`（`:193-197`）是纯内存查表，不更新 `last_used`、不落盘 |
| **M-1** 明文对话/会话/debug 数据落盘 | ❗ 部分待办 | 分三处：① `sessions.json` 只存 conversation_id / turn_count / 计数（`session_store.py:322-336`），**不存历史正文**——无此问题；② payload 抓包默认关闭、只在内存留 20 条、从不落盘（`routes_admin_debug.py:100`）——无此问题；③ **`call_log.json` 会存每次调用的响应正文前 8000 字符**（`routes_api_chat.py:224`），上限 100 条、原子写、仅 admin 可读，但未加密 → 见待办 3 |
| **M-2** 前端引 CDN `@latest` 脚本、CSP 宽松 | ❗ 半边待办 | 我方**没有任何外链脚本**：全部 JS 由 Python 模板内联（`template_*.py`，grep 无 `<script src`），供应链面为零。但我方也**完全没发安全响应头**（无 CSP / X-Frame-Options / nosniff / Referrer-Policy），比他们少一层兜底 → 见待办 2 |
| **M-3a** 提示注入放大（依赖 S-3 无隔离才成立） | ✅ 无此问题 | 前提不成立：会话按租户隔离，A 的 system 指令不会被 B 复用 |
| **M-3b** 错误信息回显上游 body | ✅ 无此问题（一处有意例外） | 未预期异常统一收敛为 `Internal server error`，真异常只进日志（`error_handlers.py:12-21`）。有意例外：流式路径会把**上游瞬时错误的可读文案**作为 content 帧发给客户端（`response_helpers.py:85, 791` 的 `⚠️ 上游错误：{exc}`）——那是为了排查「客户端只拿到 200 + 0 字节」故意加的，发的是异常字符串而非堆栈（见 `tests/test_openai_stream_upstream_error.py`） |
| **低-1** WebSocket `access_token` 放 URL query | ⚠️ 取舍 | 我方同样放 query（`substrate_client.py:233-244`）——浏览器就是这么发的，chathub 不接受 `Authorization` 头。风险面是代理 CONNECT 日志/链路 trace，属部署侧注意事项 |
| **低-2** HTTPS 代理在 host 为 IP 时跳过证书校验 | ✅ 无此问题 | 全库无 `verify=False` / `ssl=False` / `check_hostname` 关闭 |
| **低-3** 管理接口无 body 大小限制 | ⚠️ 取舍 | 我方也没有全局 body 上限（uvicorn 无默认值），仅 `routes_admin_debug.py:85` 对一处按 `content-length` 判断。实际由前置反代（Nginx `client_max_body_size`）承担；管理接口在 admin 鉴权之后，攻击面小于他们的匿名 stats |
| **低-4** responses 池 / PKCE state 无过期清理 | ✅ 无此问题 | Responses 续接不维护服务端池（签名 ID 自证）；PKCE pending 有 TTL + `_prune()` + `_MAX_PENDING = 32`（`pkce_login.py:50-52, 122-124, 161-164`） |
| **低-5** loopback 来源时信任 `X-Forwarded-For` | ✅ 无此问题（另有取舍） | 我方只用 `request.client.host`（`routes_web.py:57`、`routes_user.py:94`），从不读 XFF，因此无法被伪造成管理员 IP。反面：置于反代之后所有客户端同一 IP，登录锁定退化为**全局**锁定——见取舍 5 |
| **低-6** 未认证路径统一 401 造成枚举面 | ⚠️ 取舍 | 同样如此，信息量极低，不改 |
| 他们「已排查不算漏洞」里的 **CORS/CSRF** | ⚠️ 取舍（我方与他们不同） | 他们是「压根没设 ACAO 所以跨域被拦」；**我方是有意开 CORS**（`auth_middleware.py:24-30`，`allow_origins` 默认 `*`，可用 `ALLOWED_ORIGINS` 收窄），为的是浏览器里的 OpenAI 兼容客户端能直连。之所以不构成 CSRF/读取面：没有 `allow_credentials=True`（带 cookie 的跨域请求响应会被浏览器拦掉），admin cookie 是 `SameSite=Lax`（跨站 POST 不带 cookie），且 `/v1` 必须由调用方自带 API key。要对公网收紧就设 `ALLOWED_ORIGINS` |
| 他们「已排查不算漏洞」的其余 5 项（SSE 注入、命令注入、路径穿越、key 认证绕过、登录爆破） | — | 我方对应面同样成立：SSE 帧全部经 `json.dumps` 编码，`event:` 名为常量；无用户可控路径拼接（模板全在 Python 里）；key 只从 `Authorization`/`X-API-Key` 取；登录有 IP 锁定。命令执行：客户端内容从不进 shell（`subprocess` 只用于启动浏览器/CDP，参数由服务端构造） |

## 二、鲁棒性（audit-2026-08-07-robustness.md）

| 他们的条目 | 我方结论 | 证据 / 说明 |
|-----------|---------|------------|
| **H1** 工具完成守卫恒真放行 | ➖ 不适用 | 我方没有 `agent_ledger` 这类「完成证据」守卫；工具调用原样转给客户端执行（`tool_call_parser.py`），不代为判定「已完成」 |
| **H2** SSE 写无背压/无取消，坏客户端悬挂 goroutine + 上游 WS | ✅ 无此问题 | 结构性差异：客户端断开 → Starlette 关闭异步生成器 → 在 `yield` 处抛 `GeneratorExit` → `async with connect(...)` 退出并关闭上游 WS。我方无 `except BaseException`/`except GeneratorExit` 吞掉它（仅 `consumer_gate.py:105` 捕获 `CancelledError` 且立即 `raise`）。另有 WS idle 超时（可按 key 配置）兜底 |
| **H3** 附件无数量/总量上限，单请求可到 GB 级 | ✅ 已修 | 单张 20 MiB 上限（`substrate_upload.py:30`）、SSRF 已修（`6eabf04`）、串行下载；本轮补上**每轮数量上限** `_MAX_IMAGES_PER_TURN = 10`（`substrate_client.py`，超出截断并打 warning），见待办 1 |
| **H4** token 到期并发刷新惊群 → 大面积 502 + 误标 expired | ✅ 无此问题 | `refresh_scheduler.ensure_fresh` 按账号 `asyncio.Lock`（`:425-430, :569`），且进锁后比对凭据快照：若并发者已换出新 token 就**直接复用**，不会二次兑换同一个 RT（`:573-580`）。另有 `refresh_token_retry_after` 退避，不会一次失败就落盘 expired |
| **M1** mcp 包竞态/泄漏（死代码） | ➖ 不适用 | 无 mcp 包 |
| **M2** 持久化非原子覆盖写 | ✅ 已修 | 所有 JSON store 本来就是临时文件 + `Path.replace()` 原子替换：`key_store.py:182-184`、`account_store.py:294-296`、`session_store.py:337-340`、`call_log_store.py:21-23`、`metrics_store.py:24-26`。本轮把漏掉的**单值小文件**也统一了：新增 `atomic_write.write_text_atomic()`，`token_store` 的 5 个 profile 写入、`runtime_settings.json`、`media_proxy_secret` 全部改走它，见待办 4 |
| **M3** 锁内做磁盘 I/O，请求被磁盘延迟串死 | ✅ 无此问题 | `session_store` 改动只置脏位 + 单个合并计时器（`:265-290`），真正写盘的 `_write_now` 在锁外做 I/O（`:322-340`），进程退出用 `atexit` + shutdown hook 补一次 flush |
| **M4** session 解析无条数上限 + 兜底全量 Jaccard 扫描 | ✅ 无此问题 | 我方**没有模糊匹配**：`history_index` 是精确前缀摘要匹配，文档段明确写了为什么不做相似度；`_MAX_ENTRIES = 4096` LRU，session store 自身 1000 条上限，另有后台空闲回收（`8488ccb`，`session_autoclean.py`） |
| **M5** 无锁替换 manager 指针 | ➖ 不适用 | 无等价的运行时指针替换 |
| **M6** debug 中间件全文捕获 + 脱敏不彻底 + 日志无界 | ✅ 无此问题 | 抓包默认关闭、显式开关（`/admin/capture-toggle`）、内存 20 条上限、不落盘；`call_log` 上限 100 条 |
| **M7** 无 graceful shutdown | ✅ 无此问题 | `app.py:43-61`：shutdown 钩子停 keepalive、停 auto-cleanup、flush 会话；uvicorn 处理 SIGTERM |
| **L1** 全库无 recover，一处 panic 崩全进程 | ✅ 无此问题 | FastAPI/Starlette 按请求捕获异常转 500，单个请求异常不影响其他连接；另有 `error_handlers.py` 统一成 OpenAI 风格错误体 |
| **L2** 工具路由提示语回归致 2 个测试稳定失败 | ✅ 无此问题 | 全量 1200 passed, 2 skipped（2026-08-18） |
| **L3** 单例无锁初始化 | ➖ 不适用 | 状态在 `create_app`/`state_init.py` 里单线程建好挂到 `app.state` |
| **L4** 用无超时的 DefaultClient 请求外部 API | ✅ 无此问题 | 全部 `httpx.AsyncClient(` 调用点都带 `timeout=` |
| **L5** 配置校验错误被丢弃，静默退化默认值 | ⚠️ 取舍 | `runtime_settings` 对非法值逐项回落默认并继续启动（不中断服务），非法项不会静默「消失」，会在 /admin 面板显示为回落后的值 |
| **L6** 返回值里拷贝了含锁的结构体 | ➖ 不适用 | Python 无此坑 |
| 他们保留的验证缺口：本机无 gcc，`go test -race` 未跑 | — | 我方无对应缺口（无 race 检测器，也无 CGO 依赖）；并发行为由 `tests/test_account_concurrency.py` 等用真事件循环覆盖 |

## 三、性能（audit-2026-08-07-performance.md）

| 他们的条目 | 我方结论 | 证据 / 说明 |
|-----------|---------|------------|
| **Top1** 每请求 5-7 次同步整文件写盘且持全局锁 | ✅ 无此问题 | 见 M2/M3：合并写 + 锁外 I/O；key 校验完全不写盘。admin 面板可看 `changes` / `writes` / `last_write_at`（`session_store.stats`），即「请求数 vs 实际写盘数」有可观测比值 |
| **Top2** debug 中间件每 chunk 拷贝 + 全量 unmarshal | ✅ 无此问题 | 抓包默认关闭且不解析全文 |
| **Top3** 流式拼接 O(n²) | ⚠️ 取舍 | 我方也在累加（`substrate_client.py:572` `streamed_text += delta`、`response_helpers.py:66-69`）。CPython 对引用计数为 1 的 str 就地 realloc，实际是摊还线性，单轮回复量级（几十 KB）下量不到；真要变热点就换 list + `"".join`（对客户端可见的路径已经是 `"".join(chunks)`，见 `routes_api_chat.py:290/310`） |
| **Top4** WS 读阻塞不响应 ctx 取消，最多迟 90 秒 | ✅ 无此问题 | 我方读取是 `await asyncio.wait_for(ws.recv(), timeout=idle_timeout)`（`substrate_client.py:507/522`），取消立即穿透 |
| **Top5** session miss 时锁内全量 Jaccard | ✅ 无此问题 | 见 M4：精确匹配，无兜底相似度扫描 |

---

## 四、本轮新发现的待办（我方自己的问题，按建议顺序）

1. ~~**每轮图片数量无上限**~~ ✅ **本轮已修**。`substrate_client._upload_images` 加 `_MAX_IMAGES_PER_TURN = 10`：超出的截断并打 warning（不静默）。此前 `substrate_client.py` 直接遍历客户端给的 `images`，单张 20 MiB 上限管不住数量——一个请求带 50 个远端 URL 就是 50 次串行下载 + 每张约 27 MiB 的 base64 驻留；SSRF 已挡内网，但「拿网关当下载器 + 撑内存」这条一直开着。回归：`tests/test_substrate_image_cap.py`
2. **无任何安全响应头**。admin / user 页全内联 JS，没有 CDN 供应链面，但也没有 CSP / X-Frame-Options / X-Content-Type-Options / Referrer-Policy。内联 JS 意味着严格 CSP 需要 nonce 改造，成本不为零；先加 frame-ancestors / nosniff / Referrer-Policy 这几个零成本的。
3. **`call_log.json` 明文存响应正文**（每条上限 8000 字符、共 100 条）。仅 admin 可读、原子写、有上限，但和加密的 `accounts.json` / `keys.json` 不是同一等级：数据卷或备份泄漏时这是唯一能直接读到业务对话内容的文件。选项：只存长度不存正文（默认）＋开关；或复用 `AccountCipher` 加密该字段。
4. ~~**`token_store.py` 的 profile 小文件非原子写**~~ ✅ **本轮已修**。原文：`:145-210` 的 token / username / tone / tool_prompt / system_prompt 各一个文件，直接 `write_text`（先截断再写），断电或 kill 撞上写入会读回空 → 读侧一律当「未设置」，token 那个文件损坏就是该账号停摆。修法：新增 `atomic_write.write_text_atomic()`（临时文件 + `Path.replace()`，`mode` 在 rename **之前**打，秘密不会有一瞬间按 umask 可读；临时名带随机后缀，避免两个写同一文件的并发者抢同一个临时路径）。顺手扫出并修掉同类的另外两处：`runtime_settings._write_runtime_settings`（危害更大——写坏后下次启动解析失败，**所有**运行时设置静默回落默认值）和 `state_init` 的 `media_proxy_secret`。回归：`tests/test_atomic_write.py`

## 五、取舍清单（有意如此，不作为待办）

5. **不信任 `X-Forwarded-For`**：换来「无法伪造成管理员 IP」，代价是置于反代之后时登录失败锁定按代理 IP 聚合，等于全局锁定。当前部署（单人/小圈子）可接受；若将来对公网开放并需要按真实 IP 锁定，需要引入「可信代理列表 + 解析 XFF」，不能简单打开。
6. **`/healthz` 匿名暴露 `accounts.total/valid`**：容器探针需要它，已加缓存防打；不含 key 前缀、不含用量、无 reset 能力。
7. **raw API key 与用户口令可被 admin 明文查看**：产品要求（要发给用户），落盘已加密。
8. **WS URL 带 access_token**：上游协议要求，部署侧需保证代理日志不外泄。

---

*行号为 2026-08-18 `fox` 分支（HEAD `ce0797a`）核对时的实际位置。他们报告里的行号指向他们自己的仓库，未复核。*
