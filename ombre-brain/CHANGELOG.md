# 更新日志 / Changelog

本项目版本号见根目录 `VERSION` 文件，Docker 镜像 tag 与之对应（`p0luz/ombre-brain:<VERSION>`）。

## 2.6.5

### 安全 / Security

- OAuth 鉴权开关现在明确区分“已保存配置”与“当前进程实际生效值”；鉴权中间件与 OAuth 路由可见性仍坚持启动时快照，不再将仅写入配置的变更误报为热切换成功。
- Dashboard 通用重启接口必须通过 Dashboard 会话鉴权，且请求体必须显式携带 `confirm=true`，避免公开页面或误触发直接终止服务。
- OAuth DCR 客户端注册表使用私有权限原子 JSON 落盘；启动时会重新校验回调 URI、过期时间和数量上限，防止损坏或手工篡改的注册表绕过安全边界。

### 改进 / Changed

- Dashboard 右上角新增“重启”按钮；OAuth 等启动时配置存在待生效变更时显示红点和明确提醒，重启请求返回后自动重连页面。
- 相似度检索改为 NumPy 批量矩阵计算，同时支持 content/meaning 双向量取最高分；保留维度不匹配记 `0.0` 和同分结果的稳定顺序，避免旧 PR 的行为漂移。
- DCR 客户端有效期与 refresh token 对齐为 365 天，容器或裸机服务重启后无需客户端清缓存重新注册。

### 测试 / Tests

- 新增 DCR 重启恢复与恶意落盘数据过滤、OAuth 待重启状态、受保护重启 API、双向量批量相似度与稳定排序回归；完整测试集通过。

## 2.6.4

### 修复 / Fixed

- 修复 Dashboard“信”页面及桶详情的编辑、删除按钮偶发完全无响应：装饰性 Lucide 图标不再截获指针事件，鼠标按下与抬起稳定落在按钮本体。
- 修复全局 `MutationObserver` 与 `lucide.createIcons()` 互相触发的无限 SVG 重绘循环；图标渲染期间暂时断开观察器，避免 Console 警告/计数持续暴涨、CPU 占用和页面卡顿。
- 信件删除接口支持半删除状态的幂等自愈：Markdown 已不存在时，仍清理残留向量、embedding 待处理项和运行时桶缓存；正常存在的信件继续保留移入 archive 的软删除语义。

### 测试 / Tests

- 新增 Dashboard 图标点击与观察器防自噬、幽灵信派生状态清理回归；完整测试 `1049 passed, 45 skipped`。

## 2.6.3

### 安全 / Security

- OAuth 受保护资源元数据现在严格服从 `mcp_require_auth`：关闭鉴权时相关元数据端点返回 404；仅真实存在的 `/mcp` 路径可被发现，废弃或不存在的 MCP 路径不再误报 200；根元数据明确指向实际 `/mcp` 资源。
- 当隧道已配置而 MCP OAuth 关闭时，Dashboard 持续显示醒目的匿名公网读写风险提示，系统诊断将该组合升级为错误并给出修复建议。

### 修复 / Fixed

- 修复 Dashboard“启动时自动连接”开关可能被并发状态轮询弹回、保存失败却无明确反馈的问题。隧道配置改为加锁、原子写入、落盘回读校验；前端仅接受服务端明确确认的持久化结果，并显示真实保存错误。

### 测试 / Tests

- 新增 OAuth 开关与路径发现、隧道配置持久化失败、Dashboard 保存确认及公网暴露诊断回归，并通过 Docker 实例验证自动连接开关可写入和回读。

## 2.6.2

### 修复 / Fixed

- 修复 Dashboard 检查更新读取 `main/VERSION`、实际下载却默认取 GitHub Latest Release 的源不一致：当 Latest 仍停在 v2.4.6 时，第一次更新会降级到 2.4.6，第二次才由旧更新器拉到最新。现在默认与版本检查一致地下载 `main`，并在写盘前拒绝任何低于当前版本的更新包。
- “补齐缺失向量”升级为完整向量对账：除补齐缺失/过期向量外，也会清理“向量存在但 Markdown 桶已不存在”的孤儿向量；Dashboard 分别显示发现孤儿、已清理、清理失败、缺失和入队数量，不再出现诊断告警 114 条但按钮显示待处理 0、加入 0 且无动作的误导。

