from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from typing import Any

from ledger_replay import LedgerReplayValidator


_EVENT_TYPES = (
    "TraceCreated",
    "TraceUpdated",
    "TraceTouched",
    "TraceArchived",
    "TraceDeletedToArchive",
)


@dataclass(frozen=True)
class LedgerReplayPropertyRunner:
    """Deterministic randomized replay checks for the shadow ledger contract."""

    @classmethod
    def default(cls) -> "LedgerReplayPropertyRunner":
        return cls()

    def generate_case(self, *, seed: int, max_events: int) -> list[dict[str, Any]]:
        rng = random.Random(seed)
        max_events = max(1, int(max_events or 1))
        trace_count = max(3, min(12, max_events // 6 or 3))
        traces = [f"trace_{idx:02d}" for idx in range(trace_count)]
        created: set[str] = set()
        terminal: set[str] = set()
        events: list[dict[str, Any]] = []

        for seq in range(1, max_events + 1):
            available = [trace_id for trace_id in traces if trace_id not in terminal]
            if not available:
                available = list(traces)
                terminal.clear()

            trace_id = rng.choice(available)
            event_type = self._choose_event_type(rng, trace_id, created, terminal)
            created.add(trace_id)
            if event_type in {"TraceArchived", "TraceDeletedToArchive"}:
                terminal.add(trace_id)
            body = f"{seed}:{seq}:{trace_id}:{event_type}"
            events.append(
                {
                    "seq": seq,
                    "schema_version": 1,
                    "ledger_role": "mirror",
                    "canonical": False,
                    "event_type": event_type,
                    "trace_id": trace_id,
                    "trace_kind": _trace_kind_for(event_type),
                    "body_hash": _hash_body(body),
                    "payload": _payload_for(event_type, seq, rng),
                    "recorded_at": f"2026-07-02T00:{seq % 60:02d}:00+00:00",
                }
            )

        return events

    def run(self, *, seed: int, cases: int, max_events: int) -> dict[str, Any]:
        cases = max(1, int(cases or 1))
        max_events = max(1, int(max_events or 1))
        failures: list[dict[str, Any]] = []
        checked_events = 0
        validator = LedgerReplayValidator.default()

        for case_index in range(cases):
            case_seed = int(seed) + case_index
            events = self.generate_case(seed=case_seed, max_events=max_events)
            checked_events += len(events)
            report = validator.validate(events)
            if not report.get("ok"):
                failures.append(
                    {
                        "case_index": case_index,
                        "seed": case_seed,
                        "report": report,
                    }
                )

        return {
            "ok": not failures,
            "seed": int(seed),
            "cases": cases,
            "max_events": max_events,
            "checked_events": checked_events,
            "failures": failures,
        }

    def _choose_event_type(
        self,
        rng: random.Random,
        trace_id: str,
        created: set[str],
        terminal: set[str],
    ) -> str:
        if trace_id not in created:
            return "TraceCreated"
        if trace_id in terminal:
            return "TraceCreated"
        return rng.choices(_EVENT_TYPES[1:], weights=[5, 4, 1, 1], k=1)[0]


def _hash_body(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _trace_kind_for(event_type: str) -> str:
    if event_type == "TraceArchived":
        return "archived"
    return "dynamic"


def _payload_for(event_type: str, seq: int, rng: random.Random) -> dict[str, Any]:
    if event_type == "TraceCreated":
        return {
            "importance": rng.randint(1, 10),
            "resolved": False,
            "type": "dynamic",
        }
    if event_type == "TraceUpdated":
        return {
            "resolved": bool(rng.getrandbits(1)),
            "importance": rng.randint(1, 10),
            "changed_fields": ["resolved", "importance"],
        }
    if event_type == "TraceTouched":
        return {"activation_count": rng.randint(1, 20)}
    if event_type == "TraceArchived":
        return {"type": "archived"}
    if event_type == "TraceDeletedToArchive":
        deleted_at = f"2026-07-02T01:{seq % 60:02d}:00+00:00"
        return {
            "deleted_at": deleted_at,
            "tombstone": True,
            "tombstoned_at": deleted_at,
            "erasure_mode": "tombstone_only",
        }
    return {}
