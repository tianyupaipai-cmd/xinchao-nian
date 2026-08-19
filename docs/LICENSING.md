# 心潮·念许可与再分发边界

本仓库是多个来源组成的联合发行包，不是所有文件共用同一份许可证。

| 范围 | 来源 | 许可/约束 | 再分发要求 |
| --- | --- | --- | --- |
| 仓库根联合发行代码 | 心潮·念 | AGPL-3.0 | 保留许可并依 AGPL 提供对应源码 |
| `xinchao/` | 心潮动态心智引擎 | MIT | 保留 `xinchao/LICENSE` 中的版权与许可声明 |
| `bridge/` | xinchao-runtime-bridge 子模块 | MIT | 保留子模块自身许可 |
| `ombre-brain/` 原始部分 | P0luz/Ombre-Brain | MIT | 保留 `LICENSE.P0luz-MIT` 与原始署名 |
| `ombre-brain/` 二改及衍生部分 | CyberSealNull fork | 个人/学习/非商业 | 商用前需取得相关权利人书面许可 |

## 整体发行时的规则

联合发行包中包含受非商业条款约束的 OB 衍生内容，因此不能因为仓库根存在
AGPL-3.0 就将整个联合包理解为可以无条件商用。联合发行时应遵守各目录的上游条款，
并保留根 `NOTICE`、`ombre-brain/MODIFICATIONS.md` 及所有上游许可文件。

如只单独使用某个目录，以该目录自身许可文件及其上游来源说明为准。
