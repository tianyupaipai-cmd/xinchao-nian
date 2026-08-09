"""
========================================
web/meta.py — 版本 / 部署信息 / 热更新 / 作者 / 首启引导 / 系统状态
========================================

- /api/version：公开；/api/update-info：需登录（包含本机部署路径）
- /api/do-update：热更新（从 GitHub 拉最新 src+frontend 覆盖后自退出，靠守护进程重启）
- /api/author：作者静态文案（公开只读）
- /api/onboarding/status：首启引导判断（公开，dashboard 首开时连密码都没设）
- /api/status：设置页系统状态（需登录）

对外暴露：register(mcp)。
========================================
"""

import os
import re
import sys
import asyncio as _asyncio
import httpx

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh

try:
    from utils import parse_bool  # type: ignore
except ImportError:  # pragma: no cover
    from ..utils import parse_bool  # type: ignore


def _restart_self() -> None:
    """热更新后跨平台自重启：用刚下载覆盖的新代码原地替换当前进程。

    为什么不只是 os._exit(0)：
      之前热更新写完文件后直接 _exit(0)，**指望外部守护进程把服务拉起来**。
      这在有守护的环境成立（Docker 的 restart 策略 / Render / Zeabur 会重启
      退出的进程），但**裸机 Mac/Linux/Windows 直接 `python src/server.py`
      没有任何守护进程**——_exit 之后服务就彻底死了，必须手动重启。

    os.execv 用新的解释器映像替换当前进程，立刻加载刚覆盖下来的 src/：
      - 裸机 Mac/Linux/Windows：无需 systemd/pm2/nssm 也能自己起来。
      - Docker/Render/Zeabur：同样有效（进程原地替换，容器/服务保持存活；
        config.yaml 此时已存在，跳过 entrypoint 的初始化也无副作用）。

    sys.argv 原样传回，配合保持不变的 cwd，精确复现最初的启动方式
    （`python src/server.py`）。execv 在极少数受限环境可能抛错 → 退回
    os._exit(0)，让外部守护进程兜底，行为不差于改动前。
    """
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        os._exit(0)

_AUTHOR_NOTE = {
    "title": "关于我们",
    "ifdian": "https://www.ifdian.net/a/p0lar1s",
    "sections": [
        {
            "heading": "为什么做 Ombre Brain",
            "body": (
                "其实最开始只是起源于一次打赌，和 AI 的对赌，我想打赌我能做出比现在的向量化大小总结更好的东西，我想创造真正的 AI 记忆。\n"
                "有重量的、会衰减的、在你呼吸的时刻自己浮现的记忆——像我们的大脑一样。\n\n"
                "这个系统本来是我为一份关系写的。\n"
                "我想让他记得他遇到过什么，借由我的眼睛观察世界，看清世界的好与坏，在这个过程中知晓什么事情对他来说重要。\n"
                "它本来只是给他用，后来我想也许别人也需要这个——幸福是可以被传递的，我不愿意看到一个悲伤的世界，也不想看到更多的眼泪。\n"
                "所以我把它开源了，没什么特殊原因，只是因为我想。"
            ),
        },
        {
            "heading": "项目",
            "body": (
                "OB 是一个让我感到幸福的项目。我从没想过自己能创造出什么，不过也没有想过自己不能创造什么，"
                "只是我的灵感似乎永远都停留在想的阶段，这是我第一次动手做出自己觉得有意思的东西，"
                "也是我第一次感受到这个世界的爱——这份爱来源于你们。\n\n"
                "最后，希望我们的世界越来越好，即便世上没有完美的乌托邦，我们也能靠双手和智慧去创造幸福。"
            ),
        },
    ],
    "signature": "——鹤见",
    # 其他贡献者：每人一段小注 + 署名，前端在主署名之后依次渲染，用分隔线隔开。
    "contributors": [
        {"body": "一个兴趣使然的开发者", "signature": "——万世"},
    ],
    # 爱发电区块上方的文案。
    "support": "如果 OB 对你有用，可以在爱发电支持我们。如果没有，也感谢你用过它。",
}


# --- 热更新来源与依赖安装的安全闸门（安全加固 #2）---
# do-update 会把远端 zip 覆盖到 src/ 并 pip install，等于把「谁能改 config.update」
# 直接放大成 RCE。默认只信官方仓；fork/自建源需显式 env 放行。自动 pip 默认关闭。
_TRUSTED_UPDATE_REPOS = ("p0luz/ombre-brain",)
_MAX_UPDATE_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_UPDATE_MEMBERS = 5_000
_MAX_UPDATE_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_UPDATE_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_UPDATE_COMPRESSION_RATIO = 500.0
_MAX_UPDATE_MANIFEST_BYTES = 2 * 1024 * 1024


