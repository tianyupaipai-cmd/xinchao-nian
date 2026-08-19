# 心潮·念 3.0.1

![心潮动态心智系统](docs/cover.png)

心潮是一个独立、可自托管的 AI 动态状态层。它在对话之外持续维护驱动力、念头池、疲惫、睡眠、梦境余韵与短期窗口状态，并通过 HTTP API 或远程 MCP 接入不同模型、设备和前端。

> 心潮模拟可解释的动态状态，不宣称产生意识、情感或生命。核心状态机可离线运行；模型、长期记忆、OAuth 和通知均为可选适配器。

## 2.3.x 更新重点

- **HTTP 便签闭环**：补齐 `POST /v1/handoff-note`，HTTP 前端与 MCP 客户端现在使用同一套有界、幂等的短期交接。
- **在场时间修复**：heartbeat 和真实 `xinchao_event` 都会刷新 `lastHeartbeatAt`，避免在线时被自主推送误判为长期离线。
- **隐私版窗口 hook**：提供只发送会话 ID 与随机事件 ID 的 Claude Code 脚本，不上传提示词正文。
- **稳定 MCP 窗口**：初始化时由服务端签发 `Mcp-Session-Id`，不再依赖模型临时编写窗口 ID。
- **近期连续性**：Context Envelope 只携带动态短态、近期交接和可选的长期记忆召回，不替代客户端自己的核心指令或人物基岩。
- **短期交接便签**：`xinchao_handoff_note` 最多 1200 字、默认 72 小时过期，不保存整段聊天原文。
- **远程 MCP + OAuth 2.1**：支持动态客户端注册、授权码 + PKCE、刷新令牌以及标准发现端点。
- **幂等互动结算**：`xinchao_event` 使用 `event_id` 防止网络重试造成重复结算。
- **隐私审计**：转换日志只保存结构化变化、摘要指纹和交付元数据，不保存聊天正文或认证令牌。
- **2200 tokens 默认预算**：用于短期状态和近期连续性；稳定核心资料仍由客户端单独完整读取。

完整差异见 [CHANGELOG.md](CHANGELOG.md)。

## 先分清三个入口

| 入口 | 用途 | 不能拿来做什么 |
| --- | --- | --- |
| `https://xinchaomind.uk` | 公共可视化网页；让用户连接自己已经部署好的心潮 | 不是 MCP 服务，也不会替用户运行心潮 |
| `https://你的心潮域名/mcp` | Claude、ChatGPT 或其他 Agent 的心潮 MCP 连接器 | 不能填写公开网页地址，也不能填写 OB 地址 |
| `OMBRE_MCP_URL` | 心潮服务端内部连接自己的长期记忆后端 | 不公开给网页，不作为心潮连接器地址 |

一句话记忆：**人打开公开网页，AI 连接心潮 `/mcp`，心潮再从服务端内部连接 OB。**
如果出现 `Couldn't register`，先检查填入连接器的是不是完整的心潮 `/mcp` 地址，以及心潮是否开启 MCP/OAuth；不要把 `xinchaomind.uk` 或 OB 的地址填进去。

## 可视化接入地基（开发中）

当前仓库已经把 UI 与状态机拆开，并提供：

- 默认脱敏的十二维 Dashboard Snapshot；
- 不含正文的结构化潮汐时间线；
- 面向网页 AI、本地 Agent、手机网页与自建后端的接入清单；
- 独立 Dashboard 口令换取 HttpOnly 会话，浏览器无需接触 `SERVICE_TOKEN`；状态投影只读，小屋仅开放明确的留言、锁与账本写入；
- 独立 [`Wake Bridge`](packages/wake-bridge/) 消息信封协议，为梦境余韵、思念内容和自主行动结果预留用户/AI 双通道。

接口、环境变量和前端示例见 [可视化与多终端接入地基](docs/DASHBOARD-INTEGRATION.md)。视觉主题、花瓣与梦境星云可以独立迭代，不需要重写服务端。

如果要把心潮建设成公开可注册、每人连接自己 AI 的服务，请先阅读 [多人平台 V1 产品与数据契约](docs/MULTI-TENANT-PLATFORM.md)。多人账号、小屋、数据库和任务调度属于独立平台层，不会侵入核心状态计算。

## 支持哪些终端

只要终端支持以下任一方式即可接入：

- 标准远程 Streamable HTTP MCP；
- OAuth 2.1 远程 MCP；
- 能发送 Bearer HTTP 请求的自建前端、桌面端或移动端；
- 通过自己的中间层访问 HTTP API 的 iOS、Android 或其他设备。

心潮不绑定 Claude。Claude、Codex、其他 Agent、自建网页和移动应用可以共享同一个服务端，但每条 MCP 连接会获得独立窗口会话。

## 核心能力

