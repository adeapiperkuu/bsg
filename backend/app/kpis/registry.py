"""Typed KPI calculator registry with dependency DAG validation."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from collections.abc import Sequence

from app.kpis.contracts import CalculatorFn, RegisteredKpi

logger = logging.getLogger(__name__)


class KpiRegistryError(ValueError):
    """Raised when KPI registration is invalid."""


class KpiRegistry:
    """In-memory registry of versioned KPI definitions and calculators."""

    def __init__(self) -> None:
        self._by_key_version: dict[tuple[str, str], RegisteredKpi] = {}
        self._calculators: dict[str, CalculatorFn] = {}
        self._latest_version: dict[str, str] = {}

    def register_calculator(self, calculator_key: str, fn: CalculatorFn) -> None:
        existing = self._calculators.get(calculator_key)
        if existing is not None and existing is not fn:
            raise KpiRegistryError(f"Duplicate calculator_key: {calculator_key}")
        self._calculators[calculator_key] = fn

    def register(self, kpi: RegisteredKpi, calculator: CalculatorFn | None = None) -> None:
        key = (kpi.kpi_key, kpi.version)
        if key in self._by_key_version:
            raise KpiRegistryError(f"Duplicate KPI registration: {kpi.kpi_key}@{kpi.version}")
        if calculator is not None:
            self.register_calculator(kpi.calculator_key, calculator)
        if kpi.calculator_key not in self._calculators:
            raise KpiRegistryError(
                f"KPI {kpi.kpi_key}@{kpi.version} references unknown calculator "
                f"{kpi.calculator_key}"
            )
        self._by_key_version[key] = kpi
        current = self._latest_version.get(kpi.kpi_key)
        if current is None or _version_tuple(kpi.version) >= _version_tuple(current):
            if kpi.compatibility_status == "current":
                self._latest_version[kpi.kpi_key] = kpi.version
            elif current is None:
                self._latest_version[kpi.kpi_key] = kpi.version

    def get(self, kpi_key: str, version: str | None = None) -> RegisteredKpi | None:
        resolved = version or self._latest_version.get(kpi_key)
        if resolved is None:
            return None
        return self._by_key_version.get((kpi_key, resolved))

    def get_calculator(self, calculator_key: str) -> CalculatorFn | None:
        return self._calculators.get(calculator_key)

    def list_kpis(
        self,
        *,
        owner_agent: str | None = None,
        include_inactive: bool = False,
    ) -> list[RegisteredKpi]:
        latest: list[RegisteredKpi] = []
        for kpi_key, version in sorted(self._latest_version.items()):
            kpi = self._by_key_version[(kpi_key, version)]
            if owner_agent and kpi.owner_agent != owner_agent:
                continue
            if not include_inactive and kpi.compatibility_status == "historical":
                continue
            latest.append(kpi)
        return latest

    def versions_for(self, kpi_key: str) -> list[RegisteredKpi]:
        return [
            kpi
            for (key, _), kpi in sorted(self._by_key_version.items())
            if key == kpi_key
        ]

    def validate_dependencies(self) -> None:
        graph: dict[str, set[str]] = defaultdict(set)
        nodes = set(self._latest_version)
        for kpi in self._by_key_version.values():
            nodes.add(kpi.kpi_key)
            for dep in kpi.dependencies:
                graph[kpi.kpi_key].add(dep.depends_on_kpi_key)
                nodes.add(dep.depends_on_kpi_key)
                if not any(k == dep.depends_on_kpi_key for k, _ in self._by_key_version):
                    raise KpiRegistryError(
                        f"KPI {kpi.kpi_key} depends on unknown KPI {dep.depends_on_kpi_key}"
                    )
        indegree = {node: 0 for node in nodes}
        for src, deps in graph.items():
            for _dep in deps:
                indegree[src] = indegree.get(src, 0) + 1
            for dep in deps:
                indegree.setdefault(dep, 0)
        reverse: dict[str, set[str]] = defaultdict(set)
        for src, deps in graph.items():
            for dep in deps:
                reverse[dep].add(src)
        queue = deque(node for node, degree in indegree.items() if degree == 0)
        seen = 0
        while queue:
            node = queue.popleft()
            seen += 1
            for child in reverse.get(node, ()):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if seen != len(nodes):
            raise KpiRegistryError("KPI dependency graph contains a cycle")

    def topological_order(self, kpi_keys: Sequence[str] | None = None) -> list[str]:
        selected = set(kpi_keys) if kpi_keys is not None else set(self._latest_version)
        graph: dict[str, set[str]] = {key: set() for key in selected}
        for key in selected:
            kpi = self.get(key)
            if kpi is None:
                continue
            for dep in kpi.dependencies:
                if dep.depends_on_kpi_key in selected:
                    graph[key].add(dep.depends_on_kpi_key)
        indegree = {key: len(deps) for key, deps in graph.items()}
        reverse: dict[str, set[str]] = defaultdict(set)
        for src, deps in graph.items():
            for dep in deps:
                reverse[dep].add(src)
        queue = deque(sorted(key for key, degree in indegree.items() if degree == 0))
        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for child in sorted(reverse.get(node, ())):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if len(order) != len(selected):
            raise KpiRegistryError("Cannot topologically order KPI batch; cycle detected")
        return order


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


_REGISTRY: KpiRegistry | None = None


def get_kpi_registry() -> KpiRegistry:
    """Return the process-wide registry, loading providers on first access."""
    global _REGISTRY
    if _REGISTRY is None:
        registry = KpiRegistry()
        from app.kpis.providers import register_all_providers

        register_all_providers(registry)
        registry.validate_dependencies()
        _REGISTRY = registry
        logger.info(
            "event=kpi_registry_loaded kpi_count=%s calculator_count=%s",
            len(registry.list_kpis(include_inactive=True)),
            len(registry._calculators),
        )
    return _REGISTRY


def reset_kpi_registry_for_tests() -> None:
    """Clear the singleton so tests can rebuild a clean registry."""
    global _REGISTRY
    _REGISTRY = None
