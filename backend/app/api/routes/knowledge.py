from datetime import date
import json
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.api.deps import ExplicitUserActionDep, SessionDep
from app.core.constants import SUPPORTED_KNOWLEDGE_EXTENSIONS
from app.core.exceptions import ApiError
from app.core.security import CurrentUser, require_role
from app.db.rls import set_rls_context
from app.db.session import AsyncSessionLocal
from app.db.models import AppRole
from app.db.models.entities import (
    KnowledgeDocumentStatus,
    KnowledgeFolderKind,
    KnowledgeSourceType,
    KnowledgeVisibility,
)
from app.schemas.common import DataResponse, ListResponse, Pagination
from app.schemas.domain import (
    KnowledgeAskCreate,
    KnowledgeAskRead,
    KnowledgeBootstrapRead,
    KnowledgeConversationRead,
    KnowledgeConversationSummaryRead,
    KnowledgeDocumentAiSummaryRead,
    KnowledgeDocumentApprovalEventRead,
    KnowledgeDocumentLifecycleAction,
    KnowledgeDocumentRead,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentVersionRead,
    KnowledgeDuplicateCompareRead,
    KnowledgeDuplicateMatchRead,
    KnowledgeEvaluationReportRead,
    KnowledgeFeedbackCreate,
    KnowledgeFeedbackRead,
    KnowledgeFolderCreate,
    KnowledgeFolderRead,
    KnowledgeGapSuggestionRead,
    KnowledgeDocumentIngestionAcceptedRead,
    KnowledgeHealthScoreRead,
    KnowledgeIngestionProgressRead,
    KnowledgeLibraryHealthRead,
    KnowledgeRelatedKnowledgeRead,
    KnowledgeRetrievalQualityRead,
    KnowledgeRetrievalSettingsRead,
    KnowledgeRetrievalSettingsUpdate,
    KnowledgeSuggestionRead,
    KnowledgeVersionCompareRead,
)
from app.services.knowledge import (
    apply_knowledge_suggestion,
    approve_document,
    archive_document,
    ask_knowledge_agent,
    compare_document_versions,
    compare_duplicate_documents,
    create_document_from_upload,
    create_knowledge_folder_by_name,
    delete_document,
    dismiss_knowledge_suggestion,
    generate_content_suggestions,
    generate_document_ai_summary,
    get_document,
    get_document_file_download,
    get_gap_resolution_suggestions,
    get_knowledge_bootstrap,
    get_knowledge_conversation,
    get_knowledge_health_score,
    get_knowledge_library_health,
    get_knowledge_query_answer,
    get_related_knowledge_for_document,
    get_retrieval_quality_analysis,
    get_retrieval_settings,
    list_document_approval_history,
    list_document_duplicates,
    list_document_versions,
    list_documents,
    list_knowledge_conversations,
    list_knowledge_folders,
    list_knowledge_suggestions,
    record_knowledge_feedback,
    reject_document,
    reindex_document,
    restore_document,
    return_document_to_draft,
    prepare_stream_knowledge_ask,
    run_knowledge_evaluation_report,
    stream_prepared_knowledge_ask,
    submit_document_for_review,
    update_document,
    update_retrieval_settings,
)
from app.services.knowledge_ingestion_jobs import (
    dispatch_knowledge_ingestion_job,
    enqueue_knowledge_ingestion_job,
    get_document_ingestion_progress,
)

router = APIRouter(tags=["knowledge"])

MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
}


def _parse_enum(value: str, enum_cls, field_name: str):
    try:
        return enum_cls(value)
    except ValueError as exc:
        from app.core.exceptions import ApiError

        raise ApiError(400, "VALIDATION_ERROR", f"Invalid {field_name}.") from exc


@router.get("/knowledge/bootstrap", response_model=DataResponse[KnowledgeBootstrapRead])
async def knowledge_bootstrap(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeBootstrapRead]:
    data = await get_knowledge_bootstrap(session, current_user)
    await session.commit()
    return DataResponse(data=data)