### 测试 / Tests

- 新增热更新降级保护、默认更新源一致性及孤儿向量清理回归；相关测试 42 项通过。
- Docker 真机插入孤儿向量后运行 Dashboard 对账：孤儿数从 1 降为 0，状态显示发现 1、清理 1、失败 0。

## 2.6.1

### 修复 / Fixed

- `breath(query="<完整 bucket_id>")` 新增按 ID 直读通道：直接返回桶当前存储的完整 raw content，跳过 embedding、BM25 和 LLM 摘要/改写，避免 AI 在 `trace(content=...)` 前只能拿到压缩内容，进而覆盖原始 bullet、缩进或遗漏信息。
- 精确 ID 读取继续遵守归档、软删除、专用桶类型与浮现策略边界；token 预算不足时整桶省略，不截断或压缩正文。

### 测试 / Tests

- 新增单元回归，断言精确 bucket ID 读取不调用 embedding、BM25/search 或 dehydrator，并逐字校验原始正文哈希。
- 本地 Docker `streamable-http` 真机验证全部 12 个 MCP 工具及安全/并发边界；新增 35 条纯 bullet 桶 → 按 ID 原文读取 → `trace` 追加第 36 条 → 再次逐字读取的端到端回归。

## 2.6.0

### 修复 / Fixed

- Docker 代码播种不再只比较 `VERSION`：新增 `src/` + `frontend/` 稳定 SHA-256 镜像指纹，同版本自建镜像内容变化也会重新播种；镜像未变化时保留卷内 Dashboard 热更新。
- 镜像重新播种改为暂存、校验后切换，原健康运行树可作为 `_prev` 崩溃回滚点；回滚不会被同一次启动立即反向覆盖。
- 独立 bind/named/anonymous 代码卷可通过 mountinfo 正确识别为持久热更新，不再只认位于 `buckets_dir` 下的代码目录。
- 启动日志明确输出活动代码目录及 `image-match` / `runtime-override` / `legacy-residue` 状态；旧布局 `<数据目录>/_app` 仅在确认未被使用时告警，不自动删除。

## 2.5.5

### 变更 / Changed —— Dashboard 面板重设计（纯前端，不动数据结构）

信息架构与文案按「面板只回答好不好、婷易的妈妈能看懂」原则整体重做，均集中在 `frontend/dashboard.html`：

- **诊断 `[object Object]` 泄露修复**：`renderDiagnosticCheck` 面板主体只留 状态灯 + 一句人话 + 建议，原始 details（schema 名 / 字段路径 / 嵌套 JSON）一律折叠进「查看详情」；`esc()` 加对象兜底，任何调用点都不再吐 `[object Object]`。
- **顶栏常驻系统状态条**：全绿收成一行「系统正常 · OK」；有问题才展开「需处理」卡片，按钮 `scrollToField()` 直达对应设置字段并高亮。
- **体检项按 用户 / 开发者 分离**：22 项里只把 8 项用户相关项（数据目录 / 记忆桶 / 压缩LLM / 向量化 / 数据完整性 / GitHub备份 / 访问控制 / 运行时）显示给用户；14 项内部契约检查（事件账本 / 红线 / vNext 预检 / ADR / 代码规范…）折叠进「开发者诊断」，不再让用户误收「需处理」告警。英文术语全部中文化（surface context→浮现上下文 等）。
- **「危险区」正名「数据备份与迁移」**：去掉红色危险样式（原区实为导出/查重/zip迁移，零破坏性操作），改鼓励使用的语气。
- **设置结构重组**：加「常规 / 高级 / 备份与迁移」三个子 tab（`data-sgroup` + CSS 显隐，不物理挪 DOM），GitHub 同步归入备份组；去掉段标题的 ⓪①② 圆圈编号。
- **工具箱 tab 合并进设置**：其开关/动作在设置里本已存在（采样→桶行为、外网→我、备份→GitHub），删除重复 tab，消除「一件事劈两半」。
- **记忆桶列表翻页**：每页 10 个 + 底部翻页；搜索栏支持桶名 / 子串 / 模糊（子序列）匹配，向量化未开启时退化为纯本地匹配。
- **中英双语与字体统一**：段标题 / 子标题 / 按钮 / 空态统一「中文 + 英文小字」；`button/input/select/textarea` 强制继承 body 字体，消除表单控件用系统字体造成的割裂。
- **文案分级**：平台环境变量告警等长注释重排为「结论一句 + 框住的变量清单 + 分点说明」；删除对用户无意义的解释性文字；`一键本地化` 按钮回归短标签，操作说明下沉为小字。

