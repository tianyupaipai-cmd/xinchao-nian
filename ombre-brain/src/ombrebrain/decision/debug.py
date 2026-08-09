from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ombrebrain.decision.records import DecisionRecord
from ombrebrain.decision.replay import ReplayDebugger
from ombrebrain.fabric.storage.engine import MemoryFabric


@dataclass(frozen=True)
class DecisionDebugService:
    fabric: MemoryFabric
    replay_debugger: ReplayDebugger = ReplayDebugger.default()

    def list_records(
        self,
        *,
        limit: int = 20,
        module: str = "",
        operation: str = "",
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        problems: list[dict[str, Any]] = []
        for item in self._iter_decisions():
            if item["problem"]:
                problems.append(item["problem"])
                continue
            record = item["record"]
            if not self._matches(record, module=module, operation=operation):
                continue
            records.append(self._record_payload(record, item["event"]))
            if len(records) >= max(1, int(limit)):
                break
        return {
            "ok": True,
            "count": len(records),
            "records": records,
            "problems": problems,
        }

    def get_record(self, identifier: str) -> dict[str, Any]:
        target = str(identifier)
        for item in self._iter_decisions():
            if item["problem"]:
                continue
            record = item["record"]
            if target in {record.id, record.command_id}:
                return {
                    "ok": True,
                    "record": self._record_payload(record, item["event"]),
                }
        return {
            "ok": False,
            "error": "decision_not_found",
            "identifier": target,
        }

    def replay(self, identifier: str) -> dict[str, Any]:
        found = self.get_record(identifier)
        if not found.get("ok"):
            return found
        record = DecisionRecord.from_dict(found["record"])
        replay = self.replay_debugger.replay(record)
        return {
            "ok": replay.ok,
            "record": record.to_dict(),
            "replay": replay.to_dict(),
        }

    def health(self) -> dict[str, Any]:
        listing = self.list_records(limit=1)
        return {
            "ok": True,
            "available": True,
            "latest_count": listing["count"],
            "problem_count": len(listing["problems"]),
            "next_index": self.fabric.next_index(),
        }

    def _iter_decisions(self):
        for event in reversed(self.fabric.replay_events()):
            raw = event.metadata.get("decision_record")
            if raw is None:
                continue
            if not isinstance(raw, dict):
                yield {
                    "event": event,
                    "record": None,
                    "problem": {
                        "error": "invalid_decision_record",
                        "event_id": event.id,
                        "reason": "decision_record metadata is not an object",
                    },
                }
                continue
            try:
                record = DecisionRecord.from_dict(raw)
            except Exception as exc:  # pragma: no cover - defensive against old metadata
                yield {
                    "event": event,
                    "record": None,
                    "problem": {
                        "error": "invalid_decision_record",
                        "event_id": event.id,
                        "reason": f"{type(exc).__name__}: {str(exc)[:160]}",
                    },
                }
                continue
            if record.command_id == "cmd_unknown":
                yield {
                    "event": event,
                    "record": None,
                    "problem": {
                        "error": "invalid_decision_record",
                        "event_id": event.id,
                        "reason": "decision record is missing a command id",
                    },
                }
                continue
            yield {"event": event, "record": record, "problem": None}

    def _record_payload(self, record: DecisionRecord, event) -> dict[str, Any]:
        return {
            **record.to_dict(),
            "event": {
                "id": event.id,
                "created_at": event.created_at,
                "source_chain": list(event.source_chain),
                "content": event.content,
            },
        }

    def _matches(self, record: DecisionRecord, *, module: str, operation: str) -> bool:
        if module and record.module != module:
            return False
        if operation and record.operation != operation:
            return False
        return True
