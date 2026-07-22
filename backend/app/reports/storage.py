"""Report artifact storage adapters."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import UUID

import httpx

from app.core.config import get_settings

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_component(value: str, name: str) -> str:
    if not value or value in {".", ".."} or not _SAFE_COMPONENT.fullmatch(value):
        raise ValueError(f"Unsafe {name}.")
    return value


def report_object_path(
    org_id: UUID,
    report_id: UUID,
    format_: str,
    filename: str,
) -> str:
    safe_format = _validate_component(format_.lower(), "format")
    safe_filename = _validate_component(Path(filename).name, "filename")
    if safe_filename != filename or "/" in filename or "\\" in filename:
        raise ValueError("Report filename must not contain path components.")
    path = PurePosixPath(str(org_id), str(report_id), safe_format, safe_filename)
    if ".." in path.parts:
        raise ValueError("Report storage path traversal is not allowed.")
    return path.as_posix()


async def _store_local(object_path: str, content: bytes) -> str:
    root = Path(get_settings().report_export_dir).resolve()
    destination = (root / Path(*PurePosixPath(object_path).parts)).resolve()
    if root != destination and root not in destination.parents:
        raise ValueError("Report storage path escapes configured export directory.")

    def write() -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    await asyncio.to_thread(write)
    return object_path


async def _store_supabase(object_path: str, content: bytes, content_type: str) -> str:
    settings = get_settings()
    bucket = _validate_component(settings.report_storage_bucket, "storage bucket")
    key = settings.supabase_service_role_key
    url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{quote(bucket, safe='')}/{quote(object_path, safe='/')}"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            content=content,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
        )
        response.raise_for_status()
    return object_path


async def store_report_bytes(
    *,
    org_id: UUID,
    report_id: UUID,
    format_: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[str, str]:
    """Store bytes and return ``(backend, object_path)``."""
    object_path = report_object_path(org_id, report_id, format_, filename)
    backend = get_settings().report_storage_backend.lower()
    if backend == "local":
        return backend, await _store_local(object_path, content)
    if backend == "supabase":
        return backend, await _store_supabase(object_path, content, content_type)
    raise ValueError("report_storage_backend must be 'local' or 'supabase'.")


async def load_report_bytes(*, storage_backend: str, storage_path: str) -> bytes:
    """Load previously stored report bytes with path-traversal guards."""
    if ".." in PurePosixPath(storage_path).parts:
        raise ValueError("Report storage path traversal is not allowed.")
    if storage_backend == "local":
        root = Path(get_settings().report_export_dir).resolve()
        destination = (root / Path(*PurePosixPath(storage_path).parts)).resolve()
        if root != destination and root not in destination.parents:
            raise ValueError("Report storage path escapes configured export directory.")
        return await asyncio.to_thread(destination.read_bytes)
    if storage_backend == "supabase":
        settings = get_settings()
        bucket = _validate_component(settings.report_storage_bucket, "storage bucket")
        key = settings.supabase_service_role_key
        url = (
            f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
            f"{quote(bucket, safe='')}/{quote(storage_path, safe='/')}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            response.raise_for_status()
            return response.content
    raise ValueError("Unknown report storage backend.")