### 测试 / Tests

- 全量内联 JS `node --check` 通过；本地 Docker（`deploy/docker-compose.yml`）部署验证：登录、`/api/buckets`、`/api/system/diagnostics` 正常；造 25 桶验证分页（10/10/5、首末禁用、无重叠）与搜索（桶名 / 子串 / 模糊子序列 / 多命中）；22 项体检的 用户/开发者 分离用真实返回核对（8 用户 + 14 开发者）。
- 记录并根治部署坑：数据卷 `<vault>/_app` 影子副本 + VERSION 门控 reseed 导致「改前端不生效」，本次 VERSION 抬升会触发运行时自动重新播种。

## 2.5.4

### 修复 / Fixed

- `atomic_write_text`（`src/utils.py`）在 Windows 上未做长路径处理：domain/tag 合法长度可到 80~128 字符，落在较深的数据目录下时，拼出的桶文件全路径（含原子写入用的 `.tmp` 后缀）会超过 Windows 默认 260 字符 `MAX_PATH`，导致 `hold`/`grow` 等写入直接抛 `FileNotFoundError`（`tests/test_red_team_regressions.py::test_bucket_boundary_bounds_tags_and_domains` 在 Windows 上复现）。现在在 Windows 上一律用 `\\?\` 扩展路径前缀绕过该限制，Linux/macOS 行为不变。
- `grow(items=...)`（预拆分逐字入库分支，`src/tools/grow/core.py`）在打标 API 不可用（未配置 `OMBRE_COMPRESS_API_KEY` 或调用失败）时会直接吞掉整条内容、不创建任何桶——与文档承诺的「一字不动只补元数据」矛盾，也和同类工具 `hold` 的降级行为不一致（`hold` 会在打标失败时落回本地中性元数据并原样保存正文）。真机验证 12 个工具时发现：无 API Key 场景下 `grow(items=[...])` 返回「新0合0」，正文全部丢失。现已改为与 `hold` 一致的降级路径：打标失败时使用本地中性元数据继续建桶，正文不丢，并在返回里追加提示。
- 修复 `.gitignore` 里一条整目录忽略 `/tools/`，导致新脚本 `git add` 被静默吞掉、从未进仓库：pytest 12 个用例因此依赖的 `tools/vnext_preflight.py` 缺失而失败，系统诊断的 vnext_preflight 检查也永久报错。新建该 CLI（照 `tools/v3_health_report.py` 模板）并放开 `.gitignore`。
- 补建 README「检索质量评测」一节引用、但从未存在过的 `tools/evaluate_retrieval.py`（离线关键词通道 + `--with-embedding` 混合检索，输出 Hit@K/Recall@K/MRR）。
- 移除 `letter_write` 的过时校验实现 `src/tools/letters.py`（全仓零引用死代码，实际生效实现在 `tools/plan/core.py`，本就允许任意署名字符串），并修正 README 对 `author` 字段的过时描述。
- 移除 `/dream-hook` 端点与 SessionStart hook 里的调用：`dream`（做梦消化）按设计哲学不是义务，不该在每次会话开始被自动触发，只应由模型在需要消化时主动调用 `dream` 工具。
- SessionStart hook 脚本（`.claude/hooks/session_breath.py`）此前调用 `/breath-hook` 不带任何 token、遇 401/网络错误静默吞掉，看起来"运行正常"实则没有 breath；现已支持 `OMBRE_HOOK_TOKEN`（Authorization Bearer）、出错时打印可诊断信息到 stderr（不阻断会话启动）、默认 URL 改为 `http://localhost:18001`（此前误写 `:8000`，与 Docker 对外默认端口不符）。
- Docker 快速开始路线此前存在 onboarding 断点：README 引导把 `docs/CLAUDE_PROMPT.md` 放进 system prompt，但预构建镜像的 `.dockerignore` 排除了整个 `docs/` 和所有 Markdown，Docker 用户本地无源码也拿不到该文件。现将面向用户的 `docs/CLAUDE_PROMPT.md`、`docs/INTERNALS.md`、`docs/MULTI_OWNER.md`、`docs/OPERATIONS.md`、`README.md`、`CHANGELOG.md` 放行进镜像；内部设计稿（`docs/superpowers/`、`docs/secrets/` 等）仍不进镜像。
- 同时把 `.claude/hooks/session_breath.py`（原被整个 `.claude/` 目录忽略规则挡住、用户无处获取）放行为官方产物。
- 删除仓库根目录的 `dashboard.html`：它只是 `frontend/dashboard.html` 的字节级镜像，运行时代码（`src/web/dashboard.py`）从不读取它，纯粹为满足一条"两份必须一致"的测试断言而人工维护，是「同一事实存两处」的反模式。改为单一真源，`tests/test_release_audit_regressions.py` 及另外 5 个内容契约测试同步只校验 `frontend/dashboard.html`。
- Dashboard 前端（`frontend/dashboard.html`）补齐登录/急救屏与设置区（⓪~⑦）title 属性的中英文对照，统一采用「中文 / English」内联格式，与项目既有 Tab/标题规范对齐；技术字段名（Model/API Key/Base URL/Timeout 等）按约定保持纯英文。

