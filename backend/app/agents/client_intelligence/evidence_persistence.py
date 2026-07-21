"""Transactional persistence for validated ClientEvidencePack snapshots.

Phase 1 substrate only — no readiness scoring, insights, recommendations,
narratives, or Q&A orchestration. Does not persist automatically from the builder.

Transaction ownership:
- Caller owns the outer unit of work and must ``commit`` / ``rollback``.
- This service never calls ``session.commit()``.
- Snapshot + links are written inside ``begin_nested()`` (SAVEPOINT) so a
  failed link insert rolls back only the nested work.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.client_intelligence.contracts import (
    ClientEvidencePack,
    ClientEvidenceReference,
    EvidenceVisibility,
)
from app.agents.client_intelligence.evidence_validation import (
    EvidencePackIntegrityError,
    validate_client_evidence_pack,
)
from app.core.exceptions import ApiError
from app.core.security import CurrentUser
from app.db.models import (
    AppRole,
    ClientIntelligenceEvidenceLink,
    ClientIntelligenceSnapshot,
)
from app.services.evidence import EvidenceInput, require_evidence
from app.services.scoping import get_visible_project

SNAPSHOT_IDEMPOTENCY_CONSTRAINT = "client_intelligence_snapshots_idempotency_key"
_PG_UNIQUE_VIOLATION = "23505"


def serialize_client_evidence_pack_for_persistence(pack: ClientEvidencePack) -> dict[str, Any]:
    """Deterministic contract JSON. CLIENT_SAFE omits raw untrusted knowledge text."""
    payload = pack.model_dump(mode="json")
    if pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        knowledge = payload.get("knowledge") or {}
        for document in knowledge.get("documents") or []:
            document["document_title"] = None
        for chunk in knowledge.get("chunks") or []:
            chunk["untrusted_text"] = ""
        payload["knowledge"] = knowledge
    return payload


def reconstruct_client_evidence_pack(
    payload: dict[str, Any] | ClientEvidencePack,
) -> ClientEvidencePack:
    """Rebuild a ClientEvidencePack from stored JSON (or pass-through a pack)."""
    if isinstance(payload, ClientEvidencePack):
        return payload
    return ClientEvidencePack.model_validate(payload)


def reconstruct_pack_from_snapshot(snapshot: ClientIntelligenceSnapshot) -> ClientEvidencePack:
    """Reconstruct a pack from a persisted snapshot payload."""
    return reconstruct_client_evidence_pack(deepcopy(snapshot.pack_payload))


def persistable_evidence_references(pack: ClientEvidencePack) -> list[ClientEvidenceReference]:
    """Evidence refs that may be stored for this snapshot visibility mode."""
    if pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        return [
            item
            for item in pack.evidence
            if item.visibility == EvidenceVisibility.CLIENT_SAFE
        ]
    return list(pack.evidence)


def _link_identity_key(item: ClientEvidenceReference) -> tuple[str, str, str, str]:
    return (
        item.source_agent.value,
        item.source_table,
        str(item.source_row_id),
        item.visibility.value,
    )


def _stored_link_identity_key(link: ClientIntelligenceEvidenceLink) -> tuple[str, str, str, str]:
    return (
        link.source_agent,
        link.source_table,
        str(link.source_row_id),
        link.visibility,
    )


def _snapshot_corrupt(detail: str) -> ApiError:
    return ApiError(409, "SNAPSHOT_CORRUPT", detail)


def _assert_pack_identity(
    pack: ClientEvidencePack,
    *,
    org_id: UUID,
    project_id: UUID,
) -> None:
    if pack.project.project_id != project_id:
        raise ApiError(
            409,
            "PROJECT_MISMATCH",
            "Pack project_id does not match authorized project.",
        )
    if pack.project.org_id != org_id:
        raise ApiError(
            409,
            "TENANT_MISMATCH",
            "Pack org_id does not match authorized tenant.",
        )


async def _assert_can_persist(
    session: AsyncSession,
    *,
    current_user: CurrentUser,
    org_id: UUID,
    project_id: UUID,
) -> None:
    """Align application writes with append-only RLS INSERT roles."""
    if current_user.role in {AppRole.CLIENT, AppRole.BSG_LEADERSHIP}:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")
    if current_user.role == AppRole.DELIVERY_MANAGER and current_user.org_id != org_id:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")
    # Super Admin: get_visible_project permits any project; operational "explicit
    # scope" for SA is not fully modeled beyond project existence + RLS INSERT.
    project = await get_visible_project(session, project_id, current_user)
    if project.org_id != org_id:
        raise ApiError(
            409,
            "TENANT_MISMATCH",
            "Authorized project org_id does not match persistence tenant.",
        )


def _idempotency_filters(pack: ClientEvidencePack, *, org_id: UUID, project_id: UUID):
    period = pack.reporting_period
    return (
        ClientIntelligenceSnapshot.org_id == org_id,
        ClientIntelligenceSnapshot.project_id == project_id,
        ClientIntelligenceSnapshot.visibility_mode == pack.visibility_mode.value,
        ClientIntelligenceSnapshot.reporting_period_start == period.start_date,
        ClientIntelligenceSnapshot.reporting_period_end == period.end_date,
        ClientIntelligenceSnapshot.reporting_period_previous_start
        == period.previous_start_date,
        ClientIntelligenceSnapshot.reporting_period_previous_end
        == period.previous_end_date,
        ClientIntelligenceSnapshot.reporting_period_as_of == period.as_of,
        ClientIntelligenceSnapshot.source_fingerprint == pack.source_fingerprint,
        ClientIntelligenceSnapshot.policy_fingerprint == pack.policy_fingerprint,
    )


def _iter_exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = (
            getattr(current, "orig", None)
            or getattr(current, "__cause__", None)
            or getattr(current, "__context__", None)
        )


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    for node in _iter_exception_chain(exc):
        diag = getattr(node, "diag", None)
        name = getattr(diag, "constraint_name", None)
        if name:
            return str(name)
        name = getattr(node, "constraint_name", None)
        if name:
            return str(name)
    return None


def _integrity_sqlstate(exc: IntegrityError) -> str | None:
    for node in _iter_exception_chain(exc):
        for attr in ("sqlstate", "pgcode"):
            value = getattr(node, attr, None)
            if value:
                return str(value)
        diag = getattr(node, "diag", None)
        sqlstate = getattr(diag, "sqlstate", None)
        if sqlstate:
            return str(sqlstate)
    return None


def _is_idempotency_conflict(exc: IntegrityError) -> bool:
    """Accept only a PostgreSQL unique violation for the snapshot idempotency key."""
    if _integrity_constraint_name(exc) != SNAPSHOT_IDEMPOTENCY_CONSTRAINT:
        return False
    return _integrity_sqlstate(exc) == _PG_UNIQUE_VIOLATION


async def find_client_evidence_snapshot(
    session: AsyncSession,
    pack: ClientEvidencePack,
    *,
    org_id: UUID,
    project_id: UUID,
) -> ClientIntelligenceSnapshot | None:
    """Lookup an existing identical snapshot by the idempotency identity."""
    result = await session.execute(
        select(ClientIntelligenceSnapshot)
        .options(selectinload(ClientIntelligenceSnapshot.evidence_links))
        .where(*_idempotency_filters(pack, org_id=org_id, project_id=project_id))
    )
    return result.scalar_one_or_none()


def _assert_links_match_persistable(
    snapshot: ClientIntelligenceSnapshot,
    persistable: list[ClientEvidenceReference],
    *,
    org_id: UUID,
    project_id: UUID,
    source_fingerprint: str,
) -> None:
    links = list(snapshot.evidence_links)
    if len(links) != len(persistable):
        raise _snapshot_corrupt("Existing snapshot evidence links are incomplete.")

    by_key = {_stored_link_identity_key(link): link for link in links}
    if len(by_key) != len(links):
        raise _snapshot_corrupt("Existing snapshot evidence links contain duplicates.")

    for expected in persistable:
        key = _link_identity_key(expected)
        link = by_key.get(key)
        if link is None:
            raise _snapshot_corrupt(
                "Existing snapshot evidence links do not match persistable evidence."
            )
        if (
            link.description != expected.description
            or link.observed_at != expected.observed_at
            or list(link.claim_keys) != list(expected.claim_keys)
            or link.source_fingerprint != source_fingerprint
            or link.org_id != org_id
            or link.project_id != project_id
        ):
            raise _snapshot_corrupt(
                "Existing snapshot evidence link content does not match."
            )


def _assert_client_safe_stored_payload(
    snapshot: ClientIntelligenceSnapshot,
    reconstructed: ClientEvidencePack,
) -> None:
    if reconstructed.visibility_mode != EvidenceVisibility.CLIENT_SAFE:
        return
    for document in reconstructed.knowledge.documents:
        if document.document_title is not None:
            raise _snapshot_corrupt(
                "CLIENT_SAFE stored payload must omit Knowledge document_title."
            )
    for chunk in reconstructed.knowledge.chunks:
        if chunk.untrusted_text != "":
            raise _snapshot_corrupt(
                "CLIENT_SAFE stored payload must redact Knowledge untrusted_text."
            )
    if any(
        item.visibility != EvidenceVisibility.CLIENT_SAFE
        for item in reconstructed.evidence
    ):
        raise _snapshot_corrupt(
            "CLIENT_SAFE stored payload must not retain INTERNAL evidence references."
        )
    expected = serialize_client_evidence_pack_for_persistence(reconstructed)
    if json.dumps(expected, sort_keys=True, default=str) != json.dumps(
        snapshot.pack_payload, sort_keys=True, default=str
    ):
        raise _snapshot_corrupt(
            "CLIENT_SAFE stored payload is not in canonical persistence-redacted form."
        )


def verify_stored_snapshot_integrity(
    snapshot: ClientIntelligenceSnapshot,
    *,
    role: AppRole,
) -> ClientEvidencePack:
    """Fail closed unless stored payload, row fields, and links are intact.

    Shared by direct load and idempotent reuse. Never mutates the stored row.
    """
    try:
        reconstructed = reconstruct_pack_from_snapshot(snapshot)
    except Exception as exc:  # noqa: BLE001 — fail closed on any payload corruption
        raise _snapshot_corrupt(
            "Existing snapshot payload cannot be reconstructed."
        ) from exc

    validation = validate_client_evidence_pack(reconstructed, role=role)
    if not validation.is_valid:
        raise _snapshot_corrupt("Existing snapshot fails canonical validation.")

    period = reconstructed.reporting_period
    if (
        snapshot.org_id != reconstructed.project.org_id
        or snapshot.project_id != reconstructed.project.project_id
        or snapshot.visibility_mode != reconstructed.visibility_mode.value
        or snapshot.reporting_period_start != period.start_date
        or snapshot.reporting_period_end != period.end_date
        or snapshot.reporting_period_previous_start != period.previous_start_date
        or snapshot.reporting_period_previous_end != period.previous_end_date
        or snapshot.reporting_period_as_of != period.as_of
        or snapshot.source_fingerprint != reconstructed.source_fingerprint
        or snapshot.policy_fingerprint != reconstructed.policy_fingerprint
        or snapshot.overall_data_quality != reconstructed.overall_data_quality.value
        or snapshot.generated_at != reconstructed.generated_at
    ):
        raise _snapshot_corrupt(
            "Existing snapshot row does not match its stored pack payload."
        )

    persistable = persistable_evidence_references(reconstructed)
    _assert_links_match_persistable(
        snapshot,
        persistable,
        org_id=reconstructed.project.org_id,
        project_id=reconstructed.project.project_id,
        source_fingerprint=reconstructed.source_fingerprint,
    )
    _assert_client_safe_stored_payload(snapshot, reconstructed)
    return reconstructed


def _verify_existing_snapshot(
    snapshot: ClientIntelligenceSnapshot,
    pack: ClientEvidencePack,
    persistable: list[ClientEvidenceReference],
    *,
    role: AppRole,
) -> ClientIntelligenceSnapshot:
    """Verify a looked-up snapshot is intact and matches the requested pack identity."""
    reconstructed = verify_stored_snapshot_integrity(snapshot, role=role)
    period = pack.reporting_period
    if (
        snapshot.org_id != pack.project.org_id
        or snapshot.project_id != pack.project.project_id
        or snapshot.visibility_mode != pack.visibility_mode.value
        or snapshot.reporting_period_start != period.start_date
        or snapshot.reporting_period_end != period.end_date
        or snapshot.reporting_period_previous_start != period.previous_start_date
        or snapshot.reporting_period_previous_end != period.previous_end_date
        or snapshot.reporting_period_as_of != period.as_of
        or snapshot.source_fingerprint != pack.source_fingerprint
        or snapshot.policy_fingerprint != pack.policy_fingerprint
        or snapshot.overall_data_quality != pack.overall_data_quality.value
        or reconstructed.source_fingerprint != pack.source_fingerprint
        or reconstructed.policy_fingerprint != pack.policy_fingerprint
    ):
        raise _snapshot_corrupt(
            "Existing snapshot identity does not match the requested pack."
        )

    _assert_links_match_persistable(
        snapshot,
        persistable,
        org_id=pack.project.org_id,
        project_id=pack.project.project_id,
        source_fingerprint=pack.source_fingerprint,
    )
    return snapshot


async def load_client_evidence_snapshot(
    session: AsyncSession,
    snapshot_id: UUID,
    *,
    current_user: CurrentUser,
) -> ClientIntelligenceSnapshot:
    """Load a snapshot with project scoping and stored-payload integrity checks."""
    snapshot = (
        await session.execute(
            select(ClientIntelligenceSnapshot)
            .options(selectinload(ClientIntelligenceSnapshot.evidence_links))
            .where(ClientIntelligenceSnapshot.id == snapshot_id)
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise ApiError(404, "NOT_FOUND", "Client Intelligence snapshot was not found.")

    try:
        await get_visible_project(session, snapshot.project_id, current_user)
    except ApiError as exc:
        if exc.status_code in {403, 404}:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Client Intelligence snapshot was not found.",
            ) from exc
        raise

    if current_user.role == AppRole.CLIENT:
        if snapshot.visibility_mode != EvidenceVisibility.CLIENT_SAFE.value:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Client Intelligence snapshot was not found.",
            )
    elif current_user.role == AppRole.BSG_LEADERSHIP:
        # No approved sanitized INTERNAL aggregate scope exists yet — fail closed.
        if snapshot.visibility_mode != EvidenceVisibility.CLIENT_SAFE.value:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Client Intelligence snapshot was not found.",
            )
    elif current_user.role == AppRole.DELIVERY_MANAGER:
        if snapshot.org_id != current_user.org_id:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Client Intelligence snapshot was not found.",
            )
    elif current_user.role == AppRole.SUPER_ADMIN:
        # SA may load within get_visible_project allowance; explicit operational
        # scope beyond project existence is not fully modeled yet.
        pass
    else:
        raise ApiError(403, "FORBIDDEN", "Authenticated user lacks permission.")

    verify_stored_snapshot_integrity(snapshot, role=current_user.role)
    return snapshot


def _build_snapshot_entity(
    pack: ClientEvidencePack,
    persistable: list[ClientEvidenceReference],
    *,
    current_user: CurrentUser,
    org_id: UUID,
    project_id: UUID,
) -> ClientIntelligenceSnapshot:
    period = pack.reporting_period
    snapshot = ClientIntelligenceSnapshot(
        org_id=org_id,
        project_id=project_id,
        reporting_period_start=period.start_date,
        reporting_period_end=period.end_date,
        reporting_period_previous_start=period.previous_start_date,
        reporting_period_previous_end=period.previous_end_date,
        reporting_period_as_of=period.as_of,
        visibility_mode=pack.visibility_mode.value,
        source_fingerprint=pack.source_fingerprint,
        policy_fingerprint=pack.policy_fingerprint,
        overall_data_quality=pack.overall_data_quality.value,
        pack_payload=serialize_client_evidence_pack_for_persistence(pack),
        generated_at=pack.generated_at,
        created_by=current_user.id,
    )
    for item in persistable:
        snapshot.evidence_links.append(
            ClientIntelligenceEvidenceLink(
                org_id=org_id,
                project_id=project_id,
                source_agent=item.source_agent.value,
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                visibility=item.visibility.value,
                observed_at=item.observed_at,
                claim_keys=list(item.claim_keys),
                description=item.description,
                source_fingerprint=pack.source_fingerprint,
            )
        )
    return snapshot


async def persist_client_evidence_snapshot(
    session: AsyncSession,
    pack: ClientEvidencePack,
    *,
    current_user: CurrentUser,
    org_id: UUID,
    project_id: UUID,
) -> ClientIntelligenceSnapshot:
    """Validate and append-only persist a ClientEvidencePack + evidence links.

    Uses a nested transaction (SAVEPOINT). Never commits the outer transaction.
    Concurrent unique-key races are resolved by re-querying after rolling back
    only the savepoint.
    """
    _assert_pack_identity(pack, org_id=org_id, project_id=project_id)
    await _assert_can_persist(
        session, current_user=current_user, org_id=org_id, project_id=project_id
    )

    validation = validate_client_evidence_pack(pack, role=current_user.role)
    if not validation.is_valid:
        raise EvidencePackIntegrityError(validation)

    if pack.visibility_mode == EvidenceVisibility.CLIENT_SAFE:
        for item in pack.evidence:
            if item.visibility != EvidenceVisibility.CLIENT_SAFE:
                raise ApiError(
                    409,
                    "EVIDENCE_VISIBILITY_INVALID",
                    "CLIENT_SAFE packs cannot include internal evidence references.",
                )

    persistable = persistable_evidence_references(pack)
    require_evidence(
        [
            EvidenceInput(
                source_table=item.source_table,
                source_row_id=item.source_row_id,
                description=item.description,
            )
            for item in persistable
        ]
    )

    existing = await find_client_evidence_snapshot(
        session, pack, org_id=org_id, project_id=project_id
    )
    if existing is not None:
        return _verify_existing_snapshot(
            existing,
            pack,
            persistable,
            role=current_user.role,
        )

    snapshot = _build_snapshot_entity(
        pack,
        persistable,
        current_user=current_user,
        org_id=org_id,
        project_id=project_id,
    )

    try:
        async with session.begin_nested():
            session.add(snapshot)
            await session.flush()
    except IntegrityError as exc:
        if not _is_idempotency_conflict(exc):
            raise
        raced = await find_client_evidence_snapshot(
            session, pack, org_id=org_id, project_id=project_id
        )
        if raced is None:
            raise
        return _verify_existing_snapshot(
            raced,
            pack,
            persistable,
            role=current_user.role,
        )

    return snapshot
