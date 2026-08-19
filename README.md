# 心潮·念 3.1.0（Xinchao · Nian）

一个会**惦记你**的 AI 心智：**心潮**（动态驱力/欲望引擎）+ **Ombre Brain**（记忆库）深度融合，一键联合部署。

- **心潮** 让它有随时间变化的内在状态——想念、期待、挂念、好奇、独处欲……不是每次对话都从零开始。
- **Ombre Brain** 给它一个真正的长期记忆库——breath 浮现、hold 沉淀、dream 消化、trace 追溯。
- **融合** 让"欲望影响记忆影响行动"闭环：驱力偏置召回哪些记忆浮现，浮现的记忆又回推驱力。

## 3.1 更新重点

- **Personality Core 性格内核层**：新增与 12 维当下驱力分离的月度内核，由 AI 自主回顾并通过受鉴权工具完成评分；人类不参与打分。
- **单向、极慢的基线偏置**：仅批准的 4 组内核维度可以影响对应驱力，偏置硬封顶在 ±10%；驱力不会反向自动改写人格评分。
- **待交付内容闭环**：AI 只负责创建和确认“已经说出”，留下（hold）或放下（drop）的决定权归用户；说出与留存是两条独立状态轴。
- **引用式记忆关联**：念头与梦可以围绕具体 OB 记忆桶生成，但心潮不按 ID 修改记忆正文；保留来源链和最终落地桶 ID。
- **饱足期与驱力耦合**：满足后默认保留 2 小时平台期，只暂停自然增长；事件、记忆共振与输出回流仍可正常穿透。
- **可视化与接入收口**：补齐 Personality Core、待交付处置、记忆关联及公开网页所需的脱敏状态接口。

> 3.1 不改变隐私边界：私有 `personality.json`、状态、记忆与凭据均不进入公开仓库。完整源码说明见 [`xinchao/README.md`](xinchao/README.md)，版本差异见 [`xinchao/CHANGELOG.md`](xinchao/CHANGELOG.md)。

## 快速开始

```bash
cp .env.example .env      # 填完文件内标为“必填”的密钥与独立口令
docker compose up -d --build
```

