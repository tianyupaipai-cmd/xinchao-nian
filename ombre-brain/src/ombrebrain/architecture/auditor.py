from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict

from ombrebrain.architecture.contracts import (
    ArchitectureIssue,
    ArchitectureReport,
    ComponentDescriptor,
    ComponentGraph,
    SideEffectMode,
)
from ombrebrain.architecture.defaults import default_architecture


_PROTECTED_WRITE_SURFACES = {
    "buckets",
    "bucket-volume",
    "vector-database",
    "embeddings",
    "config",
    "oauth-secrets",
    "deployment",
    "memory_fabric",
}


@dataclass(frozen=True)
class ArchitectureAuditor:
    required_components: tuple[str, ...]

    @classmethod
    def default(cls) -> "ArchitectureAuditor":
        return cls(tuple(component.name for component in default_architecture().components if component.critical))

    def audit(self, graph: ComponentGraph) -> ArchitectureReport:
        issues: list[ArchitectureIssue] = []
        by_name = graph.by_name()
        issues.extend(self._missing_critical(by_name))
        issues.extend(self._unknown_dependencies(graph, by_name))
        issues.extend(self._cycles(graph, by_name))
        issues.extend(self._read_only_surface_ownership(graph))
        issues.extend(self._duplicate_write_owners(graph))
        return ArchitectureReport(
            ok=not issues,
            components=tuple(sorted(by_name)),
            issues=tuple(issues),
        )

    def _missing_critical(self, by_name: dict[str, ComponentDescriptor]) -> tuple[ArchitectureIssue, ...]:
        issues = []
        for name in self.required_components:
            if name not in by_name:
                issues.append(
                    ArchitectureIssue(
                        code="missing_critical_component",
                        message="critical v2.4.0 architecture component is missing",
                        component=name,
                    )
                )
        return tuple(issues)

    def _unknown_dependencies(
        self,
        graph: ComponentGraph,
        by_name: dict[str, ComponentDescriptor],
    ) -> tuple[ArchitectureIssue, ...]:
        issues = []
        for component in graph.components:
            for dependency in component.dependencies:
                if dependency not in by_name:
                    issues.append(
                        ArchitectureIssue(
                            code="unknown_dependency",
                            message="component depends on an unknown component",
                            component=component.name,
                            metadata={"dependency": dependency},
                        )
                    )
        return tuple(issues)

    def _cycles(
        self,
        graph: ComponentGraph,
        by_name: dict[str, ComponentDescriptor],
    ) -> tuple[ArchitectureIssue, ...]:
        visited: set[str] = set()
        active: list[str] = []
        cycles: set[tuple[str, ...]] = set()

        def visit(name: str) -> None:
            if name in active:
                start = active.index(name)
                cycles.add(tuple(active[start:] + [name]))
                return
            if name in visited:
                return
            visited.add(name)
            active.append(name)
            component = by_name.get(name)
            if component is not None:
                for dependency in component.dependencies:
                    if dependency in by_name:
                        visit(dependency)
            active.pop()

        for component in graph.components:
            visit(component.name)

        return tuple(
            ArchitectureIssue(
                code="dependency_cycle",
                message="component dependency cycle detected",
                component=cycle[0],
                metadata={"cycle": list(cycle)},
            )
            for cycle in sorted(cycles)
        )

    def _read_only_surface_ownership(self, graph: ComponentGraph) -> tuple[ArchitectureIssue, ...]:
        issues = []
        for component in graph.components:
            if component.side_effect_mode == SideEffectMode.READ_ONLY and component.owns_surfaces:
                issues.append(
                    ArchitectureIssue(
                        code="read_only_owns_surface",
                        message="read-only component must not own mutable surfaces",
                        component=component.name,
                        metadata={"surfaces": list(component.owns_surfaces)},
                    )
                )
        return tuple(issues)

    def _duplicate_write_owners(self, graph: ComponentGraph) -> tuple[ArchitectureIssue, ...]:
        owners: dict[str, list[str]] = defaultdict(list)
        for component in graph.components:
            if component.side_effect_mode != SideEffectMode.WRITE_LEGACY_STATE:
                continue
            for surface in component.owns_surfaces:
                if surface in _PROTECTED_WRITE_SURFACES:
                    owners[surface].append(component.name)
        return tuple(
            ArchitectureIssue(
                code="duplicate_write_owner",
                message="protected legacy surface has multiple write owners",
                surface=surface,
                metadata={"owners": sorted(names)},
            )
            for surface, names in sorted(owners.items())
            if len(names) > 1
        )
