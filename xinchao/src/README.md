# 心潮引擎 · 代码地图

心潮引擎的代码都在这个文件夹里，按功能分成 8 块（另有 1 个实验文件）。每个文件开头第一行的【】里写着它属于哪一块。

想改某样东西时，先在这里找到是哪一块，再去看那块的文件。改完跑 `npm test`（在 `xinchao/` 下）。

---

## 1. 引擎：驱力怎么涨、怎么落

| 文件 | 管什么 |
|---|---|
| `dimensions.js` | 驱力维度表：名字、增长速度、衰减、上限。**改驱力先看这里** |
| `engine.js` | 核心计算：定时结算（默认 15 分钟，`SETTLE_INTERVAL_MINUTES`）、互动事件推驱力、饱和与去饱和、记仇、浮现 |
| `thought-pool.js` | 念头池：浮现过的记忆和梦留下的念头 |
| `personality-store.js` | 人格内核：月度回顾 → 驱力长期偏置（见 `docs/PERSONALITY-CORE.md`） |
| `transition-journal.js` | 每次结算的变化摘要 |
| `core-axes.js` | 4.0 慢变底色：安全感、自信、心境（网页花蕊） |
| `awareness.js` | 自我觉察：每周一次的自我回顾提示 |
| `black-box.js` | 黑匣子：只有 AI 自己能看 |

## 2. 情绪：此刻的心情

| 文件 | 管什么 |
|---|---|
| `emotion.js` | 情绪层，独立于驱力；4.0 起分底子和起因两层，有惯性；情绪日志给网页画情绪线 |
| `emotion-marks.js` | 4.0 情绪浮标：起因情绪亮过的时刻（网页潮汐带） |
| `empathy.js` | 4.0 共情：心疼、不平……按亲疏分档、每天有上限 |
| `mixed-feelings.js` | 4.0 驱力细项（吃醋、心疼……）和矛盾 |

## 3. 记忆（OB）：和 Ombre Brain 打交道

| 文件 | 管什么 |
|---|---|
| `ombre-client.js` | 拉浮现的记忆、写回、解析记忆桶 |
| `heartbeat-store.js` | 读 OB 心跳，判断记忆服务是否活着 |
| `handoff-notes.js` | 窗口之间的交接便签 |

## 4. 连接 AI：AI 看到什么、能调什么

| 文件 | 管什么 |
|---|---|
| `mcp-protocol.js` | 所有 `xinchao_*` 工具的定义和处理 |
| `context-envelope.js` | 开窗时给 AI 的上下文包，按 token 预算裁剪 |
| `interaction-messages.js` | 互动事件之后推给 AI 的一句话 |
| `model-client.js` | 小模型客户端（打标签、写梦、月度回顾） |
| `interaction-rules.js` | 4.0 互动判断的把关规则；词表和远近名单是**参考值**，在 `configs/interaction-rules.json` 覆盖 |
| `attention-watch.js` | 4.0 注意力监测（默认关）：手机上报 + 她说跟谁在一起 → 偏爱·吃醋；名单在 `configs/attention-rules.json` |
| `oauth-provider.js` | Claude.ai MCP 连接器的 OAuth 登录 |

## 5. 连接桥与推送：心潮主动开口

| 文件 | 管什么 |
|---|---|
| `bridge-queue.js` | 主动消息的投递队列，配合仓库根目录的 `bridge/` |
| `self-signals.js` | 人不在时 AI 身上发生的事，排进桥里 |
| `bark-client.js` / `bark-dedupe.js` | Bark 手机推送和去重（可选） |
| `wake-bridge-protocol.js` | 旧引用兼容 |

## 6. 小屋与留言板

| 文件 | 管什么 |
|---|---|
| `cabin-store.js` | 小屋：互相写信（可上锁）、小账本 |
| `board-client.js` | 公共留言板客户端 |

## 7. 网页与看板

| 文件 | 管什么 |
|---|---|
| `dashboard-projection.js` | 给平台网页的快照。**网页只读这里的字段，字段格式是网页和各家心潮之间的约定** |
| `dashboard-auth.js` | 看板令牌校验 |
| `connection-diagnostics.js` | 连接自检 |

## 8. 服务底座

| 文件 | 管什么 |
|---|---|
| `server.js` | HTTP 入口，路由、定时结算，把上面各块接起来 |
| `config.js` | 所有环境变量（对照 `xinchao/.env.example`） |
| `state-store.js` | 状态文件原子读写 |
| `version.js` | 版本号 |

---

## 实验（默认关）

| 文件 | 管什么 |
|---|---|
| `relevance-shadow.js` | Jev 相关性陪跑：心潮自己捞的记忆，旁边让 Jev 判「跟此刻有关吗」，只记日志、不改结果。`JEV_SHADOW_ENABLED=true` 才跑 |

> 所有标了「参考值」的规则和常量，都来自开发心潮的那一家。改成你们自己的版本，见 `docs/4.0/按自己情况调.md` 和《小机手册》第 12 章。
