"""Database-backed report template and section plugin registry."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReportTemplate
from app.reports.contracts import SectionBuilder
from app.reports.sections import SECTION_BUILDERS


@dataclass(slots=True)
class ReportRegistry:
    sections: dict[str, SectionBuilder]

    def register(self, key: str, builder: SectionBuilder) -> None:
        if not key or key in self.sections:
            raise ValueError(f"Report section plugin '{key}' is already registered.")
        self.sections[key] = builder

    def get_section(self, key: str) -> SectionBuilder | None:
        return self.sections.get(key)

    def validate_section_config(self, section_config: list) -> None:
        errors: list[str] = []
        seen: set[str] = set()
        for index, entry in enumerate(section_config):
            if not isinstance(entry, dict):
                errors.append(f"section_config[{index}] must be an object")
                continue
            key = entry.get("key")
            if not isinstance(key, str) or not key:
                errors.append(f"section_config[{index}].key is required")
            elif key not in self.sections:
                errors.append(f"unknown report section plugin '{key}'")
            elif key in seen:
                errors.append(f"duplicate report section plugin '{key}'")
            else:
                seen.add(key)
            if "options" in entry and not isinstance(entry["options"], dict):
                errors.append(f"section_config[{index}].options must be an object")
        if errors:
            raise ValueError("; ".join(errors))

    async def list_active(
        self,
        session: AsyncSession,
        *,
        org_id: UUID | None,
    ) -> list[ReportTemplate]:
        stmt = select(ReportTemplate).where(ReportTemplate.status == "active")
        if org_id is None:
            stmt = stmt.where(ReportTemplate.org_id.is_(None))
        else:
            stmt = stmt.where(or_(ReportTemplate.org_id.is_(None), ReportTemplate.org_id == org_id))
        rows = list(
            (
                await session.execute(
                    stmt.order_by(
                        ReportTemplate.template_key.asc(),
                        ReportTemplate.org_id.desc().nullslast(),
                        ReportTemplate.version.desc(),
                    )
                )
            ).scalars()
        )
        for row in rows:
            self.validate_section_config(list(row.section_config or []))
        return rows

    async def resolve(
        self,
        session: AsyncSession,
        template_key: str,
        *,
        org_id: UUID | None,
        version: str | None = None,
        active_only: bool = True,
    ) -> ReportTemplate | None:
        stmt = select(ReportTemplate).where(ReportTemplate.template_key == template_key)
        if org_id is None:
            stmt = stmt.where(ReportTemplate.org_id.is_(None))
        else:
            stmt = stmt.where(or_(ReportTemplate.org_id == org_id, ReportTemplate.org_id.is_(None)))
        if version is not None:
            stmt = stmt.where(ReportTemplate.version == version)
        if active_only:
            stmt = stmt.where(ReportTemplate.status == "active")
        rows = list(
            (
                await session.execute(
                    stmt.order_by(
                        ReportTemplate.org_id.desc().nullslast(),
                        ReportTemplate.version.desc(),
                        ReportTemplate.updated_at.desc(),
                    )
                )
            ).scalars()
        )
        if not rows:
            return None
        template = rows[0]
        self.validate_section_config(list(template.section_config or []))
        return template


_REGISTRY = ReportRegistry(sections=dict(SECTION_BUILDERS))


def get_report_registry() -> ReportRegistry:
    return _REGISTRY


async def load_templates(
    session: AsyncSession, *, org_id: UUID | None
) -> list[ReportTemplate]:
    return await _REGISTRY.list_active(session, org_id=org_id)


async def resolve_template(
    session: AsyncSession,
    template_key: str,
    *,
    org_id: UUID | None,
    version: str | None = None,
) -> ReportTemplate | None:
    return await _REGISTRY.resolve(
        session,
        template_key,
        org_id=org_id,
        version=version,
    )
