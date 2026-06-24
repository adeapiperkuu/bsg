from datetime import date
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from app.api.deps import SessionDep
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
    KnowledgeDocumentRead,
    KnowledgeDocumentUpdate,
    KnowledgeFolderRead,
)
from app.services.knowledge import (
    ask_knowledge_agent,
    create_document_from_upload,
    delete_document,
    ensure_knowledge_folders,
    get_document,
    get_document_file_download,
    list_documents,
    reindex_document,
    update_document,
)

router = APIRouter(tags=["knowledge"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}
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


@router.get("/knowledge/folders", response_model=ListResponse[KnowledgeFolderRead])
async def list_knowledge_folders(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[KnowledgeFolderRead]:
    folders = await ensure_knowledge_folders(session, current_user.org_id)
    await session.commit()
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


@router.get("/knowledge/documents", response_model=ListResponse[KnowledgeDocumentRead])
async def list_knowledge_documents(
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> ListResponse[KnowledgeDocumentRead]:
    rows = await list_documents(session, current_user)
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
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
    file: UploadFile = File(...),
    title: str = Form(...),
    folder_kind: str = Form(...),
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
    if suffix not in ALLOWED_EXTENSIONS:
        raise ApiError(400, "VALIDATION_ERROR", "Unsupported file type. Use PDF, DOCX, TXT, MD, or CSV.")
    file_bytes = await file.read()
    if not file_bytes:
        raise ApiError(400, "VALIDATION_ERROR", "Uploaded file is empty.")
    if not title.strip() or not owner_approver.strip():
        raise ApiError(400, "VALIDATION_ERROR", "Document title and owner/approver are required.")

    row = await create_document_from_upload(
        session,
        current_user,
        folder_kind=_parse_enum(folder_kind, KnowledgeFolderKind, "folder"),
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
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeDocumentRead]:
    row = await reindex_document(session, current_user, document_id)
    await session.commit()
    return DataResponse(data=row)


@router.post("/knowledge/ask", response_model=DataResponse[KnowledgeAskRead])
async def ask_knowledge(
    payload: KnowledgeAskCreate,
    session: SessionDep,
    current_user: CurrentUser = Depends(require_role(AppRole.DELIVERY_MANAGER, AppRole.BSG_LEADERSHIP, AppRole.SUPER_ADMIN)),
) -> DataResponse[KnowledgeAskRead]:
    row = await ask_knowledge_agent(session, current_user, payload.query_text.strip())
    await session.commit()
    return DataResponse(data=row)
