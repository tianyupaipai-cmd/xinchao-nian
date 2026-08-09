from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from projection_mirror import TraceCatalogProjection


class TraceVectorProjectionManifest:
    """Read-only shadow manifest for the existing embeddings SQLite store."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._report: dict[str, Any] | None = None

    def rebuild(self, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
        catalog = TraceCatalogProjection()
        catalog.rebuild(events)
        expected_ids = {
            trace_id for trace_id, trace in catalog.traces.items()
            if _expects_vector(trace)
        }
        db_report = self._read_db()
        valid_ids = set(db_report["valid_vector_ids"])
        stored_ids = set(db_report["stored_vector_ids"])
        missing_ids = sorted(expected_ids - valid_ids)
        orphan_ids = sorted(stored_ids - expected_ids)
        source_latest_seq = catalog.applied_seq
        self._report = {
            "projection_name": "trace_vector_manifest",
            "projection_role": "shadow",
            "canonical": False,
            "path": str(self.db_path),
            "db_exists": db_report["db_exists"],
            "model_name": db_report["model_name"],
            "vector_dim": db_report["vector_dim"],
            "expected_trace_count": len(expected_ids),
            "vector_count": len(valid_ids),
            "stored_vector_count": len(stored_ids),
            "missing_vector_count": len(missing_ids),
            "orphan_vector_count": len(orphan_ids),
            "malformed_vector_count": len(db_report["malformed_vector_ids"]),
            "missing_vector_ids": missing_ids[:20],
            "orphan_vector_ids": orphan_ids[:20],
            "malformed_vector_ids": db_report["malformed_vector_ids"][:20],
            "applied_seq": catalog.applied_seq,
            "source_latest_seq": source_latest_seq,
            "lag": 0,
        }
        return dict(self._report)

    def to_report(self, *, source_latest_seq: int = 0) -> dict[str, Any]:
        if self._report is None:
            self._report = {
                "projection_name": "trace_vector_manifest",
                "projection_role": "shadow",
                "canonical": False,
                "path": str(self.db_path),
                "db_exists": self.db_path.exists(),
                "model_name": "",
                "vector_dim": 0,
                "expected_trace_count": 0,
                "vector_count": 0,
                "stored_vector_count": 0,
                "missing_vector_count": 0,
                "orphan_vector_count": 0,
                "malformed_vector_count": 0,
                "missing_vector_ids": [],
                "orphan_vector_ids": [],
                "malformed_vector_ids": [],
                "applied_seq": 0,
                "source_latest_seq": int(source_latest_seq or 0),
                "lag": int(source_latest_seq or 0),
            }
        report = dict(self._report)
        source_seq = int(source_latest_seq or report.get("source_latest_seq") or 0)
        report["source_latest_seq"] = source_seq
        report["lag"] = max(0, source_seq - int(report.get("applied_seq") or 0))
        return report

    def _read_db(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {
                "db_exists": False,
                "model_name": "",
                "vector_dim": 0,
                "stored_vector_ids": [],
                "valid_vector_ids": [],
                "malformed_vector_ids": [],
            }
        with sqlite3.connect(self.db_path) as conn:
            stored_rows = _safe_fetch_embeddings(conn)
            meta = _safe_fetch_meta(conn)
        valid_ids: list[str] = []
        malformed_ids: list[str] = []
        for bucket_id, embedding_json in stored_rows:
            if _valid_vector_json(embedding_json):
                valid_ids.append(str(bucket_id))
            else:
                malformed_ids.append(str(bucket_id))
        return {
            "db_exists": True,
            "model_name": meta.get("model_name", ""),
            "vector_dim": _int_value(meta.get("vector_dim")),
            "stored_vector_ids": sorted(str(row[0]) for row in stored_rows),
            "valid_vector_ids": sorted(valid_ids),
            "malformed_vector_ids": sorted(malformed_ids),
        }


def _expects_vector(trace: dict[str, Any]) -> bool:
    state = str(trace.get("state") or "").lower()
    if state != "active":
        return False
    if trace.get("deleted") or trace.get("tombstone"):
        return False
    trace_kind = str(trace.get("trace_kind") or "").lower()
    return trace_kind != "archived"


def _safe_fetch_embeddings(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    try:
        rows = conn.execute("SELECT bucket_id, embedding FROM embeddings").fetchall()
    except sqlite3.Error:
        return []
    return [(str(bucket_id), str(embedding_json)) for bucket_id, embedding_json in rows]


def _safe_fetch_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM embeddings_meta").fetchall()
    except sqlite3.Error:
        return {}
    return {str(key): str(value) for key, value in rows}


def _valid_vector_json(value: str) -> bool:
    try:
        vector = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return False
    return (
        isinstance(vector, list)
        and bool(vector)
        and all(isinstance(item, (int, float)) for item in vector)
    )


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