@router.get("/knowledge/library-health", response_model=DataResponse[KnowledgeLibraryHealthRead])
async def knowledge_library_health(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeLibraryHealthRead]:
    row = await get_knowledge_library_health(session, current_user)
    await session.commit()
    return DataResponse(data=row)


@router.get("/knowledge/folders", response_model=ListResponse[KnowledgeFolderRead])
async def list_knowledge_folders_route(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[KnowledgeFolderRead]:
    folders = await list_knowledge_folders(session, current_user.org_id)
    return ListResponse(
        data=[
            KnowledgeFolderRead(
                id=folder.id,
                name=folder.name,
                folder_kind=folder.folder_kind.value,
                display_order=folder.display_order,
            )
            for folder in folders
        ],
        pagination=Pagination(limit=len(folders)),
    )


@router.post("/knowledge/folders", response_model=DataResponse[KnowledgeFolderRead])
async def create_knowledge_folder_route(
    payload: KnowledgeFolderCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeFolderRead]:
    folder = await create_knowledge_folder_by_name(
        session,
        current_user.org_id,
        name=payload.name,
    )
    await session.commit()
    return DataResponse(
        data=KnowledgeFolderRead(
            id=folder.id,
            name=folder.name,
            folder_kind=folder.folder_kind.value,
            display_order=folder.display_order,
        )
    )


@router.get("/knowledge/documents", response_model=ListResponse[KnowledgeDocumentRead])
async def list_knowledge_documents(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    source_type: str | None = None,
    owner: str | None = None,
    visibility: str | None = None,
    ready: bool | None = None,
    workflow_state: str | None = None,
    effective_date_from: date | None = None,
    effective_date_to: date | None = None,
    semantic_query: str | None = None,
    ai_rank: bool = False,
    user_action: str | None = Header(default=None, alias="X-BSG-User-Action"),
) -> ListResponse[KnowledgeDocumentRead]:
    if ai_rank and user_action != "true":
        raise ApiError(400, "USER_ACTION_REQUIRED", "AI document ranking requires an explicit user action.")
    rows = await list_documents(
        session,
        current_user,
        source_type=source_type,
        owner=owner,
        visibility=visibility,
        ready=ready,
        workflow_state=workflow_state,
        effective_date_from=effective_date_from,
        effective_date_to=effective_date_to,
        semantic_query=semantic_query,
        ai_rank=ai_rank,
    )
    await session.commit()
    return ListResponse(data=rows, pagination=Pagination(limit=len(rows)))


@router.get("/knowledge/documents/{document_id}", response_model=DataResponse[KnowledgeDocumentRead])
async def get_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeDocumentRead]:
    row = await get_document(session, current_user, document_id)
    await session.commit()
    return DataResponse(data=row)


