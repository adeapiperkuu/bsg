import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

logger = logging.getLogger(__name__)


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(status_code=status_code, detail=message)


def error_response(status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "VALIDATION_ERROR", "Request validation failed.", {"errors": exc.errors()})

    @app.exception_handler(OperationalError)
    @app.exception_handler(DBAPIError)
    async def handle_database_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Database error")
        message = "Database is temporarily unavailable. Please try again."
        detail = str(getattr(exc, "orig", exc)).lower()
        if "emaxconnsession" in detail or "max clients reached" in detail:
            message = "Database connection limit reached. Restart the backend or use the transaction pooler (port 6543)."
        return error_response(503, "DATABASE_UNAVAILABLE", message)

    @app.exception_handler(ProgrammingError)
    async def handle_programming_error(_: Request, exc: ProgrammingError) -> JSONResponse:
        logger.exception("Database schema error")
        detail = str(getattr(exc, "orig", exc)).lower()
        if "does not exist" in detail:
            return error_response(
                503,
                "SCHEMA_NOT_READY",
                "A required database table is missing. Apply pending Supabase migrations and try again.",
            )
        return error_response(500, "DATABASE_ERROR", "A database query failed.")
    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        _ = exc
        return error_response(500, "INTERNAL_SERVER_ERROR", "An unexpected server error occurred.")
