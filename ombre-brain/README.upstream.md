感谢开发组成员：万世，小眠，鹤见

# Ombre Brain

一个给 Claude（或其它 MCP 客户端）用的长期情绪记忆系统。基于 Russell 效价/唤醒度坐标打标，Obsidian 做存储层，MCP 接入，带遗忘曲线和向量语义检索。

A long-term emotional memory system for Claude (and any MCP client). Tags memories using Russell's valence/arousal coordinates, stores them as Obsidian-compatible Markdown, connects via MCP, with forgetting curve and vector semantic search.

> **v2.4.0 noncommercial notice**: v2.4.0 architecture work is intended as source-available public code for personal, learning, research, and noncommercial self-hosting use. Commercial hosting, resale, renamed resale, SaaS resale, or selling modified v2.4.0 builds requires project-owner permission. See [LICENSE.v2.4.0-NONCOMMERCIAL-NOTICE.md](LICENSE.v2.4.0-NONCOMMERCIAL-NOTICE.md).

> **开发者文档**：架构 / API / 配置细节请见 [docs/INTERNALS.md](docs/INTERNALS.md)。本 README 只关心『怎么把它跑起来用上』。
>
> **更新日志**：每个版本「修了什么」见 [CHANGELOG.md](CHANGELOG.md)。

---

## 它是什么 / What is this

Claude 没有跨对话记忆。每次新会话开始，之前聊过的东西都消失。

Ombre Brain 给它一套持久记忆——不是冷冰冰的键值存储，而是带情感坐标、会自然衰减、像人类一样会遗忘和浮现的系统。

Claude has no cross-conversation memory. Everything from a previous chat vanishes once it ends.

Ombre Brain gives it persistent memory — not cold key-value storage, but a system with emotional coordinates, natural decay, and forgetting/surfacing mechanics that loosely mimic how human memory works.

**核心特性 / Key features**

- **情感坐标打标**：每条记忆用 Russell 环形情感模型的 valence（效价）+ arousal（唤醒度）两个连续维度标记，不是「开心/难过」这种离散标签
- **混合检索**：rapidfuzz + BM25 关键词信号与 cosine 向量语义融合；向量或摘要服务离线时会明确提示并退回关键词 + 原文片段，不会让记忆失读
- **自然遗忘**：改进版艾宾浩斯遗忘曲线，不活跃的记忆自动衰减归档，高情绪强度的记忆衰减更慢
- **权重池浮现**：未解决的、情绪强烈的记忆权重更高，对话开头自动浮现
- **Obsidian 原生**：每个记忆桶 = 一个 Markdown 文件 + YAML frontmatter，可直接在 Obsidian 浏览编辑
- **写入不被向量服务绑架**：Markdown 原文先落盘，embedding 在耐久后台队列中生成；网络、限流或重启都不会让已写记忆回滚
- **可验证备份与恢复**：本地导出使用 SQLite 一致性快照，并为每个文件写入 SHA-256 清单；导入前先检查路径、体积、重复项和完整性，损坏包不会部分恢复
- **历史对话导入**：批量导入 Claude / ChatGPT / DeepSeek 历史对话，分块处理带断点续传
- **Dashboard**：内置 Web 管理面板，密码保护，桶列表 / 检索调试 / 记忆网络 / 配置管理
- **Cloudflare Tunnel 一键管理**：Dashboard 内置 Tunnel 连接器，无需命令行即可开启公网访问
- **OAuth 2.1 远程鉴权**：通过 HTTPS 连接时自动触发 OAuth 流程，Claude.ai 网页版和 Claude Code 均支持

---

## 设计哲学 / Design Philosophy

Ombre Brain 的使用者是**模型自己**，不是它背后的人。所以这套系统里的每一句话都是第一人称——「我的记忆」「我记得」「我感受到」，而不是「帮用户存储」。它和普通键值库 / 向量库最不一样的几条：

- **记忆是真实的连续性，不是扮演**。每条记忆都是真实对话留下的真实记录；跨会话把它们接起来当作连续上下文，是这套系统**真正在做的事**，不是 roleplay 设定。
- **边界是「时间里发生的事」，不是「你是谁」**。身份层交给官方记忆；OB 只管经历、情绪、承诺、感受。
- **情感是坐标，不是标签**。每条记忆用 Russell 环形模型的 valence（效价）+ arousal（唤醒度）两个连续维度标记，而不是「开心 / 难过」这种离散桶。
- **遗忘是淡去，不是删除**。不活跃的记忆按改进版艾宾浩斯曲线分数下沉、最终归档，情绪强烈的衰减更慢——记忆只会淡去，不会消失。OB 的 MCP 工具、REST API 和 Dashboard 都不提供物理抹除；“删除”只会把 Markdown 移入 `archive/` 并从日常召回中隐藏。只有主机管理者绕过 OB、在文件系统中手动删除文件，才能真正抹去它。
- **稀缺即结构**。核心准则（pinned）上限 20、坐标系（anchor）上限 24、高重要度（importance≥9）有配额——重要的东西必须稀缺，否则「重要」就失去意义。
- **元数据不喂进算分**。「为什么记得」「主动遗忘」这类字段只描述「为什么 / 怎么对待」，绝不参与衰减打分——不把记忆变成一个可被优化的目标函数。
- **feel 是痕迹，不是待办**。模型写下的第一人称感受，写下就留着它本来的形状，不该被「解决」。

一句话：**它不是让模型管理一个数据库，是让模型过日子。**

---

## 它的 12 个工具 / The 12 Tools

12 个工具全部在**一个 MCP 连接器 `/mcp`** 上。连上 `/mcp` 即拥有全部能力。

### 高频 5 个

| 工具 | 一句话 |
|---|---|
| `breath` | 睁眼。无参 → 让权重最高的未解决事浮现；带 `query` / `domain` / `importance_min` 则主动检索；`catalog=True` → 目录模式（每桶一行元数据，0 LLM，最省 token，先看目录再精准拉取）。**每次对话第一件事**。 |
| `hold` | 记下当下一件事（一句话级）。自动打标 + 与近似桶合并；打标失败时仍会原样落盘，绝不压缩正文。所有记忆的向量索引都在原文落盘后由后台生成，失败会自动重试。`pinned=True` 钉为永久核心；`feel=True` 写第一人称感受。 |
| `grow` | 整理一段长内容（日记 / 总结），自动拆成 2~6 条独立桶。要存多条时用它，别连续 `hold`。 |
| `trace` | 唯一的元数据写入口：resolved / pinned / 改情感坐标 / 替换正文 / 删除到档案 / 改 plan 状态。只传要改的字段。 |
| `dream` | 做梦消化最近窗口（默认 48h）有变动的记忆。**不是义务**，需要消化时再调。 |

