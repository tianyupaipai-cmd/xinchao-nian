from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class ADRChangeSpec:
    topic: str
    adr_path: str = ""
    adr_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "topic", _normalize_topic(self.topic))
        object.__setattr__(self, "adr_path", str(self.adr_path))
        object.__setattr__(self, "adr_text", str(self.adr_text))
        object.__setattr__(self, "metadata", _json_safe_dict(self.metadata))


@dataclass(frozen=True)
class ADRDocument:
    path: str
    text: str
    topics: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", str(self.path))
        object.__setattr__(self, "text", str(self.text))
        object.__setattr__(self, "topics", tuple(_normalize_topic(topic) for topic in self.topics))
        object.__setattr__(self, "metadata", _json_safe_dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "topics": list(self.topics),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ADRRequirementIssue:
    code: str
    message: str
    path: str = ""
    topic: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "message", str(self.message))
        object.__setattr__(self, "path", str(self.path))
        object.__setattr__(self, "topic", str(self.topic))
        object.__setattr__(self, "metadata", _json_safe_dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "topic": self.topic,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ADRRequirementReport:
    documents: tuple[str, ...]
    issues: tuple[ADRRequirementIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "documents", tuple(str(document) for document in self.documents))
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "document_count": self.document_count,
            "issue_count": self.issue_count,
            "documents": list(self.documents),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class ADRRequirementsContract:
    required_topics: frozenset[str]
    required_sections: tuple[str, ...]

    @classmethod
    def default(cls) -> "ADRRequirementsContract":
        return cls(
            required_topics=frozenset(
                {
                    "new_memory_kind",
                    "new_deletion_behavior",
                    "deletion_behavior_change",
                    "archive_behavior_change",
                    "total_recall_like_feature",
                    "plugin_capability_expansion",
                    "affective_scoring_change",
                    "dream_behavior_change",
                    "i_tool_change",
                    "current_behavior_or_personality_feature",
                }
            ),
            required_sections=(
                "Decision",
                "Why this is not cognition",
                "Why this is not a database feature",
                "How forgetting still works",
                "How tombstones are preserved",
                "How present thinking remains with the LLM",
                "Rejected alternatives",
                "Tests required",
            ),
        )

    def evaluate_change(self, spec: ADRChangeSpec | Mapping[str, Any]) -> ADRRequirementReport:
        change = _coerce_change(spec)
        if change.adr_text:
            return self.evaluate_document(
                ADRDocument(
                    path=change.adr_path or f"{change.topic}.md",
                    text=change.adr_text,
                    topics=(change.topic,),
                    metadata=change.metadata,
                )
            )
        if change.topic in self.required_topics and not change.adr_path:
            return ADRRequirementReport(
                documents=(),
                issues=(
                    ADRRequirementIssue(
                        code="adr_required_missing",
                        message="philosophy-touching changes must include an ADR",
                        topic=change.topic,
                    ),
                ),
            )
        return ADRRequirementReport(documents=(change.adr_path,) if change.adr_path else (), issues=())

    def evaluate_document(self, document: ADRDocument | Mapping[str, Any]) -> ADRRequirementReport:
        adr = _coerce_document(document)
        return ADRRequirementReport(documents=(adr.path,), issues=tuple(self._document_issues(adr)))

    def evaluate_documents(
        self,
        documents: list[ADRDocument] | tuple[ADRDocument, ...],
    ) -> ADRRequirementReport:
        paths: list[str] = []
        issues: list[ADRRequirementIssue] = []
        for raw_document in documents:
            document = _coerce_document(raw_document)
            paths.append(document.path)
            issues.extend(self._document_issues(document))
        return ADRRequirementReport(documents=tuple(paths), issues=tuple(issues))

    def _document_issues(self, document: ADRDocument) -> tuple[ADRRequirementIssue, ...]:
        issues: list[ADRRequirementIssue] = []
        if not _has_valid_title(document.text):
            issues.append(
                ADRRequirementIssue(
                    code="adr_title_invalid",
                    message="ADR documents must start with an ADR title",
                    path=document.path,
                )
            )

        headings = _normalized_headings(document.text)
        for section in self.required_sections:
            if _normalize_heading(section) not in headings:
                issues.append(
                    ADRRequirementIssue(
                        code="adr_missing_required_section",
                        message="ADR document is missing a required section",
                        path=document.path,
                        metadata={"section": section},
                    )
                )
        return tuple(issues)


def _coerce_change(spec: ADRChangeSpec | Mapping[str, Any]) -> ADRChangeSpec:
    if isinstance(spec, ADRChangeSpec):
        return spec
    return ADRChangeSpec(**dict(spec))


def _coerce_document(document: ADRDocument | Mapping[str, Any]) -> ADRDocument:
    if isinstance(document, ADRDocument):
        return document
    return ADRDocument(**dict(document))


def _has_valid_title(text: str) -> bool:
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return bool(re.match(r"^#\s+ADR-[A-Za-z0-9]+:\s+\S", stripped))
    return False


def _normalized_headings(text: str) -> set[str]:
    headings: set[str] = set()
    for line in str(text).splitlines():
        match = re.match(r"^\s{0,3}#{2,6}\s+(.+?)\s*$", line)
        if match:
            headings.add(_normalize_heading(match.group(1)))
    return headings


def _normalize_heading(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _normalize_topic(value: str) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _json_safe_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False, default=str))
