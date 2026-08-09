from dataclasses import dataclass, field
from collections.abc import Mapping


_SENSITIVE_KEY_PARTS = (
    "key",
    "secret",
    "token",
    "password",
    "passwd",
    "passphrase",
    "credential",
    "authorization",
    "cookie",
    "set-cookie",
)
_REDACTED = "***"


@dataclass(frozen=True)
class OmbreContext:
    request_id: str
    actor_name: str
    permissions: tuple[str, ...] = field(default_factory=tuple)
    source: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    config_snapshot: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", tuple(self.permissions))

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def safe_config(self) -> dict[str, object]:
        return _redact_mapping(self.config_snapshot)


def _redact_mapping(config: Mapping[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in config.items():
        key_text = str(key)
        if _is_sensitive_key(key_text):
            redacted[key_text] = _REDACTED
        elif isinstance(value, Mapping):
            redacted[key_text] = _redact_mapping(value)
        elif isinstance(value, list):
            redacted[key_text] = [_redact_value(item) for item in value]
        elif isinstance(value, tuple):
            redacted[key_text] = tuple(_redact_value(item) for item in value)
        else:
            redacted[key_text] = value
    return redacted


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _redact_mapping(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("_", "-")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)
