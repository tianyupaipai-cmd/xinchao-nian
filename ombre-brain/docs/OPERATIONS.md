# Ombre Brain 可靠性与恢复手册

这份文档说明 Ombre Brain 在断网、模型限流、外部编辑和备份恢复时真正保证什么。

## 数据边界

- `buckets/**/*.md` 是记忆真源。写入成功以 Markdown 原子落盘为准。
- `embeddings.db`、BM25 缓存和脱水缓存都是可重建的派生数据。
- `.embedding_outbox.json` 只保存待索引 ID、内容哈希和重试状态，不复制记忆正文。
- `config.yaml`、`.env`、API Key、OAuth/Tunnel token 不进入本地记忆导出包。

## 写入与恢复保证

1. embedding 不可用、限流或超时时，Markdown 仍先保存，后台 outbox 持久重试。
2. 连续 provider 故障会打开全局熔断，避免每条待办都重复撞击同一个故障端点；冷却后自动恢复，也可在 Dashboard 手动补齐。
3. Obsidian、Git 或手工修改 Markdown 后，BucketManager 会按配置的轮询间隔发现文件集合/mtime/size 变化，刷新内存与 BM25，并只对正文变化重新排队向量。
4. 本地导出对正在使用的 SQLite 调用 backup API，得到事务一致快照；不会直接复制可能处于 WAL 写入中的数据库文件。
5. 新导出包含 `backup_manifest.json`，逐文件记录字节数与 SHA-256。恢复预检要求清单与 ZIP 内容完全一致。

清单只能发现残缺或意外篡改，不能证明备份由谁创建。需要来源认证时，应在可信存储或带签名的发布/备份系统中保管 ZIP。

## 日常检查

Dashboard 的“系统诊断”与命令行使用同一套只读检查：

```bash
python tools/check_buckets.py
python tools/check_buckets.py --json
```

检查项包括：

- Markdown 是否都能以 UTF-8 + frontmatter 解析；
- 是否存在重复 bucket ID 或指向 vault 外的软链接；
- `embeddings.db` 的 `PRAGMA quick_check`；
- 已没有对应 Markdown 的孤儿向量；
- 活跃 Markdown 缺向量时，是否已经进入 outbox。

历史兼容工具：

- `python tools/diagnose_permanent_reads.py` 只读检查旧版 permanent 召回问题，不再导入完整 server runtime。
- `python tools/migrate_feel_domain.py` 默认只读预演；确认旧 feel 元数据后必须显式加 `--apply`。
- `python tools/fix_unpinned_permanent.py` 默认只读。`--force-demote` 只用于人工确认的旧数据；当前显式 permanent 是合法类型，不能批量自动降级。

## 备份与恢复演练

1. 在 Dashboard 导出完整记忆包，确认请求成功且文件非空。
2. 准备一个全新的临时 vault/测试实例，不要直接覆盖唯一的生产目录。
3. 在迁移页面上传 ZIP。新包应显示“备份清单与 SHA-256 校验通过”；旧包会显示“未验证”。
4. 检查 bucket 数、冲突决策和 embedding 模型/维度，再执行导入。
5. 导入完成后运行 `python tools/check_buckets.py`，并用 `breath(query=...)` 抽查可检索性。
6. 确认 outbox 待处理数最终回到 0。模型离线时允许保持 pending，但 Markdown 必须完整可读。

导入冲突的语义：

- `skip`：保留当前记忆，不导入冲突项。
- `keep_both`：导入项获得新 ID；可复用的向量同步映射到新 ID。
- `overwrite`：当前项不会被物理抹去，而是归档并获得唯一的 `*-superseded-*` 历史 ID；导入项接管原 ID。

## 故障处置

| 现象 | 数据状态 | 处理 |
|---|---|---|
| embedding 超时/限流 | Markdown 已保存，向量 pending | 检查网络/额度；等待熔断冷却或手动补齐 |
| 语义检索不可用 | 关键词/BM25 仍可读，返回明确降级提示 | 修复 provider 后等待 outbox 清空 |
| Obsidian 修改后结果旧 | 等待外部变更轮询周期 | 检查 `storage.external_change_poll_seconds`，再看系统诊断的外部变更计数 |
| ZIP 上传被拒绝 | 本地 vault 未写入 | 按错误修复损坏、路径穿越、重复项或清单不一致，重新导出 |
| SQLite quick_check 失败 | Markdown 真源通常仍在 | 先备份 Markdown，移走损坏的派生库，再重建向量；不要删除 Markdown |
| outbox 长时间不下降 | 记忆正文仍安全 | 查看熔断状态、最近错误、Key/模型/维度和 provider 连通性 |

## 访问控制

