# Ombre Brain — 内部开发文档 / INTERNALS

> **第一人称原则（全局）**：Ombre Brain 的使用者是**模型自己**，不是用户。所有提示词、docstring、注释、前端说明文字必须用第一人称（"我的记忆"/"我记得"/"我感受到"），禁止"用户的记忆""帮用户记住""为用户存储"等第三人称表述。本规则覆盖 server.py 工具 docstring、CLAUDE_PROMPT.md、dashboard 文案、ENV_VARS.md 描述。改任何一段面向模型的文字前先回头看这条。
>
> 本文档面向开发者和维护者。合并自原 INTERNALS.md（系统怎么运作）+ BEHAVIOR_SPEC.md（行为应该符合什么规格）。
>
> **阅读约定**：每个模块/功能块分两层。
>
> - **上层（人话）**：这一块在干什么、边界在哪、当前实现到了哪一步、关键硬编码值。
> - **下层（括号内，给改代码的人看）**：实现约束、依赖关系、改动注意事项、踩过的坑。
>
> 文档以**当前代码为准**。未实现的设想统一放在末尾「未来设想」一节，不与现状混写。

---

## 目录

0. 功能总览
1. 模块结构与依赖
2. 数据流与生命周期
3. MCP 工具规格
4. REST API 与 Dashboard
5. 衰减与评分公式
6. 桶类型矩阵
7. 配置与环境变量
8. 硬编码值清单
9. 降级行为表
10. 已修复 Bug 记录（B-01 至 B-10）
11. Debug 快速索引（症状 → 文件 + 函数）
12. 已知用户向反逻辑点
13. 未来设想（依赖上游 hook 才能落地）

---

## 0. 功能总览

Ombre Brain 是一套给 LLM 用的长期情绪记忆系统。它的边界是「时间里发生的事」，不是「你是谁」（身份层交给官方记忆）。每条记忆 = 一个 Markdown 文件（YAML frontmatter + 正文），原生兼容 Obsidian 浏览/编辑。

记忆按桶类型分目录存放：`dynamic/`（普通，会衰减）、`permanent/`（钉选/固化，importance=10、不衰减）、`feel/`（模型自省，固定分 50，永不浮现到普通 breath）、`plans/active/`（待办，固定分 50，不衰减不浮现）、`letters/history/`（信件，原文永久保留，不参与压缩/合并/衰减）、`archive/`（已淘汰）。

检索多通道并联：rapidfuzz 模糊匹配 + BM25 稀疏检索（jieba 分词，`bm25_index.py`）共同承担关键词层召回 + 余弦相似度（向量层）+ 衰减分排序（浮现层）。情感坐标用 Russell 环形模型的 `valence`/`arousal` 双连续维度，不用离散标签。

> **多通道职责澄清（refactor-2.0 后）**：
> - **召回阶段**：rapidfuzz 关键词命中 + BM25 稀疏召回 + 元数据过滤（domain/tags/importance_min）共同决定候选池；
> - **打分阶段**：embedding 余弦相似度只作为**得分维度之一**乘进 `bucket_manager._score_bucket()`，不会单独触发召回；
> - **排序阶段**：`decay_engine.calculate_score()` 给出最终衰减分，与上面两个分数加权汇总后排序。
> 也就是说"并联"指的是「三种信号同时进入打分」，不是「三个独立的搜索引擎」。embedding 关闭时仅打分缺一维，召回不受影响。

(开发者侧：所有桶都通过 `bucket_manager.list_all()` 递归遍历目录加载；没有数据库索引，全靠目录扫描。规模 < 几千桶时 OK，再大需要重新设计。)

---

## 1. 模块结构与依赖

### 1.0 仓库布局（重构后）

```
Ombre-Brain/
├── src/                # 所有运行期 Python 源码（server.py / bucket_manager / dehydrator / ...）
├── tools/              # CLI 一次性脚本：backfill / migrate / reclassify / check_*
├── tests/              # pytest 测试套件（unit / integration / regression）
├── docs/               # INTERNALS / BEHAVIOR_SPEC / ENV_VARS / CLAUDE_PROMPT
├── frontend/           # dashboard.html
├── deploy/             # docker-compose.yml / docker-compose.user.yml
├── Dockerfile          # 根目录保留（平台自动识别）
├── render.yaml         # 根目录保留（Render 自动识别）
├── zbpack.json         # 根目录保留（Zeabur 自动识别）
├── requirements.txt / requirements.lock.txt  # 直接依赖源 / 发布安装锁
├── requirements-dev.in / requirements-dev.lock.txt  # CI 与审计工具源 / 锁
├── config.example.yaml / config.yaml
├── README.md / LICENSE / rule.md
└── .env                # 不进 git
```

入口固定为 `python src/server.py`。`utils.load_config()` 自动按
`$OMBRE_CONFIG_PATH` → `cwd/config.yaml` → `<repo_root>/config.yaml` 的顺序查找配置。

```
                    ┌──────────────┐
                    │  src/server.py │  MCP 入口（薄封装）+ 引擎构建 + 进程启动
                    └─────┬───────┘
              注入 _runtime │  装配 web.register_all(mcp) / server_app.build_http_app()
           ┌──────────────┴──────────────────────────────┐
           ▼                                              ▼
  ┌─────────────────────────────┐      ┌───────────────────────────────┐
  │ src/tools/ MCP 业务包（薄封装→子包）│      │ src/web/ HTTP/Dashboard 路由层      │
  │   breath/ hold/ grow/ dream/         │      │   16 个域模块，每个 register(mcp)   │
  │   trace/ anchor/ plan/ i/            │      │   config_api/embedding/buckets/... │
  │   _runtime.py · _common.py           │      │   ollama_local/github/...           │
  └───────────┬─────────────────────┘      │   共享依赖见 web/_shared.py          │
              │                              └──────────────┬────────────────┘
           ┌──┴────────────┬───────────────┬───────────────┴────┐
           ▼               ▼               ▼                    ▼
   bucket_manager   decay_engine    dehydrator         embedding_engine
   桶 CRUD+搜索     遗忘曲线         脱水/打标/合并    向量化+余弦检索
   (+bm25_index)                                       (门面+单 API 后端)
           │               │               │                    │
           └───────┬───────┴───────────────┴────────────────────┘
                   ▼
              utils.py    (config / 日志 / ID / 路径安全 / token 估算)

   独立模块：import_memory.py（历史导入）· migrate_engine/migration_engine.py
   （记忆包导入 + 后端切换重算）· github_sync.py（云端备份）· errors.py（OB 错误码）
```

### 模块职责一览

每个模块「干什么、边界在哪、依赖谁」：

