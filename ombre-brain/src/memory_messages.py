"""Shared user-facing wording for memory state transitions."""


def resolved_hint(resolved: bool) -> str:
    """Return the canonical hint for resolved state changes."""
    if resolved:
        return "已沉底，只在关键词触发时重新浮现"
    return "已重新激活，将参与浮现排序"
