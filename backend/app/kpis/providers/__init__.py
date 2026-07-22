"""Domain KPI providers — register calculators without changing formula semantics."""

from __future__ import annotations

from app.kpis.providers import client as client_provider
from app.kpis.providers import delivery as delivery_provider
from app.kpis.providers import governance as governance_provider
from app.kpis.providers import quality as quality_provider
from app.kpis.providers import tower as tower_provider
from app.kpis.providers import workforce as workforce_provider
from app.kpis.registry import KpiRegistry


def register_all_providers(registry: KpiRegistry) -> None:
    delivery_provider.register(registry)
    quality_provider.register(registry)
    workforce_provider.register(registry)
    governance_provider.register(registry)
    tower_provider.register(registry)
    client_provider.register(registry)