- Dashboard 会话默认 30 天过期，可通过 `OMBRE_DASHBOARD_SESSION_DAYS` 调整为 1-365 天。认证文件与 token 文件使用原子写入，并在支持的系统上限制为仅文件所有者可读写。
- 登录和 OAuth 授权共用失败限流。`X-Forwarded-For` / `X-Forwarded-Proto` / `X-Forwarded-Host` 只在请求确实来自可信反代时采用；内置 Tunnel 使用回环地址，外置 nginx/Caddy/容器反代应通过 `OMBRE_TRUSTED_PROXY_CIDRS` 添加准确 CIDR，不能使用 `0.0.0.0/0`。
- `limits.max_management_request_bytes` 限制普通 Dashboard/OAuth 写请求；导入文本和迁移 ZIP 仍使用各自更大的流式上限。
- `/api/update-info` 包含数据目录和容器信息，因此需要 Dashboard 登录；公开健康检查仅使用 `/health` 和 `/api/version`。

## Docker 热更新与代码播种

容器内的记忆真源和运行代码是两类资产。记忆始终以 `buckets/**/*.md` 为准；运行代码由 `entrypoint.sh` 从镜像播种到可写卷上的 `OMBRE_CODE_DIR`，Dashboard 热更新只修改后者。

启动器用两项信息判断镜像是否需要重新播种：

1. 根目录 `VERSION`；
2. 镜像 `src/` 与 `frontend/` 的稳定 SHA-256 代码指纹。

`.seeded_image_fingerprint` 保存“上次播种所用镜像”的指纹，而不是当前运行目录指纹。这个区别是刻意的：Dashboard 热更新会让运行目录不同于镜像，但只要镜像基线没变，重启必须继续保留热更新；本地以相同 `VERSION` 重建了不同代码的镜像时，镜像指纹会变化并触发重新播种。

重新播种先复制到暂存目录并检查 `src/server.py` 与 `frontend/`，完成后才切换活动树。原先健康的运行树会进入 `_prev`；新树连续启动失败达到阈值后自动回滚，回滚结果不会在同一次启动中再次被同一坏镜像覆盖。

常用日志状态：

| 状态 | 含义 |
|---|---|
| `code-state=image-match` | 活动代码与镜像完全一致 |
| `code-state=runtime-override` | 活动代码来自热更新或回滚，镜像未变化，因此保留 |
| `code-state=reseed reason=image-fingerprint-changed` | 版本号相同，但镜像代码内容变化，已重新播种 |
| `code-state=legacy-residue` | 数据目录里发现非活动的历史 `_app`，只提示、不自动删除 |

排障必须先看日志中的“活动代码目录”。默认部署的 `<数据目录>/_app` 可能正在使用，不能仅凭其中的 `VERSION` 新旧决定删除。只有明确出现 `code-state=legacy-residue` 时，该路径才是非活动遗留；建议先备份再手工清理。

紧急情况下可为单次启动设置 `OMBRE_FORCE_CODE_RESEED=1`，强制丢弃卷内运行覆盖并从镜像重新播种。确认启动成功后必须移除该变量，否则每次启动都会重新播种。

`entrypoint.sh` 本身来自镜像，不在 Dashboard 热更新覆盖范围内。升级到带有新播种逻辑的版本时必须先拉取/重建镜像一次，不能只点击 Dashboard 更新。

Dashboard 热更新会限制下载包、成员数、单文件大小、总解压量和压缩率。建立 `_prev` 回滚点失败时不会继续覆盖；逐文件写入采用原子替换。若 `requirements.txt` 有变化且未显式开启 `OMBRE_UPDATE_ALLOW_PIP=1`，热更新会回滚并要求重建镜像，避免“代码更新成功但重启后缺包”。

若希望代码与记忆目录彻底分离，生产环境优先使用命名卷或 bind mount，不要依赖无法稳定重新挂载的临时目录。例如：

```yaml
services:
  ombre-brain:
    environment:
      OMBRE_CODE_DIR: /app/ombre-code/_app
    volumes:
      - ombre-code:/app/ombre-code
      - ./buckets:/app/buckets

volumes:
  ombre-code:
```

命名卷默认可跨 `docker compose down` / `up` 复用；执行 `down -v` 会主动删除它。Dashboard 对独立代码卷的检测来自 `/proc/self/mountinfo`，不会再把它误报成容器 overlay 临时层。

## 配置

```yaml
storage:
  external_change_poll_seconds: 1.0

embedding:
  background_indexing: true
  retry_base_seconds: 5
  retry_max_seconds: 300
  circuit_failure_threshold: 3
  circuit_base_seconds: 30
  circuit_max_seconds: 600
```

轮询设为 `0` 表示每次活跃桶列表读取都检查文件状态。生产环境一般保留 `1.0`，避免高频目录扫描。
