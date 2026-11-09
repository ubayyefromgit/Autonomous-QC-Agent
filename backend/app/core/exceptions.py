"""Domain and API exception hierarchy for the QC Intelligence Platform."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from backend.app.domain.entities.state_machines import InvalidStateTransitionError


class QCPlatformError(Exception):
    """Base exception for all QC Platform errors."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str = "QC_PLATFORM_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}


class EntityNotFoundError(QCPlatformError):
    def __init__(self, entity: str, identifier: Any) -> None:
        super().__init__(
            message=f"{entity} '{identifier}' was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="ENTITY_NOT_FOUND",
            details={"entity": entity, "id": str(identifier)},
        )


class AuthorizationError(QCPlatformError):
    def __init__(self, message: str = "Insufficient permissions for this operation.") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="FORBIDDEN",
        )


class SecurityPolicyViolationError(QCPlatformError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="SECURITY_POLICY_VIOLATION",
            details=details,
        )


class ApprovalIntegrityError(QCPlatformError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code="APPROVAL_INTEGRITY_ERROR",
            details=details,
        )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(QCPlatformError)
    async def handle_qc_error(_request: Request, exc: QCPlatformError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(InvalidStateTransitionError)
    async def handle_state_transition_error(
        _request: Request, exc: InvalidStateTransitionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "INVALID_STATE_TRANSITION",
                "message": str(exc),
                "details": {},
            },
        )