### 测试 / Tests

- 全量 `pytest tests/`：961 passed，38 skipped。
- 本地裸机 Windows 真实起服务（`streamable-http`）验证：Dashboard 首页 200 可打开、真实浏览器走完首次设密/登录流程、主界面正常渲染；12 个 MCP 工具通过 `/mcp` 逐一列出并**全部**真机调用一遍（`hold`/`breath`/`grow`/`trace`/`anchor`/`release`/`pulse`/`plan`/`letter_write`/`letter_read`/`I`/`dream`），核对返回内容与文档描述一致（新记忆可被检索回读；`trace(delete=True)` 仅移入 `archive/`，未物理抹除；`grow(items=...)` 修复后正确逐字建桶）；`tools/evaluate_retrieval.py`、`tools/vnext_preflight.py`、`tools/v3_health_report.py` 均运行通过。
- 验证 Dashboard ③ 引擎的热更新：通过 `/api/env-config` 写入压缩模型 API Key 后，同进程内下一次 `hold` 调用立即使用新 Key 发起请求（服务端日志可见对应出站请求），无需重启进程。
- 本地 Docker 从零 `--no-cache` 构建 + 部署验证；12 个 MCP 工具逐一真机调用核对文档描述；红蓝队核查物理删除红线（`trace(delete=True)` 确认只移入 `archive/`，未物理抹除）、鉴权边界、路径穿越注入，均符合预期。
- 验证镜像内 `docs/` 只含 4 个白名单文件（`docs/secrets`、`docs/superpowers` 确认未进镜像）；`/dream-hook` 端点已移除（404），`/breath-hook` 鉴权正常（401）。

## 2.5.3

### 修复 / Fixed

- 统一解析带 `Z` / UTC offset 的时间字段，避免新导入记忆被误判为旧记忆并异常衰减。
- 修正字符串 `"false"` 在 OAuth、embedding、记忆状态和 LLM 结构化结果中被误当作开启的问题。
- 移除普通写入、导入和编辑路径的重复 embedding 请求，统一由 `BucketManager` 维护向量。
- embedding 热重载会同步更新 Web、MCP、桶管理、导入和完整迁移运行时，避免新旧模型并存。
- 同步两份 Dashboard，并修正 Docker 宿主机挂载提示和动态调试 ID 的安全传递。