@router.get("/knowledge/documents/{document_id}/download")
async def download_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> Response:
    file_bytes, file_name, media_type = await get_document_file_download(session, current_user, document_id)
    await session.commit()
    safe_name = quote(file_name)
    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@router.post(
    "/knowledge/documents",
    response_model=DataResponse[KnowledgeDocumentIngestionAcceptedRead],
    status_code=202,
)
async def upload_knowledge_document(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    file: UploadFile = File(...),
    title: str = Form(...),
    folder_id: str | None = Form(None),
    folder_kind: str | None = Form(None),
    source_type: str = Form(...),
    version: str = Form("v1.0"),
    visibility: str = Form("internal_only"),
    status: str = Form("draft"),
    owner_approver: str = Form(...),
    description: str | None = Form(None),
    approver: str | None = Form(None),
    project: str | None = Form(None),
    department: str | None = Form(None),
    effective_date: date | None = Form(None),
) -> DataResponse[KnowledgeDocumentIngestionAcceptedRead]:
    file_name = file.filename or "document.txt"
    suffix = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if suffix not in SUPPORTED_KNOWLEDGE_EXTENSIONS:
        raise ApiError(400, "VALIDATION_ERROR", "Unsupported file type. Use PDF, DOCX, TXT, MD, or CSV.")
    file_bytes = await file.read()
    if not file_bytes:
        raise ApiError(400, "VALIDATION_ERROR", "Uploaded file is empty.")
    if not title.strip() or not owner_approver.strip():
        raise ApiError(400, "VALIDATION_ERROR", "Document title and owner/approver are required.")
    if not folder_id and not folder_kind:
        raise ApiError(400, "VALIDATION_ERROR", "A target folder is required.")

    resolved_folder_id = UUID(folder_id) if folder_id else None
    resolved_folder_kind = _parse_enum(folder_kind, KnowledgeFolderKind, "folder") if folder_kind else None

    row = await create_document_from_upload(
        session,
        current_user,
        folder_id=resolved_folder_id,
        folder_kind=resolved_folder_kind,
        title=title,
        source_type=_parse_enum(source_type, KnowledgeSourceType, "source type"),
        version=version,
        visibility=_parse_enum(visibility, KnowledgeVisibility, "visibility"),
        status=_parse_enum(status, KnowledgeDocumentStatus, "status"),
        owner_approver=owner_approver,
        description=description,
        approver=approver,
        project=project,
        department=department,
        effective_date=effective_date,
        file_name=file_name,
        file_mime_type=file.content_type or MIME_BY_EXT.get(suffix, "application/octet-stream"),
        file_bytes=file_bytes,
    )
    if row.active_version_id is None:
        raise ApiError(500, "INTERNAL_ERROR", "Uploaded document is missing an active version.")
    job = await enqueue_knowledge_ingestion_job(session, row.id, row.active_version_id)
    await session.commit()
    dispatch_knowledge_ingestion_job(session, job.id)
    return DataResponse(
        data=KnowledgeDocumentIngestionAcceptedRead(job_id=job.id, document=row),
    )


@router.patch("/knowledge/documents/{document_id}", response_model=DataResponse[KnowledgeDocumentRead])
async def patch_knowledge_document(
    document_id: UUID,
    payload: KnowledgeDocumentUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeDocumentRead]:
    row = await update_document(session, current_user, document_id, payload)
    await session.commit()
    return DataResponse(data=row)


@router.get("/knowledge/documents/{document_id}/approval-history", response_model=ListResponse[KnowledgeDocumentApprovalEventRead])
async def get_knowledge_document_approval_history(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[KnowledgeDocumentApprovalEventRead]:
    rows = await list_document_approval_history(session, current_user, document_id)
    return ListResponse(data=rows, pagination=Pagination(items=len(rows), total=len(rows)))


@router.post("/knowledge/documents/{document_id}/submit", response_model=DataResponse[KnowledgeDocumentRead])
async def submit_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    payload: KnowledgeDocumentLifecycleAction | None = None,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeDocumentRead]:
    row = await submit_document_for_review(session, current_user, document_id, payload)
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/documents/{document_id}/approve", response_model=DataResponse[KnowledgeDocumentRead])
async def approve_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    payload: KnowledgeDocumentLifecycleAction | None = None,
    current_user: CurrentUser = Depends(require_role(AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeDocumentRead]:
    row = await approve_document(session, current_user, document_id, payload)
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/documents/{document_id}/reject", response_model=DataResponse[KnowledgeDocumentRead])
async def reject_knowledge_document(
    document_id: UUID,
    payload: KnowledgeDocumentLifecycleAction,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeDocumentRead]:
    row = await reject_document(session, current_user, document_id, payload)
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/documents/{document_id}/return-to-draft", response_model=DataResponse[KnowledgeDocumentRead])
async def return_knowledge_document_to_draft(
    document_id: UUID,
    session: SessionDep,
    payload: KnowledgeDocumentLifecycleAction | None = None,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeDocumentRead]:
    row = await return_document_to_draft(session, current_user, document_id, payload)
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/documents/{document_id}/archive", response_model=DataResponse[KnowledgeDocumentRead])
async def archive_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    payload: KnowledgeDocumentLifecycleAction | None = None,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeDocumentRead]:
    row = await archive_document(session, current_user, document_id, payload)
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/documents/{document_id}/restore", response_model=DataResponse[KnowledgeDocumentRead])
async def restore_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    payload: KnowledgeDocumentLifecycleAction | None = None,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeDocumentRead]:
    row = await restore_document(session, current_user, document_id, payload)
    await session.commit()
    return DataResponse(data=row)


