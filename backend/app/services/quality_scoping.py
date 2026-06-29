from __future__ import annotations

import re

from app.db.models import AppRole, QualitySnapshot
from app.schemas.domain import QualityDashboardRead


def team_status_label(snapshot: QualitySnapshot) -> str:
    if snapshot.has_drift_alert:
        return "Critical" if snapshot.confidence_level == "high" else "Warning"
    if snapshot.gold_set_accuracy_pct is not None and snapshot.gold_set_accuracy_pct < 94:
        return "Warning"
    return "On Track"


def filter_dashboard_for_role(dashboard: QualityDashboardRead, role: AppRole) -> QualityDashboardRead:
    if role == AppRole.CLIENT:
        return QualityDashboardRead(
            kpis=dashboard.kpis,
            trend=[],
            error_breakdown=[],
            team_scorecard=[],
            drift_alerts=[],
            narrative=dashboard.narrative,
        )
    if role == AppRole.BSG_LEADERSHIP:
        return dashboard
    return dashboard


def filter_response_for_role(text: str, role: AppRole) -> str:
    if role != AppRole.CLIENT:
        return text
    text = re.sub(r"reviewer[_\s]?id[s]?:?\s*\S+", "[redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"annotator[s]?:?\s*\S+", "[redacted]", text, flags=re.IGNORECASE)
    return text


def filter_context_for_role(context: str, role: AppRole) -> str:
    if role == AppRole.CLIENT:
        lines = []
        for line in context.splitlines():
            lower = line.lower()
            if "annotator" in lower or "reviewer" in lower or "full_name" in lower:
                continue
            lines.append(line)
        return "\n".join(lines)
    return context
