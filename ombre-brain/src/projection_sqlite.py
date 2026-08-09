from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from projection_mirror import TraceCatalogProjection


class TraceSQLiteProjection:
    """Persistent shadow projection rebuilt from ledger mirror events."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def rebuild(self, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
        catalog = TraceCatalogProjection()
        catalog.rebuild(events)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            fts_enabled = _supports_fts5(conn)
            self._reset_schema(conn, fts_enabled=fts_enabled)
            for trace in catalog.traces.values():
                self._insert_trace(conn, trace, fts_enabled=fts_enabled)
            self._set_meta(conn, "projection_name", "trace_catalog_sqlite")
            self._set_meta(conn, "projection_role", "shadow")
            self._set_meta(conn, "canonical", "false")
            self._set_meta(conn, "applied_seq", str(catalog.applied_seq))
            self._set_meta(conn, "unknown_event_count", str(catalog.unknown_event_count))
            self._set_meta(conn, "fts_enabled", "true" if fts_enabled else "false")
        return self.to_report()

    def to_report(self, *, source_latest_seq: int = 0) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "projection_name": "trace_catalog_sqlite",
                "projection_role": "shadow",
                "canonical": False,
                "path": str(self.path),
                "trace_count": 0,
                "tombstone_count": 0,
                "applied_seq": 0,
                "source_latest_seq": int(source_latest_seq or 0),
                "lag": int(source_latest_seq or 0),
                "unknown_event_count": 0,
                "fts_enabled": False,
            }
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            applied_seq = _int_meta(conn, "applied_seq")
            trace_count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
            tombstone_count = conn.execute("SELECT COUNT(*) FROM traces WHERE tombstone = 1").fetchone()[0]
            fts_enabled = _bool_meta(conn, "fts_enabled")
            unknown_event_count = _int_meta(conn, "unknown_event_count")
        source_seq = int(source_latest_seq or 0)
        return {
            "projection_name": "trace_catalog_sqlite",
            "projection_role": "shadow",
            "canonical": False,
            "path": str(self.path),
            "trace_count": int(trace_count),
            "tombstone_count": int(tombstone_count),
            "applied_seq": applied_seq,
            "source_latest_seq": source_seq,
            "lag": max(0, source_seq - applied_seq),
            "unknown_event_count": unknown_event_count,
            "fts_enabled": fts_enabled,
        }

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM traces WHERE trace_id = ?", (str(trace_id),)).fetchone()
        return _trace_from_row(row) if row else None

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists() or not str(query).strip():
            return []
        text = str(query).strip()
        max_rows = max(1, int(limit or 20))
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            if _bool_meta(conn, "fts_enabled"):
                rows = conn.execute(
                    """
                    SELECT t.*
                    FROM trace_fts f
                    JOIN traces t ON t.trace_id = f.trace_id
                    WHERE trace_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (_fts_query(text), max_rows),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM traces
                    WHERE search_text LIKE ?
                    ORDER BY latest_seq DESC
                    LIMIT ?
                    """,
                    (f"%{text}%", max_rows),
                ).fetchall()
        return [_trace_from_row(row) for row in rows]

    def _reset_schema(self, conn: sqlite3.Connection, *, fts_enabled: bool) -> None:
        conn.executescript(
            """
            DROP TABLE IF EXISTS projection_meta;
            DROP TABLE IF EXISTS traces;
            DROP TABLE IF EXISTS trace_fts;

            CREATE TABLE projection_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE traces (
                trace_id TEXT PRIMARY KEY,
                trace_kind TEXT NOT NULL,
                state TEXT NOT NULL,
                body_hash TEXT NOT NULL,
                created_seq INTEGER NOT NULL,
                latest_seq INTEGER NOT NULL,
                latest_event_type TEXT NOT NULL,
                touch_count INTEGER NOT NULL,
                resolved INTEGER NOT NULL,
                deleted INTEGER NOT NULL,
                tombstone INTEGER NOT NULL,
                name TEXT NOT NULL,
                importance INTEGER,
                metadata_json TEXT NOT NULL,
                search_text TEXT NOT NULL
            );
            """
        )
        if fts_enabled:
            conn.execute(
                """
                CREATE VIRTUAL TABLE trace_fts USING fts5(
                    trace_id UNINDEXED,
                    search_text
                )
                """
            )

    def _insert_trace(self, conn: sqlite3.Connection, trace: dict[str, Any], *, fts_enabled: bool) -> None:
        metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
        search_text = _search_text(trace)
        values = (
            str(trace.get("trace_id") or ""),
            str(trace.get("trace_kind") or ""),
            str(trace.get("state") or ""),
            str(trace.get("body_hash") or ""),
            int(trace.get("created_seq", 0) or 0),
            int(trace.get("latest_seq", 0) or 0),
            str(trace.get("latest_event_type") or ""),
            int(trace.get("touch_count", 0) or 0),
            1 if trace.get("resolved") else 0,
            1 if trace.get("deleted") else 0,
            1 if trace.get("tombstone") else 0,
            str(metadata.get("name") or ""),
            _optional_int(metadata.get("importance")),
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str),
            search_text,
        )
        conn.execute(
            """
            INSERT INTO traces (
                trace_id, trace_kind, state, body_hash, created_seq, latest_seq,
                latest_event_type, touch_count, resolved, deleted, tombstone,
                name, importance, metadata_json, search_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        if fts_enabled:
            conn.execute(
                "INSERT INTO trace_fts (trace_id, search_text) VALUES (?, ?)",
                (values[0], search_text),
            )

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO projection_meta (key, value) VALUES (?, ?)",
            (str(key), str(value)),
        )