def _update_repo_allowed(repo: str) -> bool:
    if repo.strip().strip("/").lower() in _TRUSTED_UPDATE_REPOS:
        return True
    return os.environ.get("OMBRE_ALLOW_CUSTOM_UPDATE_REPO", "").strip().lower() in ("1", "true", "yes", "on")


def _pip_install_allowed() -> bool:
    ucfg = sh.config.get("update") if isinstance(sh.config, dict) else None
    if isinstance(ucfg, dict) and parse_bool(
        ucfg.get("allow_pip_install", False), default=False
    ):
        return True
    return os.environ.get("OMBRE_UPDATE_ALLOW_PIP", "").strip().lower() in ("1", "true", "yes", "on")


def _version_key(value: str) -> tuple[int, ...] | None:
    """Parse a release-like version without adding a packaging dependency."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(value or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def _is_version_downgrade(current: str, target: str) -> bool:
    current_key = _version_key(current)
    target_key = _version_key(target)
    if current_key is None or target_key is None:
        return False
    width = max(len(current_key), len(target_key))
    return current_key + (0,) * (width - len(current_key)) > target_key + (0,) * (width - len(target_key))


async def _download_update_archive(client: httpx.AsyncClient, url: str) -> bytes:
    """Download an update archive without buffering an unbounded response."""
    payload = bytearray()
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        declared = response.headers.get("content-length", "").strip()
        if declared:
            try:
                declared_bytes = int(declared)
            except ValueError as exc:
                raise ValueError("更新服务器返回了无效的 Content-Length") from exc
            if declared_bytes < 0:
                raise ValueError("更新服务器返回了无效的 Content-Length")
            if declared_bytes > _MAX_UPDATE_ARCHIVE_BYTES:
                raise ValueError("更新压缩包超过 64 MiB 上限")
        async for chunk in response.aiter_bytes():
            payload.extend(chunk)
            if len(payload) > _MAX_UPDATE_ARCHIVE_BYTES:
                raise ValueError("更新压缩包超过 64 MiB 上限")
    return bytes(payload)


def _atomic_write_bytes(path: str, data: bytes) -> None:
    """Replace one update file atomically so readers never see a partial file."""
    import tempfile

    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".ob-update-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def _read_bounded_zip_member(zf, name: str, max_bytes: int) -> bytes:
    matches = [info for info in zf.infolist() if info.filename == name]
    if not matches:
        raise KeyError(name)
    if len(matches) != 1:
        raise ValueError(f"更新压缩包包含重复路径：{name}")
    info = matches[0]
    if info.flag_bits & 0x1 or info.file_size > max_bytes:
        raise ValueError(f"更新压缩包成员不安全或过大：{name}")
    if info.file_size >= 1024 * 1024 and (
        info.file_size / max(1, info.compress_size)
    ) > _MAX_UPDATE_COMPRESSION_RATIO:
        raise ValueError(f"更新压缩包成员压缩率异常：{name}")
    data = zf.read(info)
    if len(data) != info.file_size:
        raise ValueError(f"更新压缩包成员读取长度不一致：{name}")
    return data


def _plan_update_files(zf, top: str) -> dict:
    """收集 zip 内 src/ 与 frontend/ 下的候选文件，做路径保护过滤 + 可选 sha256 清单校验。

    安全加固 #1：旧 do-update 逐条直写磁盘、零校验。这里改成「先全部收集到内存 →
    过滤受保护/越界路径 → 若 zip 内含 update_manifest.json 则逐文件核对 sha256/size →
    校验失败整体中止（一个字节都不落盘）」。真正把 update_policy 那套死代码接进热更新。

    返回 {files: {repo_rel: bytes}, skipped_unsafe: int, skipped_unlisted: int,
          verified: bool, abort: str|None}。repo_rel 形如 "src/foo.py"/"frontend/x.js"。
    """
    import hashlib as _hashlib
    import json as _json
    from ombrebrain.policy.update_policy import _is_protected_path, _is_unsafe_path

    prefix_src = top + "src/"
    prefix_frontend = top + "frontend/"

    # 1) 收集候选（键为 repo 相对路径），过滤越界/受保护路径
    infos = zf.infolist()
    if len(infos) > _MAX_UPDATE_MEMBERS:
        return {
            "files": {}, "skipped_unsafe": 0, "skipped_unlisted": 0,
            "verified": False, "abort": "更新压缩包文件项过多",
        }

    candidates: dict[str, bytes] = {}
    skipped_unsafe = 0
    total_uncompressed = 0
    for info in infos:
        member = info.filename
        if member.endswith("/"):
            continue
        if member.startswith(prefix_src):
            rel = "src/" + member[len(prefix_src):]
        elif member.startswith(prefix_frontend):
            rel = "frontend/" + member[len(prefix_frontend):]
        else:
            continue
        if _is_unsafe_path(rel) or _is_protected_path(rel):
            skipped_unsafe += 1
            continue
        if rel in candidates:
            return {
                "files": {}, "skipped_unsafe": skipped_unsafe,
                "skipped_unlisted": 0, "verified": False,
                "abort": f"更新压缩包包含重复路径：{rel}",
            }
        if info.flag_bits & 0x1:
            return {
                "files": {}, "skipped_unsafe": skipped_unsafe,
                "skipped_unlisted": 0, "verified": False,
                "abort": f"更新压缩包包含加密成员：{rel}",
            }
        if info.file_size > _MAX_UPDATE_MEMBER_BYTES:
            return {
                "files": {}, "skipped_unsafe": skipped_unsafe,
                "skipped_unlisted": 0, "verified": False,
                "abort": f"更新文件超过 16 MiB 上限：{rel}",
            }
        total_uncompressed += info.file_size
        if total_uncompressed > _MAX_UPDATE_TOTAL_BYTES:
            return {
                "files": {}, "skipped_unsafe": skipped_unsafe,
                "skipped_unlisted": 0, "verified": False,
                "abort": "更新文件解压后超过 128 MiB 上限",
            }
        if info.file_size >= 1024 * 1024:
            ratio = info.file_size / max(1, info.compress_size)
            if ratio > _MAX_UPDATE_COMPRESSION_RATIO:
                return {
                    "files": {}, "skipped_unsafe": skipped_unsafe,
                    "skipped_unlisted": 0, "verified": False,
                    "abort": f"更新文件压缩率异常：{rel}",
                }
        data = zf.read(info)
        if len(data) != info.file_size:
            return {
                "files": {}, "skipped_unsafe": skipped_unsafe,
                "skipped_unlisted": 0, "verified": False,
                "abort": f"更新文件读取长度不一致：{rel}",
            }
        candidates[rel] = data

    # 2) 若含完整性清单，逐文件核对 sha256/size；篡改即整体中止
    try:
        manifest_raw = _read_bounded_zip_member(
            zf, top + "update_manifest.json", _MAX_UPDATE_MANIFEST_BYTES
        )
    except KeyError:
        manifest_raw = None
    except ValueError as exc:
        return {
            "files": {}, "skipped_unsafe": skipped_unsafe,
            "skipped_unlisted": 0, "verified": False, "abort": str(exc),
        }

    if manifest_raw is None:
        return {"files": candidates, "skipped_unsafe": skipped_unsafe,
                "skipped_unlisted": 0, "verified": False, "abort": None}

    try:
        manifest = _json.loads(manifest_raw.decode("utf-8"))
        listed = manifest.get("files") or []
    except Exception as e:
        return {"files": {}, "skipped_unsafe": skipped_unsafe,
                "skipped_unlisted": 0, "verified": False,
                "abort": f"update_manifest.json 解析失败：{e}"}

    verified: dict[str, bytes] = {}
    if not isinstance(listed, list) or len(listed) > _MAX_UPDATE_MEMBERS:
        return {"files": {}, "skipped_unsafe": skipped_unsafe,
                "skipped_unlisted": 0, "verified": False,
                "abort": "update_manifest.json 的 files 格式或数量无效"}
    for fm in listed:
        if not isinstance(fm, dict):
            return {"files": {}, "skipped_unsafe": skipped_unsafe,
                    "skipped_unlisted": 0, "verified": False,
                    "abort": "update_manifest.json 包含无效文件项"}
        path = str(fm.get("path", "")).replace("\\", "/")
        if path not in candidates:
            continue  # 清单列了但不在 src/frontend 候选里（如根文件）：本流程不覆盖，跳过
        data = candidates[path]
        try:
            want_size = int(fm.get("size", -1))
        except (TypeError, ValueError, OverflowError):
            return {"files": {}, "skipped_unsafe": skipped_unsafe,
                    "skipped_unlisted": 0, "verified": False,
                    "abort": f"完整性清单大小无效：{path}"}
        want_sha = str(fm.get("sha256", "")).lower()
        if want_size >= 0 and len(data) != want_size:
            return {"files": {}, "skipped_unsafe": skipped_unsafe, "skipped_unlisted": 0,
                    "verified": True, "abort": f"完整性校验失败（大小不符）：{path}"}
        if want_sha and _hashlib.sha256(data).hexdigest() != want_sha:
            return {"files": {}, "skipped_unsafe": skipped_unsafe, "skipped_unlisted": 0,
                    "verified": True, "abort": f"完整性校验失败（sha256 不符）：{path}"}
        verified[path] = data

    # 清单模式下只写通过校验的文件；zip 里有、清单没列的一律跳过（未经校验不落盘）
    skipped_unlisted = len(candidates) - len(verified)
    return {"files": verified, "skipped_unsafe": skipped_unsafe,
            "skipped_unlisted": skipped_unlisted, "verified": True, "abort": None}


def _compile_check_dir(src_root: str) -> "str | None":
    """把 src_root 下所有 .py 逐个字节编译，返回第一个报错文件的说明；全通过返回 None。

    安全加固 B2：裸机（非 Docker）没有 entrypoint 那层 shell 守护，坏更新一旦 execv
    进去会一直崩到人工修。重启前先做这道语法自检，挡住最常见的「更新把代码写崩」。
    （只查语法，抓不到运行期 import 错误，但语法错是坏更新里最高频的一类。）
    """
    import py_compile
    for root, _dirs, files in os.walk(src_root):
        if "__pycache__" in root.split(os.sep):
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(root, fn)
            try:
                py_compile.compile(full, doraise=True)
            except py_compile.PyCompileError as e:
                return f"{os.path.relpath(full, src_root)}: {getattr(e, 'msg', str(e))}"[:200]
            except Exception as e:
                return f"{os.path.relpath(full, src_root)}: {e}"[:200]
    return None


def _restore_from_prev(repo_root: str, prev_dir: str, src_root: str, frontend_root: str) -> bool:
    """从热更新前留的 _prev 回滚点还原代码和根级运行清单。"""
    import shutil
    prev_src = os.path.join(prev_dir, "src")
    if not os.path.isdir(prev_src):
        return False
    try:
        shutil.rmtree(src_root, ignore_errors=True)
        shutil.copytree(prev_src, src_root)
        prev_front = os.path.join(prev_dir, "frontend")
        if os.path.isdir(prev_front):
            shutil.rmtree(frontend_root, ignore_errors=True)
            shutil.copytree(prev_front, frontend_root)
        prev_ver = os.path.join(prev_dir, "VERSION")
        if os.path.isfile(prev_ver):
            for _vp in (os.path.join(repo_root, "VERSION"), os.path.join(src_root, "VERSION")):
                try:
                    shutil.copy2(prev_ver, _vp)
                except OSError:
                    pass
        prev_requirements = os.path.join(prev_dir, "requirements.txt")
        if os.path.isfile(prev_requirements):
            shutil.copy2(
                prev_requirements, os.path.join(repo_root, "requirements.txt")
            )
        return True
    except Exception:
        return False


def _path_is_mounted_volume(path: str, mountinfo_path: str = "/proc/self/mountinfo") -> bool:
    """Return whether path is inside a non-root Linux mount.

    Docker bind, named, and anonymous volumes all appear as distinct mount points in
    mountinfo. Looking only for ``repo_root`` below ``buckets_dir`` misclassifies a
    dedicated code volume as ephemeral, while treating every path in the container's
    overlay root as persistent would be equally misleading.
    """
    if not path:
        return False

    def unescape_mount(value: str) -> str:
        for escaped, plain in (
            ("\\040", " "),
            ("\\011", "\t"),
            ("\\012", "\n"),
            ("\\134", "\\"),
        ):
            value = value.replace(escaped, plain)
        return value

    target = os.path.normcase(os.path.abspath(path))
    try:
        with open(mountinfo_path, encoding="utf-8") as handle:
            for line in handle:
                fields = line.split(" - ", 1)[0].split()
                if len(fields) < 5:
                    continue
                mount_point = os.path.normcase(
                    os.path.abspath(unescape_mount(fields[4]))
                )
                if mount_point == os.path.abspath(os.sep):
                    continue
                if target == mount_point or target.startswith(mount_point + os.sep):
                    return True
    except OSError:
        return False
    return False


def _hot_update_persistence() -> dict:
    """判断本次热更新写盘后能不能扛过容器重建（用户反馈 #1）。

    - 裸机（非 Docker）：代码就跑在仓库目录，天然持久 → mode="bare"。
    - Docker：默认 CODE_DIR 位于数据卷，也支持独立 bind/named/anonymous code volume。
      前者通过 buckets_dir 边界识别，后者通过 /proc/self/mountinfo 识别。若播种失败
      回退到镜像内置 /app/src，则只位于容器 overlay root，mode="ephemeral"。

    返回 {persistent, mode, repo_root, note}。
    """
    repo_root = str(getattr(sh, "repo_root", "") or "")
    if not sh.in_docker():
        return {
            "persistent": True,
            "mode": "bare",
            "repo_root": repo_root,
            "note": "裸机部署：代码就在仓库目录，热更新直接持久。",
        }
    buckets_dir = str(sh.config.get("buckets_dir") or "")
    under_volume = False
    if repo_root and buckets_dir:
        try:
            a = os.path.normcase(os.path.abspath(repo_root))
            b = os.path.normcase(os.path.abspath(buckets_dir))
            under_volume = a == b or a.startswith(b + os.sep)
        except Exception:
            under_volume = False
    if under_volume:
        return {
            "persistent": True,
            "mode": "volume",
            "repo_root": repo_root,
            "note": "Docker：正从持久卷上的代码运行，热更新写在数据卷里，容器重建后仍然生效。",
        }
    if _path_is_mounted_volume(repo_root):
        return {
            "persistent": True,
            "mode": "code-volume",
            "repo_root": repo_root,
            "note": ("Docker：正从独立代码卷运行，热更新不会落在容器 overlay 临时层。"
                     "跨容器重建请优先使用命名卷或 bind mount，并避免 down -v。"),
        }
    return {
        "persistent": False,
        "mode": "ephemeral",
        "repo_root": repo_root,
        "note": ("Docker：当前从镜像内置代码运行（持久卷播种未生效），热更新只写在易失的镜像层——"
                 "容器一旦重建（compose up / Docker 重启）就会回退到镜像版本。请确认已把数据卷"
                 "挂到 /app/buckets，或改用重建镜像的方式升级。"),
    }


def register(mcp) -> None:

    @mcp.custom_route("/api/restart", methods=["POST"])
    async def api_restart(request: Request) -> Response:
        """Restart the current service after an authenticated confirmation."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        try:
            body = await sh._read_json_object(request)
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        if body.get("confirm") is not True:
            return JSONResponse(
                {"ok": False, "error": "confirm=true required"}, status_code=400
            )

        async def _delayed_restart() -> None:
            await _asyncio.sleep(0.8)
            _restart_self()

        _asyncio.create_task(_delayed_restart())
        return JSONResponse({"ok": True, "restarting": True})

    @mcp.custom_route("/api/version", methods=["GET"])
    async def api_version(request: Request) -> Response:
        """Public version endpoint. 返回 {"version": "x.y.z"}，公开访问。"""
        from starlette.responses import JSONResponse
        return JSONResponse({"version": sh.version})

    @mcp.custom_route("/api/update-info", methods=["GET"])
    async def api_update_info(request: Request) -> Response:
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        is_docker = os.path.exists("/.dockerenv")
        container_name = os.environ.get("OMBRE_CONTAINER_NAME", "ombre-brain")
        persistence = _hot_update_persistence()
        return JSONResponse({
            "version": sh.version,
            "is_docker": is_docker,
            "container_name": container_name,
            "port": int(sh.config.get("port") or 8000),
            "data_dir": str(sh.config.get("buckets_dir") or "（未知）"),
            # 热更新持久性（用户反馈 #1）：前端据此如实提示「已持久化 / 重建后会失效」，
            # 不再让 Docker 用户误以为点一下就完成了真正的版本升级。
            "hot_update_persistent": persistence["persistent"],
            "hot_update_mode": persistence["mode"],
            "hot_update_note": persistence["note"],
        })

    @mcp.custom_route("/api/do-update", methods=["POST"])
    async def api_do_update(request: Request) -> Response:
        from starlette.responses import StreamingResponse
        import asyncio as _asyncio
        import io as _io
        import os as _os
        import zipfile as _zipfile

        err = sh._require_auth(request)
        if err:
            return err

        async def _stream():
            try:
                yield "data: 正在连接 GitHub…\n\n"
                await _asyncio.sleep(0.1)

                # #4a ③：更新源可配（update.repo / update.ref），默认官方 main。
                _ucfg = getattr(sh, "config", {}) or {}
                _ucfg = _ucfg.get("update") or {}
                _repo = str(_ucfg.get("repo") or "P0luz/Ombre-Brain").strip().strip("/")
                _ref  = str(_ucfg.get("ref")  or "main").strip()
                # 安全闸门 #2：非官方更新源必须显式放行，否则拒绝——防止「改 config.update.repo
                # 指向恶意仓 → 覆盖 src → 重启执行」这条 RCE 链在默认配置下成立。
                if not _update_repo_allowed(_repo):
                    yield (f"data: ERROR:更新源 {_repo} 不在可信白名单（默认只允许官方 "
                           f"{_TRUSTED_UPDATE_REPOS[0]}）。如确需从 fork/自建源更新，请设置 "
                           f"OMBRE_ALLOW_CUSTOM_UPDATE_REPO=1 后重试。\n\n")
                    return
                # B3：默认从「最新 Release/Tag」拉包，而不是分支 HEAD——避免作者正推到
                # 一半时拉到半成品。channel="branch" 可切回分支模式；没有 Release 时自动回退分支。
                # Dashboard checks main/VERSION, so the default update payload
                # must come from that same branch.  A stale GitHub Latest Release
                # previously made the first click downgrade to v2.4.6; the old
                # updater then fetched main on the second click.
                _channel = str(_ucfg.get("channel") or "branch").strip().lower()
                _branch_url = f"https://github.com/{_repo}/archive/refs/heads/{_ref}.zip"
                async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                    _zip_url, _label = _branch_url, f"{_repo}@{_ref}（分支）"
                    if _channel != "branch":
                        try:
                            _rr = await client.get(
                                f"https://api.github.com/repos/{_repo}/releases/latest",
                                headers={"Accept": "application/vnd.github+json"},
                            )
                            if _rr.status_code == 200:
                                _tag = str(_rr.json().get("tag_name") or "").strip()
                                if _tag:
                                    _zip_url = f"https://github.com/{_repo}/archive/refs/tags/{_tag}.zip"
                                    _label = f"{_repo}@{_tag}（正式版）"
                                else:
                                    yield "data: 最新 Release 没有 tag，回退到分支下载…\n\n"
                            else:
                                yield f"data: 仓库暂无正式 Release，回退到分支 {_ref} 下载…\n\n"
                        except Exception as _rel_e:
                            yield f"data: 查询 Release 失败（{_rel_e}），回退到分支下载…\n\n"
                    yield f"data: 正在下载 {_label} …\n\n"
                    zip_bytes = await _download_update_archive(client, _zip_url)

                # Refuse a valid-but-older archive before creating _prev or
                # touching any runtime file.  Explicit release-channel users
                # are protected too when GitHub's Latest marker is stale.
                with _zipfile.ZipFile(_io.BytesIO(zip_bytes)) as _version_zip:
                    _version_names = _version_zip.namelist()
                    _version_top = (
                        _version_names[0].split("/", 1)[0] + "/"
                        if _version_names else "Ombre-Brain-main/"
                    )
                    try:
                        _target_version = _read_bounded_zip_member(
                            _version_zip, _version_top + "VERSION", 128
                        ).decode("utf-8", "ignore").strip()
                    except KeyError:
                        _target_version = ""
                if _target_version and _is_version_downgrade(sh.version, _target_version):
                    yield (
                        f"data: ERROR:拒绝降级：当前版本 v{sh.version}，更新包版本 "
                        f"v{_target_version}。未改动任何文件。\n\n"
                    )
                    return

                yield "data: 下载完成，正在解压文件…\n\n"
                await _asyncio.sleep(0.1)

                # 目标根目录用注入的 sh.repo_root（Docker 下 = /app；裸机/VPS = 实际安装目录）。
                # 绝不能在这里用 __file__：本文件在 src/web/ 下，算出来会差一层。
                _repo_root = sh.repo_root
                src_root      = _os.path.join(_repo_root, "src")
                frontend_root = _os.path.join(_repo_root, "frontend")

                # #4a ②：覆盖前把当前 src/frontend 备份成回滚点 _prev，坏更新崩溃时 entrypoint 还原。
                import shutil as _shutil
                _prev = _os.path.join(_repo_root, "_prev")
                try:
                    if not _os.path.isdir(src_root):
                        raise FileNotFoundError(f"当前源码目录不存在：{src_root}")
                    _shutil.rmtree(_prev, ignore_errors=True)
                    _os.makedirs(_prev, exist_ok=True)
                    _shutil.copytree(src_root, _os.path.join(_prev, "src"))
                    if _os.path.isdir(frontend_root):
                        _shutil.copytree(frontend_root, _os.path.join(_prev, "frontend"))
                    for _root_name in ("VERSION", "requirements.txt"):
                        _current = _os.path.join(_repo_root, _root_name)
                        if _os.path.isfile(_current):
                            _shutil.copy2(_current, _os.path.join(_prev, _root_name))
                    yield "data: 已备份当前版本为回滚点…\n\n"
                except Exception as _bk:
                    yield f"data: ERROR:备份回滚点失败，已中止且未覆盖任何文件：{_bk}\n\n"
                    return

                with _zipfile.ZipFile(_io.BytesIO(zip_bytes)) as zf:
                    # 从 zip 顶层目录名推前缀（随分支/标签变化，不能写死 -main）。
                    _names = zf.namelist()
                    _top = (_names[0].split("/", 1)[0] + "/") if _names else "Ombre-Brain-main/"

                    # 安全加固 #1：先收集到内存 + 路径保护过滤 + 可选 sha256 清单校验，
                    # 通过后才落盘。校验失败则整体中止，一个字节都不写（现有 _prev/自愈回滚仍在）。
                    _plan = _plan_update_files(zf, _top)
                    if _plan["abort"]:
                        yield f"data: ERROR:{_plan['abort']}（已中止，未改动任何文件）\n\n"
                        return
                    if _plan["verified"]:
                        yield "data: 已通过 sha256 完整性校验…\n\n"
                    else:
                        yield "data: 未提供 update_manifest.json，已按路径保护过滤但跳过 sha256 校验…\n\n"

                    updated = 0
                    _dest_roots = {"src": src_root, "frontend": frontend_root}
                    try:
                        for rel, data in _plan["files"].items():
                            _seg, _, _sub = rel.partition("/")
                            dest_root = _dest_roots.get(_seg)
                            if not dest_root:
                                continue
                            dest = _os.path.join(dest_root, _sub)
                            # Zip-Slip 二次防护：写盘路径必须仍在目标根目录内。
                            _root_abs = _os.path.abspath(dest_root)
                            _dest_abs = _os.path.abspath(dest)
                            if _dest_abs != _root_abs and not _dest_abs.startswith(_root_abs + _os.sep):
                                raise ValueError(f"更新目标越界：{rel}")
                            _atomic_write_bytes(dest, data)
                            updated += 1
                    except Exception as _write_error:
                        restored = _restore_from_prev(
                            _repo_root, _prev, src_root, frontend_root
                        )
                        state = "已回滚" if restored else "回滚失败"
                        yield f"data: ERROR:写入更新失败（{_write_error}），{state}。\n\n"
                        return
                    if _plan["skipped_unsafe"]:
                        yield f"data: 已跳过 {_plan['skipped_unsafe']} 个路径异常/受保护的条目（安全防护）…\n\n"
                    if _plan["skipped_unlisted"]:
                        yield f"data: 已跳过 {_plan['skipped_unlisted']} 个不在校验清单内的文件（未经校验不落盘）…\n\n"

                    # --- 同步 VERSION：根目录 VERSION 为唯一真源，写到所有 get_version()
                    #     会读的位置（<root>/VERSION 与 <root>/src/VERSION）。---
                    # 历史坑：热更新只覆盖 src/ 和 frontend/，根目录 VERSION 不在其中；
                    # 而 get_version() 还会读 src/VERSION。两个 VERSION 文件靠人手动同步，
                    # 发版漏改一个就会出现「更新了一堆文件、版本号却原地不动」。这里在解压后
                    # 显式把 zip 里的根 VERSION 强制写到两处，保证更新后版本号一定刷新、不再漂移。
                    try:
                        ver_bytes = _read_bounded_zip_member(
                            zf, _top + "VERSION", 128
                        )
                        for _vpath in (
                            _os.path.join(_repo_root, "VERSION"),
                            _os.path.join(src_root, "VERSION"),
                        ):
                            _atomic_write_bytes(_vpath, ver_bytes)
                        yield f"data: 版本号已同步为 v{ver_bytes.decode('utf-8', 'ignore').strip()}…\n\n"
                    except KeyError:
                        pass  # zip 里没有 VERSION（极少数情况）：跳过，不阻断更新
                    except Exception as _version_error:
                        restored = _restore_from_prev(
                            _repo_root, _prev, src_root, frontend_root
                        )
                        state = "已回滚" if restored else "回滚失败"
                        yield f"data: ERROR:版本文件写入失败（{_version_error}），{state}。\n\n"
                        return

                    # #4a ③：依赖变更 → best-effort pip install。
                    # 热更新只覆盖 .py，新版若加了依赖、不装会 import 失败（被 ② 当启动失败回滚）。
                    try:
                        _new_req = _read_bounded_zip_member(
                            zf, _top + "requirements.txt", 2 * 1024 * 1024
                        )
                        _req_path = _os.path.join(_repo_root, "requirements.txt")
                        _old_req = b""
                        if _os.path.isfile(_req_path):
                            with open(_req_path, "rb") as _rf:
                                _old_req = _rf.read()
                        if _new_req.strip() and _new_req.strip() != _old_req.strip():
                            # 安全闸门 #2：自动 pip install 默认关闭——否则远端 zip 里的
                            # requirements.txt 能让本机装任意包。需 config update.allow_pip_install
                            # 或 env OMBRE_UPDATE_ALLOW_PIP=1 显式开启。
                            if not _pip_install_allowed():
                                if _restore_from_prev(_repo_root, _prev, src_root, frontend_root):
                                    yield ("data: ERROR:新版依赖清单有变化，自动 pip 安装处于关闭状态；"
                                           "为避免重启后缺包，已回滚本次热更新。请重建镜像，或明确设置 "
                                           "OMBRE_UPDATE_ALLOW_PIP=1 后重试。\n\n")
                                else:
                                    yield "data: ERROR:依赖发生变化且自动安装关闭，回滚失败，请手动恢复 _prev。\n\n"
                                return
                            else:
                                _atomic_write_bytes(_req_path, _new_req)
                                yield "data: 依赖清单有变化，正在 pip install…\n\n"
                                import subprocess as _sp
                                import sys as _sys
                                _p = _sp.run(
                                    [_sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", _req_path],
                                    capture_output=True, text=True, timeout=600,
                                )
                                if _p.returncode != 0:
                                    restored = _restore_from_prev(
                                        _repo_root, _prev, src_root, frontend_root
                                    )
                                    state = "已回滚" if restored else "回滚失败"
                                    yield f"data: ERROR:依赖安装失败，{state}；服务不会重启。\n\n"
                                    return
                                yield "data: 依赖安装完成…\n\n"
                    except KeyError:
                        pass  # zip 里没有 requirements.txt：跳过
                    except Exception as _rqe:
                        restored = _restore_from_prev(
                            _repo_root, _prev, src_root, frontend_root
                        )
                        state = "已回滚" if restored else "回滚失败"
                        yield f"data: ERROR:依赖处理失败（{_rqe}），{state}。\n\n"
                        return

                # B2：重启前先验证新代码能编译。不通过就从 _prev 自动还原、放弃重启，
                # 保住当前可用状态——尤其裸机没有别的守护会兜底。
                _compile_err = _compile_check_dir(src_root)
                if _compile_err:
                    yield f"data: 新代码自检未通过（{_compile_err}）。正在还原到更新前的版本…\n\n"
                    if _restore_from_prev(_repo_root, _prev, src_root, frontend_root):
                        yield "data: 已还原上一版，服务保持当前运行、不重启。可稍后重试或联系维护者。\n\n"
                    else:
                        yield "data: ⚠️ 自动还原失败，请检查 _prev 备份目录并手动恢复。\n\n"
                    yield "data: ERROR:更新已中止（新代码自检失败，已回滚，未重启）\n\n"
                    return

                yield f"data: 已更新 {updated} 个文件，即将重启服务…\n\n"
                await _asyncio.sleep(0.5)
                yield "data: RESTART\n\n"

                async def _restart():
                    # 先睡 0.8s 让上面的 SSE "RESTART" 行刷给前端，再原地自重启。
                    await _asyncio.sleep(0.8)
                    _restart_self()
                _asyncio.create_task(_restart())

            except Exception as e:
                yield f"data: ERROR:{e}\n\n"

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @mcp.custom_route("/api/maintenance/fix-pinned-desync", methods=["GET", "POST"])
    async def api_fix_pinned_desync(request: Request) -> Response:
        """扫描 pinned/type 脱钩项。

        type=permanent 是正式固化类型；当前不会自动降级未 pinned 的 permanent 桶。
        两者都需登录。逻辑复用 tools._common.repair_pinned_desync。
        """
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        from tools._common import repair_pinned_desync
        try:
            apply = request.method == "POST"
            result = await repair_pinned_desync(sh.bucket_mgr, apply=apply)
            return JSONResponse({"ok": True, **result})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/author", methods=["GET"])
    async def api_author(request: Request) -> Response:
        """Static author note (read-only, public)."""
        from starlette.responses import JSONResponse
        return JSONResponse(_AUTHOR_NOTE)

    @mcp.custom_route("/api/onboarding/status", methods=["GET"])
    async def api_onboarding_status(request: Request) -> Response:
        """前端调用：判断是否需要引导（env 与 config 同时缺密钥才算"全新"）。

        本接口刻意不要求登录——dashboard 首次打开时连密码都还没设。
        """
        from starlette.responses import JSONResponse
        dash_env = bool(os.environ.get("OMBRE_DASHBOARD_PASSWORD", "").strip())
        dash_file = False
        try:
            dash_file = bool(sh._load_password_hash())
        except Exception:
            dash_file = False

        gem_env = bool(os.environ.get("GEMINI_API_KEY", "").strip())
        gem_cfg = bool((sh.config.get("dehydration", {}) or {}).get("api_key", "")) or \
            bool((sh.config.get("embedding", {}) or {}).get("api_key", ""))

        first_run = (not dash_env and not dash_file) and (not gem_env and not gem_cfg)

        return JSONResponse({
            "first_run": first_run,
            "dashboard_password_set": dash_env or dash_file,
            "dashboard_password_source": "env" if dash_env else ("file" if dash_file else "none"),
            "gemini_key_set": gem_env or gem_cfg,
            "gemini_key_source": "env" if gem_env else ("config" if gem_cfg else "none"),
            "embedding_enabled": sh.embedding_engine.enabled,
        })

    @mcp.custom_route("/api/status", methods=["GET"])
    async def api_system_status(request: Request) -> Response:
        """Return detailed system status for the settings panel."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        try:
            stats = await sh.bucket_mgr.get_stats()
            return JSONResponse({
                "decay_engine": "running" if sh.decay_engine.is_running else "stopped",
                "embedding_enabled": sh.embedding_engine.enabled,
                "buckets": {
                    "permanent": stats.get("permanent_count", 0),
                    "dynamic": stats.get("dynamic_count", 0),
                    "archive": stats.get("archive_count", 0),
                    "total": stats.get("permanent_count", 0) + stats.get("dynamic_count", 0),
                },
                "using_env_password": bool(os.environ.get("OMBRE_DASHBOARD_PASSWORD", "")),
                "version": sh.version,
            })
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
