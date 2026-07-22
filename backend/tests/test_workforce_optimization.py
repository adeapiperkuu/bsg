"""Tests for Phase 16 workforce optimization and Phase 19 field/lineage contracts."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.core.field_permissions import (
    authorize_fields,
    resolve_allowed_fields,
    role_can_access_field,
)
from app.core.security import CurrentUser
from app.db.models import (
    Annotator,
    AnnotatorSkill,
    AppRole,
    DeliverySite,
    Milestone,
    MilestoneStatus,
    ProficiencyLevel,
    Project,
    ProjectSkillRequirement,
    Skill,
    SkillRequirementPriority,
    Team,
    UtilizationSnapshot,
)
from app.schemas.recommendation_lineage import (
    RecommendationCalculation,
    RecommendationEvidenceItem,
    RecommendationSourceEntity,
    build_lineage,
)
from app.services.workforce_optimization import (
    _OptimizationContext,
    generate_rebalancing_recommendations,
    generate_resource_planning,
    generate_skill_matches,
    generate_sme_coverage,
)


def _user(role: AppRole, org_id=None) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        org_id=org_id or uuid4(),
        email=f"{role.value}@example.com",
        role=role,
        is_active=True,
    )


def _project(org_id) -> Project:
    return Project(
        id=uuid4(),
        org_id=org_id,
        name="Opt Project",
        vertical="medical",
        status="active",
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
    )


def _team(org_id, project_id, *, name="Team A", site=DeliverySite.INDIA, domain="radiology") -> Team:
    return Team(
        id=uuid4(),
        org_id=org_id,
        project_id=project_id,
        name=name,
        site=site,
        domain=domain,
        is_active=True,
    )


def _annotator(org_id, team_id, *, name="Alex", sme=False) -> Annotator:
    return Annotator(
        id=uuid4(),
        org_id=org_id,
        team_id=team_id,
        full_name=name,
        site=DeliverySite.INDIA,
        is_sme_certified=sme,
        is_active=True,
    )


def _skill(org_id, *, name="Backend", critical=True) -> Skill:
    return Skill(
        id=uuid4(),
        org_id=org_id,
        name=name,
        category="Engineering",
        domain="radiology",
        is_critical=critical,
    )


def _requirement(project, skill, *, headcount=2, sme=1, priority=SkillRequirementPriority.HIGH):
    return ProjectSkillRequirement(
        id=uuid4(),
        org_id=project.org_id,
        project_id=project.id,
        skill_id=skill.id,
        required_proficiency_level=ProficiencyLevel.ADVANCED,
        required_headcount=headcount,
        required_sme_count=sme,
        priority=priority,
    )


def _util(project, team, *, pct: str) -> UtilizationSnapshot:
    return UtilizationSnapshot(
        id=uuid4(),
        org_id=project.org_id,
        project_id=project.id,
        team_id=team.id,
        annotator_id=None,
        snapshot_date=date.today(),
        allocated_hours=Decimal("40"),
        available_hours=Decimal("40"),
        utilization_pct=Decimal(pct),
    )


def _ctx(**kwargs) -> _OptimizationContext:
    return _OptimizationContext(**kwargs)


class TestFieldPermissions:
    def test_super_admin_has_full_access(self):
        assert resolve_allowed_fields("workforce", AppRole.SUPER_ADMIN) is None
        assert role_can_access_field(AppRole.SUPER_ADMIN, "workforce", "profitability") is True

    def test_client_denied_workforce_fields(self):
        allowed = resolve_allowed_fields("workforce", AppRole.CLIENT)
        assert allowed == frozenset()
        assert role_can_access_field(AppRole.CLIENT, "workforce", "optimization") is False

    def test_delivery_manager_gets_staffing_not_profitability(self):
        assert role_can_access_field(AppRole.DELIVERY_MANAGER, "project_health", "staffing") is True
        assert (
            role_can_access_field(AppRole.DELIVERY_MANAGER, "project_health", "profitability")
            is False
        )
        assert role_can_access_field(AppRole.BSG_LEADERSHIP, "project_health", "profitability") is True

    def test_authorize_fields_strips_unauthorized_keys(self):
        payload = {
            "project_id": str(uuid4()),
            "staffing": {"headcount": 10},
            "profitability": {"margin": 0.3},
            "milestones": [],
        }
        filtered = authorize_fields(payload, AppRole.DELIVERY_MANAGER, domain="project_health")
        assert "staffing" in filtered
        assert "profitability" not in filtered
        assert "milestones" in filtered

        leadership = authorize_fields(payload, AppRole.BSG_LEADERSHIP, domain="project_health")
        assert "profitability" in leadership


class TestRecommendationLineage:
    def test_build_lineage_traces_evidence_to_sources(self):
        entity_id = uuid4()
        now = datetime.now(timezone.utc)
        lineage = build_lineage(
            recommendation_id="rec-1",
            recommendation_type="skill_match",
            generated_at=now,
            confidence_score=0.82,
            evidence=[
                RecommendationEvidenceItem(
                    evidence_id="e1",
                    summary="Annotator skill evidence",
                    source_entities=[
                        RecommendationSourceEntity(
                            source_table="annotators",
                            source_row_id=entity_id,
                            label="Alex",
                        ),
                    ],
                    metric_keys=["utilization_pct"],
                    observed_at=now,
                ),
            ],
            calculations=[
                RecommendationCalculation(
                    name="composite_match_score",
                    description="Weighted match",
                    result=0.77,
                    formula="0.4*skill + ...",
                ),
            ],
        )
        assert lineage.recommendation_id == "rec-1"
        assert lineage.confidence_score == 0.82
        assert lineage.source_entities[0].source_table == "annotators"
        assert lineage.source_entities[0].source_row_id == entity_id
        assert "utilization_pct" in lineage.metrics_involved
        assert lineage.calculations[0].name == "composite_match_score"
        assert lineage.model_version.startswith("workforce_optimization")


class TestSkillMatching:
    def test_ranks_qualified_annotator_above_unqualified(self):
        org_id = uuid4()
        project = _project(org_id)
        team = _team(org_id, project.id)
        skill = _skill(org_id)
        req = _requirement(project, skill, headcount=1, sme=0)
        strong = _annotator(org_id, team.id, name="Strong")
        weak = _annotator(org_id, team.id, name="Weak")
        ctx = _ctx(
            project=project,
            teams=[team],
            annotators=[strong, weak],
            skills_by_id={skill.id: skill},
            requirements=[req],
            assignments_by_annotator={
                strong.id: [
                    AnnotatorSkill(
                        id=uuid4(),
                        org_id=org_id,
                        annotator_id=strong.id,
                        skill_id=skill.id,
                        proficiency_level=ProficiencyLevel.EXPERT,
                    ),
                ],
                weak.id: [],
            },
            certifications_by_annotator={},
            certification_defs={},
            utilization_by_team={},
            utilization_by_annotator={},
            milestones=[],
            throughput=[],
        )
        matches = generate_skill_matches(ctx)
        assert len(matches) == 1
        names = [c.annotator_name for c in matches[0].candidates]
        assert names[0] == "Strong"
        top = matches[0].candidates[0]
        assert top.match_score > 0.5
        assert top.lineage.recommendation_type == "skill_match"
        assert top.reasoning
        assert top.strengths


class TestRebalancing:
    def test_suggests_transfer_from_overloaded_to_underutilized(self):
        org_id = uuid4()
        project = _project(org_id)
        overloaded = _team(org_id, project.id, name="Overloaded")
        under = _team(org_id, project.id, name="Under")
        person = _annotator(org_id, overloaded.id, name="Movable")
        ctx = _ctx(
            project=project,
            teams=[overloaded, under],
            annotators=[person, _annotator(org_id, under.id, name="Stay")],
            skills_by_id={},
            requirements=[],
            assignments_by_annotator={},
            certifications_by_annotator={},
            certification_defs={},
            utilization_by_team={
                overloaded.id: _util(project, overloaded, pct="95"),
                under.id: _util(project, under, pct="45"),
            },
            utilization_by_annotator={},
            milestones=[],
            throughput=[],
        )
        recs = generate_rebalancing_recommendations(ctx)
        assert len(recs) >= 1
        rec = recs[0]
        assert rec.source_team_name == "Overloaded"
        assert rec.destination_team_name == "Under"
        assert rec.annotator_name == "Movable"
        assert rec.estimated_utilization_improvement > 0
        assert rec.lineage.calculations
        assert "utilization_pct" in rec.lineage.metrics_involved


class TestResourcePlanning:
    def test_recommends_headcount_for_shortfall(self):
        org_id = uuid4()
        project = _project(org_id)
        team = _team(org_id, project.id)
        skill = _skill(org_id, name="QA Engineer")
        req = _requirement(project, skill, headcount=3, sme=0, priority=SkillRequirementPriority.CRITICAL)
        person = _annotator(org_id, team.id)
        ctx = _ctx(
            project=project,
            teams=[team],
            annotators=[person],
            skills_by_id={skill.id: skill},
            requirements=[req],
            assignments_by_annotator={
                person.id: [
                    AnnotatorSkill(
                        id=uuid4(),
                        org_id=org_id,
                        annotator_id=person.id,
                        skill_id=skill.id,
                        proficiency_level=ProficiencyLevel.ADVANCED,
                    ),
                ],
            },
            certifications_by_annotator={},
            certification_defs={},
            utilization_by_team={},
            utilization_by_annotator={},
            milestones=[
                Milestone(
                    id=uuid4(),
                    org_id=org_id,
                    project_id=project.id,
                    name="Launch",
                    planned_date=date.today(),
                    status=MilestoneStatus.AT_RISK,
                ),
            ],
            throughput=[],
        )
        plans = generate_resource_planning(ctx)
        assert any(p.skill_name == "QA Engineer" and p.estimated_headcount >= 2 for p in plans)
        assert all(p.lineage.evidence for p in plans if p.skill_id is not None)


class TestSmeCoverage:
    def test_detects_single_point_of_failure(self):
        org_id = uuid4()
        project = _project(org_id)
        team = _team(org_id, project.id)
        skill = _skill(org_id, name="Critical Domain", critical=True)
        req = _requirement(project, skill, headcount=2, sme=2)
        sme = _annotator(org_id, team.id, name="Only SME", sme=True)
        ctx = _ctx(
            project=project,
            teams=[team],
            annotators=[sme],
            skills_by_id={skill.id: skill},
            requirements=[req],
            assignments_by_annotator={
                sme.id: [
                    AnnotatorSkill(
                        id=uuid4(),
                        org_id=org_id,
                        annotator_id=sme.id,
                        skill_id=skill.id,
                        proficiency_level=ProficiencyLevel.EXPERT,
                    ),
                ],
            },
            certifications_by_annotator={},
            certification_defs={},
            utilization_by_team={},
            utilization_by_annotator={},
            milestones=[],
            throughput=[],
        )
        recs = generate_sme_coverage(ctx)
        assert len(recs) >= 1
        finding_types = {f.finding_type for f in recs[0].findings}
        assert "single_point_of_failure" in finding_types
        assert "Assign backup SME" in recs[0].recommended_actions
        assert recs[0].lineage.recommendation_type == "sme_coverage"