### 测试 / Tests

- 新增时间、布尔边界、embedding 单次写入、热重载引用和 Dashboard 一致性回归测试。
- 使用隔离的真实本地服务验证 Dashboard、12 个 MCP 工具、`hold` 落盘、`breath` 读回及 `pulse`。
- 完整测试通过：623 passed，7 skipped。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.5.3。

## 2.5.2

### 修复 / Fixed

- MCP OAuth 补齐 resource binding、反向代理公网地址规范化、PKCE 与 token 续期边界，避免授权页已弹出却无法完成连接。
- `hold` 在打标或 embedding API 不可用时仍原样保存正文；合并只追加原文，绝不调用 LLM 压缩。
- 脱水缓存键加入 API 格式、端点和模型；切换到 Haiku 等新模型后，长桶下次首次浮现会真正调用新模型，不复用旧模型摘要。
- 移除 Dashboard 物理删除入口；旧 `/api/buckets/purge` 改为只读拒绝端点，保留 API 兼容但不会抹除记忆。

### 优化 / Improved

- 收紧 `hold` / `grow` / `trace` 工具描述，要求客户端只在有明确记忆意图时发起写操作，降低模型过度调用。

### 测试 / Tests

- 新增 OAuth 授权码 + PKCE + resource + refresh token 端到端回归，并以真实本地 HTTP 服务验证 401 discovery 链。
- 新增 `hold` 打标/向量降级、原文合并、模型级脱水缓存、OAuth 开关持久化和 purge 禁用回归。
- 完整测试通过：613 passed，7 skipped。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.5.2。

## 2.5.1

### 修复 / Fixed

- Cloudflare Tunnel 在 Compose 部署下默认使用双 `v2` region edge 和 HTTP/2，绕过部分 VPN DNS
  无法解析 `_v2-origintunneld._tcp.argotunnel.com` SRV 记录导致的启动失败。
- 单实例 Compose 统一通过 `OMBRE_HOST_VAULT_DIR` 将宿主机目录 bind mount 到
  `/app/buckets`，并改用兼容 Windows 盘符的长语法；记忆、`config.yaml` 和 Tunnel token
  在 `--force-recreate` 后继续保留。
- 多实例 Compose 支持为每个 owner 单独设置宿主机持久目录，同时保留数据隔离。
- Dashboard 在 Docker 内不再把容器自己的 `.env` 误报为宿主机挂载配置；宿主机目录改为
  Compose 只读状态，并明确提示修改 compose 同目录 `.env` 后重建容器。
- 修正文档和环境变量示例中遗留的 `/data` 路径，统一为 `/app/buckets`。

### 测试 / Tests

- 新增 Compose Tunnel/DNS、Windows bind mount、owner 隔离和 Tunnel token 持久化回归测试。
- 完整测试通过：602 passed，7 skipped。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.5.1。

## 2.4.13

### 修复 / Fixed

- 修复向量 API 被反复重复调用的问题：`trace(content=...)` / `plan()` / `letter_write()` 在
  `bucket_mgr.update()` / `create()` 已经内部同步生成并存好向量之后，又各自显式调用了一次
  `embedding_engine.generate_and_store()`，导致每次写操作都对同一段内容打两次向量 API。
  现在移除了这些多余的显式调用。
- `EmbeddingEngine` 新增进程内小容量 LRU 查询缓存：`breath(query=...)` 内部会对同一个查询串
  各自调用一次向量检索（`bucket_mgr.search()` 内部一次、`surface_search()` 直接又一次），
  `hold()`/`grow()` 的 `merge_or_create` → `check_duplicate_for` → `check_plan_resolution`
  三条 fire-and-forget 链路也会对同一段新内容各嵌入一次。同一段文本对同一模型的向量结果恒定，
  缓存后这些短时间内的重复请求不再重新打向量 API。

### 测试 / Tests

