"""
========================================
web/_shared.py — Dashboard/HTTP 层的共享依赖与鉴权工具
========================================

类比 tools/_runtime.py：web/ 下的各路由模块（auth/tunnel/oauth/…）都从这里取
运行期依赖（config）和横切工具（cookie 会话鉴权、密码哈希、安全问题急救）。

为什么单独抽出来：
- server.py 历史上把 93 个 @mcp.custom_route 全平铺在一个 5000 行文件里，难维护。
- 鉴权是所有 /api/* 路由的横切关注点，必须有一个单一来源，否则一拆就到处重复。

关键行为：
- init(config)：启动时由 server.py 注入 config（之后函数按需读 config["buckets_dir"]）。
- 会话：基于 cookie 的简单会话，落盘到 <buckets_dir>/.dashboard_sessions.json，
  默认 30 天有效且可配置；_load_sessions 原地改 _sessions（不重绑），
  这样 server.py / 其它模块 `from ._shared import _sessions` 始终指向同一对象。
- 密码：PBKDF2-HMAC-SHA256 存 <buckets_dir>/.dashboard_auth.json；支持环境变量
  OMBRE_DASHBOARD_PASSWORD 覆盖；安全问题用于忘密码急救。

不做什么：
- 不定义任何路由（路由在 web/<模块>.py 里，用 register(mcp) 注册）。
- 不持有业务引擎（bucket_mgr 等仍在 server.py / tools/_runtime；需要时再按同样方式注入）。

对外暴露：init + 一组鉴权/会话/密码 helper（名字与原 server.py 完全一致，便于 import 回去）。
========================================
"""

import os
import time
import json as _json_lib
import hashlib
import hmac
import ipaddress
import secrets
import logging

from starlette.requests import Request
from starlette.responses import Response

from ombrebrain.app.execution import ExecutionEnvelope
from ombrebrain.policy.update_policy import evaluate_update_manifest as _evaluate_update_manifest

logger = logging.getLogger("ombre_brain")

# --- 运行环境探测（Docker vs 裸机）---
# 本地向量化要按宿主类型分流：Docker 里 ollama 是独立容器（连 ombre-ollama），
# 裸机/原生则连本机 127.0.0.1。结果缓存一次，避免每次 IO。
_in_docker_cache: "bool | None" = None


