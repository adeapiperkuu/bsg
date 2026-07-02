from datetime import date
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.api.deps import ExplicitUserActionDep, SessionDep
from app.core.constants import SUPPORTED_KNOWLEDGE_EXTENSIONS
from app.core.exceptions import ApiError
from app.core.security import CurrentUser, require_role
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
    KnowledgeDocumentRead,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentVersionRead,
    KnowledgeFeedbackCreate,
    KnowledgeFeedbackRead,
    KnowledgeFolderCreate,
    KnowledgeFolderRead,
    KnowledgeGapTodoRead,
    KnowledgeLibraryHealthRead,
    KnowledgeLessonCreate,
    KnowledgeLessonRead,
    KnowledgeRetrievalSettingsRead,
    KnowledgeRetrievalSettingsUpdate,
    KnowledgeVersionCompareRead,
)
from app.services.knowledge import (
    ask_knowledge_agent,
    compare_document_versions,
    create_document_from_upload,
    create_knowledge_folder_by_name,
    create_lesson,
    delete_document,
    get_document,
    get_document_file_download,
    get_knowledge_bootstrap,
    get_knowledge_library_health,
    get_knowledge_query_answer,
    get_retrieval_settings,
    list_document_versions,
    list_documents,
    list_knowledge_folders,
    list_lessons,
    process_knowledge_document_job,
    record_knowledge_feedback,
    reindex_document,
    resolve_knowledge_gap,
    stream_knowledge_ask,
    update_document,
    update_retrieval_settings,
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


@router.post("/knowledge/documents", response_model=DataResponse[KnowledgeDocumentRead])
async def upload_knowledge_document(
    background_tasks: BackgroundTasks,
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
) -> DataResponse[KnowledgeDocumentRead]:
    from app.core.exceptions import ApiError

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
    await session.commit()
    background_tasks.add_task(process_knowledge_document_job, row.id, row.active_version_id)
    return DataResponse(data=row)


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


@router.delete("/knowledge/documents/{document_id}", status_code=204)
async def delete_knowledge_document(
    document_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> None:
    await delete_document(session, current_user, document_id)
    await session.commit()


@router.post("/knowledge/documents/{document_id}/index", response_model=DataResponse[KnowledgeDocumentRead])
async def index_knowledge_document(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    _user_action: ExplicitUserActionDep = None,
) -> DataResponse[KnowledgeDocumentRead]:
    row = await reindex_document(session, current_user, document_id)
    await session.commit()
    background_tasks.add_task(process_knowledge_document_job, row.id, row.active_version_id)
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
        min_relevance_score=payload.min_relevance_score if payload.min_relevance_score is not None else org_settings.min_confidence,
        project=payload.project or org_settings.project,
        department=payload.department or org_settings.department,
    )
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/ask/stream")
async def stream_knowledge(
    payload: KnowledgeAskCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    _user_action: ExplicitUserActionDep = None,
) -> StreamingResponse:
    org_settings = await get_retrieval_settings(session, current_user.org_id)

    async def _generate():
        async for chunk in stream_knowledge_ask(
            session,
            current_user,
            payload.query_text.strip(),
            conversation_history=payload.conversation_history,
            answer_mode=payload.answer_mode,
            include_histories=payload.include_histories if payload.include_histories is not None else org_settings.include_histories,
            max_sources=payload.max_sources or org_settings.max_sources,
            min_relevance_score=payload.min_relevance_score if payload.min_relevance_score is not None else org_settings.min_confidence,
            project=payload.project or org_settings.project,
            department=payload.department or org_settings.department,
        ):
            yield chunk
        await session.commit()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/knowledge/gaps/{gap_id}/resolve", response_model=DataResponse[KnowledgeGapTodoRead])
async def resolve_gap(
    gap_id: UUID,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeGapTodoRead]:
    row = await resolve_knowledge_gap(session, current_user, gap_id)
    await session.commit()
    return DataResponse(data=row)


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


@router.get("/knowledge/lessons", response_model=ListResponse[KnowledgeLessonRead])
async def get_lessons(
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[KnowledgeLessonRead]:
    rows = await list_lessons(session, current_user.org_id)
    return ListResponse(
        data=[KnowledgeLessonRead.model_validate(row) for row in rows],
        pagination=Pagination(limit=len(rows)),
    )


@router.post("/knowledge/lessons", response_model=DataResponse[KnowledgeLessonRead])
async def post_lesson(
    payload: KnowledgeLessonCreate,
    session: SessionDep,
    current_user=Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeLessonRead]:
    lesson = await create_lesson(session, current_user.org_id, payload, current_user.id)
    await session.commit()
    await session.refresh(lesson)
    return DataResponse(data=KnowledgeLessonRead.model_validate(lesson))
