"""
github_sync.py — GitHub 仓库同步（用于 bucket 数据云端备份）

策略：
- 只同步 buckets_dir 下的 .md 文件（纯文本，体积小，可读性好）
- embeddings.db 不上传（二进制，可由 /api/embedding/migrate 重算）
- 使用 GitHub Git Trees API 批量提交（一次同步 = 一个 commit）
- 支持手动触发 + 可选的定时自动同步

依赖：httpx（已在 requirements.txt）
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger("ombre_brain.github_sync")

_API = "https://api.github.com"
_TIMEOUT = 60.0
_MAX_FILE_BYTES = 5 * 1024 * 1024  # GitHub single blob 上限 ~100MB，这里保守限 5MB
_TREE_CHUNK = 200                  # 每个 /git/trees 请求最多内联多少文件，避免单请求过大
_MANIFEST_FILENAME = "_ombre_backup_manifest.json"


class GitHubSync:
    """向 GitHub 仓库批量上传 bucket .md 文件。"""

    def __init__(
        self,
        token: str,
        repo: str,
        branch: str = "main",
        path_prefix: str = "ombre",
    ):
        self.token = token
        self.repo = repo.strip()          # "owner/repo"
        self.branch = branch.strip() or "main"
        self.path_prefix = path_prefix.strip().strip("/")

        self._headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        self.last_sync: str | None = None
        self.last_status: str = "idle"   # idle | ok | error
        self.last_error: str = ""
        self.last_count: int = 0
        self.is_validated: bool = False   # validate() 成功后置 True
        # A3：连续失败计数。自动备份可能连挂几次而用户毫无察觉（以为有备份其实没有）。
        # 每次成功归零、每次失败 +1，供诊断面板判断要不要升级为醒目告警。
        self.consecutive_failures: int = 0

    # --------------------------------------------------------
    # 公开接口
    # --------------------------------------------------------

    async def sync(self, buckets_dir: str) -> dict[str, Any]:
        """同步 buckets_dir 下所有 .md 到 GitHub。返回结果 dict。"""
        try:
            files = self._collect_files(buckets_dir)
            if not files:
                self.last_status = "ok"
                self.last_error = ""
                self.last_sync = _now_iso()
                self.last_count = 0
                return {"ok": True, "uploaded": 0, "message": "无可同步文件"}

            count = await self._batch_commit(files)
            self.last_sync = _now_iso()
            self.last_status = "ok"
            self.last_error = ""
            self.last_count = count
            self.consecutive_failures = 0
            return {"ok": True, "uploaded": count}
        except Exception as e:
            self.last_status = "error"
            self.last_error = str(e)
            self.consecutive_failures += 1
            logger.error(f"[github_sync] sync failed (连续 {self.consecutive_failures} 次): {e}")
            return {"ok": False, "error": str(e)}

    async def import_from_github(self, buckets_dir: str) -> dict[str, Any]:
        """从 GitHub 仓库把 path_prefix 下的所有 .md 拉回本地 buckets_dir（恢复 / 回滚）。

        这是 sync() 的逆操作。合并覆盖语义：同名（同相对路径）文件用 GitHub 上的覆盖，
        本地独有的文件保留不动。embeddings.db 不在仓库里，调用方应在导入后跑一次
        backfill 重建向量。带 path-traversal 防护（仓库内容不可信，防 ../ 逃逸）。
        """
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=_TIMEOUT) as c:
                # 取 branch HEAD → commit tree → 递归列出全部 blob
                r = await self._request(c, "GET", f"{_API}/repos/{self.repo}/git/ref/heads/{self.branch}")
                if _is_empty_repo_response(r):
                    return {
                        "ok": True,
                        "imported": 0,
                        "skipped": 0,
                        "message": f"GitHub 仓库 {self.repo} 还是空仓库，暂无可导入的记忆文件",
                    }
                if r.status_code == 404:
                    return {"ok": False, "error": f"分支 {self.branch} 不存在"}
                r.raise_for_status()
                head_sha = r.json()["object"]["sha"]
                r = await self._request(c, "GET", f"{_API}/repos/{self.repo}/git/commits/{head_sha}")
                r.raise_for_status()
                tree_sha = r.json()["tree"]["sha"]
                r = await self._request(c, "GET", f"{_API}/repos/{self.repo}/git/trees/{tree_sha}?recursive=1")
                r.raise_for_status()
                tj = r.json()
                tree = tj.get("tree", [])
                truncated = bool(tj.get("truncated"))

                prefix = (self.path_prefix + "/") if self.path_prefix else ""
                manifest_path = f"{prefix}{_MANIFEST_FILENAME}"
                manifest_item = next(
                    (
                        t for t in tree
                        if t.get("type") == "blob" and t.get("path") == manifest_path
                    ),
                    None,
                )
                backup_manifest = await self._read_backup_manifest_summary(c, manifest_item) if manifest_item else {"present": False}
                targets = [
                    t for t in tree
                    if t.get("type") == "blob" and t.get("path", "").startswith(prefix)
                    and t["path"].endswith(".md")
                ]
                if not targets:
                    return {"ok": True, "imported": 0, "skipped": 0,
                            "message": f"GitHub 仓库 {self.repo} 的 {prefix or '/'} 下没有 .md 记忆文件",
                            "backup_manifest": backup_manifest}

                base = os.path.abspath(buckets_dir)
                imported = 0
                skipped = 0
                errors: list[str] = []
                for t in targets:
                    rel = t["path"][len(prefix):]
                    if not rel:
                        continue
                    # path-traversal 防护：解析后必须仍在 buckets_dir 内
                    dest = os.path.abspath(os.path.join(base, rel))
                    if dest != base and not dest.startswith(base + os.sep):
                        skipped += 1
                        errors.append(f"{rel}: 越界路径，已跳过")
                        continue
                    try:
                        rb = await self._request(c, "GET", f"{_API}/repos/{self.repo}/git/blobs/{t['sha']}")
                        rb.raise_for_status()
                        bj = rb.json()
                        if bj.get("encoding") == "base64":
                            data = base64.b64decode(bj.get("content", ""))
                        else:
                            data = (bj.get("content", "") or "").encode("utf-8")
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        # 原子写：导入是覆盖本地记忆的操作，写到一半被中断绝不能留半截文件。
                        _tmp = f"{dest}.{uuid.uuid4().hex}.tmp"
                        try:
                            with open(_tmp, "wb") as f:
                                f.write(data)
                                f.flush()
                                os.fsync(f.fileno())
                            os.replace(_tmp, dest)
                        except Exception:
                            if os.path.exists(_tmp):
                                try:
                                    os.remove(_tmp)
                                except OSError:
                                    pass
                            raise
                        imported += 1
                    except Exception as e:
                        skipped += 1
                        errors.append(f"{rel}: {e}")

                self.last_sync = _now_iso()
                self.last_status = "ok"
                return {
                    "ok": True,
                    "imported": imported,
                    "skipped": skipped,
                    "total": len(targets),
                    "truncated": truncated,
                    "errors": errors[:10],
                    "backup_manifest": backup_manifest,
                }
        except Exception as e:
            logger.error(f"[github_sync] import failed: {e}")
            return {"ok": False, "error": str(e)}

    async def validate(self) -> dict[str, Any]:
        """验证 token + repo 可访问，且具有写权限（contents: write）。"""
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=15.0) as c:
                r = await c.get(f"{_API}/repos/{self.repo}")
                if r.status_code == 404:
                    return {"ok": False, "error": f"仓库 {self.repo} 不存在或无权限访问"}
                if r.status_code == 401:
                    return {"ok": False, "error": "Token 无效或已过期"}
                r.raise_for_status()
                data = r.json()

                # Check write permission via `permissions.push` field
                # (GitHub returns this field when authenticated)
                perms = data.get("permissions", {})
                can_push = perms.get("push", False) or perms.get("admin", False)
                if perms and not can_push:
                    return {
                        "ok": False,
                        "error": "Token 只有读权限，无法上传文件。请在 GitHub → Settings → Developer settings → Fine-grained tokens 中将 Contents 权限设为 Read and write",
                    }

                self.is_validated = True
                return {
                    "ok": True,
                    "repo_full_name": data.get("full_name", self.repo),
                    "private": data.get("private", False),
                    "default_branch": data.get("default_branch", "main"),
                    "can_push": can_push,
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.token and self.repo),
            "repo": self.repo,
            "branch": self.branch,
            "path_prefix": self.path_prefix,
            "last_sync": self.last_sync,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_count": self.last_count,
            "is_validated": self.is_validated,
            "consecutive_failures": self.consecutive_failures,
        }

    # --------------------------------------------------------
    # 内部实现
    # --------------------------------------------------------

    def _collect_files(self, buckets_dir: str) -> dict[str, bytes]:
        """遍历 buckets_dir，收集所有 .md 文件。"""
        result: dict[str, bytes] = {}
        if not os.path.isdir(buckets_dir):
            return result
        for root, _, filenames in os.walk(buckets_dir):
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                full = os.path.join(root, fn)
                try:
                    size = os.path.getsize(full)
                    if size > _MAX_FILE_BYTES:
                        logger.warning(f"[github_sync] skip {fn}: too large ({size} bytes)")
                        continue
                    with open(full, "rb") as f:
                        result[os.path.relpath(full, buckets_dir).replace("\\", "/")] = f.read()
                except OSError as e:
                    logger.warning(f"[github_sync] skip {fn}: {e}")
        return result

    def _build_backup_manifest(self, files: dict[str, bytes]) -> dict[str, Any]:
        """Build a JSON-safe manifest for the markdown files in one sync."""
        entries = []
        total_bytes = 0
        for rel_path, content in sorted(files.items()):
            size = len(content)
            total_bytes += size
            entries.append({
                "path": rel_path,
                "bytes": size,
                "sha256": hashlib.sha256(content).hexdigest(),
            })
        return {
            "schema_version": 1,
            "source": "ombre-brain",
            "generated_at": _now_iso(),
            "repo": self.repo,
            "branch": self.branch,
            "path_prefix": self.path_prefix,
            "file_count": len(entries),
            "total_bytes": total_bytes,
            "files": entries,
        }

    async def _batch_commit(self, files: dict[str, bytes]) -> int:
        """用 Git Trees API 一次性提交所有文件，返回上传文件数。

        关键点：tree entry 直接内联 `content`（UTF-8 文本），由 GitHub 在建
        tree 时顺带创建 blob —— 几百个文件只需 1~N 个 /git/trees 请求，而不是
        每个文件一个 /git/blobs 请求。后者会瞬间打满 GitHub 的 *secondary rate
        limit*（返回 403），正是之前同步莫名 403 的根因。

        大批量时分块提交（每块 _TREE_CHUNK 个），块与块之间用 base_tree 串联，
        最后只打一个 commit。所有请求都带指数退避重试以应对偶发的二级限流。
        """
        async with httpx.AsyncClient(headers=self._headers, timeout=_TIMEOUT) as c:
            # 1. 获取 branch HEAD commit SHA。GitHub 空仓库没有任何 ref，会在这里返回 409。
            r = await self._request(c, "GET", f"{_API}/repos/{self.repo}/git/ref/heads/{self.branch}")
            bootstrap_branch = _is_empty_repo_response(r)
            head_sha: str | None = None
            base_tree_sha: str | None = None
            if r.status_code == 404:
                raise RuntimeError(f"分支 {self.branch} 不存在，请先在 GitHub 上创建该分支")
            if not bootstrap_branch:
                r.raise_for_status()
                head_sha = r.json()["object"]["sha"]

                # 2. 获取 HEAD commit 对应的 tree SHA
                r = await self._request(c, "GET", f"{_API}/repos/{self.repo}/git/commits/{head_sha}")
                r.raise_for_status()
                base_tree_sha = r.json()["tree"]["sha"]

            # 3. 组装 tree entries（内联 content，文本直接走 UTF-8）
            entries: list[dict] = []
            for rel_path, content in files.items():
                gh_path = f"{self.path_prefix}/{rel_path}" if self.path_prefix else rel_path
                try:
                    text = content.decode("utf-8")
                    entry = {"path": gh_path, "mode": "100644", "type": "blob", "content": text}
                except UnicodeDecodeError:
                    # 非 UTF-8（理论上只同步 .md，不会走到这里）：退回 base64 blob
                    rb = await self._request(
                        c, "POST", f"{_API}/repos/{self.repo}/git/blobs",
                        json={"content": base64.b64encode(content).decode(), "encoding": "base64"},
                    )
                    rb.raise_for_status()
                    entry = {"path": gh_path, "mode": "100644", "type": "blob", "sha": rb.json()["sha"]}
                entries.append(entry)

            manifest_path = f"{self.path_prefix}/{_MANIFEST_FILENAME}" if self.path_prefix else _MANIFEST_FILENAME
            manifest = self._build_backup_manifest(files)
            entries.append({
                "path": manifest_path,
                "mode": "100644",
                "type": "blob",
                "content": json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            })

            # 4. 分块创建 tree，块间用 base_tree 串联
            cur_base = base_tree_sha
            for i in range(0, len(entries), _TREE_CHUNK):
                chunk = entries[i:i + _TREE_CHUNK]
                tree_payload: dict[str, Any] = {"tree": chunk}
                if cur_base:
                    tree_payload["base_tree"] = cur_base
                r = await self._request(
                    c, "POST", f"{_API}/repos/{self.repo}/git/trees",
                    json=tree_payload,
                )
                r.raise_for_status()
                cur_base = r.json()["sha"]
            new_tree_sha = cur_base

            # 5. 创建 commit
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            r = await self._request(
                c, "POST", f"{_API}/repos/{self.repo}/git/commits",
                json={
                    "message": f"Ombre Brain sync — {now_str} ({len(files)} files)",
                    "tree": new_tree_sha,
                    "parents": [head_sha] if head_sha else [],
                },
            )
            r.raise_for_status()
            commit_sha: str = r.json()["sha"]

            # 6. 更新已有 branch ref；空仓库首次提交则创建 branch ref
            if bootstrap_branch:
                r = await self._request(
                    c, "POST", f"{_API}/repos/{self.repo}/git/refs",
                    json={"ref": f"refs/heads/{self.branch}", "sha": commit_sha},
                )
            else:
                r = await self._request(
                    c, "PATCH", f"{_API}/repos/{self.repo}/git/refs/heads/{self.branch}",
                    json={"sha": commit_sha, "force": False},
                )
            r.raise_for_status()

        return len(files)

    async def _read_backup_manifest_summary(
        self,
        client: httpx.AsyncClient,
        manifest_item: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            sha = manifest_item.get("sha", "")
            if not sha:
                return {"present": False}
            rb = await self._request(client, "GET", f"{_API}/repos/{self.repo}/git/blobs/{sha}")
            rb.raise_for_status()
            bj = rb.json()
            if bj.get("encoding") == "base64":
                raw = base64.b64decode(bj.get("content", "")).decode("utf-8", errors="replace")
            else:
                raw = str(bj.get("content", "") or "")
            data = json.loads(raw)
            return {
                "present": True,
                "schema_version": data.get("schema_version"),
                "generated_at": data.get("generated_at", ""),
                "file_count": int(data.get("file_count") or 0),
                "total_bytes": int(data.get("total_bytes") or 0),
            }
        except Exception as e:
            return {"present": False, "error": str(e)[:200]}

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        _max_retries: int = 4,
    ) -> httpx.Response:
        """带退避重试的请求。专治 GitHub 二级限流（403/429 + Retry-After）。

        普通 4xx（权限/404 等）直接返回交由上层 raise_for_status 处理，不重试。
        """
        for attempt in range(_max_retries + 1):
            resp = await client.request(method, url, json=json)
            if resp.status_code not in (403, 429):
                return resp
            # 判断是否二级限流（而非真正的权限 403）
            body_l = resp.text.lower()
            is_rate = (
                "rate limit" in body_l
                or "retry-after" in {k.lower() for k in resp.headers}
                or resp.headers.get("x-ratelimit-remaining") == "0"
            )
            if not is_rate or attempt == _max_retries:
                return resp
            # 计算等待时长：优先 Retry-After，其次指数退避
            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                wait = int(retry_after)
            else:
                wait = min(2 ** attempt, 30)
            logger.warning(f"[github_sync] secondary rate limit, retry in {wait}s (attempt {attempt + 1})")
            await asyncio.sleep(wait)
        return resp


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_empty_repo_response(resp: httpx.Response) -> bool:
    """GitHub returns 409 when refs are requested from a zero-commit repo."""
    if resp.status_code != 409:
        return False
    try:
        message = str(resp.json().get("message", ""))
    except Exception:
        message = resp.text
    return "empty" in message.lower()