- 现有 `tests/test_embedding_api_regression.py` 等回归测试全部通过，确认门面缓存不影响
  既有向量化行为。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.13。

## 2.4.12

### 优化 / Improved

- `pulse()` 顶部统计现在单独显示 feel / plan / letter 数量，避免列表数量和头部统计看起来对不上。
- `grow()` 短内容走 hold 风格单条保存时会明确提示“没有拆分”，减少短日记归档时的误解。
- Dashboard 保存 `OMBRE_HOST_VAULT_DIR` 后直接提示需要重启容器/服务；API 也返回 `restart_required` 和 `message`。
- Dashboard 将单桶、信件和导入审核删除文案改为“删除到档案”，与清理模式里的物理永久删除明确区分。
- `trace(resolved=1)` 与 REST resolve 共用同一套中文提示，Dashboard 会展示“已沉底/已重新激活”的一致说明。
- `config.example.yaml` 移除已废弃的 active `wikilink:` 配置段，只保留 deprecated 说明。

### 测试 / Tests

- 新增 `tests/test_priority4_confusion_cleanup.py` 覆盖上述高频困惑点的回归。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.12。

## 2.4.11

### 修复 / Fixed

- MCP OAuth 支持 `refresh_token` grant：授权码换 token 时会同时返回 refresh token，headless 服务器环境下 access token 失效后可直接刷新，不再必须重新打开浏览器授权页。
- OAuth discovery 与动态客户端注册现在声明 `refresh_token`，并兼容旧版 `.dashboard_mcp_tokens.json` access token 存储格式。
- 修复 v3 legacy 桥接层缺失的 runtime/web/bucket side-channel API，恢复工具调用、Web 路由注册、更新策略评估和 bucket 生命周期事件的只读旁路记录。

### 测试 / Tests

- 新增 `tests/test_oauth_refresh_token.py` 覆盖 refresh token 元数据声明、授权码换 refresh token、刷新 access token、未知 refresh token 拒绝。
- 修复并恢复 `tests/test_v3_legacy_*` 桥接回归，测试用例显式注入 fake embedding，避免绕开当前“写入必须有向量化”的生产约束。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.11。

## 2.4.10

### 新增 / Added

- GitHub 同步现在会在同一次 commit 中写入 `_ombre_backup_manifest.json`，记录备份生成时间、文件数、总字节数、每个 bucket markdown 的大小和 sha256。
- 从 GitHub 导入/恢复时会读取 manifest 摘要并返回给调用方，后续可用于恢复前校验和备份选择。

### 测试 / Tests

- 新增 `tests/test_github_backup_manifest.py` 覆盖 manifest 生成、同步写入和恢复读回。
- 更新 zero-commit 空仓库同步测试，确认首次提交也包含 manifest。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.10。

## 2.4.9

### 新增 / Added

- Dashboard 历史对话导入新增上传前预检：选中文件后先显示识别格式、轮次、分块数、预计 API 调用、文件大小、首个分块预览和警告，再由用户确认开始导入。
- 新增 `POST /api/import/preflight`，复用导入解析/分块逻辑做只读预检，不写 bucket、不启动后台任务。
- 新增 `preview_import()` 纯函数，便于后续把导入体验继续拆成更明确的预检查项。

### 测试 / Tests

- 新增 `tests/test_import_preflight.py` 覆盖导入预检纯函数和 API 路由。
- 新增 `tests/test_dashboard_import_preflight.py` 覆盖 Dashboard 预检入口。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.9。

## 2.4.8

### 新增 / Added

- Dashboard 设置页新增“系统体检”面板，可一键查看数据目录、记忆桶统计、脱水/打标 LLM、向量化、GitHub 备份、访问控制和运行时状态。
- 新增 `GET /api/system/diagnostics` 只读接口，返回结构化 `ok` / `warning` / `error` 检查项；体检不主动请求外部 API，避免设置页被慢网络卡住。

### 测试 / Tests

- 新增 `tests/test_system_diagnostics.py` 覆盖诊断接口和缺配置告警。
- 新增 `tests/test_dashboard_diagnostics_panel.py` 覆盖 Dashboard 体检入口。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.8。