def in_docker() -> bool:
    """是否运行在 Docker 容器里。看 /.dockerenv 与 /proc/1/cgroup。结果缓存。"""
    global _in_docker_cache
    if _in_docker_cache is not None:
        return _in_docker_cache
    found = False
    try:
        if os.path.exists("/.dockerenv"):
            found = True
        else:
            with open("/proc/1/cgroup", "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            found = ("docker" in txt) or ("containerd" in txt) or ("kubepods" in txt)
    except Exception:
        found = False
    _in_docker_cache = found
    return found


def data_dir_persistence(buckets_dir: str) -> dict:
    """判断记忆数据目录是不是真的在持久盘上（记忆最怕的就是「以为存住了其实没有」）。

    - 裸机：目录就在用户磁盘上 → 本地持久。
    - Docker 且该目录不是挂载点：躺在容器临时层，容器一重建/删除记忆全丢 → 危险，硬告警。
    - Docker 且已挂载：至少能扛住重启/常规重建；若显式挂了宿主/命名卷则更稳。

    只做检测与提示，绝不阻断启动（阻断会伤部署体验）。返回 {persistent, mode, note}。
    """
    if not in_docker():
        return {"persistent": True, "mode": "local",
                "note": "本地部署：记忆就存在你磁盘上的这个目录里。"}
    is_mount = False
    try:
        is_mount = os.path.ismount(buckets_dir) if buckets_dir else False
    except Exception:
        is_mount = False
    if not is_mount:
        return {
            "persistent": False,
            "mode": "ephemeral",
            "note": ("记忆目录没有挂到持久卷，正躺在容器的临时层——容器一旦重建或删除，"
                     "记忆会全部丢失。请在 docker-compose 里把它挂到命名卷或宿主机目录。"),
        }
    if os.environ.get("OMBRE_HOST_VAULT_DIR", "").strip():
        return {"persistent": True, "mode": "host_mount",
                "note": "记忆目录已挂到宿主机/命名卷，重建容器也不会丢。"}
    return {
        "persistent": True,
        "mode": "volume",
        "note": ("记忆目录在 Docker 卷上，重启和常规重建都不会丢。若你用的是匿名卷，"
                 "建议改成命名卷或宿主机目录，避免 `docker compose down -v` 等操作误删。"),
    }


# --- 注入的运行期配置（server.py 启动时 init 进来）---
config: dict = {}

# --- 注入的业务引擎与运行期信息（类比 tools/_runtime；server.py 启动时 init_runtime）---
# 各 web 路由模块通过 sh.<name> 读取，避免和 server.py 各持一份不一致。
# embedding_engine 会被热重载替换 —— 替换方必须写 sh.embedding_engine（属性赋值），
# 这样所有模块下次读 sh.embedding_engine 都拿到新实例。
version: str = ""
repo_root: str = ""   # 仓库根目录（server.py 注入；用于定位 frontend/ 等，避免各模块各算 __file__）
bucket_mgr = None
dehydrator = None
decay_engine = None
embedding_engine = None
embedding_outbox = None
import_engine = None
migrate_engine = None
github_sync_instance = None
v3_runtime = None


def init(cfg: dict) -> None:
    """启动时由 server.py 调用，注入全局 config。"""
    global config
    config = cfg


def init_runtime(**kwargs) -> None:
    """启动时注入业务引擎与版本等运行期对象。

    用法：init_runtime(version=..., bucket_mgr=..., decay_engine=..., ...)
    只更新传入的键，未传的保持不变。
    """
    globals().update(kwargs)


async def _read_json_object(request: Request) -> dict:
    """Parse a JSON request body and reject non-object top-level values.

    Mutation routes use named fields. Accepting arrays, strings, or scalars makes
    later ``body.get(...)`` calls fail as HTTP 500s and can turn malformed input
    into an unintended default action. Callers keep control of their response
    shape by catching ``ValueError`` alongside JSON parse errors.
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    return body


def replace_embedding_engine(engine) -> None:
    """Atomically publish a hot-reloaded embedding engine to all holders."""
    global embedding_engine
    embedding_engine = engine

    for holder_name, attribute in (
        ("bucket_mgr", "embedding_engine"),
        ("import_engine", "embedding_engine"),
        ("migrate_engine", "_embedding_engine"),
    ):
        holder = globals().get(holder_name)
        if holder is not None:
            try:
                setattr(holder, attribute, engine)
            except Exception:
                logger.warning(
                    "Failed to refresh %s.%s", holder_name, attribute,
                    exc_info=True,
                )

    # MCP tools keep a separate runtime container. Without updating it, reads
    # keep using the old model while Dashboard writes use the new one.
    try:
        from tools import _runtime as tools_runtime  # type: ignore
    except ImportError:  # pragma: no cover
        try:
            from ..tools import _runtime as tools_runtime  # type: ignore
        except ImportError:
            tools_runtime = None
    if tools_runtime is not None:
        tools_runtime.embedding_engine = engine
    outbox = globals().get("embedding_outbox")
    if outbox is not None:
        try:
            outbox.set_embedding_engine(engine)
        except Exception:
            logger.warning("Failed to refresh embedding outbox engine", exc_info=True)


def evaluate_v3_update_manifest(manifest, content_by_path):
    """Evaluate hot-update manifests through v3 policy when available."""
    runtime = globals().get("v3_runtime")
    evaluator = getattr(runtime, "evaluate_update_manifest", None)
    if callable(evaluator):
        try:
            return evaluator(manifest, content_by_path)
        except Exception as exc:
            logger.warning(f"v3 update manifest evaluation failed, falling back: {exc}")
    return _evaluate_update_manifest(manifest, content_by_path)


def run_v3_web_operation(
    operation: str,
    payload: dict | None,
    handler,
    *,
    module: str,
    permissions: tuple[str, ...] = (),
    required_permissions: tuple[str, ...] = (),
    actor_name: str = "dashboard",
    source: str = "web",
    capability: str = "",
    writes_memory: bool = False,
    protected_paths: tuple[str, ...] = (),
    feature_flags: tuple[str, ...] = (),
):
    """Run a web operation through the optional v3 execution side channel."""
    runtime = globals().get("v3_runtime")
    runner = getattr(runtime, "run_operation", None)
    if not callable(runner):
        return handler()
    envelope = ExecutionEnvelope(
        module=module,
        operation=operation,
        payload=payload or {},
        actor_name=actor_name,
        source=source,
        permissions=permissions,
        required_permissions=required_permissions,
        capability=capability,
        writes_memory=writes_memory,
        protected_paths=protected_paths,
        feature_flags=feature_flags,
    )
    return runner(envelope, handler)


# --- 心跳 / 活跃时间戳（原 server.py；移到这里让 heartbeat 路由与工具共用同一来源）---
_SERVER_START_TS = time.time()
_LAST_OP_TS = _SERVER_START_TS


def _mark_op(name: str = "") -> None:
    """记录一次工具/接口活跃时间，供 /api/heartbeat 上报。

    server.py 启动时把本函数注入 tools._runtime.mark_op，工具调用即更新；
    /api/heartbeat（web/system.py）读 _LAST_OP_TS。两边同一来源，不会不一致。
    """
    global _LAST_OP_TS
    _LAST_OP_TS = time.time()


# --- server.py 级 helper 的注入位（保持定义在 server.py，这里只持引用）---
# 这些函数读/写 server.py 的 webhook 全局等，搬过来会引发级联，故用注入而非搬迁。
# 在它们各自定义之后由 server.py 调 init_runtime(...) 填入。
fire_webhook = None            # async def(event: str, payload: dict) -> None
write_deletion_notice = None   # def(names: list) -> None
pop_deletion_notice = None     # def() -> str
restart_github_auto_task = None # def(interval_minutes: int) -> None（起停后台 GitHub 同步任务）


# --- 项目 .env 读写（config / env-config / host-vault 路由共用，故放共享层）---
# 与原 server.py 行为一致：.env 落在 src/.env。本文件在 src/web/ 下，上两级即 src/。
def _project_env_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def _read_env_var(name: str) -> str:
    """Return current value of `name` from process env first, then .env file (best-effort)."""
    val = os.environ.get(name, "").strip()
    if val:
        return val
    env_path = _project_env_path()
    if not os.path.exists(env_path):
        return ""
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _write_env_var(name: str, value: str) -> None:
    """Idempotent upsert of `NAME=value` in project .env. Creates file if missing.
    Preserves other entries verbatim. Quotes values containing spaces.
    """
    env_path = _project_env_path()
    quoted = f'"{value}"' if value and (" " in value or "#" in value) else value
    new_line = f"{name}={quoted}\n"

    lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    replaced = False
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, _, _v = stripped.partition("=")
        if k.strip() == name:
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line)

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


# --- Dashboard 鉴权常量（原 server.py 调参面板）---
_PASSWORD_SALT_BYTES = 16            # secrets.token_hex(该值) → 32 char hex salt
_SESSION_TOKEN_BYTES = 32            # secrets.token_urlsafe(该值) → ~43 char token
_DEFAULT_SESSION_TTL_DAYS = 30
_MAX_SESSION_TTL_DAYS = 365
_MAX_ACTIVE_SESSIONS = 256
_SESSION_TTL_SECONDS = 86400 * _DEFAULT_SESSION_TTL_DAYS
_SESSION_TTL = _SESSION_TTL_SECONDS  # compatibility constant for older callers


def _session_ttl_seconds() -> int:
    """Return a bounded dashboard session lifetime.

    A century-long persisted bearer cookie made a copied session effectively
    permanent. Operators can still choose a longer window, but the default and
    hard cap now keep that exposure finite.
    """
    raw = os.environ.get("OMBRE_DASHBOARD_SESSION_DAYS", "").strip()
    try:
        days = int(raw) if raw else _DEFAULT_SESSION_TTL_DAYS
    except (TypeError, ValueError, OverflowError):
        days = _DEFAULT_SESSION_TTL_DAYS
    return max(1, min(days, _MAX_SESSION_TTL_DAYS)) * 86400

_sessions: dict[str, float] = {}  # {token: expiry_timestamp}


# --- 登录失败限流 / 指数退避锁定（防在线密码爆破）---
# 纯内存滑窗，无外部依赖；进程重启即清零（可接受：重启本身打断了攻击者的连续尝试）。
# 按客户端标识（X-Forwarded-For 首段，回退 request.client.host）分桶，避免一个坏客户端
# 把所有人都锁死。成功登录立即清零。
_LOGIN_WINDOW_SECONDS = 900          # 15 分钟滑窗内统计失败
_LOGIN_MAX_FAILURES = 5              # 窗口内允许的失败次数，超过即进入锁定
_LOGIN_BASE_LOCK_SECONDS = 60        # 首次锁定时长，按超出次数指数增长
_LOGIN_MAX_LOCK_SECONDS = 3600       # 锁定时长上限（1 小时）

_login_failures: dict[str, list[float]] = {}      # {client_key: [失败时间戳...]}
_login_locked_until: dict[str, float] = {}        # {client_key: 解锁时间戳}


def _client_key(request: Request) -> str:
    """Return a spoof-resistant login rate-limit key.

    Forwarding headers are accepted only from an explicitly trusted proxy.
    Direct clients cannot evade lockout by rotating a forged X-Forwarded-For.
    The built-in Cloudflare child connects over loopback, which is trusted by
    default. Additional proxy CIDRs can be listed in
    ``OMBRE_TRUSTED_PROXY_CIDRS``.
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", "") if client else ""
    peer = str(host or "").strip()
    if _is_trusted_proxy(peer):
        try:
            forwarded = (
                request.headers.get("x-forwarded-for") or ""
            ).split(",", 1)[0].strip()
            if forwarded:
                return str(ipaddress.ip_address(forwarded))
        except (AttributeError, ValueError):
            pass
    try:
        return str(ipaddress.ip_address(peer))
    except ValueError:
        return peer or "unknown"


def _trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    raw = os.environ.get(
        "OMBRE_TRUSTED_PROXY_CIDRS", "127.0.0.0/8,::1/128"
    )
    networks = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logger.warning("[auth] ignoring invalid trusted proxy CIDR: %s", item)
    return tuple(networks)


def _is_trusted_proxy(peer: str) -> bool:
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(address in network for network in _trusted_proxy_networks())


def _trusted_forwarded_value(request: Request, header: str) -> str:
    """Read one forwarded header only when the immediate peer is trusted."""
    client = getattr(request, "client", None)
    peer = str(getattr(client, "host", "") or "") if client else ""
    if not _is_trusted_proxy(peer):
        return ""
    try:
        return (request.headers.get(header) or "").split(",", 1)[0].strip()
    except Exception:
        return ""


def _login_retry_after(request: Request) -> int:
    """>0 = 当前被锁，返回建议等待秒数；0 = 允许尝试。"""
    key = _client_key(request)
    now = time.time()
    until = _login_locked_until.get(key, 0.0)
    if until > now:
        return int(until - now) + 1
    if until:
        _login_locked_until.pop(key, None)
    return 0


def _record_login_failure(request: Request) -> None:
    """记一次失败；窗口内累计超阈值则按指数退避锁定该客户端。"""
    key = _client_key(request)
    now = time.time()
    fails = [t for t in _login_failures.get(key, []) if now - t < _LOGIN_WINDOW_SECONDS]
    fails.append(now)
    _login_failures[key] = fails
    if len(fails) >= _LOGIN_MAX_FAILURES:
        over = len(fails) - _LOGIN_MAX_FAILURES
        lock = min(_LOGIN_BASE_LOCK_SECONDS * (2 ** over), _LOGIN_MAX_LOCK_SECONDS)
        _login_locked_until[key] = now + lock
        logger.warning(f"[auth] login rate-limit: client {key} locked for {int(lock)}s after {len(fails)} failures")


def _record_login_success(request: Request) -> None:
    """成功登录：清空该客户端的失败计数与锁定。"""
    key = _client_key(request)
    _login_failures.pop(key, None)
    _login_locked_until.pop(key, None)


def _get_auth_file() -> str:
    return os.path.join(config["buckets_dir"], ".dashboard_auth.json")


def _get_sessions_file() -> str:
    return os.path.join(config["buckets_dir"], ".dashboard_sessions.json")


def _atomic_write_private_json(path: str, data: object) -> None:
    """Atomically persist authentication material with owner-only permissions."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.{secrets.token_hex(6)}.tmp"
    fd = -1
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            _json_lib.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _load_sessions() -> None:
    """Load persisted sessions from disk on startup. Drop expired ones.

    原地改 _sessions（clear+update），不重绑对象 —— 这样别处 `from ._shared import
    _sessions` 拿到的引用始终有效。
    """
    try:
        path = _get_sessions_file()
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            raw = _json_lib.load(f)
        now = time.time()
        max_expiry = now + _session_ttl_seconds()
        # 文件格式：{token: expiry_ts}；过期、畸形和超出当前安全窗口的值不照单全收。
        valid = {
            tok: min(float(exp), max_expiry)
            for tok, exp in raw.items()
            if isinstance(tok, str)
            and 20 <= len(tok) <= 256
            and isinstance(exp, (int, float))
            and exp > now
        }
        if len(valid) > _MAX_ACTIVE_SESSIONS:
            valid = dict(
                sorted(valid.items(), key=lambda item: item[1], reverse=True)[
                    :_MAX_ACTIVE_SESSIONS
                ]
            )
        _sessions.clear()
        _sessions.update(valid)
    except Exception as e:
        logger.warning(f"[auth] failed to load sessions: {e}")


def _save_sessions() -> None:
    """Atomically persist active sessions to disk."""
    try:
        path = _get_sessions_file()
        now = time.time()
        active = {
            tok: exp
            for tok, exp in sorted(
                _sessions.items(), key=lambda item: item[1], reverse=True
            )[:_MAX_ACTIVE_SESSIONS]
            if exp > now
        }
        _atomic_write_private_json(path, active)
    except Exception as e:
        logger.warning(f"[auth] failed to save sessions: {e}")


def _load_auth_data() -> dict:
    try:
        auth_file = _get_auth_file()
        if os.path.exists(auth_file):
            with open(auth_file, "r", encoding="utf-8") as f:
                return _json_lib.load(f)
    except Exception:
        pass
    return {}


def _load_password_hash() -> str | None:
    return _load_auth_data().get("password_hash")


# --- 密钥派生（密码 / 安全问题答案）---
# 历史格式是单轮 `salt:sha256hex`，auth 文件一旦泄露离线爆破成本极低。
# 改用 PBKDF2-HMAC-SHA256（慢 KDF）。存储格式：pbkdf2_sha256$<迭代数>$<salt_hex>$<hash_hex>。
# 旧格式仍能校验（向后兼容），并在下次校验成功时静默升级到新格式（见 _verify_any_password）。
_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 240_000


def _hash_secret(secret: str) -> str:
    """把明文口令/答案派生成 pbkdf2_sha256$iter$salt$hash 存储串。"""
    salt = secrets.token_hex(_PASSWORD_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_ALGO}${_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def _verify_secret(secret: str, stored: str) -> bool:
    """校验明文与存储串是否匹配。支持新 PBKDF2 格式与旧 `salt:sha256hex` 格式。"""
    if not stored:
        return False
    if stored.startswith(_PBKDF2_ALGO + "$"):
        try:
            _algo, iter_s, salt, expected = stored.split("$", 3)
            iterations = int(iter_s)
            dk = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt), iterations)
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(dk.hex(), expected)
    # 旧格式：salt:sha256(salt:secret)
    if ":" in stored:
        salt, h = stored.split(":", 1)
        return hmac.compare_digest(h, hashlib.sha256(f"{salt}:{secret}".encode()).hexdigest())
    return False


def _needs_rehash(stored: str) -> bool:
    """旧格式或迭代数低于当前标准 → 建议校验成功时静默升级。"""
    if not stored or not stored.startswith(_PBKDF2_ALGO + "$"):
        return True
    try:
        return int(stored.split("$", 3)[1]) < _PBKDF2_ITERATIONS
    except (ValueError, IndexError):
        return True


def _save_password_hash(password: str, *, keep_qa: bool = True) -> None:
    auth_file = _get_auth_file()
    os.makedirs(os.path.dirname(auth_file), exist_ok=True)
    data: dict = {"password_hash": _hash_secret(password)}
    if keep_qa:
        existing = _load_auth_data()
        if existing.get("security_question"):
            data["security_question"] = existing["security_question"]
        if existing.get("security_answer_hash"):
            data["security_answer_hash"] = existing["security_answer_hash"]
    _atomic_write_private_json(auth_file, data)


def _save_security_qa(question: str, answer: str) -> None:
    auth_file = _get_auth_file()
    os.makedirs(os.path.dirname(auth_file), exist_ok=True)
    data = _load_auth_data()
    data["security_question"] = question.strip()
    data["security_answer_hash"] = _hash_secret(answer.strip().lower())
    _atomic_write_private_json(auth_file, data)


def _verify_security_answer(answer: str) -> bool:
    stored = _load_auth_data().get("security_answer_hash", "")
    return _verify_secret(answer.strip().lower(), stored)


def _is_setup_needed() -> bool:
    """True if no password is configured (env var or file)."""
    if os.environ.get("OMBRE_DASHBOARD_PASSWORD", ""):
        return False
    return _load_password_hash() is None


def _verify_any_password(password: str) -> bool:
    """Check password against env var (first) or stored hash."""
    env_pwd = os.environ.get("OMBRE_DASHBOARD_PASSWORD", "")
    if env_pwd:
        return hmac.compare_digest(password, env_pwd)
    stored = _load_password_hash()
    if not stored:
        return False
    if not _verify_secret(password, stored):
        return False
    # 校验通过：若存的是旧格式或低迭代数，趁手里有明文静默升级到当前 PBKDF2 标准。
    if _needs_rehash(stored):
        try:
            _save_password_hash(password)
        except Exception as e:
            logger.warning(f"[auth] password hash upgrade failed: {e}")
    return True


def _create_session() -> str:
    now = time.time()
    expired = [tok for tok, exp in _sessions.items() if exp <= now]
    for tok in expired:
        _sessions.pop(tok, None)
    while len(_sessions) >= _MAX_ACTIVE_SESSIONS:
        oldest = min(_sessions, key=_sessions.get)
        _sessions.pop(oldest, None)
    token = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
    _sessions[token] = now + _session_ttl_seconds()
    _save_sessions()
    return token


def _is_authenticated(request: Request) -> bool:
    token = request.cookies.get("ombre_session")
    if not token:
        return False
    expiry = _sessions.get(token)
    if expiry is None or time.time() > expiry:
        if expiry is not None:
            _sessions.pop(token, None)
            _save_sessions()
        return False
    return True


def _is_https_request(request: Request) -> bool:
    """Detect HTTPS through Cloudflare/reverse-proxy via X-Forwarded-Proto header."""
    proto = _trusted_forwarded_value(request, "x-forwarded-proto").lower()
    if proto == "https":
        return True
    try:
        return request.url.scheme == "https"
    except Exception:
        return False


def _set_session_cookie(resp: Response, token: str, request: Request) -> None:
    """Set the ombre_session cookie. Mark Secure when behind HTTPS so modern
    browsers (Safari/Chrome) actually persist it across navigations.
    本地 http://127.0.0.1 走 secure=False，公网 https 自动开启 Secure。
    """
    resp.set_cookie(
        "ombre_session",
        token,
        httponly=True,
        samesite="lax",
        secure=_is_https_request(request),
        max_age=_session_ttl_seconds(),
        path="/",
    )


def _require_auth(request: Request) -> Response | None:
    """Return JSONResponse(401) if not authenticated, else None."""
    from starlette.responses import JSONResponse
    if not _is_authenticated(request):
        return JSONResponse(
            {"error": "Unauthorized", "setup_needed": _is_setup_needed()},
            status_code=401,
        )
    return None