def _supports_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._fts_probe USING fts5(value)")
        conn.execute("DROP TABLE temp._fts_probe")
        return True
    except sqlite3.Error:
        return False


def _trace_from_row(row: sqlite3.Row) -> dict[str, Any]:
    metadata = json.loads(row["metadata_json"] or "{}")
    return {
        "trace_id": row["trace_id"],
        "trace_kind": row["trace_kind"],
        "state": row["state"],
        "body_hash": row["body_hash"],
        "created_seq": int(row["created_seq"]),
        "latest_seq": int(row["latest_seq"]),
        "latest_event_type": row["latest_event_type"],
        "touch_count": int(row["touch_count"]),
        "resolved": bool(row["resolved"]),
        "deleted": bool(row["deleted"]),
        "tombstone": bool(row["tombstone"]),
        "name": row["name"],
        "importance": row["importance"],
        "metadata": metadata,
    }


def _search_text(trace: dict[str, Any]) -> str:
    metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
    parts = [
        trace.get("trace_id"),
        trace.get("trace_kind"),
        trace.get("state"),
        metadata.get("name"),
        metadata.get("why_remembered"),
        metadata.get("summary"),
        metadata.get("tags"),
        metadata.get("domain"),
    ]
    return " ".join(_flatten_text(parts)).strip()


def _flatten_text(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, dict):
        texts: list[str] = []
        for key, value in values.items():
            texts.append(str(key))
            texts.extend(_flatten_text(value))
        return texts
    if isinstance(values, (list, tuple, set)):
        texts = []
        for item in values:
            texts.extend(_flatten_text(item))
        return texts
    return [str(values)]


def _fts_query(value: str) -> str:
    tokens = [token.replace('"', '""') for token in str(value).split() if token.strip()]
    if not tokens:
        return '""'
    return " OR ".join(f'"{token}"' for token in tokens)


def _int_meta(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute("SELECT value FROM projection_meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def _bool_meta(conn: sqlite3.Connection, key: str) -> bool:
    row = conn.execute("SELECT value FROM projection_meta WHERE key = ?", (key,)).fetchone()
    return bool(row and str(row[0]).lower() == "true")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
