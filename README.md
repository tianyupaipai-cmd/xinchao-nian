# 心潮·念（Xinchao · Nian）

一个会**惦记你**的 AI 心智：**心潮**（动态驱力/欲望引擎）+ **Ombre Brain**（记忆库）深度融合，一键联合部署。

- **心潮** 让它有随时间变化的内在状态——想念、期待、挂念、好奇、独处欲……不是每次对话都从零开始。
- **Ombre Brain** 给它一个真正的长期记忆库——breath 浮现、hold 沉淀、dream 消化、trace 追溯。
- **融合** 让"欲望影响记忆影响行动"闭环：驱力偏置召回哪些记忆浮现，浮现的记忆又回推驱力。

## 快速开始

```bash
cp .env.example .env      # 填 3 个必填项（OB 压缩 key、Dashboard 密码、内部令牌）
docker compose up -d --build
```

- OB Dashboard：`http://127.0.0.1:18001`（本机，建议再用 Nginx/隧道反代）
- 两服务在同一 docker 网络内部通信，对外只暴露本机端口。

## 结构

```
compose.yaml       两服务联合编排（共享网络、内部互通）
.env.example       合并配置模板
xinchao/           心潮源码（动态心智）—— MIT
ombre-brain/       Ombre Brain 源码（记忆库）—— 见 NOTICE / LICENSE
bridge/            心潮念 Runtime Bridge（git 子模块）—— 用户主动互动的本地连接桥
buckets/           记忆数据卷（首启自动生成 config，重启不丢）
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

- `xinchao/`（心潮）：MIT。
- `ombre-brain/`（Ombre Brain）：基于 P0luz 的 Ombre Brain 与 Yinglianchun 的 fork，
  **保留其原始许可证与署名**，见 [NOTICE](NOTICE)。本项目对其的修改记录见 `ombre-brain/MODIFICATIONS.md`。
- 本融合项目**非纯 MIT**；商业使用需取得上游 OB 作者的书面许可。

> 详细边界见上游来源说明。融合不改变 OB 原生记忆库功能——breath/hold/grow/dream/trace/
> anchor/release/forget/restore/purge/I/plan/letter/pulse 与 Dashboard 全部保留。