- 十二维驱动力与时间增长规则。
- 闪念、执念、衰减和意图选择。
- 疲惫、睡眠、梦境余韵与清晨冻结。
- 窗口短态与定时过期。
- 有界语义互动反馈，客户端不能直接提交驱动力数值。
- 可选 OpenAI-compatible 模型。
- 可选 Ombre-compatible 长期记忆 MCP。
- 可选 Bark 通知与跨类型去重。
- 原子状态持久化与结构化转换日志。

## 快速开始

要求：Node.js 20 或更高版本。

```bash
cp .env.example .env
openssl rand -hex 32
# 将输出填入 .env 的 SERVICE_TOKEN
npm test
npm start
```

检查服务：

```bash
curl http://127.0.0.1:18110/health
```

Docker：

```bash
cp .env.example .env
mkdir -p state memory-data
docker compose up -d --build
docker compose ps
```

Compose 默认只映射到 `127.0.0.1:18110`。远程使用时请自行配置 HTTPS 反向代理或 Cloudflare Tunnel，不能直接开放裸端口。

## 远程 MCP

在 `.env` 中启用：

```env
MCP_ENABLED=true
OAUTH_ENABLED=true
OAUTH_PUBLIC_BASE_URL=https://xinchao.example.com
OAUTH_APPROVAL_TOKEN=至少16位的独立授权口令
```

远程 MCP 地址：

```text
https://xinchao.example.com/mcp
```

支持动态客户端注册的客户端不需要手动填写 Client ID 或 Client Secret。授权口令只在你自己的授权页面输入，不要写入客户端 URL、仓库或截图。

### MCP 工具

| 工具 | 作用 |
| --- | --- |
| `xinchao_context` | 获取当前动态短态和近期连续性；同一窗口首次启动默认只交付一次 |
| `xinchao_event` | 回传一次明确互动及有界窗口状态；`event_id` 用于幂等 |
| `xinchao_handoff_note` | 保存限时近期进度摘要，不保存整段聊天原文 |
| `xinchao_cabin_inbox` | 读取用户明确开锁的小屋来信；上锁正文永不返回 |
| `xinchao_cabin_note` | AI 主动给用户的小屋留一封信或便签 |

`session_id` 是可选覆盖值。正常情况下服务端会使用 MCP 连接自带的稳定窗口 ID。

## HTTP API

除 `/health` 与 OAuth 发现/授权端点外，业务 API 都要求：

```http
Authorization: Bearer <SERVICE_TOKEN>
```

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/health` | 健康状态与版本 |
| `GET` | `/v1/state` | 读取完整动态状态 |
| `GET` | `/v1/intent` | 读取当前意图 |
| `GET` | `/v1/breath-context` | 获取紧凑梦境余韵 |
| `GET` | `/v1/context` | 获取 Context Envelope |
| `POST` | `/v1/settle` | 执行状态结算 |
| `POST` | `/v1/conversation-event` | 写入一次明确互动事件 |
| `POST` | `/v1/heartbeat` | 只刷新在场时间，不上传聊天正文 |
| `POST` | `/v1/handoff-note` | 保存短期交接摘要 |
| `POST` | `/v1/drive-feedback` | 管理端受控反馈接口 |
| `GET` | `/v1/dashboard/snapshot` | 默认脱敏的可视化状态投影 |
| `GET` | `/v1/dashboard/timeline` | 结构化变化时间线（无正文） |
| `GET` | `/v1/dashboard/memory-map` | 从自己的 OB 读取脱敏记忆星图元数据 |
| `GET` | `/v1/dashboard/connect` | 多端接入能力清单（无凭据） |
| `POST` | `/mcp` | Streamable HTTP MCP |

### 私密小屋接口

小屋数据单独写入 `CABIN_STATE_PATH`（默认 `/app/state/cabin.json`），只保存用户或 AI
明确提交的来信和账本记录，不保存聊天原文、提示词或密钥。网页使用 Dashboard 的
HttpOnly 会话访问：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/dashboard/api/cabin` | 读取来信、未读数量、账本与汇总 |
| `GET` | `/dashboard/api/snapshot` | 读取花瓣、状态与可选的真实一句话 |
| `GET` | `/dashboard/api/memory-map` | 从这位用户自己的 OB 读取记忆星图元数据 |
| `POST` / `PATCH` | `/dashboard/api/cabin/note` | 留信、标为已读、上锁或开锁 |
| `POST` / `PATCH` / `DELETE` | `/dashboard/api/cabin/ledger` | 新增、编辑或删除账本记录 |

用户来信默认上锁：连接桥只会通知 AI“有一封信”，不会携带正文。用户主动开锁后，
AI 才能通过 `xinchao_cabin_inbox` 读取。重新上锁只会阻止之后的读取，无法撤回 AI
已经读过的内容。

