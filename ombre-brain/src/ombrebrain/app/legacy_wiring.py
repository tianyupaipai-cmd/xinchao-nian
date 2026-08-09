from __future__ import annotations

from typing import Any

from ombrebrain.app.legacy_runtime import LegacyRuntime


def attach_v3_runtime_to_components(runtime: LegacyRuntime, *components: object | None) -> int:
    attached = 0
    for component in components:
        if component is None:
            continue
        attach = getattr(component, "attach_v3_runtime", None)
        if callable(attach):
            attach(runtime)
            attached += 1
            continue
        try:
            setattr(component, "v3_runtime", runtime)
            attached += 1
        except Exception:
            continue
    return attached


def build_v3_runtime(
    config: dict[str, Any],
    *,
    bucket_mgr: object | None = None,
    components: tuple[object | None, ...] = (),
) -> LegacyRuntime:
    runtime = LegacyRuntime.from_config(config)
    attach_v3_runtime_to_components(runtime, bucket_mgr, *components)
    return runtime
