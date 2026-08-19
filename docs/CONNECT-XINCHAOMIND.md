# 心潮·念连接公开可视化

## 先理解这条链路

公开网页只负责展示和互动；每位用户仍运行自己的心潮·念，数据不会因为注册网页账号
而自动出现在网页里。连接时需要的是这位用户自己部署实例的地址，以及该实例的
`DASHBOARD_ACCESS_TOKEN`。

### 三个地址不能混用

```text
人 ──打开──> https://xinchaomind.uk（公开网页）
AI ──连接──> https://你的心潮域名/mcp（心潮 MCP）
心潮 ──内部调用──> OMBRE_MCP_URL（OB 记忆后端）
```

- `xinchaomind.uk` 不是 MCP 服务，也不会替你部署心潮。
- OB 地址不是“心潮公开网页地址”，也不是“心潮 MCP 连接器地址”。
- 公开网页连接时填的是**你自己的心潮基础地址**，只填域名/端口，不追加 `/mcp`。
- AI 的 MCP 连接器则必须在心潮基础地址后追加 `/mcp`。

## 1. 完成服务端配置

在心潮·念根目录的 `.env` 中设置：

```env
# 心潮业务 API 的内部令牌，至少 32 字符
DYNAMIC_MIND_TOKEN=请生成独立随机值

# 可视化专用，不能与上面的令牌或 OB 密钥相同
DASHBOARD_ENABLED=true
DASHBOARD_ACCESS_TOKEN=请生成另一段至少32字符的随机值
DASHBOARD_SESSION_TTL_SECONDS=43200
DASHBOARD_INCLUDE_PRIVATE_TEXT=false

# 只有心潮需要从 OB 读记忆/星图时才配置；这不是网页地址
OMBRE_MCP_URL=http://ombre-brain:8000/mcp
OMBRE_MCP_TOKEN=你的OB服务端令牌
OMBRE_READ_ENABLED=true
```

可用 `openssl rand -hex 32` 分别生成随机值。修改后必须重新构建或重启心潮：

```bash
docker compose up -d --build
```

访问 `http://127.0.0.1:18110/health`，应看到 `ok: true`。

## 2. 选择一种连接方式

### A. 同一设备直接连接

只适用于“浏览器”和“心潮服务”运行在同一台电脑，或同一台手机的情况：

```env
DASHBOARD_PUBLIC_BASE_URL=http://localhost:18110
DASHBOARD_ALLOWED_ORIGINS=https://xinchaomind.uk
```

在网页连接窗口选择“我的心潮就在这台设备上”，地址填写：

```text
http://127.0.0.1:18110
```

同一 Wi-Fi 不等于同一设备。手机浏览器里的 `localhost` 指手机自己，不能指向家里的
电脑或 N100；HTTPS 网页也会阻止它访问另一台设备的普通内网 HTTP 地址。

### B. 手机或另一台设备连接

给运行心潮的设备配置一个公网可达的 HTTPS 地址，例如：

```text
https://xinchao.example.com
```

Cloudflare Tunnel、Tailscale Funnel、Nginx/Caddy 反向代理都可以；核心要求只有两个：

- 外部能够通过 HTTPS 访问该地址的 `/health` 与 `/dashboard/session`；
- 代理目标是心潮端口 `18110`，不是 OB、MCP 或其他服务。

服务端设置：

```env
DASHBOARD_PUBLIC_BASE_URL=https://xinchao.example.com
```

网页选择“我的心潮有公网地址”，只填写 `https://xinchao.example.com`。这一模式由
网页服务器代为访问心潮，不需要 `DASHBOARD_ALLOWED_ORIGINS`。

## 3. 常见提示怎么判断

| 提示 | 含义 | 检查 |
| --- | --- | --- |
| 连不上这个地址 / 网络不太顺 | 地址根本不可达或手机误填 localhost | 确认设备关系、端口与 HTTPS 隧道 |
| HTTP 401 / 口令未接受 | 地址可达，但口令不对 | 填 `DASHBOARD_ACCESS_TOKEN`，不要填 SERVICE_TOKEN |
| 浏览器提示 CORS / Origin | 本机直连白名单未生效 | 添加 `DASHBOARD_ALLOWED_ORIGINS=https://xinchaomind.uk` 后重启 |
| HTTP 404 | 请求打到了错误服务或旧镜像 | 确认反代目标是心潮 18110，并重新构建最新版 |
| HTTP 1101 | 托管 Worker/隧道异常 | 检查对应托管平台和隧道，不是 Dashboard 口令问题 |
| 网页能连心潮，但星图显示未接入 OB | 心潮未开启 OB 读取 | 检查 `OMBRE_MCP_URL` / `OMBRE_MCP_TOKEN` / `OMBRE_READ_ENABLED=true` |
| Claude 提示 Couldn't register | 把公开网页或 OB 地址当成了心潮 MCP | 使用自己的心潮 HTTPS 域名加 `/mcp` |

## 安全边界

- 不要把 `SERVICE_TOKEN`、OB token 或 OAuth 管理口令交给网页。
- 不要把任何 token 放进 URL、截图、公开仓库或群聊。
- `DASHBOARD_ALLOWED_ORIGINS` 只填写实际使用的完整网页来源；不要填写 `*`。
- 公开 HTTPS 地址仍由 Dashboard 独立口令保护，Cloudflare Tunnel 本身不等于鉴权。