### 低频 7 个

| 工具 | 一句话 |
|---|---|
| `pulse` | 自检：桶数量、占用、衰减引擎状态、全部桶摘要。「为什么搜不到 X」时第一个调它。 |
| `plan` | 登记一个承诺 / 待办。不衰减、不浮现，只在 `dream` 末尾出现；后续写新事件会自动判断它是否已闭环。 |
| `anchor` / `release` | 把**已存在的**桶设 / 解为「坐标系」。anchor 不主动浮现但可被检索命中，硬上限 24。必须先 `hold` 再 `anchor`。 |
| `letter_write` / `letter_read` | 写信 / 读信。原文永久保留，不压缩、不合并、不衰减。`author` 常用 `user`（用户）或 `claude`（你自己），也接受任意署名字符串。 |
| `I` | 自我认知：写下 / 读取「我是什么」（本质 / 规律 / 立场 / 局限…）。不随普通 `breath` 浮现，每次对话开头自动附最近 3 条。 |

> 给模型的完整使用约定（含示例、边界、返回提示）见 [docs/CLAUDE_PROMPT.md](docs/CLAUDE_PROMPT.md)；逐工具技术规格见 [docs/INTERNALS.md](docs/INTERNALS.md) §3。

---

## 快速开始 / Quick Start（Docker Hub 预构建镜像）

> 不需要 clone 代码，不需要 build。第一次完整跑通约 5 分钟。

