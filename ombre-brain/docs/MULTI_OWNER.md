# 一个大脑、多人共用、记忆隔离 / One Brain, Multiple Owners

同一套 OB 代码 / 一台机器，给多个人用，但**每个人的记忆完全隔离、互不可见**。前端会在
Dashboard 顶部标明「这份记忆是谁的」——**只有 2 人及以上时才显示**（单人保持干净）。

## 原理一句话

**每个人 = 一个独立实例**：独立数据目录（`OMBRE_VAULT_DIR`）+ 独立端口（`OMBRE_PORT`）。
记忆桶、向量库（`embeddings.db`）、脱水缓存、错误日志全部落在各自的数据目录下，**天生隔离**，
不改一行核心代码。两个新变量控制前端归属徽标：

| 环境变量 | 作用 | 谁设置 |
|---|---|---|
| `OMBRE_OWNER_NAME` | 这个人的显示名（徽标文字） | 每个实例各设自己的 |
| `OMBRE_OWNER_COUNT` | 共用这套 OB 的总人数 | 所有实例设成相同值（= 人数） |

规则：`OWNER_COUNT >= 2` 且 `OWNER_NAME` 非空 → 显示徽标；否则不显示。

> ⚠️ `OMBRE_OWNER_NAME` 只从进程环境读取，**不会**被写进共享的 `src/.env`，所以多实例不会互相串名。

---

## 方式一：本地一键启动器（跨平台，推荐本机 / 单机多用户）

1. 复制配置模板并按需修改：
   ```bash
   cp deploy/owners.example.yaml deploy/owners.yaml
   ```
   ```yaml
   owners:
     - name: 小明
       port: 18001
       vault: ./buckets-ming
     - name: 小红
       port: 18002
       vault: ./buckets-hong
   ```
2. 启动（Windows / Linux / macOS 通用，只依赖 Python + PyYAML）：
   ```bash
   python deploy/multi_owner.py
   ```
   启动器会自动：按人数注入 `OMBRE_OWNER_COUNT`、为每人建数据目录、拉起各自实例、打印
   「谁在哪个端口」。`Ctrl+C` 一次性停止所有实例；任一实例意外退出会整体收摊。

3. 各自访问：小明 `http://localhost:18001`、小红 `http://localhost:18002`。

**加第 N 个人**：在 `owners.yaml` 里再加一段 `name/port/vault`（端口、目录都要唯一），重启启动器即可，`OWNER_COUNT` 自动重算。

---

## 方式二：Docker 多实例（推荐服务器 / VPS 长期在线）

```bash
docker compose -f deploy/docker-compose.multi.yml up -d --build
```

`deploy/docker-compose.multi.yml` 每个人一个 service（独立卷 + 独立端口 + `OMBRE_OWNER_NAME`）。
**加人**：照抄一个 service 块，改 `container_name` / 端口 / 卷 / `OMBRE_OWNER_NAME`，并把每个块的
`OMBRE_OWNER_COUNT` 一起改成新的总人数。敏感 key 走 `deploy/.env`。

---

## 方式三：托管平台（Zeabur / Railway / Render 等）

这些平台一个 project 就是一个实例。给每个人开一个 project，各自挂持久卷，在平台的环境变量里设：

```
OMBRE_VAULT_DIR   = /app/buckets      # 或平台的持久卷挂载路径
OMBRE_OWNER_NAME  = 小明
OMBRE_OWNER_COUNT = 2                  # 所有人填相同的总人数
```

端口、数据卷天生隔离（各 project 各一份），记忆自然不串。

---

## 验证隔离是否成立

- 小明那份写一条记忆 → 只在小明的 Dashboard / `buckets-ming` 里出现，小红那份完全看不到。
- 单人（`OWNER_COUNT=1` 或不设）→ 顶部无归属徽标；≥2 人 → 出现「记忆归属：<名字>」徽标。
- 自动化测试见 `tests/test_multi_owner_isolation.py`（存储隔离）与 `tests/test_owner_identity.py`（后端字段）。
