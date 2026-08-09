# MODIFICATIONS — 心潮念对 Ombre Brain 的修改

本目录的 Ombre Brain 源码是**衍生版本**，血统与许可证：

```
P0luz/Ombre-Brain（原项目, MIT, © P0lar1zzZ）
  → CyberSealNull 二改（在原 MIT 之上追加"新增内容非商业"约束）
    → 心潮念（本仓库）在其基础上做了下面的修改
```

- 原项目：https://github.com/P0luz/Ombre-Brain  （MIT，见 `LICENSE.P0luz-MIT`）
- 二改仓库：CyberSealNull（fork of P0luz，见 `LICENSE.CyberSealNull` / `NOTICE.CyberSealNull.md`；
  其新增内容仅限个人 / 学习 / 非商业，商用需该 fork 维护者书面许可）
- 本版本基线：`VERSION` = 2.6.5

## 心潮念在此基础上的改动

1. **breath-meta（记忆共振依赖）**
   - `src/tools/breath/_verbatim.py`：`breath` 返回时，在每条桶的表头带上结构化
     `[domain:…] [tags:…]`（新增 `_affinity_meta()`）。
   - 目的：让上层的"心潮"动态心智直接按 domain 算亲和度、把浮现的记忆回推到驱力
     （记忆共振），不用猜关键词。additive、向后兼容——老输出没有该表头时按空处理。

2. **压缩/脱水模型默认**（部署配置层，非源码逻辑）
   - 压缩模型从 GLM-Z1 换成 DeepSeek-V3（11.5s → ~1.0s）。通过 config / 环境变量配置，
     不改源码。

> OB 原生功能全部保留：breath / hold / grow / dream / trace / anchor / release / forget /
> restore / purge / I / plan / letter / pulse 与 Dashboard。心潮念只做上述增量，不裁剪。

## 合并后整体许可证

心潮念整体**非纯 MIT**：`ombre-brain/` 部分受 CyberSealNull 二改的非商业约束 + P0luz 原 MIT 的
署名/许可保留要求约束。商业使用需取得上游（P0luz 及 CyberSealNull fork 维护者）的书面许可。
详见仓库根 `NOTICE`。