## 2.4.7

### 修复 / Fixed

- 修复 GitHub 新建空仓库（Zero Commit，首页仍是 Quick setup）首次同步时报 `409 Conflict` 的问题。现在 Ombre 会在空仓库中创建初始 tree/commit，并创建 `refs/heads/<branch>`，无需用户先手动添加 README。
- 从空 GitHub 仓库导入时返回“暂无可导入文件”，不再把空仓库 409 当作异常。

### 测试 / Tests

- 新增 `tests/test_github_sync_zero_commit.py` 覆盖 zero-commit 仓库首次存档 bootstrap 流程。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.7。

## 2.4.6

### 优化 / Improved

- Dashboard 批量导入的 LLM 抽取结果解析改为宽松 JSON 清洗：支持 DeepSeek 等模型在 JSON 数组/对象前后附带说明文字，减少 `Import extraction JSON parse failed`。
- 抽出通用 `clean_llm_json()`，让导入解析与 grow/dehydrator 的 JSON 解析共用同一套 code fence/JSON 片段提取逻辑。

### 测试 / Tests

- 新增 `tests/test_import_extraction_json.py` 覆盖模型回复包含说明文字时的导入解析回归。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.6。

## 2.4.5

### 优化 / Improved

- 新增 LLM / embedding 请求超时配置：`dehydration.timeout_seconds`、`embedding.timeout_seconds`，以及环境变量 `OMBRE_COMPRESS_TIMEOUT_SECONDS`、`OMBRE_EMBED_TIMEOUT_SECONDS`。
- 写记忆时的脱水/打标、原生 Gemini、OpenAI 兼容 embedding 请求都会使用配置的超时时长，方便国内自托管服务器连接云端 API 较慢时调大等待时间。

### 测试 / Tests

- 新增 `tests/test_api_timeout_config.py` 覆盖 config/env 覆盖和运行时对象 timeout 传递。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.5。

## 2.4.4

### 修复 / Fixed

- 允许在 Dashboard 清空或修改 `AI_NAME`，避免关闭 OAuth 后仍显示旧的 AI 显示名；清空后回退为默认 `AI`。
- 统一桶元数据读取层的日期时间序列化，将 `created` / `last_active` 中的 `datetime` / `date` 归一化为 ISO 字符串，避免 `dream()`、Dashboard 首页和导入页面 JSON 序列化报错。
- 版本检查优先通过 GitHub Contents API 读取 `VERSION`，避免 raw CDN 在 push 后继续返回旧版本导致热更新检测不到新版本。

### 测试 / Tests

- 新增 `tests/test_env_config_identity.py` 覆盖 AI 显示名清空回归。
- 新增 `tests/test_datetime_metadata_normalization.py` 覆盖 YAML/frontmatter 时间戳被解析为 `datetime` 后的序列化回归。
- 新增 `tests/test_dashboard_update_source.py` 覆盖 Dashboard 版本检查的 GitHub API 优先顺序。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.4。

## 2.4.0

### 架构 / Architecture

- 将当前高级架构线统一作为对外发布版本 `2.4.0`。
- 保留内部 `src/ombrebrain/` 架构层命名：acceptance、eventsourcing、retrieval、microkernel、plugins、distributed 等模块继续作为内部深内核层存在。
- 保持 MCP tool names、bucket markdown、Dashboard existing routes、config/env 语义不变。

### 修复 / Fixed

- 修复 `tests/test_permanent_breath_regression.py` 中写死 Windows 路径分隔符的断言，改为 `os.sep`，避免 Linux / Docker / CI 下出现跨平台假失败。

### 维护 / Chores

- VERSION + `src/VERSION` -> 2.4.0。
- capability catalog 的 manifest version 改为读取项目版本，避免对外元数据继续暴露旧的架构草案版本号。

## 2.3.22

### 前端 / Frontend

- 写信表单「身份」下拉固定为 `user` / `AI`（对面是 AI 这点不必纠结具体模型名）；
  具体署名由用户在旁边的「署名」框自行填写。