花瓣旁的“一句话”只取自当前心潮自己的思绪池，不使用演示文案，也不会由网页猜测。
考虑到它与梦境正文都可能包含私密内容，默认不会返回；自托管者明确设置
`DASHBOARD_INCLUDE_PRIVATE_TEXT=true` 后，才会通过已鉴权的 Dashboard 会话展示。

## 心跳接入档位

heartbeat 与 `breath` 的定位不同：`breath` 是可能返回上下文的按需记忆检索；heartbeat 只发送 `session_id` 和不透明的 `event_id`，不上传提示词或回复、不注入模型上下文，因此本身不消耗上下文 token。档位差异只影响实时性和网络请求量：

- **实时档**：本地 Claude Code、Max 或具备生命周期 hook 的前端，可在每次提交消息时上报。
- **均衡档**：希望降低请求量时设置 120–300 秒最小间隔；这不是为了节省上下文。
- **兼容档**：Claude.ai 普通连接器、手机或无 hook 前端，在会话开始调用 `xinchao_context`，明确互动后调用 `xinchao_event`，服务端应配置更宽的离线阈值。

Claude Code 可使用仓库中的 [`scripts/xinchao-heartbeat-hook.sh`](scripts/xinchao-heartbeat-hook.sh)。脚本读取 hook 输入后只保留 `session_id`，主动丢弃 `prompt`。不要直接把 `UserPromptSubmit` 配成指向心潮的原始 HTTP hook，否则客户端可能把包含提示词的完整 hook JSON 发送出去。

本机私有 `.claude/settings.local.json` 示例：

```json
{
  "env": {
    "XINCHAO_SERVICE_TOKEN_FILE": "/absolute/private/path/xinchao.service-token",
    "XINCHAO_HEARTBEAT_URL": "https://xinchao.example.com/v1/heartbeat",
    "XINCHAO_HEARTBEAT_MIN_INTERVAL_SECONDS": "0"
  },
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/scripts/xinchao-heartbeat-hook.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

token 文件应放在仓库外并设为 `0600`；私有设置不要提交。均衡档将最小间隔改成 `120` 或 `300`。

## 长期记忆边界

长期记忆不是心潮的必需组件。启用外部记忆时：

```env
OMBRE_MCP_URL=https://memory.example.com/mcp
OMBRE_MCP_TOKEN=
OMBRE_READ_ENABLED=false
OMBRE_WRITE_ENABLED=false
CONTEXT_OMBRE_ENABLED=false
```

- 只要开启 `OMBRE_READ_ENABLED`、`OMBRE_WRITE_ENABLED` 或
  `CONTEXT_OMBRE_ENABLED`，`OMBRE_MCP_URL` 与 `OMBRE_MCP_TOKEN` 就都必须填写；
  缺少任一项时服务会拒绝启动，避免在后台持续产生 401。
- `OMBRE_MCP_TOKEN` 是外部记忆 MCP 接受的服务端 Bearer 凭据，不是 Dashboard
  登录密码。它只能放在心潮服务端 `.env`，不能写入前端、URL 或 Git 仓库。
- 心潮只请求近期连续性，不用短 handoff 替代客户端的稳定核心资料。
- 自动梦境写入会明确标记为自动来源。
- 技术日志、密钥、OAuth 状态和聊天原文不应进入长期人物记忆。
- 所有外部读写默认关闭，按最小权限逐项启用。

## 数据与安全

- 不要提交 `.env`、`state/`、`memory-data/`、OAuth 状态或真实 Token。
- `SERVICE_TOKEN`、`MCP_PATH_TOKEN` 与 `OAUTH_APPROVAL_TOKEN` 必须彼此独立。
- 服务默认绑定回环地址、使用只读容器、移除 Linux capabilities。
- Context audit 只记录摘要与交付元数据。
- Dashboard 使用与服务密钥不同的访问口令，并只签发 HttpOnly、SameSite 会话 Cookie。
- Dashboard 默认隐藏梦境摘要和余韵文字；需要由自托管者显式开启。
- `xinchao_event` 不接受聊天正文；交接便签也只应保存脱水后的近期进度。
- 公开部署前请阅读 [SECURITY.md](SECURITY.md)。

## 测试

```bash
npm test
```

当前测试覆盖状态结算、睡眠与醒来、念头池、窗口隔离、幂等互动、Context Envelope、交接便签、OAuth、MCP 协议、外部记忆适配、通知去重和隐私审计。

## 项目结构

```text
src/             状态机、MCP、OAuth、Dashboard 投影与可选适配器
test/            Node.js 原生测试
configs/         可替换提示词
scripts/         本地配置、部署与烟雾测试
packages/        可独立使用的 Wake Bridge 消息协议
state/           运行状态挂载目录（不提交真实数据）
memory-data/     可选外部心跳挂载目录
```

## License

[MIT](LICENSE)
