# Ombre Brain（心潮念 vendored 版）

> **模块导读**
>
> - **这是什么**：Ombre Brain 记忆库：长期记忆的存放、浮现、沉淀、梦的消化
> - **依赖谁**：不依赖心潮，可以单独跑；需要一个小模型 key 做压缩，向量化 key 可选
> - **部署顺序**：整个仓库的第 ② 步，最先起来，心潮在它后面起。完整顺序见 [从这里开始](../docs/从这里开始.md)
> - **建议**：压缩模型用非推理模型（推理模型慢，会让 AI 等超时）；18001 端口只给后台管理和心潮内部用，**不要当 MCP 连接器填给 AI**
> - **相关指南**：[OB 运维](docs/OPERATIONS.md) · [内部结构](docs/INTERNALS.md) · [多人共用](docs/MULTI_OWNER.md) · [给模型的说明](docs/CLAUDE_PROMPT.md) · [文档目录](../docs/README.md)

心潮念的记忆库层。**从源码构建**（`compose.yaml` 里 `build: ./ombre-brain`），不依赖外部镜像。

- 基线版本：`VERSION` = 2.6.5
- 血统与许可证：P0luz（原, MIT）→ CyberSealNull（二改, 非商业）→ 心潮念（breath-meta 等）。
  详见 [MODIFICATIONS.md](MODIFICATIONS.md)、`LICENSE.P0luz-MIT`、`LICENSE.CyberSealNull`、
  `NOTICE.CyberSealNull.md` 与仓库根 `../NOTICE`。
- OB 原生功能完整保留：breath / hold / grow / dream / trace / anchor / release / forget /
  restore / purge / I / plan / letter / pulse + Dashboard。

## 文件

```
Dockerfile              构建（Python 3.12-slim + cloudflared + 源码）
src/ frontend/          OB 源码 + Dashboard 前端
entrypoint.sh           容器入口
requirements.lock.txt   带 hash 的生产依赖锁
config.default.yaml     首启自动生成 config 的默认模板
deploy/                 cloudflared 下载脚本等
docs/                   面向用户/模型的说明
README.upstream.md      OB 自带 README（镜像内即此文件）
```

> 上层 `../compose.yaml` 负责编排、端口、数据卷（`/app/buckets`）与环境变量。
> 单独构建：`docker build -t ombre-brain ./ombre-brain`（跳过 cloudflared 加 `--build-arg INSTALL_CLOUDFLARED=0`）。
