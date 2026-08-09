# Ombre Brain（记忆库）

联合部署时 `compose.yaml` 默认用现役镜像 `guchuan/ombre-brain:breath-meta-20260807`
（Docker Hub 公开），OB 原生功能完整保留：breath/hold/grow/dream/trace/anchor/release/
forget/restore/purge/I/plan/letter/pulse + Dashboard。

## 发布前待补（build-from-source 路径）

- 从 `runtime/ombre-brain-ours`（2.6.5 + breath-meta）vendoring 源码到此
- 补 `Dockerfile`（VPS 镜像的构建方式）
- 拷入上游 `LICENSE`（P0luz / Yinglianchun，见 ../NOTICE）
- 写 `MODIFICATIONS.md`（我们改了什么：breath-meta domain/tags、压缩模型 DeepSeek-V3 等）

来源哈希与边界见主仓库 `docs/ombre-brain/来源与边界.md`。