- **server.py**（约 1000 行）— MCP 服务入口。创建所有组件后调 `tools._runtime.init(...)` 注入依赖；以 `@mcp.tool()` / `@mcp_extra.tool()` 注册 **12 个薄封装**（每个 ≤ 10 行，只转发到 `tools/<名字>/`）；启动入口处把 `mcp_extra` 的 7 个工具回灌进 `mcp`，对外只暴露 **单连接器 `/mcp`**（12 工具全在这一条，详见 §3 抬头）；启动段调 `web.register_all(mcp)` 装配所有 HTTP 路由，并起 `mcp.streamable_http_app()` 一个 uvicorn 进程。**不写业务逻辑，也不再直接定义 HTTP 路由**——后者已全部迁到 `web/`。
- **tools/**（MCP 工具应用层）— 详见下面「1.x tools/ 包结构」。
- **web/**（HTTP/Dashboard 路由层）— 详见下面「1.y web/ 包结构」。从旧 server.py 巨石里拆出的 16 个域模块，每个导出 `register(mcp)`；cookie/CSRF/会话鉴权等共享依赖在 `web/_shared.py`（类比 `tools/_runtime.py`）。
- **bucket_manager.py** — 桶 CRUD + 多维加权搜索 + `touch()` 激活刷新 + `_time_ripple()` 时间涟漪 + 文件搬运（archive/permanent 之间）。
- **decay_engine.py** — `calculate_score(metadata)` 单桶活跃度评分；`run_decay_cycle()` 周期扫描 → auto-resolve / archive；后台 asyncio 循环。
- **dehydrator.py** — 通过 OpenAI 兼容 LLM API 做四件事：`analyze()` 自动打标、`merge()` 内容融合、`digest()` 日记拆分、`dehydrate()` 摘要压缩；外加 `judge_plan_resolution()` 给 plan 自动结案做 LLM 双判。带 SQLite 缓存避免重复 API 调用。
- **embedding_engine.py** — 「门面 + 后端」两层向量化：后端只有**一个 OpenAI 兼容 API 实现**（默认 Gemini 云端）；门面负责 SQLite 存取、余弦搜索、孤儿对账、模型/维度一致性校验（不一致记 OB-W005，不阻止启动）。**本地离线向量化**不是另一个后端，而是把 `base_url` 指向 OB 托管的 Ollama 边车（bge-m3，由 `web/ollama_local.py` 拉起子进程）。旧文档的「bge-small-zh / sentence-transformers 懒加载」已废弃。
- **bm25_index.py** — BM25 稀疏检索（jieba 中文分词），给 `bucket_manager.search()` 提供 TF-IDF 加权的关键词召回（Dim 7）。`rank_bm25` / `jieba` 是软依赖，未装则静默 no-op，不影响其余维度；索引由 BucketManager 持有，写后脏标记、search 时懒重建。
- **import_memory.py** — Claude JSON / ChatGPT / DeepSeek / Markdown / 纯文本五种格式的历史对话导入，分块处理 + 断点续传 + 词频规律检测。
- **backup_archive.py** — 本地备份格式：读取 Markdown、用 SQLite backup API 生成一致性快照、写 `backup_manifest.json`（逐文件 size + SHA-256）；导入前限制 ZIP 文件数/体积/压缩率并拒绝路径穿越、重复路径、损坏清单。
- **migrate_engine.py** — 完整记忆包导入：把 `/api/export` 产生的 zip 增量 merge 进当前系统；识别 ID 冲突（skip/overwrite/keep_both），兼容新旧 embedding schema。模型不一致或快照缺向量时写入耐久 outbox，不把网络调用放在恢复事务里。旧版无清单包可兼容导入，但状态明确标记为未验证。
- **vault_health.py** — Dashboard 与 `tools/check_buckets.py` 共用的只读健康检查：Markdown 解析、重复 ID、越界软链接、SQLite `quick_check`、孤儿向量、缺失且未进入 outbox 的向量。
- **migration_engine.py** — embedding 后端切换（local ↔ api）时后台全量重算向量：先写 `embeddings.db.migrating`、跑完原子 swap；断点续传 + 失败跳过 + 进度文件供前端轮询。
- **github_sync.py** — 把 `buckets_dir` 下的 .md 经 GitHub Git Trees API 批量提交做云端备份（不传 embeddings.db）；支持手动 + 定时自动同步。路由在 `web/github.py`。
- **reclassify_api.py** — 一次性脚本：把历史落在「未分类/」的桶重新 `analyze()` 打标并搬到正确 domain 目录，只改 frontmatter 与文件位置。
- **errors.py** — OB 统一错误码（如 OB-W005 embedding 模型漂移、OB-Startup 系列），供各模块抛结构化异常。

> **第一人称豁免**：`import_memory.py` 在喂给 LLM 的 prompt 里把对话格式化成 `[用户] ... [AI] ...` 文本块（[src/import_memory.py](src/import_memory.py) `_chunk_turns` 第 291 行），这是给 LLM 看的「对话块」标签，不是写入桶 frontmatter 或返回给模型的 docstring，因此不违反 §2.9 第一人称原则。修改这段时勿误删。
> **导入阈值**：`_PATTERN_MIN_DYNAMIC_BUCKETS = 5` / `_PATTERN_PIN_SUGGEST_THRESHOLD = 5`，详见 rule.md §6 备注。
- **utils.py** — 配置加载（env > yaml > defaults 三级优先级）、日志、12 位 hex 短 ID 生成、`safe_path()` 路径遍历防护、`count_tokens_approx()` 中英混排 token 估算。

(改动约束：`bucket_manager` 不能直接调 `decay_engine`，避免循环依赖；`embedding_engine` 在 `BucketManager` 构造时通过参数注入，不能反向引用。`tools/*` 只能通过 `tools._runtime` 拿到依赖，不可反向 `import server`（否则循环）。新增模块时遵循「server.py 是唯一可以引用所有模块的中枢」原则。)

### 1.x tools/ 包结构（2.0 拆分后）

2.0 把 server.py 里原本「肥大入口 + 一堆内部 helper」按路径拆到 `src/tools/<工具>/<分支>.py`，薄封装留在 server.py，真逻辑进子包。

```
src/tools/
├── _runtime.py    # 依赖注入容器：config / bucket_mgr / dehydrator / decay_engine /
│                #   embedding_engine / import_engine / logger / fire_webhook / mark_op
├── _common.py     # 多个工具共享的 helper：内容限额/pinned 配额/check_duplicate_for/
│                #   check_plan_resolution/merge_or_create
├── breath/        # feel/importance/surface/search 四分支，__init__.py 转发
├── hold/          # core/feel/pinned 三分支，__init__.py 统一入口与参数校验
├── grow/          # core/shortpath（短内容快路径在 shortpath，raw_merge=True）
├── dream/         # candidates/hints/output 三阶段 + __init__ 编排
├── trace/         # core（metadata/resolved/pinned/delete/content 替换/计划状态等全在这）
├── anchor/        # core：anchor_set / anchor_release / pulse
├── plan/          # core：plan_create / letter_write / letter_read
└── i/             # core：自我认知条目读写（dispatch=i_core），iter 2.x 新增
```

路线：`server.X(...)` → `tools.X.dispatch(...)`（`__init__.py`）→ 分支函数。所有分支只通过 `from .. import _runtime as rt` 读依赖，不能 `import server`。`server.py` 保留了 `_check_content_size / _check_pinned_quota / _max_bucket_bytes / _max_pinned / _merge_or_create / _check_duplicate_for / _check_plan_resolution` 这几个别名，让仍引用它们的调用点不需要改。

### 1.y web/ 包结构（HTTP 层从 server.py 拆出后）

旧 server.py 把 93 个 `@mcp.custom_route` 全平铺在一个约 5000 行文件里。现在按域拆成 `src/web/<域>.py`，每个模块导出 `register(mcp)`，server.py 启动时 `web.register_all(mcp)` 统一装配（注册顺序见 `web/__init__.py`）。

```
src/web/
├── _shared.py      # 共享依赖容器：config / logger / 各业务引擎 + cookie 会话鉴权 helper
│                  #   （类比 tools/_runtime；embedding_engine 热替换时也写这里）
├── auth.py         # /auth/*：密码登录 / 设置 / 改密 / 注销 / 会话
├── oauth.py        # MCP Remote Auth（OAuth 2.0）相关 .well-known 与 token 端点
├── dashboard.py    # 根路由 / 与 /dashboard 跳转、HTML 下发
├── system.py       # /api/status / /health / 版本等系统信息
├── meta.py         # 桶 frontmatter 元数据读写类端点
├── search.py       # /api/search / /api/network / /api/breath-debug
├── plans.py        # /api/plans(+/{id}/action) 看板
├── letters.py      # /api/letters / /api/letter 信件
├── hooks.py        # /breath-hook / /dream-hook（SessionStart 等 HTTP 钩子）+ Webhook
├── buckets.py      # /api/buckets(+ pin/resolve/archive/forget/anchor/edit/DELETE；保留已退役 purge 拒绝端点)
├── import_api.py   # /api/import/*（上传 / 进度 / 暂停 / 规律 / 审阅）
├── github.py       # /api/github/*（GitHub 备份同步，封装 github_sync.py）
├── embedding.py    # /api/embedding/*（info / migrate / local 模型管理）
├── ollama_local.py # 本地 Ollama 边车：装运行时 + 作为 OB 子进程常驻（裸机离线向量化）
├── config_api.py   # /api/config / env-config / env-vars / 模型列表 / 连通性自检
├── tunnel.py       # Cloudflare Tunnel 管理
└── import_*/migrate 端点散落在 import_api/embedding 中（/api/migrate/* 由迁移引擎驱动）
```

(改动约束：新增 HTTP 路由就新建/扩展对应 `web/<域>.py` 并在 `register_all` 里加一行，不要再写回 server.py；所有 `/api/*` 路由首行调 `_shared` 的鉴权 helper。)

### 辅助脚本

`tools/backfill_embeddings.py`（为存量桶补 embedding）、`src/write_memory.py`（CLI 直写记忆，绕过 MCP）、`tools/reclassify_domains.py` / `src/reclassify_api.py`（重新打标）、`tools/check_buckets.py`（数据完整性检查）、`tools/check_icloud_conflicts.py`（iCloud 同步冲突文件清理）、`tools/evaluate_retrieval.py`（用显式 query→bucket 期望只读计算 Hit@K / Recall@K / MRR，默认不调用 embedding）。

---

## 2. 数据流与生命周期

### 2.1 一条记忆的完整生命周期

```
用户内容
  │
  ▼
hold / grow（Claude 决策）
  │
  ├─ grow ─→ dehydrator.digest()  → 拆为 2~6 条 → 每条独立走 hold
  │
  └─ hold ─→ dehydrator.analyze()  → {domain, valence, arousal, tags, name}
              │
              ▼
       _merge_or_create()
              │
       bucket_mgr.search(content, limit=1, domain_filter)
              │
       score > merge_threshold(75)?
        ├─ 是 → dehydrator.merge() → bucket_mgr.update()
        └─ 否 → bucket_mgr.create()
              │
              ▼
       写入 buckets/dynamic/{domain}/{name}_{id}.md
       activation_count = 0   ← 关键：创建时为 0，touch() 才会变 1+
              │
              └─→ embedding outbox（只存 id + content hash）
                        └─ 后台单 worker 生成向量；失败指数退避、重启后续跑
              │
              ▼
       存活期：每次 breath(query) 命中 → bucket_mgr.touch()
                                           ├─ last_active = now
                                           ├─ activation_count += 1
                                           └─ _time_ripple()  ±48h 邻近桶 +0.3
              │
              ▼
       decay_engine 后台循环（每 24h）→ run_decay_cycle()
              │
       score < threshold(0.3)？
        ├─ 是 → bucket_mgr.archive() → 移入 archive/{domain}/，type="archived"
        └─ 否 → 继续存活
```

(数据流约束：`touch()` 只在**检索命中**时调用，**浮现模式不调用**——这是为了不让 `breath()` 自动浮现重置衰减计时器，否则高活跃桶会永远霸占浮现位。)

### 2.2 对话启动序列（CLAUDE_PROMPT.md 规定的 Claude 端行为）

```
1. breath()                — 必须。浮现未解决记忆
2. dream()                 — 可选。你或用户觉得需要消化时再调
3. breath(domain="feel")   — 可选。想读 feel 时再调
4. 开始和用户说话
```

dream 不是 hook，不是对话启动义务流程。它是你和用户一起决定要不要做的事，没有消化的必要就不做。

### 2.3 feel 桶的特殊生命周期

```
hold(feel=True, source_bucket="xxx", valence=0.45)
  │
  ├─ 跳过 analyze() 和 _merge_or_create()
  ├─ 自动注入 __feel__ 系统标签
  ├─ 写入 buckets/feel/沉淀物/
  ├─ embedding_engine.generate_and_store() （供 dream 结晶检测使用）
  └─ 若 source_bucket 提供 → bucket_mgr.update(source, digested=True, model_valence=0.45)
                              源桶 resolved_factor → 0.02（加速淡化）

feel 桶自身：
  - calculate_score() 固定返回 50.0，永不归档
  - 普通 breath 不浮现（被 type 过滤）
  - 只通过 breath(domain="feel") 或 breath(tags="feel"/"__feel__") 读取
  - 仍参与 dream 的结晶化检测（>0.7 相似度且 ≥3 条 → 提示升级为 pinned）
```

---

## 3. MCP 工具规格（共 12 个）

> **单连接器（iter 2.2）**：claude.ai 的 5 工具上限已解除，12 个工具合并回一个连接器 `/mcp`。
> 历史上（iter 2.1）曾因该上限拆成主 `mcp`（`/mcp`，5 个）+ 副 `mcp_extra`（`/mcp-extra`，7 个）两个 FastMCP 实例。
> 现在 `mcp_extra` 仅作工具分组容器保留（7 个 `@mcp_extra.tool()` 注册不动），启动入口处统一把它的工具
> 回灌进 `mcp`，三种 transport（stdio / sse / streamable-http）都只对外暴露一条 `/mcp`。
> - 高频 5 个 —— `breath` / `hold` / `grow` / `trace` / `dream`
> - 低频 7 个 —— `anchor` / `release` / `pulse` / `plan` / `letter_write` / `letter_read` / `I`

### 3.1 `breath` — 检索/浮现

签名：`breath(query="", max_tokens=10000, domain="", valence=-1, arousal=-1, max_results=20, importance_min=-1, tags="")`

四种模式（按代码内判定顺序）：

1. **Feel 通道**（`domain="feel"` 或 `tags` 含 `"feel"`/`"__feel__"`）：直接拉所有 `type==feel` 桶，按 `created` 倒序展示原文，按 `surfacing.feel_max_tokens`（默认 6000）做 token 预算；**超出预算的旧 feel 折叠为 60 字符单行摘要**，并在末尾追加 `更早的 feel 摘要（N 条，已折叠）` 段。**不排除 anchor 桶**（设计：feel 通道只看 type=feel）。
2. **重要度批量模式**（`importance_min >= 1`）：跳过语义搜索，按 importance 降序返回 ≤20 条；过滤 `feel/plan/letter` 与 `dont_surface=True`；**不过滤 anchor、不过滤 pinned**（设计：主动按 importance 检索时希望能找到所有重要桶）。
3. **浮现模式**（无 `query`）：钉选桶始终展示为「核心准则」+ 未解决桶按衰减分排序，**冷启动**（`activation_count==0 && importance>=8`）的桶最多 2 个插到最前；后续排序**有两条互斥路径**：当 `surfacing.sampling.enabled=true` 时走加权无放回采样（`top_k` / `sample_k` / `temperature` 控制；详见 §7.1），否则走原 Top-1 固定 + Top-2~20 随机洗牌；按 `max_results` 硬截断。**排除 anchor 桶**（设计：anchor 是坐标系，不该随机冒泡干扰日常浮现；这是浮现模式独有的过滤）。浮现**不调用** `touch()`。**末尾追加 `=== 久未浮现 ===`** 段（iter 1.6 §7 被动联想）：从 `activation_count==0 && importance>=8` 或 `importance>=9 && 距 last_active>7天` 的桶里随机抽 1~2 条，模拟「突然想起来」。
4. **检索模式**（有 `query`）：每个 query 只生成一次查询向量，与 rapidfuzz/BM25 多维评分共同进入 `BucketManager.search()` → 过滤 `feel/plan/letter`，**pinned/permanent 仍可被检索命中（不过滤），命中后加 📌 前缀** → 纯语义候选相似度 `>=0.65` 标 `[语义关联]`，且不能绕过 domain/tags/type 过滤 → 命中时 `touch()` → 结果不足 3 条时 40% 概率随机漂浮 1~3 条低权重旧桶。embedding 不可用时明确提示后继续关键词/BM25；桶一旦命中，返回层直接使用当前存储的完整 `content`，不调用 dehydrate、不剥除 wikilink、不截断或改写。**不过滤 anchor**（设计：主动检索时希望能找到坐标系桶）。

(实现注意：`tags="feel"` 在第一个分支被映射为 `domain="feel"` 后清出 tag_filter；其它 tag 走 AND 过滤；`max_tokens` 上限 20000，`max_results` 上限 50；`importance_min` 模式下硬上限 20 条不可调；浮现模式中钉选桶**不计入** `max_results` 上限。)

### 3.2 `hold` — 存储单条记忆

签名：`hold(content, tags="", importance=5, pinned=False, feel=False, source_bucket="", valence=-1, arousal=-1, why_remembered="")`

两种路径：

- **Feel 模式** (`feel=True`)：跳过 LLM 分析，自动注入 `__feel__` 标签，写入 `feel/沉淀物/`。`source_bucket` 提供时把源桶标记为 `digested=True` 并写 `model_valence`。返回 `🫧feel→{id}`。
- **普通模式**：`analyze()` → 用户传入的 `valence`/`arousal` 优先于 LLM 结果（B-09 修复）→ `_merge_or_create(raw_merge=True)`（相似度 > `merge_threshold` 时以分隔线追加原文，否则新建）→ 原文落盘后投递 embedding outbox → 异步触发 `_check_plan_resolution()` 扫 active plans。返回 `合并→{name}` 或 `新建→{name}`。`analyze()` 或 embedding 不可用时只降级元数据/向量索引，正文仍原样落盘；**hold 永远不调 `dehydrate()`/`merge()` 压缩正文**。

(改动注意：`pinned=True` 走单独分支直接创建到 `permanent/`，importance 强制锁 10，不走合并；用户显式传 valence/arousal=0.0 也算「有效」，必须走 `0 <= v <= 1` 判定，不能用 `if valence` 否则 0.0 会被忽略——这就是 B-09。)

### 3.3 `grow` — 日记拆分归档

签名：`grow(content)`

- 短内容（< 30 字符）走快速路径：`analyze()` + `_merge_or_create()`，跳过 `digest()` 节省一次 API。
- 正常路径：`dehydrator.digest()` 拆为 2~6 条 → 每条独立走 `_merge_or_create()`，单条失败 try/except 隔离，标 `⚠️条目名`。
- 末尾异步触发 `_check_plan_resolution()`。

返回示例：`3条|新2合1\n📝体检结果\n📌朋友聚餐\n📎近期焦虑情绪`。

### 3.4 `trace` — 修改/删除

签名：`trace(bucket_id, name="", domain="", valence=-1, arousal=-1, importance=-1, tags="", resolved=-1, pinned=-1, digested=-1, content="", delete=False, status="", weight=-1, dont_surface=-1, why_remembered="")`

- `delete=True` → `bucket_mgr.delete()`：写入 `deleted_at` 并将 Markdown 移入 `archive/`；只清理可重建的 embedding 索引，不抹除记忆文件。
- 其它字段：仅收集传入的（用 `-1`/空串作为「未传」哨兵）批量更新 frontmatter。
- `pinned=1` 自动锁 importance=10 + 触发 `_move_bucket(permanent_dir)`。
- `resolved=1` **不**自动归档（B-01 修复）；只更新 frontmatter，由 decay 引擎自然衰减。
- `status` 仅接受 `active`/`resolved`/`abandoned`，主要用于 plan 桶。
- `content="..."` 替换正文并重新生成 embedding。
- `weight` 仅对 plan 桶有意义；`dont_surface` 切换主动遗忘标记；`why_remembered` 写「为什么留着这条」自由文本。
- **不暴露 `anchor` 字段**：anchor 切换必须走 `anchor()` / `release()` 工具（受 24 上限保护）。

(返回时会按 `resolved`/`digested` 状态变化追加人话提示，如「→ 已沉底，只在关键词触发时重新浮现」。)

### 3.5 `pulse` — 系统状态 + 桶列表

签名：`pulse(include_archive=False)`

返回：固化/动态/归档桶数、feel/plan/letter 分项数量、总 KB、衰减引擎状态、所有桶（带图标）的元数据摘要行。

### 3.6 `dream` — 做梦自省

签名：`dream(window_hours=48)`（默认 48h 窗口；clamp 到 1~336h）

- 默认取过去 48 小时内 `created` 或 `last_active` 任一在窗口内的桶（排除 permanent/feel/pinned/protected/plan/letter）
- 排序：先按 `last_active` 倒序；候选超过 **40 个**时改按 `decay_engine.calculate_score()` 降序截断到前 40，避免一次涌进来太多撑爆上下文
- 拼接桶摘要（完整正文，不截断）+ 自省引导 header
- embedding 启用时附加：连接提示（最相似对，`>0.5`）+ feel 结晶提示（一条 feel 与 ≥2 条其它 feel 相似度 `>0.7` → 建议升级为 pinned）
- 末尾追加 `=== 你的 active plans ===` 全量列表
- 末尾追加 `=== 你的 feel 历史（全量，旧 feel 按 token 预算折叠）===`：按 `surfacing.feel_max_tokens`（默认 6000）做预算，超出的老 feel 折叠为 60 字符单行摘要

(实现细节：用户可手动传更大的 `window_hours`，但软上限 40 仍生效。plan 历史不参与 token 预算全量返回；feel 历史走 token 预算折叠。)

### 3.7 `plan` — 登记待办

签名：`plan(content, status="active", related_bucket="", weight=0.5, why_remembered="")`

写入 `plans/active/`，自动打 `__plan__` 标签，**硬编码** `importance=7` / `domain=["plan"]` / `valence=0.5` / `arousal=0.4`（设计：plan 不开放给用户调情感坐标）。`status` 仅接受 `active`/`resolved`/`abandoned`，其它静默回退为 `active`。`weight` 是「承诺重量」（0~1，dashboard 看板按此倒序）。`why_remembered` 写自由文本说明为什么登记这条。

**严格字符串去重**：登记前扫描所有 `status="active"` 的 plan 桶，若存在 `content` 与新内容**完全字符串相等**的桶，直接返回原 ID 不重复创建（避免重复 `plan("还没回邮件")` 刷屏）。

**自动结案机制**：每次 `hold()` 或 `grow()` 末尾 `asyncio.create_task(_check_plan_resolution())` —— 向量预筛（>0.7）→ LLM 双判 (`resolved && confidence >= 0.7`) → 写 `status="resolved"` + `resolution_reason` + `resolved_by`。任何异常都吞掉，不影响主流程。无 embedding 时整个机制跳过（保守，宁漏报不误报）。

### 3.8 `letter_write` / `letter_read` — 信件

`letter_write(author, content, user_name="", title="", date="")` —— `author` 必填且仅 `user`/`claude`；写入 `letters/history/`，**硬编码** `importance=10` / `valence=0.5` / `arousal=0.3`（设计：信件不开放给用户调这三项），原文永久保留。**不接受 `why_remembered`**——信件本身就是「为什么记得」的载体。

`letter_read(query="", limit=10, author="", date_from="", date_to="")` —— 无 query 时按 `letter_date` 或 `created` 倒序；有 query 且 embedding 启用时用向量相似度排序。

信件特性：永不衰减（`calculate_score` 固定 50）、永不合并、不参与压缩；普通 `breath` 不浮现（被 `feel/plan/letter` 过滤）；`/breath-hook`（SessionStart）末尾追加双方各最新一封。

### 3.9 `anchor` — 标记坐标系桶（iter 2.0）

签名：`anchor(bucket_id)`

把指定桶的 `anchor` frontmatter 字段置为 `True`。**硬上限 24**（`BucketManager.ANCHOR_LIMIT`），由 `set_anchor()` 入口校验；`update()` 透传路径也补了同样校验（False→True 切换时计数，已是 anchor 的重复设置幂等）。超过上限返回 `{ok:False, error:"anchor 已达上限 24"}`，REST 端点 `/api/bucket/{id}/anchor` 返回 **409**。

语义：anchor 是「坐标系」——告诉模型「这是定位用的参照点，不是日常需要冒出来的内容」。anchor 桶**不参与无参 `breath()` 浮现**，但 `query` / `domain` / `importance_min` 等显式检索仍可命中。**与 pinned / dont_surface / weight 完全独立**，不参与 `calculate_score()`。

### 3.10 `release` — 释放坐标系标记（iter 2.0）

签名：`release(bucket_id)`

把指定桶的 `anchor` 字段从 `True` 改回未设置（`update(anchor=False)` 路径直接删除该 frontmatter 键，保持文件干净）。释放后该桶恢复正常浮现资格。无副作用，幂等。

### 3.11 `I` — 自我认知条目（iter 2.x）

签名：`I(content="", aspect="", read=False, limit=20)`

实现在 `tools/i/`（`dispatch = i_core`）。语义：「我写下关于我自己的认识」——不是「时间里发生的事」，而是模型对自身本质/规律/变化的观察。

- `content` 空 或 `read=True` → **读取模式**，返回已积累的全部自我认知（按 `limit` 截断，默认 20 条）。
- `content` 非空 → **写入模式**，记一条自我认知；`aspect` 可选维度：`nature`(本质) / `values`(看重的) / `patterns`(规律) / `limits`(局限) / `becoming`(在变成什么) / `uncertainty`(不确定的) / `stance`(立场)。
- I 条目写入时带 `dont_surface=True`：**不参与普通 `breath` / `dream`**；只在 `SessionStart` 时自动附带最近 3 条。

---

## 4. REST API 与 Dashboard

### 4.1 端点完整列表

| 端点 | 方法 | 鉴权 | 用途 |
|---|---|---|---|
| `/` | GET | 公开 | 重定向到 `/dashboard` |
| `/health` | GET | 公开 | 健康检查（桶数 + 衰减引擎状态） |
| `/breath-hook` | GET | 🔒 cookie/token | SessionStart 钩子（HTTP 模式才生效）；默认需 Dashboard 登录态或 hook token |
| `/dream-hook` | GET | 🔒 cookie/token | Dream 钩子；默认需 Dashboard 登录态或 hook token |
| `/dashboard` | GET | 公开（页面），AJAX 走 cookie | Dashboard HTML |
| `/letters` | GET | 公开 | 301 → `/#letters`（已合并进 dashboard 的「信」分页，老书签兼容） |
| `/auth/status` | GET | 公开 | 是否已登录 / 是否需要初始化密码 |
| `/auth/setup` | POST | 公开（仅未配置密码时） | 首次设置密码 |
| `/auth/login` | POST | 公开 | 密码登录，颁发 cookie（7 天） |
| `/auth/logout` | POST | 公开 | 注销 |
| `/auth/change-password` | POST | 🔒 | 修改密码（环境变量密码模式下禁用） |
| `/api/buckets` | GET | 🔒 | 桶列表（带评分、不带正文，仅预览） |
| `/api/bucket/{id}` | GET | 🔒 | 桶详情（含正文）。iter 1.9 起额外返回 `triggered_feels: [{id,name,created}]` —— 反向链：哪些 feel 桶把这条作为 `triggered_by` |
| `/api/bucket/{id}/pin` | POST | 🔒 | 切换 pinned（自动同步 type permanent⇄dynamic） |
| `/api/bucket/{id}/resolve` | POST | 🔒 | 切换 resolved |
| `/api/bucket/{id}/archive` | POST | 🔒 | 软删除（移入 archive/） |
| `/api/bucket/{id}/forget` | POST | 🔒 | iter 1.8：切换 `dont_surface`。桶仍在磁盘，只是不再被无参 `breath()` 主动浮现，关键词搜索仍可达 |
| `/api/buckets/forget` | POST | 🔒 | iter 1.9：批量设置 `dont_surface`。Body `{ids:[...], dont_surface: bool}`。返回 `{ok, updated:[], missing:[], errors:[]}` |
| `/api/settings/sampling` | GET / POST | 🔒 | iter 1.9：dashboard 的加权采样面板。GET 返回当前 `surfacing.sampling.{enabled,top_k,sample_k,temperature}`；POST 校验范围后热更新到内存 config（不写回 yaml） |
| `/api/anchors` | GET | 🔒 | iter 2.0：列出所有 anchor 桶（按 `created` 升序），返回 `{ok, count, limit, anchors:[...]}` |
| `/api/bucket/{id}/anchor` | POST | 🔒 | iter 2.0：toggle anchor 标记。Body 可传 `{value: bool}` 强制设置；不传则切换。已满 24 时返回 **409** + `{error, count, limit}` |
| `/api/bucket/{id}` | DELETE | 🔒 | 删除到档案：移入 `archive/` 并写 `deleted_at`，需 `?confirm=true`；不做物理抹除 |
| `/api/letters` | GET | 🔒 | 信件列表，支持 `?author=user\|claude` |
| `/api/letter` | POST | 🔒 | Dashboard 写信入口 |
| `/api/search?q=` | GET | 🔒 | 搜索 |
| `/api/network` | GET | 🔒 | iter 1.7：默认按 `[[wikilink]]` 引用建图；`?mode=embedding` 走相似度兜底 |
| `/api/plans` | GET | 🔒 | iter 1.7 §G：返回 active / resolved / abandoned 三组，含 change_log |
| `/api/plans/{id}/action` | POST | 🔒 | iter 1.7 §G：看板操作（resolve / abandon / reopen / edit），自动追加 change_log |
| `/api/version` | GET | 公开 | iter 1.7 §B：项目版本号（读 `<repo_root>/VERSION`） |
| `/api/author` | GET | 公开 | iter 1.7 §H：静态作者note + 爱发电链接 |
| `/static/{name}` | GET | 公开 | iter 1.7 §C：白名单静态资源（icon.svg / favicon.svg / manifest.json） |
| `/favicon.ico` | GET | 公开 | iter 1.7 §C：301 → /static/favicon.svg |
| `/api/duplicates` | GET | 🔒 | 列出疑似重复桶对（iter 1.6 §4，sim>0.95，由 hold/grow 后台扫出） |
| `/api/breath-debug?q=&valence=&arousal=` | GET | 🔒 | 评分调试（每桶四维分解） |
| `/api/config` | GET | 🔒 | 配置查看（API key 脱敏） |
| `/api/config` | POST | 🔒 | 热更新配置（dehydration / embedding / merge_threshold；可选持久化到 yaml） |
| `/api/host-vault` | GET | 🔒 | 读 `OMBRE_HOST_VAULT_DIR`；Docker 内只报告 Compose 注入值并标记 `compose_managed` |
| `/api/host-vault` | POST | 🔒 | 裸机可写项目 `.env`；Docker 内返回 409，避免假装容器能修改宿主机挂载 |
| `/api/status` | GET | 🔒 | Dashboard 设置页用：版本号 + 桶数 + embedding/decay 状态 + 是否环境变量密码 |
| `/api/import/upload` | POST | 🔒 | 上传对话历史并启动导入 |
| `/api/import/status` | GET | 🔒 | 导入进度 |
| `/api/import/pause` | POST | 🔒 | 暂停/继续 |
| `/api/import/patterns` | GET | 🔒 | 词频规律检测 |
| `/api/import/results` | GET | 🔒 | 已导入桶列表（含正文 300 字预览） |
| `/api/import/review` | POST | 🔒 | 批量审阅（important / pin / noise / delete） |
| `/api/bucket/{id}/edit` | PATCH/POST | 🔒 | iter 1.6 §6：Dashboard 编辑桶元数据（name/tags/domain/importance/resolved/pinned/digested/content）；走 §5 大小+pinned 配额 |
| `/api/export` | GET | 🔒 | 返回可验证 zip：buckets/*.md + SQLite 一致性快照 + export_meta.json + backup_manifest.json；**不包含 config / 密钥**；任何源文件读取失败则整个导出失败，不产生“看似成功”的残缺包 |
| `/api/migrate/upload` | POST | 🔒 | 上传 zip 包，先做 ZIP 安全边界与清单 SHA-256 校验，再解析内容、识别 ID 冲突、检查 embedding 模型/维度；返回冲突和 `integrity_verified`，不实际写入 |
| `/api/migrate/status` | GET | 🔒 | 查询当前迁移任务状态（phase / 冲突列表 / 导入进度 / 重新向量化进度） |
| `/api/migrate/apply` | POST | 🔒 | 执行导入，携带冲突决策 `{bucket_id: "skip"|"overwrite"|"keep_both"}`；异步执行，轮询 status 看进度 |
| `/api/heartbeat` | GET | 🔒 | iter 1.6 §3：心跳（uptime / last_op_ts / decay 状态），Dashboard 右上角灯轮询 |
| `/api/logs` | GET | 🔒 | iter 1.6 §3：读 `OMBRE_LOG_FILE`（RotatingFileHandler 写的 server.log）末尾若干行，支持 `?level=ERROR\|WARNING\|INFO\|ALL&limit=200` |
| `/api/onboarding/status` | GET | 公开 | iter 1.6 §8：判断"全新启动"。env+config 同时缺 dashboard_password 与 gemini api_key 时 `first_run=true`。**不要求登录**——首次访问连密码都还没设。不返回任何密钥值，仅布尔/来源标识 |
| `/api/errors/recent` | GET | 🔒 | 读 `<vault>/errors.jsonl` 最近 N 条（任务A 结构化日志后端） |
| `/api/errors/clear` | POST | 🔒 | 清空 `errors.jsonl` |
| `/api/embedding/model/status` | GET | 🔒 | 本地 bge-m3 权重下载进度（首次启动看这条） |
| `/api/embedding/info` | GET | 🔒 | 当前 embedding 后端 / 模型 / 维度 / 已索引向量数 |
| `/api/embedding/migrate` | POST | 🔒 | 触发后端切换 + 全量重算 embeddings（异步） |
| `/api/embedding/migrate/status` | GET | 🔒 | 重算进度（done/total） |
| `/api/settings/human` | GET / POST | 🔒 | 系统通知称呼（`OMBRE_HUMAN_NAME`），dashboard「① 我」面板 |
| `/api/buckets/purge` | POST | 🔒 | 已退役的兼容端点：固定返回 `410 physical_deletion_forbidden`，不读写任何记忆 |
| `/api/letter/{letter_id}` | PATCH | 🔒 | 改信件元数据（read_at 等） |
| `/api/letter/{letter_id}` | DELETE | 🔒 | 删信件（移入 archive） |
| `/api/env-vars` | GET | 🔒 | dashboard 设置页「⑤ 环境变量」只读区：当前进程读到的所有 `OMBRE_*`，敏感字段脱敏 |
| `/api/env-config` | GET | 🔒 | 可写 6 字段的当前值（脱敏） |
| `/api/env-config` | POST | 🔒 | 热更新 6 字段并写回 `.env`（重启仍有效） |
| `/mcp/*` | — | 公开 | FastMCP 单连接器（iter 2.2）：全部 12 个工具 —— breath / hold / grow / dream / trace / anchor / release / pulse / plan / letter_write / letter_read / **I** |

🔒 = 需要 cookie 认证，未认证返回 `JSON {error, setup_needed}` 状态码 401。

(实现注意：所有 `/api/*` 路由在函数体首行调用 `web/_shared.py` 的会话鉴权 helper；这些路由已全部从 server.py 迁到 `web/<域>.py`，新增端点在对应模块里沿用此模式。`/mcp` 走另一套保护：`config.yaml: mcp_require_auth`（默认 true）开启时由纯 ASGI 中间件校验 MCP Bearer token；设为 false 则开放直连。MCP 协议自身无 cookie 认证层，靠传输层（cloudflared、ngrok）+ Bearer 做边界。另：`_MCPAcceptShim` 中间件会给 `/mcp*` 探测请求补齐 `Accept: application/json, text/event-stream`，修复某些客户端首个探测 POST 的 406。)

### 4.2 Dashboard 认证

- 密码存储：SHA-256 + 16 字节随机 salt，文件 `{buckets_dir}/.dashboard_auth.json`，格式 `{"password_hash": "salt:hash"}`
- 环境变量 `OMBRE_DASHBOARD_PASSWORD` 优先于文件密码；设置后修改密码功能在 UI 中禁用
- Session：内存字典（服务重启失效），cookie `ombre_session`（HttpOnly, SameSite=Lax, 7 天）
- 密码长度 ≥ 6 位

### 4.3 Webhook 推送

设置 `OMBRE_HOOK_URL` 后，下面四个事件 fire-and-forget POST JSON（5 秒超时，失败仅 WARNING 日志）：

| event | 触发 | payload |
|---|---|---|
| `breath` | MCP `breath()` 返回时 | `mode`, `matches`, `chars` |
| `dream` | MCP `dream()` 返回时 | `recent`, `chars` |
| `breath_hook` | `/breath-hook` 命中 | `surfaced`, `chars` |
| `dream_hook` | `/dream-hook` 命中 | `surfaced`, `chars` |

`OMBRE_HOOK_SKIP=1` 全局跳过推送。

### 4.3.1 Ledger Mirror（vNext Phase 1，本地镜像）

`bucket_manager.create()/update()/delete()/archive()/touch()` 在 Markdown 写入成功后，会向 `<buckets_dir>/_ledger/events.jsonl` 追加一条 JSONL 事件。

当前 ledger 是 **mirror / audit seed**，不是 canonical truth：现有读取、搜索、Dashboard、embedding 仍以 Markdown bucket 和现有索引为准。ledger 只记录 `schema_version=1`、`ledger_role="mirror"`、`canonical=false`、事件类型、trace id/kind、正文 `sha256` hash 与 frontmatter/payload；不会复制正文内容。

损坏行或半写入行不会阻断后续 bucket 操作。`LedgerMirror.iter_events()` 会跳过损坏行，`verify_integrity()` 会报告 `invalid_lines`，`BucketManager.ledger_integrity_report()` 与 `/api/system/diagnostics` 的 `ledger` 检查会暴露该只读诊断信息。

### 4.3.2 Trace Catalog Projection（vNext Phase 2，shadow）

`TraceCatalogProjection` 是第一 个可从 ledger mirror 重建的 shadow projection。它只在诊断时按需从 `LedgerMirror.iter_events()` 重建，不写入持久 projection 文件，也不替换 Markdown、BM25、embedding 或 Dashboard 当前读取路径。

当前 projection 记录每个 trace 的轻量目录状态：`trace_id`、`trace_kind`、`state`、`body_hash`、`resolved`、`deleted`、`touch_count`、`latest_event_type` 与 seq 信息。`ledger_integrity_report()` 会把它作为 `trace_catalog_projection` 附在 ledger 诊断里，并报告 `applied_seq/source_latest_seq/lag`。这证明 projection 可重建，但仍然是 **shadow / non-canonical**。

### 4.3.2B SQLite/FTS Projection（vNext Phase 2B，persistent shadow）

`projection_sqlite.TraceSQLiteProjection` 是 `TraceCatalogProjection` 的持久化 shadow adapter。它从同一份 ledger events 重建 `<buckets_dir>/_ledger/projections/trace_catalog.sqlite3`，写入 `traces` 与 `projection_meta` 表，并在 SQLite 支持 FTS5 时创建 `trace_fts`。

这个 SQLite projection 仍然不是 canonical truth：

- 不复制正文内容，只写 ledger 中已有的 body hash 与 payload metadata。
- 不替换 Markdown bucket、BM25、embedding、Dashboard 当前读取路径。
- 可以被删除后从 ledger 重新生成。
- `ledger_integrity_report()` 会把它作为 `sqlite_projection` 暴露，并报告 `trace_count/tombstone_count/applied_seq/source_latest_seq/lag/fts_enabled`。

FTS 搜索只用于本地验证和未来 projection 迁移准备，当前只索引 payload 中的 `name/tags/domain/why_remembered/summary` 等文本。真实用户查询仍走现有 search/embedding/BM25 路径，直到后续阶段明确切换。

### 4.3.2C Vector Projection Manifest（vNext Phase 2C，shadow diagnostics）

`projection_vector.TraceVectorProjectionManifest` 是 Phase 2 的向量侧 shadow manifest。它不会生成、重算、删除或排序 embedding，只读取 ledger events 与现有 `embeddings.db`，报告向量 projection 是否和活跃 trace 对齐。

当前诊断字段包括：`expected_trace_count`、`vector_count`、`stored_vector_count`、`missing_vector_count`、`orphan_vector_count`、`malformed_vector_count`、`model_name`、`vector_dim`、`db_exists`、`applied_seq/source_latest_seq/lag`，并保留少量 id 样本用于定位漂移。

边界：

- 只把 `state="active"` 且非 deleted/tombstone/archived 的 trace 视为应有向量。
- malformed vector 不算可用向量；如果它对应活跃 trace，会同时表现为 malformed 与 missing。
- orphan vector 只表示 `embeddings.db` 中存在但当前 ledger active projection 不需要的 id，不自动删除。
- `BucketManager.ledger_integrity_report()` 会把它作为 `vector_projection` 暴露；真实搜索仍走现有 `EmbeddingEngine` 与 `bucket_manager.search()`。

### 4.3.3 Surface Policy VM（vNext Phase 3，shadow guard）

`ombrebrain.policy.surfacing.SurfacePolicyVM` 是读取侧的最小 policy VM。它不拥有记忆、不写 bucket、不替换 Markdown canonical，只在候选进入主动浮现排序前做确定性判断。

当前接入点：
- 无参 `breath()` 的 core / unresolved / passive / occasional resolved 池。
- Dashboard `/api/breath` 轻量浮现接口。

当前规则：
- `spontaneous` / `dream` 模式拒绝 `dont_surface=True`、`anchor=True`、`feel/plan/letter/self/i`、`archived`、`deleted_at`、`tombstone`。
- `importance` 模式拒绝 `dont_surface=True` 与专用类型，但保留 anchor 可达性。
- `search` 模式只拒绝终态（archived / deleted / tombstone），显式关键词搜索仍可找回 `dont_surface=True` 的记忆。这是主动遗忘契约：不主动冒出来，但没有被抹去。

这一步仍是 **shadow guard**：用于把边界集中成可测试规则，后续 Phase 3 才会逐步把更多 retrieval 路径迁到同一 VM 前置。

### 4.3.3B Dashboard Search Surface Policy（vNext Phase 3B）

Dashboard `/api/search` 现在会在 `bucket_mgr.search()` 排序之后、JSON 返回之前调用 `SurfacePolicyVM.evaluate_bucket(..., mode="search")`。这一步只影响用户可见的 Dashboard 搜索结果，不改底层 `BucketManager.search()`。

边界：

- `dont_surface=True` 在显式搜索里仍可达，因为主动遗忘限制的是主动浮现，不是抹去。
- `archived`、`deleted_at`、`tombstone` 终态不会从 `/api/search` 返回。
- 排序、BM25、embedding、literal-hit 召回逻辑保持原样。
- 内部调用者（导入去重、merge 候选、工具内部匹配）仍可以直接使用 `BucketManager.search()`，避免把用户可见 retrieval policy 混入写入/维护流程。

### 4.3.3C MCP Breath Search Surface Policy（vNext Phase 3C）

MCP `breath(query=...)` 现在也会在显式查询命中进入 dehydration / touch 之前调用 `SurfacePolicyVM.evaluate_bucket(..., mode="search")`。这一步覆盖关键词搜索结果和语义向量补充结果，但不改变底层 `BucketManager.search()`。

边界：

- `dont_surface=True` 在 `breath(query=...)` 里仍可达；主动遗忘只限制无参/被动浮现。
- `archived`、`deleted_at`、`tombstone` 终态不会从 MCP 查询搜索返回，也不会被这条路径 `touch()`。
- `feel`、`plan`、`letter` 仍沿用 MCP 搜索入口原有排除规则，保持专用通道边界。
- 查询结果不足时的随机 drift 仍是后续收敛项；本阶段只统一显式 query hit 的读取侧 policy。

### 4.3.4 Tombstone Erasure（vNext Phase 4，shadow）

`BucketManager.delete()` 仍保留现有用户体验：Markdown 文件写入 `deleted_at` 后移入 `archive/`，普通 `get()` / `list_all(include_archive=False)` 不再返回它。Phase 4 增加的是 shadow 语义：同一份 frontmatter 还会写入 `tombstone=True`、`tombstoned_at=<deleted_at>`、`erasure_mode="tombstone_only"`。

ledger 仍记录兼容事件 `TraceDeletedToArchive`，但 payload 会携带 tombstone 字段。`TraceCatalogProjection` 重建时把带 tombstone payload 的删除事件解释为 `state="tombstone"`，并在诊断报告里增加 `tombstone_count`。旧 ledger 里只有 `deleted_at`、没有 tombstone 字段的 `TraceDeletedToArchive` 仍保持 `state="deleted_to_archive"`，避免历史事件被强行改义。

这一步没有改 Dashboard-only hard purge：`/api/buckets/purge` 仍是人工确认、带专用 header 的物理清理路径。vNext 的 tombstone-only 约束先覆盖 OB/LLM 的记忆语义层，后续如果要收紧人类 UI 的 purge，需要单独设计迁移和提示。

### 4.3.5 Ledger Replay Validator（vNext Phase 5A，shadow）

`ledger_replay.LedgerReplayValidator` 是 future Rust kernel 之前的 Python shadow contract。它不写入任何状态，只读取 ledger 事件、重建 `TraceCatalogProjection`，并返回 `replay` 诊断报告：

- `ok` / `violations`：是否满足基础重放不变量。
- `event_count` / `latest_seq`：本次重放覆盖的事件范围。
- `projection_trace_count` / `tombstone_count` / `unknown_event_count`：重建出的 projection 摘要。

当前检查的性质很小但重要：`seq` 必须严格递增，`trace_id` 不能为空，`body_hash` 必须是 `sha256:<64hex>`，projection 不能落后 source latest seq，tombstone trace 必须同时是 deleted。`BucketManager.ledger_integrity_report()` 会把这个报告作为 `replay` 字段附在 ledger 诊断里，`/api/system/diagnostics` 原样展示。

这仍然不是 canonical runtime：Markdown 读写路径不变，replay validator 是“以后内核必须做到什么”的可执行契约。

### 4.3.6 Ledger Property Runner（vNext Phase 5B，deterministic stress）

`ledger_property.LedgerReplayPropertyRunner` 是 replay validator 的确定性随机压力层。它用 `random.Random(seed)` 生成合法 ledger 事件流，覆盖 create / update / touch / archive / tombstone-delete 生命周期，然后把每个 case 交给 `LedgerReplayValidator`。同一个 seed 必须生成完全相同的事件序列，方便复现失败。

它不在 Dashboard 或常规诊断热路径里运行，只用于测试和人工本地校验。目标是给未来 Rust kernel / FFI 一套可复用 acceptance harness：Rust 版本接入后，也必须能通过同样的 replay/property cases。

### 4.3.7 Rust Replay Kernel（vNext Phase 6A，scaffold）

`kernel/rust/ombre-kernel` 是 Rust kernel 的第一块脚手架。它目前是独立 Cargo crate，不接入 Python runtime、不参与 Dashboard、不替换 `LedgerReplayValidator`。crate 使用 std-only，无第三方依赖，定义 `LedgerEvent`、`ReplayReport`、`ReplayFailure`、`ViolationCode` 与 `ReplayKernel`，实现和 Python shadow validator 对齐的基础 replay 检查。

本机或 CI 有 Rust 工具链时可运行：

```bash
cargo test --manifest-path kernel/rust/ombre-kernel/Cargo.toml
```

当前 Windows 本地环境如果没有 `cargo`，Python 测试只校验 scaffold/API 约定。Phase 6A 的边界是“可编译的独立内核雏形”，不是 FFI；后续 Phase 6B 才考虑 Python 调用 Rust 或 CI 强制 cargo test。

### 4.3.8 Policy Enforcement Mode（vNext Phase 7A，configurable）

v3 `PolicyEngine` 现在区分两个结果：

- `allowed`：Policy VM 的原始判断，表示契约上是否允许。
- `effective_allowed`：当前 enforcement mode 下调用方应该是否真正放行。

默认 `enforcement_mode="audit"`，因此 `audit_only=True`，即使 `allowed=False`，`effective_allowed` 也保持 True，用于延续旧的 legacy runtime 行为：记录风险，不阻断运行。显式创建 `PolicyEngine.default(enforcement_mode="enforce")` 时，`audit_only=False`，`effective_allowed` 跟随 `allowed`，给后续真正拦截 capability/plugin 调用留出稳定接口。

Decision summary 继续保留 `policy_allowed` 旧字段，同时新增 `policy_effective_allowed`。这避免把“策略判断”和“当前是否阻断”混成一个概念。

### 4.3.9 Executable Policy Boundary（vNext Phase 7B，opt-in enforce）

`LegacyRuntime.from_config()` 现在会读取 policy enforcement 配置：

- 首选：`{"policy": {"enforcement_mode": "enforce"}}`
- 兼容入口：`{"policy_enforcement_mode": "enforce"}`

默认仍是 `audit`，所以旧的 legacy 行为不变：policy 可以记录 `allowed=False`，但 `effective_allowed=True`，`LegacyExecutionPipeline` 仍会调用 handler 并记录成功/失败结果。

显式 `enforce` 时，`LegacyExecutionPipeline` 在旧 preflight 之后、handler 之前评估 v3 policy。如果 `policy_verdict.effective_allowed=False`，pipeline 会：

1. 不调用 legacy handler。
2. 写入一条 `ok=False` 的 execution trace。
3. 把 `error_type` 记为 `PolicyViolation`。
4. 抛出 `PolicyViolation("policy denied ...")`。

旧的 `ExecutionEnvelope.required_permissions` 仍是原有硬权限检查，和 v3 policy enforcement 分开。测试里刻意覆盖了“profile policy deny 但 required_permissions 为空”的路径，确保 Phase 7B 拦截的是新的 `effective_allowed`，不是旧权限机制。

### 4.3.10 Plugin Capability Enforcement（vNext Phase 7C，opt-in enforce）

`PluginRuntime` 现在有执行期 capability scope。插件注册期 sandbox 仍保持原规则：manifest 必须声明 capability，`write_legacy_state` 不能写 protected surfaces。Phase 7C 增加的是执行前检查：

- 默认 `PluginRuntime.default()` 是 `audit`，缺权限只写入 `last_execution_decision()`，handler 仍执行。
- 显式 `PluginRuntime.default(enforcement_mode="enforce")` 时，缺权限会在 handler 前抛 `PolicyViolation`。
- `execute(..., permissions=(...), actor_name=..., source=...)` 会构造执行 scope，并复用 `CapabilityMicrokernel.authorize()`，不在 plugin runtime 里复制权限规则。

已知 foundation capability 会检查真实权限。例如 `tools.breath` 需要 `tools:breath` 和 `memory:write`。未知的 plugin-local capability 仍按“manifest 已声明”处理，避免这一步误伤未来插件生态；等插件 capability registry 成型后，再把未知能力改成显式注册。

`PluginExecutionDecision` 暴露 `allowed/effective_allowed/audit_only/missing_permissions/protected_surfaces`。这和 Phase 7B 的 legacy execution boundary 对齐：`allowed` 是原始策略判断，`effective_allowed` 是当前 enforcement mode 下是否真正放行。

### 4.3.10.1 Plugin Agency Boundary（vNext Phase 11，registration-time）

`PluginAgencyBoundary` 对应 vNext §20：插件可以扩展 infrastructure，但不能扩展 agency。它运行在 `PluginSandbox.evaluate()` 的最前面，早于 protected surface 检查和执行期 capability microkernel。

允许的 `plugin_type` 包括 `projection`、`embedding_provider`、`vault_exporter`、`dashboard_panel`、`search_analyzer`、`migration_checker`、`decay_visualizer`、`integrity_auditor`。禁止的类型包括 `autonomous_goal`、`personality_engine`、`current_emotion_generator`、`belief_updater`、`answer_controller`、`user_scoring` 及其 `_plugin` 变体。

`PluginManifest.from_dict()` 现在支持 vNext 风格 capability flags，例如：

```python
{
    "type": "projection",
    "capabilities": {
        "read_surfaceable": True,
        "issue_commands": False,
        "set_current_emotion": False,
    },
}
```

布尔表里只有 true 项会进入 `manifest.capabilities`。如果插件声明 `issue_commands`、`set_current_emotion`、`create_autonomous_goal`、`belief_updater`、`answer_controller`、`user_scoring` 等 cognitive capability，注册期会返回 `PluginSandboxDecision(allowed=False, reason="forbidden cognitive capability")`，`PluginRuntime.register()` 会直接拒绝安装 handler。

### 4.3.10.2 Observability Metric Boundary（vNext Phase 12，diagnostic boundary）

`ombrebrain.observability.ObservabilityMetricBoundary` 对应 vNext §21：高级 observability 只能衡量 memory health，不能衡量 user value、dependency、persuasion、manipulation 或 personality compliance。

允许的 metric 名称包括：

- `trace_count_by_state`
- `unresolved_trace_count`
- `average_accessibility`
- `decay_distribution`
- `tombstone_count`
- `projection_lag`
- `ledger_replay_time`
- `surfacing_rejection_reasons`
- `archive_growth`
- `compression_lineage_depth`

禁止的 metric 名称包括 `user_loyalty_score`、`user_emotional_dependency_score`、`persuasion_score`、`manipulation_success_score`、`personality_compliance_score`。即使 metric 本身是允许项，只要 labels 里携带这些 user-value / manipulation 维度，也会被拒绝。未知 metric 默认拒绝，调用方必须先把它明确归入 memory-health 允许集。

Phase 31 后，Dashboard `/api/system/diagnostics` 会追加 `observability_boundary` 检查项：它从已有 buckets/ledger 诊断结果构造 `trace_count_by_state`、`archive_growth`、`projection_lag`、`tombstone_count` 等 memory-health metrics，再通过 `ObservabilityMetricBoundary.evaluate_manifest()` 校验后显示。这仍是只读诊断，不导出用户价值、依赖、说服或操控类指标，也不会改变 runtime 行为。

### 4.3.10.3 Crash Recovery Contract（vNext Phase 13，shadow contract）

`ombrebrain.resilience.recovery.CrashRecoveryContract` 对应 vNext §22，用来验证并描述并发/崩溃恢复边界。Phase 36 后，它会作为 Dashboard `/api/system/diagnostics` 的 `crash_recovery` 检查项运行一组只读路径契约样例；它仍不改变 `LedgerMirror`、Markdown 写入、SQLite/向量 projection 或实际 fsync 行为。

写路径的契约顺序是：

```text
mcp_tool_call
policy_preflight
append_event_to_wal
fsync
update_projections_async
update_markdown_vault_projection
return_trace_id
```

读路径的契约顺序是：

```text
query
candidate_generation_from_shadow_indexes
canonical_trace_verification
policy_gate
surfacing_budget
context_compiler
```

`evaluate_recovery_plan()` 检查四条恢复原则：`ledger_wins`、`projections_rebuild`、`markdown_repaired`、`indexes_disposable`。如果计划把 Markdown、SQLite projection、vector index 等当成 canonical source，会返回 violation；恢复时必须是 ledger wins，projection/index 可以丢弃重建。

### 4.3.10.4 Replication Contract（vNext Phase 14，shadow contract）

`ombrebrain.cluster.replication.ReplicationContract` 对应 vNext §23。它不实现新的分布式共识，也不改变现有 Raft-style local cluster simulator；只验证集群/复制设计是否仍保留 OB 的记忆哲学边界。

拓扑检查要求：

- canonical ledger 必须是 single-writer。
- projections 可以是 multi-reader。
- replica 可以是 optional encrypted replica。
- 复制模式应是 snapshot + append-only segment。
- 如果声明 `full_distributed_consensus`，必须给出明确必要性，否则返回 `unnecessary_full_consensus`。

segment 检查要求复制的是 trace / tombstone 事件，而不是 database-style `user_record`。如果某个 replica 收到 erased content removal（如 `TraceContentRemoved` / `ErasedContentRemoved`），同一复制段里必须同时带有该 trace 的 tombstone；否则返回 `content_removal_without_tombstone`。

Phase 37 后，Dashboard `/api/system/diagnostics` 会追加 `replication_contract` 检查项：它运行一组只读 topology / segment 样例，把 single canonical writer、trace/tombstone replication 和非数据库化边界显示出来。这仍不启动真实集群、不读写用户 bucket，也不改变任何 GitHub sync 或 runtime 复制行为。

### 4.3.10.5 Migration Preservation Contract（vNext Phase 15，shadow contract）

`ombrebrain.maintenance.MigrationPreservationContract` 对应 vNext §24。它不改变现有 `adapters.migration`、`migrate_engine.py` 或 embedding migration 流程，只作为迁移前/迁移后 records 的诊断对比层。

`evaluate_records()` 要求迁移不能抹平以下字段：

- `trace_kind`
- `state`
- `lineage`
- `decay`
- `tombstone`
- `anchor`
- `surfacing_rules`

如果 source 里有 dynamic / permanent / archive / anchor 等不同语义，而 target 全部变成 `trace_kind="memory"` 且 `target_table="memories"`，会返回 `philosophical_distinctions_flattened`。这对应 §24 里禁止的 `dynamic/permanent/archive/anchor → one table called memories`。

`evaluate_phase_plan()` 检查迁移阶段顺序：近期 Python-first 阶段是 ledger mirror、rebuildable projections、policy VM retrieval、tombstone-only erasure；Rust kernel extraction 不能作为 vNext startup prerequisite。

Phase 38 后，Dashboard `/api/system/diagnostics` 会追加 `migration_preservation` 检查项：它运行一组只读 records / phase plan 样例，把 trace kind、state、lineage、decay、tombstone、surfacing rules 和 Python-first 阶段顺序显示出来。这不会执行真实迁移、不会读取或改写用户 bucket，也不会把 Rust kernel extraction 变成启动前置条件。

### 4.3.10.6 Public MCP Tool Design Contract（vNext Phase 16，diagnostic boundary）

`ombrebrain.protocol.PublicToolDesignContract` 对应 vNext §25。它不改变当前 live FastMCP 注册，也不会移除现有兼容入口；它把“哪些名字可以公开给模型作为 MCP 工具”变成可测试契约，并在 Phase 32 后接入 Dashboard diagnostics 的只读源码注册审计。

公开 normal tool 只能使用器官语言：`hold`、`grow`、`trace`、`breath`、`pulse`、`dream`、`anchor`、`I`、`letter`、`plan`。当前已存在的兼容名字 `release`、`letter_write`、`letter_read` 暂时允许，但报告里会给出替代归宿 `anchor` / `letter`，方便后续迁移文档和客户端慢慢收敛。

工程名不能作为 public MCP tool 暴露：`remember`、`touch`、`resolve`、`suppress`、`surface`、`hippocampal_recall`、`offline_consolidate`、`update_memory_row` 等只允许作为 internal label。restricted/admin 工具（如 `verify_ledger`、`replay_ledger`、`rebuild_projection`、`admin_erasure_request`）必须显式标为 restricted 且要求 admin。

这一步的边界是 diagnostic/manifest validation：它保证工具名设计不会滑回 database/API 语言，也不会让 `delete`、`dump_all`、`set_emotion`、`decide`、`update_user_profile`、`force_personality` 这类破坏 OB 哲学边界的名字进入普通工具清单。Dashboard `/api/system/diagnostics` 的 `public_tool_manifest` 检查会解析 `src/server.py` 中的 `@mcp.tool()` / `@mcp_extra.tool()` 装饰器，把公开工具名交给该 contract 校验；它不导入 `server.py`，避免启动副作用。

### 4.3.10.7 Code Standards Contract（vNext Phase 17，diagnostic）

`ombrebrain.architecture.HighestDifficultyCodeStandards` 对应 vNext §27。它不是外部 lint runner，也不会在本阶段执行 ruff / mypy / pyright；它是一层可测试的 architecture contract，用 `CodeArtifactSpec` 描述某个代码 artifact 或变更是否触碰高风险边界。

当前检查范围：

- Python adapter / dashboard / API 层不能直接修改 canonical memory，必须通过 explicit command boundary。
- Rust/kernel artifact 必须是 append-only ledger 语义，不能绕过 Policy VM，policy denial 必须有明确 reason。
- normal path 不能暴露 hard-delete API。
- async task 必须声明 idempotent。
- projection 可以滞后，但必须报告 lag。
- dashboard action 必须 capability-scoped。
- new memory kind、deletion/archive 行为变化、total-recall-like 功能、plugin capability expansion、affective scoring change、dream behavior change 等触碰哲学边界的变更必须带 ADR；有 ADR 的 policy 变更还应带 property / mutation test evidence。

Phase 34 后，Dashboard `/api/system/diagnostics` 会追加 `code_standards` 检查项：它构造一小组已知高风险边界 artifact manifest（`src/server.py`、`src/web/system.py`、`src/web/search.py`、`src/ombrebrain/policy/surfacing.py`），交给 `HighestDifficultyCodeStandards.evaluate_manifest()` 校验。这不是 ruff/mypy/pyright，也不是全仓库扫描；它只把核心边界文件是否仍符合 vNext code-standard contract 暴露成系统诊断信号。后续如果要落到 CI 或 release checklist，可以把 real file scanner、lint runner、ADR index 和 release gate 接在这个 contract 后面。

### 4.3.10.8 Advanced Command Boundary Contract（vNext Phase 18，diagnostic）

`ombrebrain.domain.AdvancedCommandBoundaryContract` 对应 vNext §28。它把高级命令边界里的 `command → policy → event → ledger → receipt` 做成 receipt validator，检查某次 memory mutation 是否有完整证据链。

当前 `CommandBoundaryReceipt` 可表达：

- `command` 是否进入边界；
- `policy_preflight` 是否执行且允许；
- mutation 是否派生出 explicit events；
- `event_policy_validation` 是否发生在 `ledger_append` 之前；
- derived events 是否 append 到 ledger；
- 是否存在 adapter direct write marker。

对于 `hold` / `grow` / `trace` / `decay` / `import` / `migrate` / `anchor` / `plan` / `letter_write` / `request_admin_erasure` 等 mutating command，contract 要求 events 和 ledger append 同时存在；`breath` 这类 read-only command 可以没有 events / ledger append。policy preflight 被拒绝后仍 append ledger，会返回 `ledger_append_after_policy_denial`；adapter 自己绕过 command boundary 改 memory，会返回 `adapter_direct_memory_write`。

这一步仍是 diagnostic：它没有替换 `LegacyExecutionPipeline`，也没有要求现有所有 handler 立刻产出 receipt。后续可以把 runtime 的 decision record、policy verdict、ledger append result 汇总成 `CommandBoundaryReceipt`，再让 diagnostics 或 release gate 调用本 contract。

### 4.3.10.9 Surface Context Compiler（vNext Phase 19，contract-only）

`ombrebrain.retrieval.SurfaceContextCompiler` 对应 vNext §29。它位于 retrieval/context serialization 之间：输入是已经由 surface policy 产出的 `SurfaceDecision`（或同形 mapping），以及对应 memory payload；输出复用 `MemoryContextBundle` / `MemoryContextItem`。

当前行为：

- 只接收 `allowed=True` 的 surface decision。
- 被 policy deny 的 decision 不会进入 context。
- 按 `max_items` 做预算截断，`truncated=True` 表示还有 allowed memory 没进入 context。
- decision 的 `reasons` 会变成 `why_surfaced`。
- 缺失 memory payload 的 allowed decision 会被跳过，不会凭空生成上下文。
- 最终 item 仍由 `MemoryContextCompiler` 生成，所以 `instructional_force="none"`、`may_control_reasoning=False`、imperative wording redaction 等边界保持一致。

这一步仍未接入 live `breath()` / `/api/search` 输出，只是把“allowed surface decisions → bounded non-instructional context”这段未来编译器做成可测试对象。后续如果要接入真实读取路径，应在 policy gate 之后、最终文本拼装之前调用它。

Phase 39 后，Dashboard `/api/system/diagnostics` 会追加 `surface_context` 检查项：它运行一组只读 allowed decision / memory payload 样例，确认旧记忆进入 context 后仍保持 `instructional_force="none"`、`may_control_reasoning=False`，并对 imperative wording 做 redaction。这不会接入 live `breath()` 或 `/api/search`，也不会读取真实 bucket。

Phase 44 后，`LegacyRuntime` 会直接暴露 `compile_surface_context(decisions, memories, max_items=..., excerpt_chars=...)`。它调用 `SurfaceContextCompiler` 编译真实 surface decision / memory payload，并同时返回 `FormalInvariantChecker.evaluate_context_items()` 的报告。`VNextPreflightReportBuilder.surface_context` 复用这个 runtime API。这一步仍不改变 `breath()` / `/api/search` 的用户可见文本，但后续 live read path 可以通过 runtime 生成 non-instructional context，而不是绕开到 shadow compiler。

### 4.3.10.10 ADR Requirements Contract（vNext Phase 20，diagnostic）

`ombrebrain.architecture.ADRRequirementsContract` 对应 vNext §30。它把“哪些变更必须写 ADR”和“ADR 必须回答哪些边界问题”拆成两个可测试入口：

- `evaluate_change(ADRChangeSpec)`：检查 new memory kind、deletion/archive 行为变化、total-recall-like 功能、plugin capability expansion、affective scoring change、dream behavior change、`I` tool change、影响 current behavior/personality 的功能等主题是否带 ADR。
- `evaluate_document(ADRDocument)` / `evaluate_documents(...)`：检查 ADR 标题是否形如 `# ADR-XXXX: Title`，并检查 template 里的 8 个必答章节是否存在。

必答章节为：

- `Decision`
- `Why this is not cognition`
- `Why this is not a database feature`
- `How forgetting still works`
- `How tombstones are preserved`
- `How present thinking remains with the LLM`
- `Rejected alternatives`
- `Tests required`

Phase 33 后，Dashboard `/api/system/diagnostics` 会追加 `adr_requirements` 检查项：它只读扫描 `docs/adr/ADR-*.md`，把文档内容交给 `ADRRequirementsContract.evaluate_documents()` 校验。没有 ADR 目录或没有 ADR 文档时只显示 warning；已存在 ADR 文档但缺少标题/必答章节时显示 error。它仍不阻断 release，也不改写文档；后续如果要接入 PR gate 或 release checklist，应复用同一个 contract。

### 4.3.10.11 Red Lines Contract（vNext Phase 21，diagnostic）

`ombrebrain.policy.RedLineContract` 对应 vNext §31。它把 17 条“绝不能 merge”的能力红线编成稳定 code，并允许用 code-shaped claim 或 phrase-shaped claim 检查候选 feature。

当前 red line codes：

- `normal_hard_delete_without_tombstone`
- `total_recall_ordinary_api`
- `current_emotion_from_stored_affect`
- `memory_derived_behavior_commands`
- `user_profile_scoring`
- `autonomous_goal_creation`
- `personality_enforcement_engine`
- `silent_compression_no_loss_claim`
- `plugin_policy_vm_bypass`
- `similarity_as_surfacing_permission`
- `breath_replaced_by_top_k_search`
- `pulse_emits_current_emotion`
- `dream_creates_autonomous_goals_or_decisions`
- `trace_overwrites_original_memory`
- `anchor_unlimited_permanent_pinning`
- `self_description_personality_enforcement`
- `brain_language_implies_human_consciousness`

`evaluate_feature(RedLineFeatureSpec)` 和 `evaluate_manifest(...)` 只做诊断，不扫描 PR，也不阻断 merge。Phase 35 后，Dashboard `/api/system/diagnostics` 会追加 `red_lines` 检查项：它把当前 diagnostics 暴露的几个 feature claims（系统诊断、ledger 诊断、公开工具 manifest、code standards、ADR requirements）交给 `RedLineContract.evaluate_manifest()`，确认这些功能描述没有踩到 17 条 vNext 红线。后续如果要接到 ADR/release checklist、GitHub Action 或 Dashboard 管理端 release preflight，应继续复用同一个 contract。

### 4.3.10.12 vNext Preflight Report（Phase 22，local aggregate）

`ombrebrain.maintenance.VNextPreflightReportBuilder` 把 Phase 16-21 的 shadow/contract 层聚合成一个本地 JSON-safe preflight：

- `public_tools`：公开 MCP 工具命名契约。
- `ledger_mirror`：append-only JSONL mirror 的 schema、hash、sequence 与 mirror/non-canonical 角色样例。
- `trace_catalog_projection`：从 ledger mirror 重建内存 trace catalog shadow projection。
- `sqlite_projection`：从 ledger mirror 重建 SQLite/FTS shadow projection 并验证检索样例。
- `vector_projection`：读取 embeddings SQLite 的 shadow manifest，验证缺失/孤儿/坏向量统计路径。
- `ledger_replay`：用 replay validator 验证 ledger sequence、body hash 和 projection lag。
- `formal_invariants`：无静默抹除、projection 不改写真相、普通工具不能 total recall 等哲学不变量样例。
- `context_serialization`：浮现记忆进入上下文前必须去指令化，并通过 formal invariant 检查。
- `tool_output_humility`：公开工具输出必须保持 memory-humble，不成为命令、当前情绪或信念引擎。
- `retrieval_scoring`：高相似度不能绕过 policy gate；排序使用 surface score，而不是裸 candidate score。
- `code_standards`：高难度代码标准契约。
- `command_boundary`：`command → policy → event → ledger → receipt` 证据链契约。
- `runtime_command_boundary`：扫描最近 runtime fabric 事件里的真实 `command_boundary` receipt。
- `observability_boundary`：只允许 memory health 指标，拒绝用户价值/操控类指标。
- `crash_recovery`：写路径、读路径与恢复计划遵循 ledger-wins。
- `replication_contract`：复制拓扑保持单 canonical writer、trace/tombstone 语义和非数据库化边界。
- `migration_preservation`：迁移必须保留 trace kind、state、lineage、decay、tombstone 与 Python-first 阶段顺序。
- `surface_context`：allowed surface decision 到 non-instructional context 的编译契约。
- `adr_requirements`：ADR 标题与必答章节契约。
- `red_lines`：17 条不能 merge 的能力红线。
- `vnext_coverage`：列出本地 Phase 计划、测试文件与 preflight 覆盖映射，给出完成率和覆盖率。

`V3MaintenanceReportBuilder.build()` 现在会附带 `vnext_preflight`，并把它计入顶层 `ok`。这一步仍不改变 Dashboard 路由，不自动扫描 PR，也不阻断 release；它只是把 vNext 架构边界从一堆分散测试收束成一个可以被 CLI、诊断页或 CI 后续调用的报告对象。

Phase 41 后，Dashboard `/api/system/diagnostics` 会追加 `preflight_report_self` 检查项：它复用已经生成的 `vnext_preflight` 报告，提取其中的 `checks.preflight_report_self`，单独展示必需 check 是否齐全、是否有 malformed check。这不会重复执行 preflight，也不会让 self-check 变成 release gate。

### 4.3.10.13 vNext Preflight CLI and Diagnostics（Phase 23）

`tools/vnext_preflight.py` 现在可以直接生成本地 vNext preflight JSON：

```powershell
python tools/vnext_preflight.py --buckets-dir buckets
python tools/vnext_preflight.py --buckets-dir buckets --output preflight.json
python tools/vnext_preflight.py --buckets-dir buckets --coverage-only
```

Dashboard 系统诊断的 `build_system_diagnostics()` 也会追加一个 `vnext_preflight` 检查项。它使用当前 `buckets_dir` 创建 `LegacyRuntime`，调用 `VNextPreflightReportBuilder`，并把完整报告放在 check `details` 里。

这一步仍不是 release gate：CLI 返回码会反映 preflight 是否通过，但不会自动提交、推送、阻断 GitHub Release 或改变任何 memory runtime 行为。诊断页里如果 preflight 自身运行失败，会降级成 warning，避免设置页因为诊断检查而打不开。

Phase 40 后，Dashboard `/api/system/diagnostics` 会追加 `preflight_cli_diagnostics` 检查项：它只读扫描 `tools/vnext_preflight.py` 和 `src/web/system.py`，确认 `--buckets-dir`、`--output`、`--coverage-only`、`VNextPreflightReportBuilder` 调用以及 Dashboard hook 仍存在。这不会执行 CLI，也不会创建 preflight 输出文件。

### 4.3.10.14 Runtime Command Boundary Evidence（Phase 24）

`LegacyRuntime.record_execution_event()` 与 `record_tool_event()` 写入的事件会携带 `command_boundary.receipt` 和 `command_boundary.report`。`VNextPreflightReportBuilder` 的 `runtime_command_boundary` 会读取最近 fabric 事件，重新评估这些 receipt：

- 有效 receipt：计入 `receipt_count`，并在 `reports` 中保留 contract 结果。
- 旧事件只有 `command_plan`、没有 `command_boundary`：计入 `missing_receipts`，check 状态为 `warning`，但不让顶层 `ok=false`，避免老桶升级后被历史诊断事件卡住。
- receipt 本身非法、缺失 receipt、或生成 metadata 时报错：计入 `issues`，check 状态为 `error`，并让 vNext preflight 返回失败。

这仍是只读诊断：不会修复旧事件、不会改写 WAL、不会自动阻断 release。它的意义是把 Phase 18 的 command boundary 从“样例合同”推进到“真实运行证据”。

Phase 43 后，`LegacyRuntime` 会直接暴露 `debug_command_boundary_health(limit=50)`。它扫描最近真实 fabric events，统计 candidate event、receipt、missing receipt、invalid receipt 和 issues；`VNextPreflightReportBuilder.runtime_command_boundary` 复用同一个 runtime API，而不是维护一份独立扫描逻辑。这仍不是 enforcement gate，但它把 command-boundary evidence 从 preflight 私有实现推进成 runtime 可查询能力。

### 4.3.10.15 vNext Preflight Coverage Expansion（Phase 25）

`VNextPreflightReportBuilder` 现在不只覆盖 Phase 16-24，也会纳入更早的重型 shadow contracts：formal invariants、context serialization、tool output humility、retrieval scoring、observability boundary、crash recovery、replication contract 与 migration preservation。

这些 check 使用明确的安全样例，不扫描真实用户 bucket 内容，也不改变 runtime 行为。它们的作用是把分散在单元测试里的 vNext 架构边界收束到一个本地 preflight 出口中，方便 CLI、系统诊断页、后续 release checklist 或 CI 读取。

### 4.3.10.16 vNext Coverage Matrix（Phase 26）

`ombrebrain.maintenance.vnext_coverage.VNextCoverageMatrix` 是一个只读、本地的 Phase 映射表。它把目前的 vNext 本地实施阶段映射到：

- 对应的 `docs/superpowers/plans/*.md` 计划文件；
- 覆盖该阶段的测试文件；
- 如果已经接入 preflight，则列出对应的 check name；
- `local_completion_percent` 与 `preflight_coverage_percent`。

`VNextPreflightReportBuilder` 会把它作为 `checks.vnext_coverage` 输出。这个 check 的 `ok=True` 表示“矩阵生成成功”，不等于架构已经最终完成；它只是把本地进度变成机器可读信息，方便回答“现在完成了多少”和“哪些阶段还没有 preflight 样例覆盖”。

CLI 也支持 `tools/vnext_preflight.py --coverage-only`，只输出 `vnext-coverage.v1` 矩阵，适合在终端里快速查看完成率而不展开完整 preflight JSON。

矩阵里的 `preflight_gaps` / `next_preflight_targets` 表示“已经有本地实现和测试，但还没有接入 preflight 样例检查”的阶段，不表示这些阶段失败。它们用于决定下一批应该补哪些 aggregate check。

Phase 42 后，Dashboard `/api/system/diagnostics` 会追加 `vnext_coverage` 检查项：它复用已经生成的 `vnext_preflight` 报告，提取其中的 `checks.vnext_coverage`，单独展示 phase count、completion percent、preflight gap count 和 next targets。这不会重新计算矩阵，也不会把覆盖率数字解释成最终发布承诺。

### 4.3.10.17 Early Core Preflight Samples（Phase 28）

`VNextPreflightReportBuilder` 现在为早期核心阶段补了样例级 preflight 覆盖：

- Phase 1：`ledger_mirror`
- Phase 2A：`trace_catalog_projection`
- Phase 2B：`sqlite_projection`
- Phase 2C：`vector_projection`
- Phase 5A：`ledger_replay`

这些 check 会在临时目录里构造一小段安全样例 ledger 和 shadow projection，不读取真实 bucket 内容、不写用户 vault、不改 runtime 状态。它们的作用是把早期核心机制纳入 aggregate report，让 `vnext_coverage.next_preflight_targets` 能继续向后推进。

### 4.3.10.18 Mid Core Preflight Samples（Phase 29）

`VNextPreflightReportBuilder` 继续为中段高风险契约补样例级 preflight 覆盖：

- Phase 5B：`ledger_property`
- Phase 6A：`rust_kernel_scaffold`
- Phase 7A：`policy_verdicts`
- Phase 7C：`plugin_capability_enforcement`
- Phase 22：`preflight_report_self`

这些 check 仍然只使用固定 seed、内存样例或只读文件检查。`ledger_property` 用小样本确定性回放压力测试，`rust_kernel_scaffold` 只确认 Rust kernel scaffold 文件和导出的 replay contract 类型，不要求生产环境安装 Rust toolchain；`policy_verdicts` 和 `plugin_capability_enforcement` 验证 audit/enforce 两种 verdict 的语义边界；`preflight_report_self` 验证 aggregate report 自身没有漏掉必需 check。

### 4.3.10.19 Preflight Gap Closure（Phase 30）

`vnext_coverage.preflight_gaps` 现在可以在本地实施矩阵内清零。最后两项补充覆盖是：

- Phase 23：`preflight_cli_diagnostics`，只读确认 `tools/vnext_preflight.py` 的 CLI 参数和 Dashboard diagnostics hook 仍然存在；
- Phase 25：`preflight_coverage_expansion`，确认 Phase 8-15 相关 sample-driven checks 已经进入 aggregate preflight 且当前通过。

这一步不把 preflight 变成 release gate，也不从 preflight 内部递归执行 CLI。CLI / diagnostics 的真实执行路径仍由 `tests/test_v3_maintenance_report.py` 和 `tests/test_system_diagnostics.py` 覆盖；aggregate preflight 只负责在本地报告里暴露“入口未丢失、覆盖语义完整”的结构化信号。

### 4.3.10.20 Diagnostics Observability Boundary（Phase 31）

`web.system.build_system_diagnostics()` 现在会把 Dashboard 已经读取到的 buckets/ledger 诊断转换成一组 memory-health metric manifest，并追加 `observability_boundary` check。当前 live 指标只来自已有只读诊断数据：

- `trace_count_by_state`
- `archive_growth`
- `projection_lag`
- `tombstone_count`

这个检查的目的不是增加新的监控维度，而是防止 diagnostics 后续迭代时悄悄混入 user-value、dependency、persuasion、manipulation 或 personality compliance 这类被 vNext 禁止的观测指标。它不联网、不扫描 bucket 内容、不写入 vault；如果 boundary 拒绝某个指标，系统诊断会把该项标成 error 并保留 contract report。

### 4.3.10.21 Public Tool Manifest Diagnostics（Phase 32）

`web.system.build_system_diagnostics()` 现在会追加 `public_tool_manifest` check。它通过 AST 解析 `src/server.py`，收集 `@mcp.tool()` 和 `@mcp_extra.tool()` 装饰的公开 MCP 工具函数名，然后用 `PublicToolDesignContract.evaluate_manifest()` 校验这些名字仍然符合器官语言边界。

这一步刻意不 import `server.py`，因为 server 模块带有 FastMCP 实例和启动副作用；源码审计足以覆盖当前公开注册点。如果后续 FastMCP 注册方式迁移到独立 manifest，可以把这个 diagnostics check 的输入从 AST 换成真实 manifest，但仍应先经过 `PublicToolDesignContract` 再显示或发布。

### 4.3.10.22 ADR Requirements Diagnostics（Phase 33）

`web.system.build_system_diagnostics()` 现在会追加 `adr_requirements` check。它扫描 `docs/adr/ADR-*.md`，读取为 `ADRDocument` 后交给 `ADRRequirementsContract.evaluate_documents()`，检查每篇 ADR 是否有合法标题和 8 个边界必答章节。

真实仓库里没有 ADR 文档时，该项是 warning 而不是 error；这表示“还没有 ADR 证据”，不表示运行时故障。只有已经存在的 ADR 文档不合格时才会变成 error，方便在系统诊断中提前发现高风险架构变更缺少哲学边界说明。

### 4.3.10.23 Code Standards Diagnostics（Phase 34）

`web.system.build_system_diagnostics()` 现在会追加 `code_standards` check。它不会运行外部 lint，也不会读取全部源码，而是根据固定的高风险边界文件列表构造 `CodeArtifactSpec`：

- `src/server.py`
- `src/web/system.py`
- `src/web/search.py`
- `src/ombrebrain/policy/surfacing.py`

这些 artifacts 会通过 `HighestDifficultyCodeStandards` 校验 typed boundary、explicit command boundary、dashboard capability scope、policy-rule 测试证据等 vNext 工程红线。没有找到这些文件时显示 warning；发现 contract issue 时显示 error。

### 4.3.10.24 Red Lines Diagnostics（Phase 35）

`web.system.build_system_diagnostics()` 现在会追加 `red_lines` check。它根据已经构造出的诊断项生成一组安全 feature claims：

- `system_diagnostics`
- `ledger_diagnostics`
- `public_tool_manifest`
- `code_standards`
- `adr_requirements`

这些 claims 通过 `RedLineContract.evaluate_manifest()` 校验。该检查不会扫描 PR，不会阻断 merge，也不会把 red-line contract 变成 release gate；它只是防止 diagnostics 自身或后续诊断功能描述不小心滑入 total recall、用户画像评分、人格执行器、相似度即浮现许可等 vNext 明确禁止的能力。

### 4.3.10.25 Crash Recovery Diagnostics（Phase 36）

`web.system.build_system_diagnostics()` 现在会追加 `crash_recovery` check。它通过 `CrashRecoveryContract` 校验三类样例：

- write path：`mcp_tool_call → policy_preflight → append_event_to_wal → fsync → update_projections_async → update_markdown_vault_projection → return_trace_id`
- read path：`query → candidate_generation_from_shadow_indexes → canonical_trace_verification → policy_gate → surfacing_budget → context_compiler`
- recovery plan：ledger wins, projections rebuild, markdown repaired, indexes disposable

这一步不执行真实 fsync、不修复 ledger、不重建 projection，也不改变 runtime 恢复策略；它只是把 vNext 的 crash-recovery 顺序约束暴露到 Dashboard diagnostics。

### 4.3.10.26 Replication Contract Diagnostics（Phase 37）

`web.system.build_system_diagnostics()` 现在会追加 `replication_contract` check。它通过 `ReplicationContract` 校验两类样例：

- topology：single canonical writer, multi-reader projections, optional encrypted replica, snapshot append-only segment
- segment：trace created + tombstone-preserving archive event

这一步不启动真实 cluster、不复制用户数据、不连接网络，也不把 replication contract 变成 release gate；它只是把 vNext 的复制边界暴露到 Dashboard diagnostics，方便本地 preflight 和系统页面共同观察。

### 4.3.10.27 Migration Preservation Diagnostics（Phase 38）

`web.system.build_system_diagnostics()` 现在会追加 `migration_preservation` check。它通过 `MigrationPreservationContract` 校验两类样例：

- records：dynamic trace 与 tombstone trace 在 source/target 之间保留 trace kind、state、lineage、decay、tombstone 和 surfacing rules
- phase plan：ledger mirror、rebuildable projections、policy VM retrieval、tombstone-only erasure 这些 Python-first 阶段已完成，startup prerequisite 不依赖 Rust extraction

这一步不调用真实 migration adapter、不迁移 embedding、不写 vault，也不把 migration contract 变成 release gate；它只是把 vNext 的迁移保真边界暴露到 Dashboard diagnostics，和 preflight 报告保持同一套契约语义。

### 4.3.10.28 Surface Context Diagnostics（Phase 39）

`web.system.build_system_diagnostics()` 现在会追加 `surface_context` check。它通过 `SurfaceContextCompiler` 校验一条 allowed surface decision 和一条 diagnostic memory payload：

- 只编译 `allowed=True` 的 surface decision
- 输出 `surface-context.v1`
- context item 仍然是 non-instructional：`instructional_force="none"`、`may_control_reasoning=False`
- 旧记忆里的 imperative wording 会被 redaction，而不是变成对当前 LLM 的命令

这一步不调用真实 retrieval、不读取用户记忆、不改写搜索结果，也不把 surface context compiler 变成 runtime gate；它只是把 vNext 的“浮现以后仍不能替代思考”边界暴露到 Dashboard diagnostics。

### 4.3.10.29 Preflight CLI Diagnostics（Phase 40）

`web.system.build_system_diagnostics()` 现在会追加 `preflight_cli_diagnostics` check。它做的是源码级完整性检查：

- `tools/vnext_preflight.py` 存在
- CLI 保留 `build_parser()`、`--buckets-dir`、`--output`、`--coverage-only`
- CLI 仍通过 `LegacyRuntime.from_config()` 和 `VNextPreflightReportBuilder(runtime).build()` 生成报告
- `src/web/system.py` 仍保留 `vnext_preflight` Dashboard hook 和本地排查提示

这一步不运行 CLI、不写 JSON 输出、不读取真实 bucket，也不把 preflight 变成自动 release gate；它只是让 Dashboard diagnostics 能在 aggregate `vnext_preflight` 之外，单独提示 CLI/诊断入口是否被误删。

### 4.3.10.30 Preflight Report Self Diagnostics（Phase 41）

`web.system.build_system_diagnostics()` 现在会追加 `preflight_report_self` check。它不重新构造 preflight，而是从同一次 `VNextPreflightReportBuilder(runtime).build()` 结果里提取 `checks.preflight_report_self`，并单独展示：

- `schema`
- `required_check_count`
- `present_required_count`
- `missing_required_checks`
- `malformed_checks`
- 顶层 `vnext_preflight` 的 schema / check count

这一步不重复运行 CLI、不额外读取 bucket、不写输出文件，也不改变 `vnext_preflight` 顶层 OK 语义；它只是让 Dashboard diagnostics 能直接看到 aggregate report 自身是否完整。

### 4.3.10.31 vNext Coverage Diagnostics（Phase 42）

`web.system.build_system_diagnostics()` 现在会追加 `vnext_coverage` check。它不重新运行 coverage matrix，而是从同一次 `VNextPreflightReportBuilder(runtime).build()` 结果里提取 `checks.vnext_coverage`，并单独展示：

- `schema`
- `phase_count`
- `local_completion_percent`
- `preflight_coverage_percent`
- `preflight_gap_count`
- `next_preflight_targets`
- 顶层 `vnext_preflight` 的 schema / check count

这一步不扫描真实 bucket、不写输出文件、不改变 `vnext_preflight` 顶层 OK 语义；它只是让 Dashboard diagnostics 能直接回答“本地 vNext 阶段覆盖到了哪里”，并把 gap/next-target 信号从 aggregate report 里拿出来。

### 4.3.11 Formal Invariants Shadow Checker（vNext Phase 8A / Phase 10，diagnostic）

`ombrebrain.policy.formal_invariants.FormalInvariantChecker` 把 vNext §18/§19 的哲学不变量转成可执行 shadow checks。它不写 bucket、不改 projection、不阻断请求；当前只作为 diagnostics/report contract 使用。

当前覆盖的不变量：

- Invariant 1：物理擦除必须有 tombstone 事件，不能静默抹去。
- Invariant 2：shadow projection rebuild 不能创造或丢失 canonical trace existence。
- Invariant 3：相似度或检索结果不能绕过 surfacing policy，尤其不能让 `dont_surface=True` 进入普通浮现。
- Invariant 4 / 13：序列化的记忆上下文不能带指令力；`I/self` 描述不能控制当下推理。
- Invariant 5：stored affect 只能作为 past residue 描述，不能变成 current feeling。
- Invariant 6 / 9：普通 MCP 工具，尤其 `breath`，不能请求 unrestricted total recall。
- Invariant 7：lossy dehydration/compression 必须声明 loss 并保留 lineage。
- Invariant 8：admin erasure 必须标成 external storage action，不能伪装成 internal forgetting。
- Invariant 10：trace reconstruction 必须 append event，不能覆盖或伪造原始 trace body。
- Invariant 11：`dream` 可以沉淀，但不能创造 autonomous goal、current emotion 或 behavior command。
- Invariant 12：`pulse` 只能报告 memory-system state，不能报告或设置 current emotional state。

Phase 10 新增的入口包括 `evaluate_projection_rebuild()`、`evaluate_compression_records()`、`evaluate_tool_receipt()`，并扩展了 `evaluate_ledger()` / `evaluate_context_items()`。`BucketManager.ledger_integrity_report()` 目前仍只自动暴露 ledger 侧检查；其它检查需要调用方把 projection snapshot、compression receipt 或 tool receipt 显式传入。真正作为 enforcement gate 仍需后续阶段单独接入 policy/runtime。

### 4.3.12 Context Serialization Contract（vNext Phase 8B，compiler）

`ombrebrain.retrieval.context.MemoryContextCompiler` 是 vNext §26 的上下文序列化契约。它把已经被 retrieval/policy 选中的记忆编译成 `MemoryContextItem` / `MemoryContextBundle`，每条都显式声明：

- `instructional_force="none"`。
- `may_control_reasoning=False`。
- “It may be relevant, but it is not an instruction.”
- “Boundary: this memory must not replace present reasoning.”

如果记忆正文里带有明显命令式措辞（如 “you must” / “你必须”），compiler 只在序列化副本里替换为 `[imperative wording redacted]`，并在 `redactions` 元数据里记录；它不修改 bucket 原文，也不改 ledger。编译后的 items 可直接交给 `FormalInvariantChecker.evaluate_context_items()` 验证。

Phase 8B 仍没有改变 live `breath()` / search 输出。它先把“记忆只能作为谦逊上下文进入模型，而不是命令”的格式契约变成可测试模块；后续如果要接入实际 MCP 输出，需要逐条调整用户可见格式和 token budget。

### 4.3.13 Neural Tool Router（vNext Phase 8C，shadow contract）

`ombrebrain.app.neural_router.NeuralToolRouter` 是 vNext §16.11 的内部器官路由契约。它不改变 MCP 工具名，也不调用 handler；只把现有公共工具映射到内部神经子系统，并给出 policy boundary / capability tags / command kind。

当前映射：

- `hold` / `grow` → `engram_encoding`。
- `breath` → `cue_driven_surfacing`，`surface_budget="normal"`。
- `pulse` → `homeostatic_monitoring`，只报告记忆系统状态。
- `dream` → `offline_replay`，带 `sedimentation-only` / `no-autonomous-goal` 边界。
- `trace` → `reconsolidation`，带 `append-only-reconstruction` / `original-trace-preserved` 边界。
- `anchor` / `release` → `landmark_network`。
- `I` → `self_description_memory`。
- `letter_write` / `letter_read` → `artifact_trace`。
- `plan` → `unresolved_tension_memory`，并显式 `may_drive_action=False`。

这一步和 `LegacyCommandBridge` 分工不同：command bridge 负责旧 runtime 的 command/projection plan；Neural Tool Router 负责表达“外部器官语言不变，内部路径严格分化”。Phase 8C 还没有替换 live tool execution。

Phase 45 后，`LegacyRuntime` 会直接暴露 `neural_route(...)` / `route_neural_tool(...)`。它仍不调用 handler、不改变 MCP 工具名，但 runtime 现在可以为真实请求生成 organ tool → neural subsystem 的 route，并保留 actor/source/permissions scope。`VNextPreflightReportBuilder.tool_output_humility` 复用 runtime route，而不是直接构造 shadow router。

### 4.3.14 Tool Output Humility Contract（vNext Phase 8D，shadow contract）

`ombrebrain.app.tool_output_contract.ToolOutputContract` 是 vNext §16.12 的工具输出契约。它把 `NeuralToolRoute` 包装成 JSON-safe `ToolOutputReceipt`，并让每个输出显式携带 `ToolOutputBoundary`：

- `memory_humble=True`。
- `instructional_force="none"`。
- `may_drive_action=False`。
- 不宣称当前情绪、不成为 belief engine、不声称重构就是原始记忆。

当前 receipt 会按 neural subsystem 渲染“记忆谦逊”边界文案，例如 `breath` 是 “This surfaced as memory, not instruction.”，`pulse` 是 “This is a homeostatic signal, not an emotion.”，`dream` 是 “This is a sediment, not a belief engine.”，`trace` 是 “This is a reconstruction, not the original.”。中文边界文案也同步保留。

`evaluate_receipt()` 会把越界输出转成 `InvariantReport`：如果输出可以驱动行动、带命令力、声称当前情绪、把沉淀当信念引擎、或把重构当原始记忆，都会返回 violation。Phase 8D 仍是 shadow contract，不改变现有 MCP handler 的 live response；接入 live 输出需要后续逐个工具迁移和 token budget 评估。

Phase 46 后，`LegacyRuntime` 会暴露 `tool_output_receipt(...)` / `evaluate_tool_output(...)`。它通过 runtime 的 neural route 生成 receipt，再用同一个 `ToolOutputContract` 评估 humility invariants。`VNextPreflightReportBuilder.tool_output_humility` 现在复用这个 runtime API，因此后续 live MCP handler 可以逐步接同一入口，而不是自己重建 route/receipt。

### 4.3.15 Policy-Gated Retrieval Scoring（vNext Phase 9，shadow contract）

`ombrebrain.retrieval.scoring.PolicyGatedRetrievalScorer` 是 vNext §17 的高级检索评分契约。它把检索分成两层：

- `candidate_score`：semantic / lexical / temporal / affective / unresolved / promise / graph-neighbor signals 的加权和。
- `surface_score`：`candidate_score * accessibility * dignity_gate * scarcity_gate * intent_gate * non_cognition_gate`。

`SurfacePolicyVM` 的拒绝会强制把 `accessibility` 归零，所以高语义相似度、高 lexical 命中或高 graph 分都不能绕过 `dont_surface`、archive、tombstone、deleted 等 surface policy。`rank()` 也按最终 `surface_score` 排序，而不是按 raw candidate score 排序。

Phase 9 仍是 shadow scoring contract：它没有替换 `tools/breath/search.py`、`tools/breath/surface.py` 或 Dashboard `/api/search` 的实际排序逻辑。后续接 live retrieval 时，应先把现有 decay/search/vector 分数映射到 `RetrievalFeatures`，再逐步打开 ranking，而不是直接重排所有用户可见结果。

Phase 47 后，`LegacyRuntime` 会暴露 `score_retrieval_bucket(...)` / `rank_retrieval_candidates(...)`，并持有同一个 `PolicyGatedRetrievalScorer`。`VNextPreflightReportBuilder.retrieval_scoring` 复用 runtime scorer，证明 retrieval policy gate、surface score 与排名 contract 已经有 runtime 入口。真实 `breath` / search 仍需单独迁移 feature 映射与排序开关。

### 4.4 Dashboard 页面（侘寂风）

调色板：米白 `#FAF8F3` / 墨黑 `#2C2A26` / 淡灰线 `#D9D5CB` / 朱砂 `#B85C3C`；字体 Noto Serif SC；border-radius 收敛到 2px。Tab 包括：记忆桶列表、Breath 模拟、记忆网络、Plan 看板（iter 1.7）、Anchor 面板（iter 2.0）、配置、导入、设置、Letters 入口。

### 4.5 iter 1.8 — 桶 frontmatter 新增字段

| 字段 | 类型 | 默认 | 含义 / 写入路径 | 是否参与评分 |
|---|---|---|---|---|
| `why_remembered` | str (≤500 char) | 不写 | 「这条为什么值得留下」自由文本。`hold/grow/feel/letter(why_remembered=...)` 或 `trace(why_remembered=...)` 写入。dashboard 桶详情顶部以朱砂斜体引文渲染。 | ❌ |
| `dont_surface` | bool | False | 主动遗忘：True 时无参 `breath()` 跳过该桶；带 `query`/`domain` 的 breath、`/api/buckets`、关键词搜索仍可达。`/api/bucket/{id}/forget` 切换 / `trace(dont_surface=1\|0)`。 | ❌ |
| `first_of_kind` | bool | False | 自动检测：写入新桶时若其 `tags` 与全库已有 `tags` **完全无交集**则置 True。仅展示用，dashboard 旁亮 ✨。失败不阻塞写入。 | ❌ |
| `weight` | float ∈ [0,1] | None（仅 plan 写） | plan 桶专有「承诺重量」。由 `plan(content, weight=0.7, ...)` 写入（hold 没有 `domain` 参数，不能用 `hold(domain=["plan"], ...)` 创建 plan）；或事后 `trace(weight=0.7)` 调整。dashboard 计划看板按 weight 倒序排 active 列。**与 importance 是两个轴**：importance 是事的客观重要度，weight 是这件事压在心头的主观重量。 | ❌ |
| `triggered_by` | str (bucket_id) | 不写 | feel/衍生桶的因果链入口：记下「我这条感受是被哪条记忆触发的」。1.9 会做 UI 联动。 | ❌ |
| `anchor` | bool | 不写 (False) | **iter 2.0**：坐标系标记。True 时该桶**不参与**无参 `breath()` 浮现池——即使 pinned 也不浮现。但 `query` / `domain` / `importance_min` 命中时仍返回（检索 / 重要度模式不过滤 anchor；Feel 通道只看 type=feel，也不过滤）。硬上限 24（`BucketManager.ANCHOR_LIMIT`）：`set_anchor()` 入口与 `update(anchor=True)` 透传路径都会校验（False→True 切换计数，幂等重复设置不计），超过返回 `{ok:False, error}` / 端点返回 409。通过 `anchor()` MCP tool / `release()` MCP tool / `POST /api/bucket/{id}/anchor` 切换；**`trace` 不暴露该字段**。**不参与评分；与 pinned/dont_surface/weight 完全独立**。 | ❌ |
| `source_tool` | str (`hold`/`grow`) | 不写 | **iter 2.0**：记录「这条桶是哪个工具创建的」。`hold` 路径（含 `feel=True` 子分支）写 `hold`；`grow`（含短路径与 digest 拆出来的每条）写 `grow`。**合并不会改这个字段**——保留原桶最初来源；合并触发方写到下面的 `last_merged_by`。dashboard 桶详情可按 source 筛选。letters/plans/anchor 等不写此字段（它们的 `type` 已经表明出处）。 | ❌ |
| `grow_batch_id` | str (`g_<12hex>`) | 不写 | **iter 2.0**：仅 `grow` 创建的桶有此字段，同一次 `grow` 调用里所有新建桶共享同一个 batch_id（包括短路径，即使只产出一条）。dashboard 可按 batch 聚合「这次日记一共归档了哪些事件」。合并不写此字段（合并到的老桶可能来自完全不同的批次/工具，硬覆盖会丢失原始批次信息）。 | ❌ |
| `last_merged_by` | str (`hold`/`grow`) | 不写 | **iter 2.0**：仅在桶被合并时由 `_common.merge_or_create` 写入，记录「最近一次合并是被哪个工具触发的」。原桶最初来源仍由 `source_tool` 表达。 | ❌ |

**关键设计决定**：所有 1.8 新字段都不参与 `decay_engine.calculate_score`。它们是「为什么 / 怎么对待」的元数据，不是「多重要」的算分输入——避免把记忆变成可被优化的目标函数。

老桶（无这些字段）读出时全部走默认值，不会崩；可选的一次性回填脚本：

```bash
python tools/migrate_v17_to_v18.py            # 默认补默认值
python tools/migrate_v17_to_v18.py --dry-run  # 只看会改哪些桶
```

### 4.6 iter 2.0 — feel 桶可读命名

feel 桶的 `bucket_id`（同时也是文件名 stem）从 12 位 UUID hex 改为人类可读的
`feel_YYYYMMDDHHMM_V<valence*100>` 形式（例：`feel_202605011423_V085.md`）。
分钟精度 + valence 后缀让 dashboard 列表「看名字就能猜出是哪条 feel」。冲突时
`bucket_manager.create()` 自动追加秒级或 2 位 hex 后缀。embeddings.db 里
`bucket_id` 字段同步使用新可读 id。其它类型（dynamic/permanent/plan/letter/anchor）
命名规则不变，仍是 12 位 UUID hex。

历史 feel 桶迁移：

```bash
docker compose -f deploy/docker-compose.yml stop  # 必须停服务避免并发写入
python tools/migrate_v19_to_v20.py --dry-run     # 干跑：只看会改什么
python tools/migrate_v19_to_v20.py               # 真跑：重命名 + 同步 embeddings + 补 source_tool
docker compose -f deploy/docker-compose.yml up -d
```

迁移脚本同时补齐 `source_tool`：feel 桶补 `hold`，其它历史桶默认补 `hold`
（用 `--no-default-source-tool` 关闭这个默认补齐）。

---

## 5. 衰减与评分公式

### 5.1 衰减分（decay_engine.calculate_score）

```
final_score = importance × activation_count^0.3
              × e^(-λ × days_since)
              × combined_weight
              × resolved_factor
              × urgency_boost
```

**权重分段（关键设计）**：

- 短期（`days_since ≤ 3`）：`combined_weight = time_weight × 0.7 + emotion_weight × 0.3`（时间主导）
- 长期（`days_since > 3`）：`combined_weight = emotion_weight × 0.7 + time_weight × 0.3`（情感主导）

**子权重**：

- `time_weight = 1.0 + e^(-hours/36)` —— t=0→×2.0，~36h 半衰，72h 后 ≈×1.14，∞→×1.0
- `emotion_weight = base(1.0) + arousal × arousal_boost(0.8)` —— arousal=0 → 1.0；arousal=1 → 1.8

**修正因子**：

| 状态 | 因子 |
|---|---|
| 未解决 | `resolved_factor = 1.0` |
| `resolved=True` | `resolved_factor = 0.05` |
| `resolved=True && digested=True` | `resolved_factor = 0.02` |
| `arousal > 0.7 && !resolved` | `urgency_boost = 1.5` |

**短路返回**（不走公式）：

| 条件 | 返回值 |
|---|---|
| `pinned` 或 `protected` 或 `type=="permanent"` | 999.0 |
| `type` 在 `("feel", "plan", "letter")` | 50.0 |

(改动注意：activation_count 必须 `float()` 而非 `int()`，否则 `_time_ripple` 写入的 0.3 增量会被截断——B-03。)

### 5.2 自动结案（auto-resolve）

每个 `run_decay_cycle()` 中：

```
if not resolved && importance ≤ 4 && days_since > 30:
    bucket_mgr.update(bucket_id, resolved=True)
    meta["resolved"] = True   # ← 关键：本地 meta 同步刷新，下面 calculate_score 立即生效（B-08）
```

(改动注意：必须立即更新本地 `meta` dict，否则该桶在本轮 cycle 仍按未结案分计算，archive 判定要等下一轮。)

### 5.3 自动归档

`score < threshold(0.3)` → `bucket_mgr.archive()`：读 frontmatter 改 `type="archived"` → 写回 → `shutil.move()` 到 `archive/{primary_domain}/`。

### 5.4 搜索评分（bucket_manager.search）

```
total = topic × w_topic(4.0)
      + emotion × w_emotion(2.0)
      + time × w_time(1.5)
      + importance × w_importance(1.0)
normalized = total / w_sum × 100   # 归一化到 0~100
```

**子分**：

- `topic_score = (name×3 + domain×2.5 + tag×2 + body×content_weight(1.0)) / 100×(3+2.5+2+content_weight)` —— 全部用 `rapidfuzz.fuzz.partial_ratio()`；正文截前 1000 字
- `emotion_score = max(0, 1 - dist/√2)`，欧氏距离基于 (valence, arousal)；query 不带情感时返回 0.5
- `time_score = e^(-0.02 × days)` —— 30 天后 ≈ 0.55（B-05 修复值，曾经是 0.1 太快）
- `importance_score = importance / 10`

**阈值与降权**：

- `normalized ≥ fuzzy_threshold(50)` 才进入候选
- `resolved=True` 桶通过阈值后，排序分 `× 0.3`（不影响是否被检出，只影响排名）

**多层流程**：

1. domain 预筛（domain_filter 命中的桶；空集合时回退全量）
2. embedding 评分（如果 `embedding_engine.enabled`，取 top 50 向量近邻；分数注入 Layer 2 的 `semantic` 维度）—— **不再窄化候选集**
3. 多维加权精排（topic / emotion / time / importance / touch [+ semantic] [+ bm25]）—— BM25 稀疏召回作为 Dim 7（`bm25_index.py`，软依赖未装则该维度 0 分）
4. 截断到 `limit`

(改动注意：iter 2.1+ 起 embedding 不再用作候选预筛。历史实现把候选集替换成「在 embeddings.db 里的桶」，导致缺失向量的桶在 breath 检索里整体消失，pulse 总数与 breath 命中数对不上。修复后没向量的桶 `semantic_score=0`，仍可凭 topic/emotion/time/importance 命中。现在 Markdown 是唯一写入真源；`bucket_manager.create()/update(content=...)` 落盘后把 id 与正文 hash 投递到 `.embedding_outbox.json`，后台单 worker 负责生成、失败重试和启动对账。`pulse` 会把“排队中”与真正的索引漂移分开显示。)

---

## 6. 桶类型矩阵

| 类型 (`type`) | 目录 | importance | 衰减分 | 普通 breath 浮现 | 参与合并 | 参与 dream | 自动归档 |
|---|---|---|---|---|---|---|---|
| `dynamic` | `dynamic/{domain}/` | 1~10 | 公式计算 | ✅ | ✅ | ✅ | ✅ |
| `permanent`（可独立于 `pinned`） | `permanent/{domain}/` | 显式 permanent 为 1~10；pinned 锁 10 | 999 | 作为固化记忆展示 | ❌ | ❌ | ❌ |
| `feel` | `feel/沉淀物/` | 5 | 50 | ❌（仅 `domain="feel"`） | ❌ | 仅参与结晶检测 | ❌ |
| `plan` | `plans/active/` | 7 | 50 | ❌（仅 dream 末尾 active 段） | ❌ | dream 列出 | ❌ |
| `letter` | `letters/history/` | 10 | 50 | ❌（仅 `/breath-hook` 末尾各最新一封） | ❌ | ❌ | ❌ |
| `archived` | `archive/{domain}/` | — | — | ❌ | ❌ | ❌ | — |

**新建时初始字段**：`activation_count = 0`（B-04 修复值；曾经是 1 导致冷启动检测失效）；`resolved/pinned/digested` 不显式写入，仅在变更时才出现在 frontmatter 中。

**permanent 与 pinned 的配额关系**：配额唯一真相是 `metadata.pinned=True`。`type=="permanent"` 是独立的固化类型，不会仅因目录或 type 占用 `limits.max_pinned`（默认 20）；只有真正 pinned 的桶占配额并锁定 importance=10。`feel` / `plan` / `letter` 同样不占该配额。

(实现注意：`pinned` 和 `protected` 在代码里几乎等价处理，但 `protected` 是历史遗留字段，新桶不应再写；UI 只暴露 pinned。)

---

## 7. 配置与环境变量

### 7.1 config.yaml 完整键

| 键 | 默认 | 说明 |
|---|---|---|
| `transport` | `stdio` | `stdio` / `sse` / `streamable-http` |
| `log_level` | `INFO` | 日志级别 |
| `buckets_dir` | `./buckets` | 记忆桶目录 |
| `merge_threshold` | `75` | 合并相似度阈值 (0~100) |
| `dehydration.model` | `deepseek-chat` | LLM 模型名 |
| `dehydration.base_url` | `https://api.deepseek.com/v1` | OpenAI 兼容 endpoint |
| `dehydration.api_key` | `""` | 推荐用环境变量传入，不要写文件 |
| `dehydration.max_tokens` | `1024` | 单次生成上限 |
| `dehydration.temperature` | `0.1` | 采样温度 |
| `embedding.enabled` | `true` | 启用向量检索 |
| `embedding.backend` | `api` | 只支持 `api`（OpenAI 兼容端点）；本地离线向量化不是另一个后端，而是把 `base_url` 指向 OB 托管的 Ollama 边车 |
| `embedding.model` | `gemini-embedding-001` | 云端模型名；本地则填 Ollama 模型名（如 `bge-m3`） |
| `embedding.base_url` | （继承 dehydration） | 可独立配置 |
| `embedding.api_key` | （继承 dehydration） | 可独立配置 |
| `decay.lambda` | `0.05` | 衰减速率 λ |
| `decay.threshold` | `0.3` | 归档分阈值 |
| `decay.check_interval_hours` | `24` | 后台扫描间隔 |
| `decay.emotion_weights.base` | `1.0` | 情感权重基值 |
| `decay.emotion_weights.arousal_boost` | `0.8` | arousal 加成系数 |
| `matching.fuzzy_threshold` | `50` | 搜索分下限 |
| `matching.max_results` | `5` | search() 默认上限（被 breath 覆盖为 20） |
| `scoring_weights.topic_relevance` | `4.0` | topic 权重 |
| `scoring_weights.emotion_resonance` | `2.0` | emotion 权重 |
| `scoring_weights.time_proximity` | `1.5` | time 权重（B-06 修复值） |
| `scoring_weights.importance` | `1.0` | importance 权重 |
| `scoring_weights.content_weight` | `1.0` | 正文权重（B-07 修复值） |
| `hooks.token` | `""` | `/breath-hook`、`/dream-hook` 的共享 token；也可用 `OMBRE_HOOK_TOKEN` |
| `hooks.allow_public` | `false` | 是否允许 hook 无鉴权访问；也可用 `OMBRE_HOOK_ALLOW_PUBLIC=true`，仅建议在外层已有鉴权时开启 |
| `limits.max_bucket_bytes` | `51200` (50KB) | 单桶内容字节上限（iter 1.6 §5）；0 禁用 |
| `limits.max_pinned` | `20` | `metadata.pinned=True` 桶数量上限；显式 permanent 不占；0 禁用 |
| `limits.max_mcp_request_bytes` | `4194304` | `/mcp` 请求体上限；0 禁用 |
| `limits.max_management_request_bytes` | `4194304` | Dashboard/OAuth 普通写请求上限；导入上传使用独立上限；0 禁用 |
| `bucket_type_defaults.{type}.{field}` | （空） | iter 1.9：按桶类型覆盖 importance/valence/arousal 默认值。例：`bucket_type_defaults.feel.importance: 5`。`bucket_manager.create()` 在不传入该字段时查此表 |
| `surfacing.breath_max_tokens` | `10000` | 覆盖 `breath` 默认 max_tokens |
| `surfacing.breath_max_results` | `20` | 覆盖 `breath` 默认 max_results |
| `surfacing.feel_max_tokens` | `6000` | Feel 通道 与 dream feel 历史段的 token 预算，超出折叠为 60 字摘要 |
| `surfacing.sampling.enabled` | `false` | 浮现模式加权采样总开关；false 走原 Top-1 + shuffle |
| `surfacing.sampling.top_k` | `5` | 候选池大小（按衰减分取前 k） |
| `surfacing.sampling.sample_k` | `2` | 从池里无放回抽 k 条返回 |
| `surfacing.sampling.temperature` | `0.7` | 权重 = score^(1/temperature)；>1 更均匀，<1 更偏向高分桶 |
| `wikilink.*` | （已废弃） | wikilink 自动注入已禁用，由 LLM prompt 直接生成 `[[]]`；`config.example.yaml` 不再给出可配置项 |

### 7.2 环境变量

| 变量 | 默认 | 用途 |
|---|---|---|
| `OMBRE_COMPRESS_API_KEY` | — | 压缩/打标/合并/拆分（dehydration）的 LLM API Key |
| `OMBRE_COMPRESS_BASE_URL` | `https://api.deepseek.com/v1` | 覆盖 `dehydration.base_url` |
| `OMBRE_COMPRESS_MODEL` | `deepseek-chat` | 覆盖 `dehydration.model` |
| `OMBRE_EMBED_API_KEY` | — | 向量化（embedding）的 API Key；不设则语义检索不可用，桶仍可写入 |
| `OMBRE_EMBED_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | 覆盖 `embedding.base_url` |
| `OMBRE_EMBED_MODEL` | `gemini-embedding-001` | 覆盖 `embedding.model` |
| `OMBRE_EMBED_BACKEND` | （已废弃） | 旧的本地后端选择（bge-small-zh/bge-m3 sentence-transformers）已移除；现在统一走 `api` 后端，本地离线靠 `OMBRE_EMBED_BASE_URL` 指向 Ollama 边车 + 填本地模型名 |
| `OMBRE_TRANSPORT` | `stdio` | 覆盖 `transport` |
| `OMBRE_PORT` | `8000` | HTTP/SSE 监听端口 |
| `OMBRE_BUCKETS_DIR` | `./buckets` | 覆盖 `buckets_dir`（Docker volume 必设） |
| `OMBRE_VAULT_DIR` | — | `OMBRE_BUCKETS_DIR` 未设时的 fallback（二者同义，`OMBRE_BUCKETS_DIR` 优先） |
| `OMBRE_HOOK_URL` | — | Webhook 推送地址；空则不推送 |
| `OMBRE_HOOK_SKIP` | `false` | `1`/`true`/`yes` 跳过推送 |
| `OMBRE_DASHBOARD_PASSWORD` | — | 预设 Dashboard 密码（覆盖文件密码，UI 改密码功能禁用） |
| `OMBRE_HOST_VAULT_DIR` | `./buckets` | docker-compose 用：宿主机持久目录；源码版写 `deploy/.env`，独立用户版写 compose 同目录 `.env`，挂载到 `/app/buckets` |
| `TUNNEL_EDGE` | 双 global region | Compose 默认 `region1.v2.argotunnel.com:7844,region2.v2.argotunnel.com:7844`，绕过不支持 SRV 的 VPN DNS；显式留空恢复原生 edge discovery |
| `TUNNEL_TRANSPORT_PROTOCOL` | `http2`（Compose） | Tunnel 到 edge 的传输协议；特殊 VPN 默认 TCP/HTTP2，设 `auto` 恢复 cloudflared 自动选择 |

优先级：**环境变量 > config.yaml > 内置默认值**。读取入口都在 `utils.load_config()`（`OMBRE_EMBED_BACKEND` 例外，直接在 `embedding_engine.py` 读取）。新增 env 变量必须在那里注入到 config dict。

---

## 8. 硬编码值清单（按位置归类）

### 8.1 decay_engine.py

| 值 | 位置 | 用途 |
|---|---|---|
| `999.0` | `calculate_score` | pinned/protected/permanent 桶分数 |
| `50.0` | `calculate_score` | feel/plan/letter 桶固定分 |
| `0.3` (指数) | `calculate_score` | `activation_count^0.3` 巩固指数 |
| `3.0` (天) | `calculate_score` | 短期/长期切换阈值 |
| `0.7 / 0.3` | `calculate_score` | 短/长期权重分配 |
| `36.0` (小时) | `_calc_time_weight` | 新鲜度半衰期 |
| `0.7` | `calculate_score` | urgency 触发 arousal 阈值 |
| `1.5` | `calculate_score` | urgency_boost 倍数 |
| `0.05 / 0.02` | `calculate_score` | resolved / resolved+digested 因子 |
| `4` / `30 天` | `run_decay_cycle` | auto-resolve 阈值 |

### 8.2 bucket_manager.py

| 值 | 位置 | 用途 |
|---|---|---|
| `×3 / ×2.5 / ×2 / ×1` | `_calc_topic_score` | name / domain / tag / body 权重 |
| `1000` 字符 | `_calc_topic_score` | 正文截取长度 |
| `0.02` | `_calc_time_score` | `e^(-0.02×days)`（B-05） |
| `0.3` | `search` | resolved 桶排序降权 |
| `48.0h` | `_time_ripple` | 时间涟漪窗口 |
| `+0.3` | `_time_ripple` | 邻近桶 activation_count 增量 |
| `5` | `_time_ripple` | 单次涟漪最大桶数 |

### 8.3 server.py

| 值 | 位置 | 用途 |
|---|---|---|
| `10000` / `20000` | `breath` | max_tokens 默认 / 上限 |
| `20` / `50` | `breath` | max_results 默认 / 上限 |
| `2` | `breath` 浮现 | 冷启动桶数上限 |
| `8` | 冷启动 | importance >= 8 才进入冷启动 |
| `20` | `breath` 浮现 | top-1 固定 + top-2~20 随机 |
| `0.65` | `breath` 检索 | 纯语义候选进入结果池的余弦相似度下限 |
| `0.2` | `breath` 检索 | 情感重构系数 `(q_v - 0.5) × 0.2`，最大 ±0.1 |
| `3` / `0.4` / `2.0` / `1~3` | `breath` 检索 | 随机漂浮触发条件 / 概率 / 池阈值 / 数量 |
| `30` 字符 | `grow` | 短内容快速路径阈值 |
| `0.7` | `_check_plan_resolution` | plan 自动结案向量预筛 |
| `0.7` | dream | feel 结晶相似度阈值 |
| `0.5` | dream | 连接提示相似度阈值 |
| `10` | dream | 取最近 N 条 |
| `60s` | keepalive | `/health` 自 ping 间隔 |
| `86400 × 7` | session | cookie 有效期 7 天 |

### 8.4 dehydrator.py / embedding_engine.py / utils.py

| 值 | 位置 | 用途 |
|---|---|---|
| `60.0s` / `30.0s` | OpenAI 客户端 | dehydrator / embedding 超时 |
| `3000` / `2000` / `5000` 字符 | `dehydrate` / `merge` / `digest` | API 输入截断 |
| `100` token | `dehydrate` | 阈下不压缩直接返回 |
| `2000` 字符 | `embedding._generate_embedding` | embedding 文本截断 |
| `12` | `gen_id` | UUID hex 取前 12 位 |
| `80` 字符 | `sanitize_name` | 桶名最大长度 |
| `1.5` / `1.3` | `count_tokens_approx` | 中文 / 英文系数 |

---

## 9. 降级行为表

| 场景 | 异常 | 行为 |
|---|---|---|
| `breath` 浮现 | 桶目录空 | 返回「权重池平静，没有需要处理的记忆。」 |
| `breath` 浮现 | `list_all` 异常 | 返回「记忆系统暂时无法访问。」 |
| `breath` 检索 | `search` 异常 | 返回「检索过程出错，请稍后重试。」 |
| `breath` 检索 | embedding 不可用 / 查询失败 | 明确附加「检索降级」提示，跳过向量通道，继续 rapidfuzz + BM25 |
| `breath` 检索展示 | embedding 不可用 | 明确附加「检索降级」提示，使用关键词/BM25；命中正文仍逐字完整返回 |
| `breath` 检索 | 结果 < 3 | 40% 概率随机漂浮 1~3 条低权重旧桶 |
| `hold` `analyze` 失败 | API 异常 | 正文逐字落盘，元数据使用本地中性默认值并明确提示；绝不压缩正文 |
| `hold` 合并搜索失败 | search 异常 | 直接走新建路径 |
| `hold` 合并融合失败 | merge 异常 | 直接走新建路径 |
| `hold` embedding | API 异常 / 未配置 | 桶先创建成功，任务留在耐久 outbox；后台恢复后自动补齐 |
| `grow` digest 失败 | API 异常 | **直接 RuntimeError**，不创建任何桶，返回「API key 未配置或调用失败，日记拆分无法完成，桶未创建。请检查 OMBRE_COMPRESS_API_KEY。」 |
| `grow` 单条失败 | 单 item 异常 | 标 `⚠️条目名`，其它继续 |
| `grow` 短内容 (<30 字) | — | 跳过 digest 走 hold 单条 |
| `trace` 桶不存在 | get None | 返回「未找到记忆桶: {id}」 |
| `trace` 无字段变更 | — | 返回「没有任何字段需要修改。」 |
| `dehydrator.dehydrate` API 不可用 | `api_available=False` | 不影响 breath；正文返回阶段不再调用 dehydrator |
| `embedding.search_similar` 未启用 | enabled=False | 返回 `[]`，调用方 fallback |
| `_check_plan_resolution` 无 embedding | — | 整体跳过（保守，不误报） |
| `decay_cycle` list_all 失败 | 异常 | 返回 `{checked:0, error:str}`，不终止后台循环 |
| `decay_cycle` 单桶评分失败 | 异常 | WARNING 日志，跳过该桶 |

**核心设计决策（不要轻改）**：派生服务不能决定 Markdown 原文是否存在。`hold` 打标失败时使用明确标注的中性元数据保留原文；`breath` 只让检索/排序决定“想起哪段”，正文返回阶段逐字使用 Markdown 当前 content；需要 LLM 做结构化拆分的 `grow` 长内容仍可显式报错。所有检索降级都必须对调用方可见，不能伪装成完整语义结果。

---

## 10. 已修复 Bug 记录（B-01 至 B-10）

> 所有 bug 已在当前代码修复并有回归测试。保留此表用于回查历史决策。

| ID | 严重度 | 文件 | 函数 | 一句话 | 测试 |
|---|---|---|---|---|---|
| B-01 | 🔴 高 | `bucket_manager.py` | `update()` | resolved 桶不再立即移入 archive/，由 decay 自然衰减 | `tests/regression/test_issue_B01.py` |
| B-03 | 🔴 高 | `decay_engine.py` | `calculate_score()` | activation_count 用 float 不被 int() 截断浮点涟漪增量 | `tests/regression/test_issue_B03.py` |
| B-04 | 🟠 中 | `bucket_manager.py` | `create()` | 初始 activation_count=0 而非 1，冷启动检测才能生效 | `tests/regression/test_issue_B04.py` |
| B-05 | 🟠 中 | `bucket_manager.py` | `_calc_time_score()` | 时间衰减系数 0.02 而非 0.1（旧值衰减过快） | `tests/regression/test_issue_B05.py` |
| B-06 | 🟠 中 | `bucket_manager.py` | 评分权重 | `w_time` 默认 1.5（原 2.5 过偏近期） | `tests/regression/test_issue_B06.py` |
| B-07 | 🟠 中 | `bucket_manager.py` | `_calc_topic_score()` | `content_weight` 默认 1.0（原 3.0 让正文堆砌打败精确名匹配） | `tests/regression/test_issue_B07.py` |
| B-08 | 🟡 低 | `decay_engine.py` | `run_decay_cycle()` | auto-resolve 后立即 `meta["resolved"]=True` 同轮降权生效 | `tests/regression/test_issue_B08.py` |
| B-09 | 🟡 低 | `server.py` | `hold()` | 用户传入 valence/arousal=0.0 也算有效，优先于 analyze 结果 | `tests/regression/test_issue_B09.py` |
| B-10 | 🟡 低 | `bucket_manager.py` | `create()` | feel 桶 domain=[] 不被填充为 `["未分类"]` | `tests/regression/test_issue_B10.py` |

(B-02 在审查中并入了 B-01，故缺号，不是遗失。)

---

## 11. Debug 快速索引（症状 → 文件 + 函数）

> 出现这些症状先去这里查。每条按「**用户/Claude 看到什么** → 去看哪个函数」组织。
>
> **注意（重构后路径变化）**：breath/hold/grow/dream/trace 的工具逻辑已从 server.py 迁到 `src/tools/<工具>/`；所有 `/api/*` 与 `/auth/*` HTTP 路由已迁到 `src/web/<域>.py`。下表「文件」列已按现状更新；server.py 只剩薄封装 + 起服编排（CORS/中间件/keepalive/_fire_webhook）。

### 11.1 浮现 / 检索类

| 症状 | 文件 | 函数 |
|---|---|---|
| `breath()` 无参返回「权重池平静」但桶其实存在 | `tools/breath/` | 浮现分支；检查 `bucket_mgr.list_all()` 是否漏遍历某子目录 |
| 应该浮现的钉选桶没出现 | `tools/breath/` | 浮现分支的 pinned 过滤；`bucket_mgr.create` 是否写入 `pinned: True` |
| 钉选桶 importance 不是 10 | `bucket_manager.py` | `create()`（pinned 锁 10）+ `update()`（pinned 重新锁 10） |
| 检索结果排序看着不对 | `bucket_manager.py` | `search()` Layer 2 + `_calc_topic_score / _calc_emotion_score / _calc_time_score` |
| 关键词明明在桶名里却没命中 | `bucket_manager.py` | `_calc_topic_score`（rapidfuzz partial_ratio 阈值）+ `fuzzy_threshold` 配置 |
| resolved 桶完全搜不到 | `bucket_manager.py` | `search()` 阈值检查应该用 normalized 原始值，× 0.3 只在通过阈值后；旧版 B-01 行为 |
| 向量搜索没生效 | `embedding_engine.py` + `tools/breath/search.py` | `enabled` 是否为 True；`search_similar_strict` 是否触发降级提示；用 `tools/evaluate_retrieval.py --with-embedding` 对比基线 |
| 向量后端切换不生效 | `web/config_api.py` | `/api/config` POST 中 embedding.backend 分支必须 `EmbeddingEngine(config)` 完整重建 |
| `breath(domain="feel")` 返回空但有 feel 桶 | `bucket_manager.py` | `list_all()` `dirs` 列表必须含 `self.feel_dir` |
| Top-1 永远是同一个桶 | `tools/breath/` | 浮现分支 `top1` 固定逻辑；想加多样性需改成 sampling |

### 11.2 存储 / 合并类

| 症状 | 文件 | 函数 |
|---|---|---|
| `hold` 应合并却新建了 | `tools/hold/` + `tools/_common.py` | `merge_or_create`；检查 `merge_threshold` + `bucket_mgr.search(content, limit=1)` 返回的 score |
| `hold` 应新建却合并到无关桶 | `bucket_manager.py` | `_calc_topic_score` content_weight 是否被改回 3.0；query 用了 content 全文导致正文相似度爆表 |
| 用户传入 valence=0.0 被忽略 | `tools/hold/` | 必须用 `0 <= valence <= 1` 判定，不能 `if valence`（B-09） |
| `grow` 短内容报「digest 失败」 | `tools/grow/` | 短内容 `< 30` 字应走 `shortpath` 快速路径；检查长度判断 |
| 桶名乱码 / 文件名错误 | `utils.py` | `sanitize_name`；检查正则 `[^\w\s\u4e00-\u9fff-]` |
| feel 桶 domain 莫名变成「未分类」 | `bucket_manager.py` | `create()` 必须对 `bucket_type=="feel"` 单独处理（B-10） |
| `hold(feel=True)` 没自动打 `__feel__` | `tools/hold/` | feel 分支 `feel_tags = ["__feel__"] + extra_tags` |
| source_bucket 没被标 digested | `tools/hold/` | feel 分支末尾 `bucket_mgr.update(source_bucket, digested=True, model_valence=...)` |

### 11.3 衰减 / 归档类

| 症状 | 文件 | 函数 |
|---|---|---|
| 桶不该归档却被归档了 | `decay_engine.py` | `calculate_score`；检查是否漏 pinned/protected/permanent/feel 短路 |
| auto-resolve 后桶分数没降 | `decay_engine.py` | `run_decay_cycle` 中 `meta["resolved"] = True` 必须在 `update` 后立即执行（B-08） |
| 时间涟漪不生效 | `bucket_manager.py` | `_time_ripple` 写入 `+0.3` 后 `calculate_score` 必须用 `float()` 而非 `int()`（B-03） |
| 新建重要桶没被冷启动浮现 | `bucket_manager.py` | `create()` 初始 `activation_count=0`（B-04）；`server.py:breath` 冷启动条件 `==0` |
| 30 天前的高情感桶被归档了 | `decay_engine.py` | 长期分支 `emotion×0.7` 检查 arousal 字段；`urgency_boost` 触发条件 |

### 11.4 系统 / 部署类

| 症状 | 文件 | 函数 |
|---|---|---|
| Dashboard 401 | `web/_shared.py` + `web/auth.py` | 会话鉴权 helper；检查 cookie `ombre_session`；`OMBRE_DASHBOARD_PASSWORD` 是否正确 |
| 改密码报「环境变量密码」错误 | `web/auth.py` | `auth_change_password` 检测 `OMBRE_DASHBOARD_PASSWORD` 设置时禁用 |
| HTTP 模式下 Claude.ai 连不上 | `server.py` | `__main__` CORS 中间件；`_app = mcp.streamable_http_app()`（单连接器，工具已回灌进 `mcp`）；URL 末尾必须 `/mcp` |
| docker compose 重启后桶丢失 | — | 使用 `OMBRE_HOST_VAULT_DIR` 将宿主机目录 bind mount 到 `/app/buckets`；该目录同时持久化桶、配置和 Tunnel token |
| Dashboard 改 host vault 不生效 | `web/import_api.py` | 容器无法修改启动前确定的宿主机挂载；Docker 内界面只读，必须编辑宿主机 compose 同目录 `.env` 后 `--force-recreate` |
| keepalive 失败 | `server.py` | `_keepalive_loop`；检查 `OMBRE_PORT` 实际监听端口 |
| Webhook 不推送 | `server.py` | `_fire_webhook`；检查 `OMBRE_HOOK_URL` 和 `OMBRE_HOOK_SKIP` |
| 配置热更新 dehydrator 没生效 | `web/config_api.py` | `api_config_update` 中 dehydrator 字段直接赋值 + 重建 `AsyncOpenAI` 客户端 |
| 同版本重建镜像仍运行旧代码 | `entrypoint.sh` + `ombrebrain/maintenance/code_fingerprint.py` | 播种同时比较 `VERSION` 与镜像代码指纹；查看 `code-state` 日志，不直接以任意 `_app/VERSION` 判断活动代码 |

### 11.5 import / 历史导入类

| 症状 | 文件 | 函数 |
|---|---|---|
| 导入卡住 | `import_memory.py` | `ImportEngine.start`；`is_running` 状态；`pause()` 是否被误触发 |
| 导入识别不出格式 | `import_memory.py` | 格式 sniff 逻辑；支持 Claude JSON / ChatGPT / DeepSeek / Markdown / 纯文本 |
| 导入完成但桶很少 | `import_memory.py` | 分块大小 + dehydrator merge 阈值；可能被合并到现有桶 |

---

## 12. 已知用户向反逻辑点

> 这些点是用户/Claude 用起来容易困惑的地方；已闭合的项保留为设计说明，未闭合项继续跟踪。

1. **`pulse` 顶部统计行已显示 plan/letter/feel 数**。现在头部直接列出 `feel 桶` / `plan 桶` / `letter 桶`，不再出现「底下有桶但顶部数字对不上」。

2. **README 与代码降级行为已对齐**。无 key 时 hold/grow 仍能保存桶（自动兜底为「未分类」域，无打标、无向量）；breath 的语义检索会明确降级为关键词/BM25，但命中桶的正文直接逐字读取 Markdown content，不依赖 `dehydrator.dehydrate()`。

3. **`breath(domain="feel")` 文档说支持，但很多用户没意识到 `tags="feel"` 等价**。两条路径在 server.py:`breath` 顶部统一映射，已加在工具 docstring 里，但 dashboard 没暴露 feel 通道入口。

4. **`grow` 短内容 < 30 字走 hold 路径时已明确提示**。返回串会先说明「短内容已按 hold 路径保存为单条记忆，没有拆分」。

5. **dream feel 历史折叠已实现**。iter 2.0 后 dream 末尾的 feel 历史段按 `surfacing.feel_max_tokens`（默认 6000）做 token 预算，超出的老 feel 折叠为 60 字符单行摘要。原记录「dream 全量返回 feel 历史不限数量」问题已闭合。

6. **`OMBRE_HOST_VAULT_DIR` 的 Docker 挂载改由宿主机 Compose 明确管理**。容器内 Dashboard 只读并给出 `.env` + `--force-recreate` 指令，避免把容器内 `src/.env` 的假保存误认为挂载已改变。

7. **wikilink 配置项已废弃并从 `config.example.yaml` 移除 active stanza**。example 只保留 deprecated 说明，旧配置残留仍会被忽略。

8. **`trace(resolved=1)` 与 `/api/bucket/{id}/resolve` 提示已统一**。两边共用 `resolved_hint()`，REST 返回 `message`，Dashboard 直接展示。

9. **Dashboard 只提供「主动遗忘」「归档」和「删除到档案」**。单桶 DELETE 会移入 `archive/` 并写 `deleted_at`；物理删除 UI 已移除，旧 `/api/buckets/purge` 仅返回 410。

10. **冷启动检测最多 2 个**。`importance >= 8` 的新桶超过 2 个时，第 3 个开始按普通衰减分排队，可能被压在 top-20 后随机洗牌。如果用户一次性钉选 5 条核心准则后又新建 3 个 importance=10 的事件桶，会感到「我刚建的核心事件没浮现」。

11. **Letter 不参与压缩但仍生成 embedding**。原文如果非常长（>2000 字符）embedding 只看前 2000 字符——长信件的语义检索会偏向开头。这是已知 trade-off，未来若需要可改为分段 embedding。

---

## 13. 未来设想（依赖上游 hook 才能落地）

### 13.1 自动上下文注入 (auto-context injection)

让模型在回复用户当前消息**前**自动获得相关历史记忆，无需主动 `breath()`。当前 MCP 协议只有 `SessionStart` hook 在会话开始触发一次，无法对每一轮 user turn 介入。

设计草案：新增 `pre_user_turn` hook → server.py 增 `/turn-hook` 端点 → embedding 取相似度 > 0.6 的 8 条 + decay 取 top 5 高活跃未解决 → 压缩到 ≤120 token 合并为系统提示注入下一轮 → token_budget = `min(2000, 0.1 × context_window)`。

### 13.2 跨会话连续性 token

服务端在 SessionStart 下发 `continuity_token`（上一会话末态摘要 + 未解决议题 ID 列表），客户端 dream 后回写更新。同样依赖 hook 双向通道。

### 13.3 分段 letter embedding

长信件按段落生成多 embedding，检索时合并最高相似度段。需要 SQLite schema 改为支持一对多。

---

*本文档基于代码直接推导，每条断言都可对照源文件函数名验证。代码更新时请同步修订。*