- 两服务在同一 docker 网络内部通信，对外只暴露本机端口。
- 可视化前端使用 [xinchaomind.uk](https://xinchaomind.uk)，不需要直接访问 OB 端口。

## 先分清三个入口

| 入口 | 用来做什么 | 应该填在哪里 | 绝对不要 |
| --- | --- | --- | --- |
| `https://xinchaomind.uk` | 公开可视化网页 | 浏览器打开 | 不要当 MCP URL，它也不会替你运行心潮 |
| `https://你的心潮域名/mcp` | 心潮·念 MCP/OAuth 网关 | Claude / ChatGPT / IDE 的 MCP 连接器 | 不要填 `xinchaomind.uk` 或 OB 地址 |
| `OMBRE_MCP_URL` | 心潮内部读写 OB 记忆 | 只写在心潮服务端 `.env` | 不要交给公开网页，不要当心潮连接器 |

> 一句话判断：**人打开公开网页，AI 连接心潮 `/mcp`，心潮再在服务器内连接 OB。**

## 连接 Claude.ai MCP 连接器

心潮·念自带 OAuth 2.1 MCP 端点，可直接作为 Claude.ai 的 MCP 连接器使用。

**重要：连接器必须指向你自己的心潮（端口 18110），不是公开网页，也不是 Ombre Brain（端口 18001）。**
OB 的 18001 端口仅用于 Dashboard 管理和内部通信，不要把它当 MCP 连接器添加到 Claude.ai。

在 `.env` 中启用并重启：

```env
MCP_ENABLED=true
OAUTH_ENABLED=true
OAUTH_PUBLIC_BASE_URL=https://你的心潮公网地址    # 必须 HTTPS，指向心潮 18110 端口的反代
OAUTH_APPROVAL_TOKEN=自己生成的授权口令至少16字符  # 添加连接器时在授权页面输入这个
```

然后在 Claude.ai 添加 MCP 连接器，URL 填 `https://你的心潮公网地址/mcp`。
授权页面会显示「心潮念」，输入你设置的 `OAUTH_APPROVAL_TOKEN` 即可。

如果你看到的授权页面显示的是「Ombre Brain」而不是「心潮念」，说明你连错了端口——
检查你的反代/隧道是否指向 18110（心潮），而不是 18001（OB）。

## 连接心潮念公开可视化

前提是你已经按上面的步骤部署并启动了心潮·念。`xinchaomind.uk` 是可视化
前端，不会替你运行心潮，也无法访问另一台设备的 `localhost`。

先在 `.env` 配好并重启：

```env
DASHBOARD_ENABLED=true
DASHBOARD_ACCESS_TOKEN=一段至少32字符且与其他密钥不同的随机口令
DASHBOARD_PUBLIC_BASE_URL=http://localhost:18110
DASHBOARD_ALLOWED_ORIGINS=https://xinchaomind.uk
```

然后按使用场景选择：

1. **网页浏览器和心潮在同一台设备**：在网页选择“我的心潮就在这台设备上”，
   地址填 `http://127.0.0.1:18110`，口令填 `DASHBOARD_ACCESS_TOKEN`。
2. **用手机访问电脑/主机里的心潮，或心潮跑在 VPS/N100**：先用 Cloudflare
   Tunnel、Tailscale Funnel 或自己的反向代理给心潮配置公网 HTTPS 地址；把
   `DASHBOARD_PUBLIC_BASE_URL` 改成该地址并重启，再在网页选择“我的心潮有公网地址”。

只填到域名或端口，不要追加 `/mcp`、`/dashboard` 或 `/v1/dashboard/connect`。
`SERVICE_TOKEN`、OB token、OAuth 口令都不能代替 Dashboard 独立口令。

> **常见问题：网页端显示"未接入 OB / 记忆星图不可用"。**
> 这几乎都是 `OMBRE_READ_ENABLED` 没打开——它默认 `false`，跟 OB 是否真的部署成功、能否连接是两回事。
> 接了 OB 想在网页看记忆星图，务必在 `.env` 设 `OMBRE_READ_ENABLED=true` 并重启容器
> （联合部署 compose 已默认开好）。配了 `OMBRE_MCP_URL` 却没开 read 时，启动日志也会打一条告警提醒。

完整判断表、配置示例和常见错误见
[连接公开可视化](docs/CONNECT-XINCHAOMIND.md)。

## 结构

```
compose.yaml       两服务联合编排（共享网络、内部互通）
.env.example       合并配置模板
xinchao/           心潮源码（动态心智）—— MIT
ombre-brain/       Ombre Brain 源码（记忆库）—— 见 NOTICE / LICENSE
bridge/            心潮念 Runtime Bridge（git 子模块）—— 用户主动互动的本地连接桥
（数据用 docker 命名卷 ombre-buckets / xinchao-state，首启自动生成、重启不丢）
```

> 含子模块，克隆用 `git clone --recursive`，或克隆后 `git submodule update --init`。

## 连接桥（Runtime Bridge）

`bridge/` 子模块指向独立仓库 [xinchao-runtime-bridge](https://github.com/tianyupaipai-cmd/xinchao-runtime-bridge)——
一个**本地、可审计、拉取式**的连接工具：把用户在网页上主动发出的互动 / 便签 / 预约
（`user_interaction` / `user_note` / `scheduled_interaction`）从心潮念平台队列拉取，注入用户自己的
AI Runtime。梦境、余韵、思念、内部状态与 AI 自主行动**不允许**自动注入窗口——只留在心潮念里，
用户主动回应或转成便签后才进桥。

- 它是**用户本地运行**的工具，不是服务端组件，不进 `compose.yaml`。
- 需要心潮念平台实现 `/bridge/v1/*` 服务端接口后端到端可用（服务端队列即心潮的 BridgeQueue）。

## 融合能力

| 能力 | 说明 |
|---|---|
| 输出回流 | 它说出口的话回过头改自己的状态 |
| 时间地板 | 每维驱力各自静息天花板，缺席抬底值 |
| 记忆共振 | breath 吐 domain/tags，心潮按亲和度回推驱力 |
| 作息预期 + 挂念 | 从你真实到达节律长出"在等你"和"想你了"，失落内化不责备 |
| 梦境安全化 | 梦是消化残渣、不冒充真实记忆，不自噬 |

## 许可证与署名

- 仓库根的联合发行代码标示为 AGPL-3.0；`xinchao/` 目录仍保留其 MIT 许可文件。
- `ombre-brain/`（Ombre Brain）：基于 P0luz 的 Ombre Brain 与 Yinglianchun 的 fork，
  **保留其原始许可证与署名**，见 [NOTICE](NOTICE)。本项目对其的修改记录见 `ombre-brain/MODIFICATIONS.md`。
- 本融合项目**非纯 MIT**；商业使用需取得上游 OB 作者的书面许可。

详细的分目录边界见 [许可说明](docs/LICENSING.md)。根目录的 AGPL 不会覆盖
`ombre-brain/` 已有的上游非商业约束。

> 详细边界见上游来源说明。融合不改变 OB 原生记忆库功能——breath/hold/grow/dream/trace/
> anchor/release/forget/restore/purge/I/plan/letter/pulse 与 Dashboard 全部保留。