- 写信表单的日期选择改造成拟态化「按钮」：点击主动唤起原生日期选择器（`showPicker()`
  + `focus/click` 兜底），选定后按钮显示所选日期；解决了原生小日历图标与提示文字重叠、
  以及透明输入框点击无响应的问题。
- 「服务日志」页右上角的日志文件路径只显示文件名（如 `server.log`），完整路径移到鼠标
  悬停提示，界面更干净、也不在页面上暴露本机绝对路径。

### 维护 / Chores

- VERSION + `src/VERSION` → 2.3.22。

## 2.3.21

### 新增 / Added

- **letter 署名支持自定义 AI 名称。** `letter_write` 的 `author` 不再限定
  `"user"`/`"claude"`，改为接受任意字符串署名：
  - `"user"` → 用户侧（`user_name` 逻辑不变）；
  - `"ai"`、等于 `ai_name` 的值、或历史遗留的 `"claude"` → 统一存为 `ai_name` 的值；
  - 其它任意字符串 → 原样作为署名。
  新增可选参数 `ai_name`（显式传入优先），默认取环境变量 `AI_NAME`，回退 `"AI"`。
  `letter_read` 原样返回存储的署名、不做转换；按 `author` 过滤时 `"ai"` 会同时
  命中新署名与历史 `"claude"` 信件。Dashboard 写信/筛选、SessionStart 钩子的「最近的信」
  同步适配。（`src/tools/plan/core.py`、`src/web/letters.py`、`src/web/hooks.py`、
  `src/server.py`、`frontend/dashboard.html`；回归测试 `tests/test_letter_author_regression.py`）
- 新增共享 helper `utils.get_ai_name()`：统一从环境变量 `AI_NAME` 读取 AI 显示名（回退 `"AI"`）。
- `.env.example` 新增 `AI_NAME=` 条目及说明。

### 变更 / Changed

- **全局去除面向用户文本与注释中的 "Claude" 硬编码。** 面向用户的文案（OAuth 授权页、
  Dashboard 删除确认/提示、配置项说明）改为中性的 "AI"；代码注释中的 "Claude" 统一改为
  "AI"/"LLM"。保留第三方服务/格式/文件的固有名（如 `Claude Desktop`、`claude.ai`、
  `claude_desktop_config.json`、Claude/ChatGPT 导出格式、Anthropic 模型 ID），以及 letter
  存储层对历史 `"claude"` 署名的向后兼容判断。

### 维护 / Chores

- 同步 bump `src/VERSION`（热更新读取的副本）与根 `VERSION` 至 2.3.21。

## 2.3.20

### 修复 / Fixed

- **`breath(importance_min=N)` 在高重要度桶塞满上限时，刚被 `trace` 降级的桶看似「未刷新」**
  之前 `breath(importance_min=N)` 把所有符合阈值的桶按 importance 降序排，直接截取前 20 条。当 `importance=10` 的桶超过 20 个时，一个刚用 `trace` 从 10 降到 9 的桶会被高分桶挤出列表，看起来像「trace 改了 importance 但 breath 没刷新」。
  现在改为先给每个符合阈值的 importance 档位（10、9…）各预留一条最近更新的桶，再按正常排序填满剩余名额，确保降级后的桶在其档位仍可见。
  （`src/tools/breath/importance.py` `_select_importance_buckets`；回归测试见 `tests/test_trace_importance_regression.py`）

  > 说明：`trace` 写入 importance 后，`breath` 是每次从磁盘实时重读、无缓存，本身不存在「需要额外操作触发刷新」。若 `trace` 降级看似无效，请先确认目标桶不是 `pinned`/`protected`——这类核心桶 importance 被锁定为 10，`trace` 会拒绝降级并返回提示，需先 `trace(bucket_id, pinned=0)` 再调整 importance。

### 维护 / Chores

- 修正 `.gitignore`：`docs/secrets/`（复数）此前未被忽略，补上规则，避免本地密钥/设计稿目录被纳入版本控制。