@router.delete("/knowledge/documents/{document_id}", status_code=204)
async def delete_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> None:
    await delete_document(session, current_user, document_id)
    await session.commit()


@router.post(
    "/knowledge/documents/{document_id}/index",
    response_model=DataResponse[KnowledgeDocumentIngestionAcceptedRead],
    status_code=202,
)
async def index_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[KnowledgeDocumentIngestionAcceptedRead]:
    row = await reindex_document(session, current_user, document_id)
    if row.active_version_id is None:
        raise ApiError(500, "INTERNAL_ERROR", "Re-indexed document is missing an active version.")
    job = await enqueue_knowledge_ingestion_job(session, row.id, row.active_version_id)
    await session.commit()
    dispatch_knowledge_ingestion_job(session, job.id)
    return DataResponse(
        data=KnowledgeDocumentIngestionAcceptedRead(job_id=job.id, document=row),
    )


@router.post(
    "/knowledge/documents/{document_id}/reindex",
    response_model=DataResponse[KnowledgeDocumentIngestionAcceptedRead],
    status_code=202,
)
async def reindex_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[KnowledgeDocumentIngestionAcceptedRead]:
    return await index_knowledge_document(document_id, session, current_user, _user_action)


@router.get("/knowledge/documents/{document_id}/progress", response_model=DataResponse[KnowledgeIngestionProgressRead])
async def get_knowledge_document_progress(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeIngestionProgressRead]:
    row = await get_document_ingestion_progress(session, document_id, current_user=current_user)
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/ask", response_model=DataResponse[KnowledgeAskRead])
async def ask_knowledge(
    payload: KnowledgeAskCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[KnowledgeAskRead]:
    org_settings = await get_retrieval_settings(session, current_user.org_id)
    row = await ask_knowledge_agent(
        session,
        current_user,
        payload.query_text.strip(),
        conversation_history=payload.conversation_history,
        answer_mode=payload.answer_mode,
        include_histories=payload.include_histories if payload.include_histories is not None else org_settings.include_histories,
        max_sources=payload.max_sources or org_settings.max_sources,
        max_candidates=org_settings.max_candidates,
        min_relevance_score=payload.min_relevance_score if payload.min_relevance_score is not None else org_settings.min_relevance,
        project=payload.project or org_settings.project,
        department=payload.department or org_settings.department,
        folder_id=payload.folder_id,
        folder_ids=None if payload.folder_id else org_settings.folder_ids,
        source_type=payload.source_type,
        source_types=None if payload.source_type else org_settings.source_types,
        effective_date_from=payload.effective_date_from,
        effective_date_to=payload.effective_date_to,
        only_approved=True,
        conversation_id=payload.conversation_id,
    )
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/ask/stream")
async def stream_knowledge(
    payload: KnowledgeAskCreate,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    _user_action: ExplicitUserActionDep = None,
) -> StreamingResponse:
    query_text = payload.query_text.strip()

    async def _generate():
        async with AsyncSessionLocal() as prep_session:
            await set_rls_context(prep_session, json.dumps({"sub": str(current_user.id)}))
            org_settings = await get_retrieval_settings(prep_session, current_user.org_id)
            include_histories = (
                payload.include_histories if payload.include_histories is not None else org_settings.include_histories
            )
            max_sources = payload.max_sources or org_settings.max_sources
            max_candidates = org_settings.max_candidates
            min_relevance_score = (
                payload.min_relevance_score
                if payload.min_relevance_score is not None
                else org_settings.min_relevance
            )
            project = payload.project or org_settings.project
            department = payload.department or org_settings.department
            early_events, prepared = await prepare_stream_knowledge_ask(
                prep_session,
                current_user,
                query_text,
                conversation_history=payload.conversation_history,
                answer_mode=payload.answer_mode,
                include_histories=include_histories,
                max_sources=max_sources,
                max_candidates=max_candidates,
                min_relevance_score=min_relevance_score,
                project=project,
                department=department,
                folder_id=payload.folder_id,
                folder_ids=None if payload.folder_id else org_settings.folder_ids,
                source_type=payload.source_type,
                source_types=None if payload.source_type else org_settings.source_types,
                effective_date_from=payload.effective_date_from,
                effective_date_to=payload.effective_date_to,
                only_approved=True,
                conversation_id=payload.conversation_id,
            )
            await prep_session.commit()
        for chunk in early_events:
            yield chunk
        if prepared is not None:
            async for chunk in stream_prepared_knowledge_ask(prepared):
                yield chunk

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/knowledge/feedback", response_model=DataResponse[KnowledgeFeedbackRead])
async def submit_knowledge_feedback(
    payload: KnowledgeFeedbackCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeFeedbackRead]:
    row = await record_knowledge_feedback(
        session,
        current_user,
        query_id=payload.query_id,
        rating=payload.rating,
        comment=payload.comment,
        feedback_reason=payload.feedback_reason,
    )
    await session.commit()
    return DataResponse(data=row)


@router.get("/knowledge/queries/{query_id}", response_model=DataResponse[KnowledgeAskRead])
async def get_knowledge_query(
    query_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeAskRead]:
    row = await get_knowledge_query_answer(session, current_user, query_id)
    await session.commit()
    return DataResponse(data=row)


@router.get("/knowledge/conversations", response_model=ListResponse[KnowledgeConversationSummaryRead])
async def list_knowledge_conversation_history(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    limit: int = Query(default=30, ge=1, le=100),
) -> ListResponse[KnowledgeConversationSummaryRead]:
    rows = await list_knowledge_conversations(session, current_user, limit=limit)
    await session.commit()
    return ListResponse(data=rows, pagination=Pagination(limit=limit))


@router.get("/knowledge/conversations/{conversation_id}", response_model=DataResponse[KnowledgeConversationRead])
async def get_knowledge_conversation_history(
    conversation_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeConversationRead]:
    row = await get_knowledge_conversation(session, current_user, conversation_id)
    await session.commit()
    return DataResponse(data=row)


@router.get("/knowledge/documents/{document_id}/versions", response_model=ListResponse[KnowledgeDocumentVersionRead])
async def get_knowledge_document_versions(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[KnowledgeDocumentVersionRead]:
    rows = await list_document_versions(session, current_user, document_id)
    await session.commit()
    return ListResponse(data=rows, pagination=Pagination(limit=len(rows)))


@router.get("/knowledge/documents/{document_id}/versions/compare", response_model=DataResponse[KnowledgeVersionCompareRead])
async def compare_knowledge_document_versions(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    left_version_id: UUID = Query(...),
    right_version_id: UUID = Query(...),
) -> DataResponse[KnowledgeVersionCompareRead]:
    row = await compare_document_versions(session, current_user, document_id, left_version_id, right_version_id)
    await session.commit()
    return DataResponse(data=row)


@router.get("/knowledge/retrieval-settings", response_model=DataResponse[KnowledgeRetrievalSettingsRead])
async def read_knowledge_retrieval_settings(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeRetrievalSettingsRead]:
    row = await get_retrieval_settings(session, current_user.org_id)
    await session.commit()
    return DataResponse(data=row)


@router.patch("/knowledge/retrieval-settings", response_model=DataResponse[KnowledgeRetrievalSettingsRead])
async def patch_knowledge_retrieval_settings(
    payload: KnowledgeRetrievalSettingsUpdate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeRetrievalSettingsRead]:
    row = await update_retrieval_settings(session, current_user, payload)
    await session.commit()
    return DataResponse(data=row)


@router.get("/knowledge/health-score", response_model=DataResponse[KnowledgeHealthScoreRead])
async def knowledge_health_score(
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> DataResponse[KnowledgeHealthScoreRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    return DataResponse(data=await get_knowledge_health_score(session, current_user))


@router.get("/knowledge/suggestions", response_model=ListResponse[KnowledgeSuggestionRead])
async def knowledge_list_suggestions(
    session: SessionDep,
    status: str | None = Query(default=None),
    document_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> ListResponse[KnowledgeSuggestionRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    rows = await list_knowledge_suggestions(session, current_user, status=status, document_id=document_id)
    return ListResponse(data=rows, pagination=Pagination(total=len(rows), limit=len(rows), offset=0))


@router.post("/knowledge/suggestions/generate", response_model=ListResponse[KnowledgeSuggestionRead])
async def knowledge_generate_suggestions(
    session: SessionDep,
    document_id: UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> ListResponse[KnowledgeSuggestionRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    rows = await generate_content_suggestions(session, current_user, document_id=document_id)
    await session.commit()
    return ListResponse(data=rows, pagination=Pagination(total=len(rows), limit=len(rows), offset=0))


@router.post("/knowledge/suggestions/{suggestion_id}/apply", response_model=DataResponse[KnowledgeSuggestionRead])
async def knowledge_apply_suggestion(
    suggestion_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> DataResponse[KnowledgeSuggestionRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    row = await apply_knowledge_suggestion(session, current_user, suggestion_id)
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/suggestions/{suggestion_id}/dismiss", response_model=DataResponse[KnowledgeSuggestionRead])
async def knowledge_dismiss_suggestion(
    suggestion_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> DataResponse[KnowledgeSuggestionRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    row = await dismiss_knowledge_suggestion(session, current_user, suggestion_id)
    await session.commit()
    return DataResponse(data=row)


@router.get("/knowledge/gaps/suggestions", response_model=ListResponse[KnowledgeGapSuggestionRead])
async def knowledge_gap_suggestions(
    session: SessionDep,
    min_occurrences: int = Query(default=2, ge=1, le=50),
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> ListResponse[KnowledgeGapSuggestionRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    rows = await get_gap_resolution_suggestions(session, current_user, min_occurrences=min_occurrences)
    await session.commit()
    return ListResponse(data=rows, pagination=Pagination(total=len(rows), limit=len(rows), offset=0))


@router.get("/knowledge/retrieval-quality", response_model=DataResponse[KnowledgeRetrievalQualityRead])
async def knowledge_retrieval_quality(
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> DataResponse[KnowledgeRetrievalQualityRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    return DataResponse(data=await get_retrieval_quality_analysis(session, current_user))


@router.get(
    "/knowledge/documents/{document_id}/duplicates",
    response_model=ListResponse[KnowledgeDuplicateMatchRead],
)
async def knowledge_document_duplicates(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> ListResponse[KnowledgeDuplicateMatchRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    rows = await list_document_duplicates(session, current_user, document_id)
    return ListResponse(data=rows, pagination=Pagination(total=len(rows), limit=len(rows), offset=0))


@router.get("/knowledge/duplicates/compare", response_model=DataResponse[KnowledgeDuplicateCompareRead])
async def knowledge_duplicates_compare(
    session: SessionDep,
    left_id: UUID = Query(...),
    right_id: UUID = Query(...),
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> DataResponse[KnowledgeDuplicateCompareRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    return DataResponse(data=await compare_duplicate_documents(session, current_user, left_id, right_id))


@router.post(
    "/knowledge/documents/{document_id}/summary",
    response_model=DataResponse[KnowledgeDocumentAiSummaryRead],
)
async def knowledge_generate_summary(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> DataResponse[KnowledgeDocumentAiSummaryRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    row = await generate_document_ai_summary(session, current_user, document_id)
    await session.commit()
    return DataResponse(data=row)


@router.get(
    "/knowledge/documents/{document_id}/related",
    response_model=DataResponse[KnowledgeRelatedKnowledgeRead],
)
async def knowledge_related_documents(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> DataResponse[KnowledgeRelatedKnowledgeRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    return DataResponse(data=await get_related_knowledge_for_document(session, current_user, document_id))


@router.post("/knowledge/evaluation/run", response_model=DataResponse[KnowledgeEvaluationReportRead])
async def knowledge_run_evaluation(
    session: SessionDep,
    current_user: CurrentUser = Depends(
        require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)
    ),
) -> DataResponse[KnowledgeEvaluationReportRead]:
    await set_rls_context(session, json.dumps({"sub": str(current_user.id)}))
    return DataResponse(data=await run_knowledge_evaluation_report(session, current_user))