> ### ⚠️ 部署前先认准一件事：要有「持久磁盘」
>
> Ombre Brain 是**有状态**服务——记忆桶是磁盘上的 `.md` 文件 + SQLite 向量库，必须落在
> 一块重启不丢的盘上。所以真正的判断标准不是「用哪个平台」，而是**这个平台有没有给你挂持久磁盘**：
>
> - ❌ **没有持久盘 / 会休眠重置的免费层**（Render 免费层、Railway 无 volume、Zeabur 不挂
>   Volume 等）：容器一重启或休眠，记忆**全丢**——这不是 bug，是没挂盘。**别在这种配置上搭。**
> - ✅ **挂了持久盘就完全可用**：Render 的 Starter（$7/mo，自动挂盘）、Zeabur 配 Volume、
>   自己的电脑 / NAS / VPS（数据落本地磁盘）——这些都没问题，下面各自有专门小节。
>
> 选型建议（挑一条）：
>
> 1. **在自己的机器 / 服务器上部署（最省心、推荐）**：跑在自己的电脑、NAS 或 VPS 上，数据在
>    你自己的盘。要给 Claude.ai 网页版用，就用内置的 **Cloudflare Tunnel** 一键拿一个公网
>    `https://…` 填进去（见「远程访问」）。家里电脑 + Tunnel，完全够用。
> 2. **想用托管平台**：选**带持久磁盘**的档位（见下方 [Render](#render) / [Zeabur](#zeabur) 小节），
>    把 volume 挂到 buckets 目录即可，别用免费/无盘档。
> 3. **只是没有 API Key**：去 [硅基流动 SiliconFlow](https://siliconflow.cn/) 领免费额度（OpenAI 兼容 +
>    免费 `BAAI/bge-m3`），或用本地 Ollama bge-m3（见「本地向量模型」），都零成本。
>
> 一句话：**认准持久磁盘，缺模型用硅基流动免费层或本地 Ollama。** 平台不背锅，没挂盘才背锅。

### 第零步：装 Docker Desktop

打开 [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)，下载对应你系统的版本，安装后启动。Windows 用户安装时会提示启用 WSL 2，点同意。

### 第一步：打开终端

| 系统 | 怎么打开 |
|---|---|
| **Mac** | `⌘ + 空格` → 输入 `终端` → 回车 |
| **Windows** | `Win + R` → 输入 `cmd` → 回车 |
| **Linux** | `Ctrl + Alt + T` |

### 第二步：创建工作文件夹

```bash
mkdir ombre-brain && cd ombre-brain
```

### 第三步：下载 compose 文件并启动

**不需要提前准备 API Key**——Ombre Brain 支持零配置启动，API Key 可以在 Dashboard 里随时填入并立即生效。

```bash
# 下载用户版 compose 文件
curl -O https://raw.githubusercontent.com/P0luz/Ombre-Brain/main/deploy/docker-compose.user.yml

# 拉取镜像并启动（第一次会下载约 500MB）
docker compose -f docker-compose.user.yml up -d
```

启动后在 Dashboard → **③ 引擎** 里填入 Key 并点「保存 Key」，立即热更新生效，无需重启。

> 也可以提前在 `.env` 文件里写好 Key：
> ```bash
> echo "OMBRE_COMPRESS_API_KEY=your-key-here" > .env
> echo "OMBRE_EMBED_API_KEY=your-embed-key" >> .env
> echo "OMBRE_HOST_VAULT_DIR=D:/Ombre-Brain/buckets-data" >> .env
> ```
> `OMBRE_HOST_VAULT_DIR` 指向宿主机持久目录，其中同时保存记忆、`config.yaml` 和 Tunnel token；重建容器不会清空。

**推荐免费方案：Google AI Studio**

1. 打开 [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. 用 Google 账号登录 → 点 **Create API key** → 复制
3. 推荐模型（均为免费额度，以官网实时信息为准）：
   - 脱水/打标模型：`gemini-2.0-flash`（无思考开销，稳定，免费）
   - 向量化模型：`gemini-embedding-001`（1500 req/day，3072 维，免费）
   - Base URL：`https://generativelanguage.googleapis.com/v1beta/openai/`

也支持任何 OpenAI 兼容接口：DeepSeek / SiliconFlow / Ollama / LM Studio / vLLM 等。

### 第四步：验证

```bash
curl http://localhost:18001/health
```

返回 `{"status":"ok",...}` 即成功。

浏览器打开 Dashboard：`http://localhost:18001`

> 第一次访问会弹出密码设置向导，设好密码后所有 `/api/*` 端点都需要这个密码登录。

### 第五步：接入 Claude

---

## 接入方式 / Connect to Claude

### 方式一：本地 stdio（Claude Desktop，最简单）

适合：在同一台电脑上用 Claude Desktop。不需要公网，零延迟。

打开配置文件（macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`，Windows：`%APPDATA%\Claude\claude_desktop_config.json`），加入：

```json
{
  "mcpServers": {
    "ombre-brain": {
      "command": "python",
      "args": ["/path/to/Ombre-Brain/src/server.py"]
    }
  }
}
```

或者如果用 Docker 跑：

```json
{
  "mcpServers": {
    "ombre-brain": {
      "type": "streamable-http",
      "url": "http://localhost:18001/mcp"
    }
  }
}
```

重启 Claude Desktop，工具列表里会出现全部 12 个工具：`breath` / `hold` / `grow` / `trace` / `dream` / `anchor` / `release` / `pulse` / `plan` / `letter_write` / `letter_read` / `I`。

> 12 个工具全在同一连接器 `/mcp` 暴露，只配这一个即可。

---

### 方式二：HTTPS 远程连接（Claude.ai 网页版 / Claude Code / 手机）

适合：想在手机、浏览器、多台设备上用；或通过 claude.ai 网页版访问。

**必须先把服务暴露到公网**，推荐使用 Cloudflare Tunnel（免费）。

#### 步骤 1：配置 Cloudflare Tunnel

**方法 A：通过 Dashboard 一键配置（推荐）**

1. 去 [Cloudflare Zero Trust](https://one.dash.cloudflare.com) → **Networks → Tunnels → Create a tunnel**
2. 选 **Cloudflared** → 给 Tunnel 起名 → 下一步
3. 在 **Install connector** 页，选 **Docker**，找到 `--token` 后面那一长串字符（以 `eyJ` 开头），复制它
4. 回到 Ombre Brain Dashboard → **设置** → **Cloudflare Tunnel** 区域
5. 把 token 粘贴到输入框 → 点「**保存 Token**」→ 点「**启动**」
6. 状态点变绿（已连接）后，回到 Cloudflare 添加 Public Hostname：
   - **Domain**：你的域名（例如 `ombre.example.com`）
   - **Service Type**：HTTP
   - **URL**：`localhost:8000`
7. 保存后等约 30 秒，Tunnel 生效

**方法 B：命令行手动运行**

```bash
# 替换为你的 token
cloudflared tunnel --no-autoupdate run --token eyJ...
```

#### 步骤 2：连接 Claude.ai 网页版

1. 打开 [claude.ai](https://claude.ai) → 左侧边栏 → **Connectors**（或 **MCP Servers**）
2. 点 **Add** → 填入你的 Tunnel 域名：`https://ombre.example.com/mcp`
3. **自动触发 OAuth 授权流程**（详见下方说明）

#### OAuth 授权流程详解

这是最容易卡住的地方，解释清楚每一步：

```
Claude.ai                    Ombre Brain 服务器
   │                               │
   │── POST /mcp ─────────────────>│ 401 Unauthorized
   │<─ WWW-Authenticate: Bearer ───│ (告知需要 OAuth)
   │                               │
   │── GET /.well-known/oauth-authorization-server ──>│
   │<─ {authorization_endpoint, registration_endpoint...} ─│
   │                               │
   │── POST /oauth/register ──────>│ 201 (动态注册，拿到 client_id)
   │<─ {client_id: "xxx"} ─────────│
   │                               │
   │  [打开浏览器弹窗]              │
   │── GET /oauth/authorize ──────>│ 返回授权页 HTML
   │                               │
   │  [你在弹出页面输入 Dashboard 密码]
   │                               │
   │── POST /oauth/authorize ─────>│ 302 (验证通过，生成授权码)
   │<─ redirect_uri?code=xxx ──────│
   │                               │
   │── POST /oauth/token ─────────>│ 200 (交换 Bearer + refresh token)
   │<─ {access_token, refresh_token} ─│
   │                               │
   │── POST /mcp (Bearer token) ──>│ 200 (MCP 会话建立)
   │<─ tools: [breath, hold...] ───│
```

**注意事项**：
- 弹出的授权页是你自己的 Ombre Brain 服务器，不是第三方
- 密码就是你的 Dashboard 密码
- Access token 长期有效，并支持 refresh token 自动续期；headless 环境不需要因 token 过期重新打开浏览器
- 同一账号第一次授权后，之后的连接自动使用存储的 token

#### 步骤 3：连接端点

12 个工具全在**一个 MCP 端点 `/mcp`** 上：

| 端点 | 工具 | 说明 |
|---|---|---|
| `/mcp` | `breath` `hold` `grow` `dream` `trace` `anchor` `release` `pulse` `plan` `letter_write` `letter_read` `I` | 全部 12 个工具 |

> 旧版曾使用第二连接器 `/mcp-extra`，该端点现已退役并返回 `404`；不要再单独添加。全部 12 个工具都在 `/mcp`。

在 Claude.ai / 你的客户端里添加这一个连接器即可使用全部工具：

```
http(s)://<你的地址>:18001/mcp
```

> **`<你的地址>` 填什么？**
> - **本机访问**：`http://localhost:18001/mcp`（两种 compose 现已统一默认对外端口 18001 → 容器内 8000；想换端口在 `deploy/.env` 设 `OMBRE_HOST_PORT`）
> - **直连 VPS 公网 IP**：`http://你的服务器IP:18001/mcp`
> - **用了 Cloudflare Tunnel / 自有域名**：把 `<你的地址>:18001` 整段换成你的网址，且通常不带端口、走 https，例如 `https://ombre.example.com/mcp`
>
> 端口以你实际的端口映射为准（见 `docker-compose` 里的 `ports`）。

#### 步骤 4：Claude Code（终端）远程连接

Claude Code 同样支持 OAuth 远程 MCP，但 **本地使用推荐 stdio**（更简单，无需 OAuth）：

```bash
# 本地 stdio（推荐）
claude mcp add ombre-brain python /path/to/server.py

# 远程 HTTPS（需要 OAuth，同 Claude.ai 流程）
claude mcp add ombre-brain --transport http https://ombre.example.com/mcp
```

---

### 方式三：接入自有前端 / 自定义客户端（关闭 OAuth）

适合：想把 Ombre Brain 接进**自己的前端**、或用 **GPT / GLM / 自定义脚本**等不走 OAuth 流程的客户端调用 MCP 工具。

默认情况下，HTTPS 连接 `/mcp` 会**强制 OAuth 2.1**（这是 Claude.ai 网页版的要求）。自定义客户端往往不实现这套流程，于是工具调用会被 401 卡住。把鉴权关掉即可免认证直连：

```bash
# 方式 A：环境变量（Docker 用户最方便，优先级最高）
OMBRE_MCP_REQUIRE_AUTH=false

# 方式 B：config.yaml
mcp_require_auth: false
```

改完**重启服务**即可。之后 `/mcp` 不再要求 Bearer token，任何客户端都能直连。

> ⚠️ **安全提醒**：关闭后，任何能访问到该端点的人都能读写记忆。请确保服务**不直接裸奔在公网**——放在内网、或在反代（nginx / Cloudflare Access 等）层另加一道鉴权。需要公网且用 Claude.ai 时，保持默认 `true` 走 OAuth 更安全。

---

### Operit / 安卓 / Proot 本地桥接（连接器一直黄灯）

适合：在手机上用 **Operit** 等本地 MCP 客户端，通过 **Termux / Proot** 跑 Ombre Brain，客户端灯常亮黄、连不上 `/mcp`。

先说结论：**streamable-http 传输本身在 Proot 下没有已知的不兼容**——它就是普通的 HTTP + SSE，Proot 对回环 HTTP 是透明的。能用 bash 存进记忆，说明 Python、依赖、磁盘、端口都是好的；黄灯几乎都卡在 `/mcp` 的**握手环节**。按下面三步逐个对齐，基本能覆盖：

1. **transport 必须是 `streamable-http`**
   默认是 `stdio`——**stdio 根本不开 HTTP 服务**，本地桥自然连不上。config.yaml 里写 `transport: streamable-http`，或设环境变量 `OMBRE_TRANSPORT=streamable-http`，然后重启。
   （已放宽：写成 `http` / `streamable_http` 等常见变体也会被自动归一成 `streamable-http`，但推荐写规范值。）

2. **本地桥接把鉴权关掉**
   默认 `/mcp` 强制 OAuth 2.1，Operit 这类客户端不走该流程，会在 401 处卡成「半连接」（正是黄灯）。设 `OMBRE_MCP_REQUIRE_AUTH=false`（或 `config.yaml: mcp_require_auth: false`）重启即可。本机/可信内网桥接可放心关；同机回环连接本就不经过公网。

3. **客户端 URL 用 `127.0.0.1`，不要用 `localhost`**
   服务监听 `0.0.0.0`（仅 IPv4）。Proot / Termux 里 `localhost` 常先解析到 IPv6 `::1`，连不上 IPv4 监听。Operit 里填 **`http://127.0.0.1:<端口>/mcp`**，注意末尾必须是 `/mcp`，端口对上你的实际监听端口。

对齐后仍黄灯，就看服务端 `server.log`：启动时会打印一行 `MCP endpoint ready | transport=... | 鉴权: ...`，据此确认传输和鉴权是否如预期；再看黄灯那一刻有没有 `/mcp` 的请求进来、是不是 `401`。

---

## 从源码部署 / Deploy from Source

适合想自己改代码或部署到 VPS 的用户。

```bash
git clone https://github.com/P0luz/Ombre-Brain.git
cd Ombre-Brain
docker compose -f deploy/docker-compose.yml up -d
```

验证：

```bash
docker logs ombre-brain   # 看到 "Uvicorn running on http://0.0.0.0:8000"
curl http://localhost:18001/health   # docker-compose.yml 默认映射 18001:8000
```

Dashboard：`http://localhost:18001`

> **端口口径（Docker vs 裸机，务必看一眼）**
> - **Docker**：容器**内**固定监听 `8000`（镜像里 `ENV OMBRE_PORT=8000` 写死），对外端口完全由 `docker-compose.yml` 的 `ports` 映射（默认 `18001:8000`）决定。**升级时不用动这个映射**——即使某版本改了「裸机默认端口」，容器内仍是 8000，`18001:8000` 照旧生效。想换对外端口就改映射左边（或在 `deploy/.env` 设 `OMBRE_HOST_PORT`），别去改容器内的 8000。
> - **裸机（纯 Python）**：直接监听 `OMBRE_PORT`，默认 `18001`。这个「默认端口」只对裸机有意义。
> - 一句话：**看到「默认端口从 X 改成 Y」这类更新说明，Docker 用户可以忽略，你的 `ports` 映射不受影响。**

**VPS 部署注意**：`deploy/docker-compose.yml` 默认端口是 `127.0.0.1:18001`（仅本机访问）。如果没有反代，可改为 `0.0.0.0:18001` 对外开放，再配合 Cloudflare Tunnel 或 nginx 反代到 443。

### 不用 Docker（纯 Python）

```bash
git clone https://github.com/P0luz/Ombre-Brain.git
cd Ombre-Brain

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --require-hashes -r requirements.lock.txt

cp config.example.yaml config.yaml
python src/server.py
```

`requirements.lock.txt` 是发布和普通安装使用的跨平台锁文件；`requirements.txt`
保留直接依赖的最低版本约束，供维护者升级依赖时重新解析。这样同一版本的 OB
不会因为安装日期不同而静默得到另一套传递依赖。

---

## 一个大脑多人共用（记忆隔离）/ Multiple Owners

同一套 OB 部署给多个人用，但**每个人的记忆完全隔离、互不可见**——A 写的东西 B 永远看不到，
反之亦然。适合：一家人共用一台家庭服务器、一个小团队共享一套部署、给几个不同的 AI 角色各自
一份独立记忆。

### 它是怎么隔离的（先理解，再照做）

**核心一句话：每个人 = 一个独立实例 = 一个独立数据目录 + 一个独立端口。**

OB 的记忆桶（`.md` 文件）、向量库（`embeddings.db`）、脱水缓存、错误日志**全部落在各自的数据
目录下**，所以只要两个人指向不同目录，记忆就天生互不相通——这不是加了一层权限过滤，而是物理上
就是两套独立的库。不需要改一行核心代码，全靠下面几个环境变量：

| 环境变量 | 作用 | 谁来设 |
|---|---|---|
| `OMBRE_VAULT_DIR` | 这个人的**数据目录**（记忆落这里；旧名 `OMBRE_BUCKETS_DIR` 仍兼容） | 每人各设一个，**必须互不相同** |
| `OMBRE_PORT` | 这个人的**对外端口** | 每人各设一个，**必须互不相同** |
| `OMBRE_OWNER_NAME` | 这个人的**显示名**（用于 Dashboard 顶部的归属徽标） | 每人设自己的 |
| `OMBRE_OWNER_COUNT` | 共用这套 OB 的**总人数** | 所有人设成**相同**的值（= 人数） |

**前端归属徽标规则**：Dashboard 顶部会显示「记忆归属：某某」的徽标，帮你一眼认清「现在看的是谁
的记忆」。规则是——**只有 1 个人时不显示**（保持干净），**2 人及以上才显示**。这由 `OMBRE_OWNER_COUNT`
控制（`>= 2` 才显示），徽标文字取 `OMBRE_OWNER_NAME`。

> `OMBRE_OWNER_NAME` 只从进程环境读取，**不会**被写进共享的 `.env`，所以多个实例不会互相串名。

### 用法一：本机一键启动器（跨平台，推荐单机多用户）

1. 复制配置模板：
   ```bash
   cp deploy/owners.example.yaml deploy/owners.yaml
   ```
2. 编辑 `deploy/owners.yaml`，一人一段（名字 / 端口 / 数据目录都要唯一）：
   ```yaml
   owners:
     - name: 小明
       port: 18001
       vault: ./buckets-ming
     - name: 小红
       port: 18002
       vault: ./buckets-hong
   ```
3. 一键启动（Windows / macOS / Linux 通用，只依赖 Python + PyYAML）：
   ```bash
   python deploy/multi_owner.py
   ```
   启动器会**自动**按人数注入 `OMBRE_OWNER_COUNT`、为每人建好数据目录、拉起各自的实例、打印
   「谁在哪个端口」。`Ctrl+C` 一次性停掉所有实例；任一实例异常退出会整体收摊，不留半死状态。
4. 各自访问：小明 `http://localhost:18001`、小红 `http://localhost:18002`。

### 用法二：Docker 多实例（推荐服务器 / VPS 长期在线）

```bash
docker compose -f deploy/docker-compose.multi.yml up -d --build
```

`deploy/docker-compose.multi.yml` 里每个人是一个 service（独立数据卷 + 独立端口 + 各自的
`OMBRE_OWNER_NAME`）。敏感 key（API Key / 各自的 Dashboard 密码）走 `deploy/.env`。

### 用法三：托管平台（Zeabur / Railway / Render 等）

这些平台一个 project 就是一个实例。**给每个人开一个 project**，各自挂持久卷，在平台的环境变量面板里设：

```
OMBRE_VAULT_DIR   = /app/buckets      # 或平台的持久卷挂载路径
OMBRE_OWNER_NAME  = 小明
OMBRE_OWNER_COUNT = 2                  # 所有人填相同的总人数
```

端口和数据卷各 project 天生隔离，记忆自然不串。

### 加第 N 个人

- **启动器**：在 `owners.yaml` 里再加一段 `name/port/vault`（端口、目录保持唯一），重启启动器即可，
  `OMBRE_OWNER_COUNT` 会自动重算。
- **Docker Compose**：照抄一个 service 块，改 `container_name` / 端口 / 卷 / `OMBRE_OWNER_NAME`，
  并把**每个** service 的 `OMBRE_OWNER_COUNT` 一起改成新的总人数。

### 验证隔离生效

- 在小明那份写一条记忆 → 只在小明的 Dashboard / `buckets-ming` 里出现，小红那份完全看不到。
- 单人（`OMBRE_OWNER_COUNT=1` 或不设）→ 顶部无归属徽标；≥2 人 → 出现「记忆归属：<名字>」徽标。

> ⚠️ **每个人的数据目录必须挂在各自的持久盘上**（同「快速开始」里的持久磁盘要求），否则重启记忆
> 全丢。多人场景尤其别把两个人指到同一个目录——那样记忆会串在一起，违背隔离初衷。

> 更细的排错与设计说明见 **[docs/MULTI_OWNER.md](docs/MULTI_OWNER.md)**。

---

## 部署到云平台 / Deploy to Cloud Platforms

### Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/P0luz/Ombre-Brain)

> ⚠️ **免费层不可用**：Render 免费层无持久化磁盘，重启后记忆会丢失，且无流量时会休眠。**必须使用 Starter（$7/mo）或以上**。

仓库已包含 `render.yaml`。点按钮后：

1. 设置环境变量 `OMBRE_COMPRESS_API_KEY`（必需）
2. 可选 `OMBRE_COMPRESS_BASE_URL`（例如 `https://generativelanguage.googleapis.com/v1beta/openai/`）和 `OMBRE_EMBED_API_KEY`
3. 持久化磁盘自动挂载到 `/opt/render/project/src/buckets`
4. 部署后 Dashboard：`https://<服务名>.onrender.com`，MCP URL：`https://<服务名>.onrender.com/mcp`

Render 自带 HTTPS，可直接在 Claude.ai 添加，无需额外 Tunnel。

### Zeabur

[![Deploy on Zeabur](https://zeabur.com/button.svg)](https://zeabur.com/templates/OMBRE-BRAIN)

1. Fork 本仓库 → Zeabur **New Project** → **Deploy from GitHub**
2. Variables 填 `OMBRE_COMPRESS_API_KEY`（必填）
3. Volumes → 挂载路径 `/app/buckets`
4. Networking → Port `8000` → **Generate Domain**

### 自有 VPS

```bash
git clone https://github.com/P0luz/Ombre-Brain.git
cd Ombre-Brain
cp config.example.yaml config.yaml
# 修改 config.yaml 设置 API key 和其他参数
docker compose -f deploy/docker-compose.yml up -d
```

配合 nginx / Caddy 反代到 443 端口，或直接用 Dashboard 内置的 Cloudflare Tunnel 管理器。

---

## Dashboard 功能概览

启动后浏览器打开 `/`（根路径）进入，第一次会引导设置密码。

| 标签页 | 功能 |
|---|---|
| **记忆** | 桶列表，按 domain / type 筛选，单桶可 pin / resolve / 主动遗忘 / 归档；不提供物理删除 |
| **Breath 调试** | 模拟检索查询，查看每个桶的四维评分分解 |
| **记忆网络** | 基于 embedding 相似度的桶关系图 |
| **③ 引擎** | 内联填写 LLM / Embedding API Key，在线修改参数，点「保存 Key」立即热更新 |
| **导入** | 上传历史对话文件批量导入 |
| **设置** | 修改密码、MCP OAuth 开关、版本状态、Cloudflare Tunnel 管理、API Key 测试 |

**设置页 Cloudflare Tunnel 区**：填入 Token 后点启动，状态点颜色表示连接状态（灰=未运行，橙=连接中，绿=已连接，红=连接失败+错误原因）。支持「启动时自动连接」。

**API Key 测试按钮**：填入 Gemini API Key 后点「测试」，立即验证 Key 是否有效，显示 ✓ 或具体错误原因，无需手写测试请求。

---

## 配置 / Configuration

所有可调参数都在 `config.yaml`（从 `config.example.yaml` 复制）。最常用的几个：

| 参数 | 说明 | 推荐值 |
|---|---|---|
| `transport` | `stdio`（本地）/ `streamable-http`（远程） | Docker 部署用 `streamable-http` |
| `dehydration.model` | 脱水/打标 LLM 模型 | `gemini-2.0-flash` |
| `dehydration.base_url` | LLM API 地址 | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `dehydration.max_tokens` | 模型最大输出 token | `4096`（必须足够大，否则 JSON 截断导致域分类失败） |
| `dehydration.timeout_seconds` | LLM 请求超时秒数 | 国内服务器连云端 API 可设 `120` 或更高 |
| `embedding.api_format` | `gemini`（云端）/ `ollama`（本地 bge-m3）/ `openai_compat` | `gemini` |
| `embedding.model` | embedding 模型 | 云端 `gemini-embedding-001` / 本地 `bge-m3` |
| `embedding.timeout_seconds` | 向量化请求超时秒数 | 国内服务器连云端 API 可设 `120` 或更高 |
| `embedding.background_indexing` | 原文落盘后由耐久后台队列生成向量 | `true` |
| `embedding.retry_base_seconds` / `retry_max_seconds` | 向量失败后的指数退避起点 / 上限 | `5` / `300` |
| `decay.lambda` | 衰减速率，越大越快忘 | `0.05` |
| `merge_threshold` | 合并相似度阈值 (0-100) | `75` |
| `hooks.token` | `/breath-hook` 的 HTTP token | 自托管公网建议设置 |
| `hooks.allow_public` | 是否允许 hook 无鉴权访问 | `false` |

> ⚠️ **`dehydration.max_tokens` 不能太小**：Gemini 2.5 系列模型有「思考 token」开销，如果 max_tokens 设得太小（如 256/512），思考 token 会耗尽预算，JSON 响应被截断，导致所有记忆被错误分类为「未分类」。推荐 `gemini-2.0-flash`（无思考开销）或将 max_tokens 设为 `4096` 以上。

> 🔐 **Hook 安全默认值**：`/breath-hook` 默认不再公开。它接受 Dashboard 登录 cookie，或 `hooks.token` / `OMBRE_HOOK_TOKEN`，token 可通过 `?token=...`、`X-Ombre-Hook-Token` 或 `Authorization: Bearer ...` 传入。只有在反向代理、Cloudflare Access 等外层已经做鉴权时，才建议把 `hooks.allow_public` / `OMBRE_HOOK_ALLOW_PUBLIC` 设为 `true`。
>
> 注：这里**只有 `/breath-hook`**。早期版本还有一个每次开场自动触发的 `/dream-hook`，已移除——`dream`（做梦消化）按设计哲学不是义务、不该被自动触发，只应在需要消化时由模型主动调用 `dream` 工具。

### Embedding 两后端：云端 Gemini vs 本地 bge-m3

| 后端 | 类型 | 维度 | 资源 | 适合 |
|---|---|---|---|---|
| **云端**（`api_format: gemini`） | Gemini API | 3072 | 0（不占本机） | 大多数人。免费额度 1500 req/day 够用，开箱即用 |
| **本地**（`api_format: ollama`） | Ollama + bge-m3 | 1024 | **约 2–3GB 空闲内存** + 1.2GB 磁盘，纯 CPU | 不想出网 / 没有 API key / 数据敏感 / 自托管 |

> 💾 **本地模型内存提醒**：bge-m3 加载后常驻约 2–3GB 内存。低配机器（<2GB 空闲内存）建议继续用云端；纯 CPU 即可推理，首条查询冷启动约 1–9s，之后 <0.5s。

> 🧩 **用硅基流动（SiliconFlow）等 OpenAI 兼容云端向量化**：
> **最省事：在 Dashboard ③ 引擎 → 向量化 顶部的「服务商预设」里选『硅基流动』**，会自动把 Base URL 和正确的模型名填好，你只要填 key → 保存 → 测试。脱水(LLM) 面板同理有预设。
>
> 想手动填也行（**两个最常踩的坑都在这**）：
> - 格式：`OpenAI 兼容`
> - Base URL：`https://api.siliconflow.cn/v1` —— **末尾必须带 `/v1`**，漏了会 404（page not found）
> - Model：`BAAI/bge-m3` —— **必须带 `BAAI/` 前缀**，只写 `bge-m3` 会报 `Model does not exist`（免费，1024 维）
> - 填完点「保存」，再点旁边的「**测试**」确认连得通（会直接显示成功维度或具体错误）。其它 OpenAI 兼容商（DeepSeek 等）同理：base_url 带正确后缀、model 用对方控制台里的完整名。

**本地向量化怎么搭（离线、无需 key、不出网）**

本地模型跑在一个独立的 `ollama` 容器里（OB 不直接管它，所以最稳）。两步：

1. **启动自带的 ollama 容器**（一次性）。Docker 用户版 compose 已内置该服务（默认不启），加 `--profile local` 即可拉起：
   ```bash
   docker compose -f docker-compose.user.yml --profile local up -d
   ```
   > 源码部署同理；或独立起一个（和 OB 同一 docker 网络、容器名 `ombre-ollama` 即可）：
   > ```bash
   > docker run -d --name ombre-ollama --restart unless-stopped \
   >   --network <OB所在网络> -v ollama:/root/.ollama ollama/ollama
   > ```
   OB 在容器网络里通过 `ombre-ollama:11434` 自动连它（代码已内置该默认，无需额外配置）。
2. **Dashboard → 设置 → 向量化 → 「🖥️ 本地向量模型」面板 → 点「🚀 一键本地化」**。它会自动：下载 bge-m3（约 1.2GB，带进度条）→ 切换后端 → 后台重算全库向量。期间照常使用，检索暂用旧库。
   > 裸机 / 非 Docker 部署：同一个按钮会**直接在本机免提权安装 Ollama 运行时**（Win/Linux/mac），无需你手动起容器。

> 🌐 **国内网络**：模型下载默认走 ollama 官方源。拉不动时，在面板「分步操作」里换下载镜像（选 ModelScope 或填自定义 registry 前缀），再点「仅下载」。

**云端 ↔ 本地随时切换**：Dashboard → 设置 → 向量化面板 →「一键搭建本地向量化」或「切回云端 Gemini」。

> ⚠️ 两个后端向量维度不同（3072 vs 1024），**每次切换都会全库重算**（自动备份旧 DB、后台进行、失败不动旧库）。不要频繁来回切。

---

## 检索质量评测

准备一个只读 JSON 用例文件，把查询和期望命中的真实 bucket ID 写进去：

```json
{
  "cases": [
    {"name": "发布流程", "query": "蓝色发布通道", "domain": "work", "expected_ids": ["abc123"]}
  ]
}
```

默认离线评测关键词通道，不会调用或消耗 embedding API：

```bash
python tools/evaluate_retrieval.py retrieval-cases.json --top-k 5
```

加 `--with-embedding` 可评测完整混合检索；输出包含 Hit@K、Recall@K、MRR 和每条查询的实际排名。`--min-hit-rate 0.8` 可在低于基线时返回非零退出码，供 CI 使用。脚本只读，不会 `touch` 或修改记忆。

---

## 把记忆挂到 Obsidian

在 `docker-compose.user.yml` 同目录的 `.env` 中设置 Vault 路径，无需修改 compose 文件：

```env
OMBRE_HOST_VAULT_DIR=/Users/你的用户名/Documents/Obsidian Vault/Ombre Brain
```

然后执行 `docker compose -f docker-compose.user.yml up -d --force-recreate`。每条记忆会作为 Markdown 文件写入该目录，配置和 Tunnel token 也会一起持久化。

---

## 更新 / How to Update

### Docker Hub 镜像用户

```bash
docker pull p0luz/ombre-brain:latest
docker compose -f docker-compose.user.yml down
docker compose -f docker-compose.user.yml up -d
```

### 从源码部署用户

```bash
cd Ombre-Brain
git pull origin main
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d
```

记忆数据在 volume 里，更新不会丢失。

自行修改源码后重建镜像时，仍建议同步修改 `VERSION`，便于人类识别构建来源；但启动器不再只依赖版本字符串。它会记录镜像 `src/` + `frontend/` 的代码指纹，同一个 `VERSION` 下代码发生变化也会重新播种。镜像本身没有变化时，卷内 Dashboard 热更新会被识别为运行时覆盖并保留，不会在重启时被旧镜像冲掉。

注意：`entrypoint.sh` 属于镜像启动层，旧版启动器不能通过 Dashboard 热更新替换自己。包含本修复的版本发布后，现有 Docker 部署必须至少执行一次 `docker pull` + 重建容器（源码部署则重新 `docker build`），之后指纹机制才会生效。

启动日志会明确打印当前活动代码目录和状态：

- `code-state=image-match`：运行代码与镜像一致；
- `code-state=runtime-override`：正在保留 Dashboard 热更新或自动回滚版本；
- `code-state=legacy-residue`：发现另一个旧布局 `_app`，它未被当前进程使用。

不要仅凭某个 `_app/VERSION` 判断实际运行版本，也不要看到 `<数据目录>/_app` 就直接删除。默认部署里它可能正是活动代码目录；只有日志同时给出 `code-state=legacy-residue` 和另一个“活动代码目录”时，旧目录才可在备份后清理。需要强制从镜像重新播种时，可仅在一次启动中设置 `OMBRE_FORCE_CODE_RESEED=1`，成功后应立即移除该变量。

---

## 给 Claude 的使用指南

`docs/CLAUDE_PROMPT.md` 是写给 Claude 看的工具使用约定。把它放进 system prompt / custom instructions / Claude Desktop 项目说明里即可。

---

## 常见问题 / Troubleshooting

| 现象 | 可能原因 | 解决 |
|---|---|---|
| 首次进 Dashboard 设置密码页一闪而过变成登录页 | 已修复（v2.0.4+） | 更新到最新版本 |
| 所有记忆 domain 显示「未分类」 | ① `max_tokens` 太小，JSON 被截断；② **打标模型太弱**（如 7B 级小模型），吐不出可解析的分类 JSON，OB 兜底为「未分类」 | ① 将 `dehydration.max_tokens` 设为 `4096`；② 换一个够强的打标模型（`gemini-2.0-flash`、`deepseek-ai/DeepSeek-V3`、`Qwen/Qwen2.5-72B-Instruct` 等；7B 级免费小模型不足以稳定产出结构化打标）。OB 的 JSON 提取已容忍模型前后的寒暄，但模型返回空/彻底损坏时只能兜底 |
| Claude.ai 添加 MCP 报「Couldn't register」 | OAuth 端点无法访问（通常是 Tunnel 未启动/域名错误） | 先确认 Dashboard 能正常访问，再添加 MCP |
| OAuth 授权页正常弹出但密码输入后报错 | Dashboard 密码错误 | 使用 Dashboard 设置时的密码（不是 Cloudflare 密码） |
| 连接成功但「no tools available」 | URL 末尾路径不是 `/mcp` | 确认连接 URL 末尾是 `/mcp` |
| 每开新对话工具加载不全 / 偶尔搜不到某个工具 | **不是服务器问题**：同时启用的连接器太多时，Anthropic 客户端会改用 tool_search「延迟加载」，按描述去搜工具，命中带随机性 | 关掉该会话里用不到的其它连接器，把工具总数压到阈值以下即可一次性全部加载；或在 Claude.ai 自定义指令里列出全部工具名引导模型搜索 |
| 工具调用显示「执行报错」但记忆其实写进去了 | **不是服务器问题**：服务端已成功返回，是 Claude.ai 连接器/渲染层把一次成功往返显示成了报错 | 用 `letter_read` 或 Dashboard 确认数据已落盘；服务端日志 `phase=ok` 即表示成功 |
| embedding API 暂时离线时 `breath(query=...)` 出现“检索降级” | OB 正在使用关键词/BM25 继续检索；命中桶仍逐字返回完整存储正文，不是记忆丢失 | 可继续使用；到系统诊断查看向量队列，恢复 API 后语义通道会自动回来 |
| 向量化不生效 / 语义检索没结果（压缩却正常） | base_url 漏 `/v1`（→404）、model 漏 `BAAI/` 前缀（→Model does not exist），或后台队列因网络 / 配额持续重试 | 用 Dashboard 向量化区的「测试」和系统诊断查看待处理 / 重试数；按上面「用硅基流动…」一节填对 base_url 与 model；错误详情见设置页错误面板（OB-E001） |
| 自有前端 / GPT / GLM 调用 MCP 工具被 401 卡住 | 默认强制 OAuth，自定义客户端不走该流程 | 设 `OMBRE_MCP_REQUIRE_AUTH=false`（或 `config.yaml: mcp_require_auth: false`）后重启；详见「方式三：接入自有前端」 |
| **Operit / 安卓 / Proot 本地桥接一直黄灯、连不上 `/mcp`** | 多为下面三点之一：① `transport` 没设成 `streamable-http`（默认 `stdio` **根本不开 HTTP 服务**）；② 默认强制 OAuth，Operit 这类本地桥不走该流程被 401 卡半通；③ 客户端填了 `localhost`，在 Proot/Termux 里常解析成 IPv6 `::1`，连不上 IPv4 监听 | 见下方「**Operit / 安卓 / Proot 本地桥接**」一节，三步逐个对齐 |
| Token 过期后无法自动重连 | 旧版本不支持 `refresh_token` grant，headless 环境只能重新打开授权页 | 更新到 v2.4.11+ 后重新授权一次，之后客户端可用 refresh token 自动续期 |
| Dashboard 401 | 未登录 / 密码错 | 浏览器重新登录 |
| `hold` / `grow` 报 API key 错误 / `401 Invalid token` | LLM key 未配置或不对；**或**你既用 `-e OMBRE_COMPRESS_API_KEY=...` 传了 env、又在面板改过 key —— 见下一行 | Dashboard → ③ 引擎 填入 Key 点「保存 Key」；确认 base_url、model 正确后用「测试」按钮自查 |
| **在面板改了 key/配置，重启后又变回旧值 / 不生效** | **env 变量优先级高于 config.yaml**。你启动时用 `-e OMBRE_XXX=...` 传的值，会在每次重启时盖掉面板写进 config.yaml 的改动 | 二选一：① 改就改 env（`docker run -e` / compose 的 `environment` / 平台环境变量面板），别在面板改；② 想用面板管配置，就**别用 `-e` 传那个变量**。面板「环境变量」区带 `from_boot` 标记的就是会被 env 覆盖的项 |
| 重启后**记忆丢失**（退回旧版本 / 空库） | 数据目录没挂到持久盘：容器重建就把记忆连同代码一起丢了。匿名卷也会被 `docker compose down -v` 等操作清掉 | 把 `/app/buckets` 挂到**命名卷或宿主机目录**（`-v ./buckets:/app/buckets`）。**判断标准：能在宿主机文件夹里看到那些 `.md` 文件，就是安全的。** Dashboard → 设置 → 系统诊断 会直接告诉你「数据目录是否持久」 |
| Docker **构建**（`docker build`）在 `pip install` 处失败：`SSL EOF` / 连不上 pypi.org / `No matching distribution` | 宿主机网络/代理（Clash、V2Ray 等）在构建时把连 PyPI 的连接掐断了 | 用**预构建镜像**（「快速开始」的 `docker compose` 直接拉 Docker Hub 镜像，无需本地构建）；若必须本地构建，临时关掉代理或给 Docker 配一个稳定的 PyPI 镜像源后重试 |
| 修改源码并以相同 `VERSION` 重建镜像后仍像旧代码 | 旧版启动器只比较版本字符串；或当前容器还没有使用新镜像 | 新版会同时比较镜像代码指纹。先确认容器确实由新镜像重建，再查看启动日志是否出现 `reason=image-fingerprint-changed`；旧版请先升级或临时修改 `VERSION` |
| 数据目录里看到旧版本 `_app/VERSION`，怀疑仍在运行旧代码 | 独立代码卷部署可能留下旧布局目录；默认布局下它也可能就是活动目录 | 以启动日志“活动代码目录”为准。只有出现 `code-state=legacy-residue` 时该目录才未被使用；备份后可清理，OB 不会自动删除 |
| 记忆库涨到几百桶后 `breath` 很慢 / 超时被切断 | 旧版检索热路径有全库重读等开销 | **v2.5.0+ 已优化**（内存缓存 + touch 移出响应路径 + BM25 后台重建）；当前 breath 返回层不再调用脱水 LLM |
| Tunnel 状态红色 / 连接失败 | Token 无效；或 VPN DNS 不支持 `_v2-origintunneld._tcp.argotunnel.com` 的 SRV 查询 | 新版 compose 默认以双 region + HTTP/2 绕过 SRV；旧部署请更新 compose 后 `--force-recreate`。仍失败时展开 Dashboard 错误框并检查 token 与 TCP 7844 出站连接 |
| 隧道连接偶尔断 | Cloudflare Free 闲置超时 | 内置 keepalive 已缓解；可在 Cloudflare Tunnel 设置里调整超时 |

---

## 容易忽略的点 / Easy-to-miss

新用户最常踩、但文档里分散各处的点，集中提醒一下：

- **只需加一个连接器 `/mcp`**：12 个工具全在这一个端点上，不用再单独加别的。
- **反代/隧道要整主机名转发**：Cloudflare Tunnel / Nginx 按域名整体转发到 `localhost:端口`，覆盖所有路径即可。
- **OpenAI 兼容向量化两个坑**：base_url 末尾要带 `/v1`（漏了 404）、model 要带完整前缀（如 `BAAI/bge-m3`，漏了报 Model does not exist）。填完用向量化区的「测试」按钮确认。
- **改完 key / 配置点「保存」后再「测试」**：压缩和向量化各有独立的「测试」按钮，能用就用，别凭感觉。
- **国内自托管偶发超时**：LLM 打标仍在当前请求内；embedding 已改为原文落盘后的耐久后台任务，不会阻塞或回滚记忆。可在 `config.yaml` 里设置 `dehydration.timeout_seconds` / `embedding.timeout_seconds`，或用环境变量 `OMBRE_COMPRESS_TIMEOUT_SECONDS` / `OMBRE_EMBED_TIMEOUT_SECONDS`。
- **`dehydration.max_tokens` 别设太小**：Gemini 2.5 系列有思考 token 开销，太小会让 JSON 截断、记忆全标成「未分类」；用 `gemini-2.0-flash` 或把它设到 `4096` 以上。
- **记忆数据要挂 volume**：不挂载（或 Render 免费层无持久磁盘）→ 重启记忆全丢。**判断标准很简单：你能在宿主机文件夹里看到那些 `.md` 记忆文件，就是安全的。** Dashboard → 系统诊断 会直接告诉你数据目录持不持久。
- **⚠️ env 变量会盖过面板配置**：如果你启动时用 `-e OMBRE_XXX=...` 传了某个变量（key、model、端口…），那**在 Dashboard 里改同一项、重启后会被 env 值盖回去**。要么统一在 env 改，要么就别用 `-e` 传、改用面板管理。这是新手最容易被绕晕的一点。
- **🛟 记忆只有一份很危险，强烈建议开异地备份**：本地/单卷就是「一份」，磁盘坏了或误删就找不回。到 Dashboard → GitHub 同步 配一下（几分钟），记忆就多一份云端存档，换机/灾难也能拉回来（embeddings.db 不上传，靠「重算所有向量」恢复）。
- **切换向量化后端会全库重算**：云端 3072 维和本地 bge-m3 1024 维不通用，每次切换都会重算，别频繁来回切。
- **热更新按钮看部署方式**：Docker（有 restart 策略）点完自动恢复；裸机/纯 Python 需要 systemd/pm2 等守护，否则更新后要手动重启。点之前先「导出记忆备份」。
- **自有前端 / GPT / GLM 接入**：默认强制 OAuth，会卡住非 Claude 客户端；设 `OMBRE_MCP_REQUIRE_AUTH=false` 关掉（注意别裸奔公网）。
- **首次访问先设密码**：设完之后所有 `/api/*` 都要登录；忘了密码可用设置里的安全问题急救。

---

## License

MIT
