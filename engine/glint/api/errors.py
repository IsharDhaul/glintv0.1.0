"""The §5.5 error model: expected states return `{error: CODE, message, build_id}`."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from glint.api.build import BuildUnavailableError
from glint.api.deps import response_build_id
from glint.contracts.api import ErrorCode, ErrorResponse
from glint.core.log import get_logger
from glint.screen.validate import InvalidScreenError

log = get_logger(__name__)


class ApiError(Exception):
    def __init__(
        self, status: int, code: ErrorCode, message: str, path: list[str | int] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.path = path


PRESET_BODY_HINT = (
    "This looks like a whole preset: POST its `screen` object (`.preset.screen`), not the preset"
)
DISCRIMINATOR_TAGS = frozenset({"condition", "group"})  # pydantic union tags, not Screen fields


def not_implemented(worktree: str) -> ApiError:
    return ApiError(501, ErrorCode.NOT_IMPLEMENTED, f"Not implemented yet ({worktree})")


def validation_path(
    errors: list[dict[str, Any]], drop: frozenset[str] = frozenset()
) -> list[str | int]:
    """The first pydantic error's location, without union tags (and any `drop` prefixes)."""
    first: dict[str, Any] = errors[0] if errors else {}
    return [p for p in first.get("loc", ()) if p not in drop and p not in DISCRIMINATOR_TAGS]


def request_build_id(request: Request) -> str | None:
    return response_build_id(request)


def error_json(request: Request, status: int, body: ErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _error(
    request: Request,
    status: int,
    code: ErrorCode,
    message: str,
    *,
    path: list[str | int] | None = None,
    build_id: str | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        build_id=build_id if build_id is not None else request_build_id(request),
        error=code,
        message=message,
        path=path,
    )
    return error_json(request, status, body)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _error(request, exc.status, exc.code, exc.message, path=exc.path)

    @app.exception_handler(BuildUnavailableError)
    async def _no_build(request: Request, exc: BuildUnavailableError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _error(request, 503, exc.error_code, exc.message, build_id=exc.build_id)

    @app.exception_handler(InvalidScreenError)
    async def _invalid_screen(request: Request, exc: InvalidScreenError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        path = list(exc.issues[0].path) if exc.issues else None
        return _error(request, 422, ErrorCode.INVALID_SCREEN, exc.message, path=path)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        codes = {404: ErrorCode.NOT_FOUND, 405: ErrorCode.METHOD_NOT_ALLOWED}
        code = codes.get(exc.status_code, ErrorCode.INVALID_REQUEST)
        return _error(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        errors: list[dict[str, Any]] = list(exc.errors())
        message = str(errors[0].get("msg", "invalid request")) if errors else "invalid request"
        is_screen = request.url.path.startswith("/api/screen")
        body: object = exc.body
        if is_screen and isinstance(body, dict) and "screen" in body:
            message = PRESET_BODY_HINT
        code = ErrorCode.INVALID_SCREEN if is_screen else ErrorCode.INVALID_REQUEST
        path = validation_path(errors, frozenset({"body"}))
        return _error(request, 422, code, message, path=path)

    @app.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        log.exception("unhandled_error", extra={"path": request.url.path})
        return _error(request, 500, ErrorCode.INTERNAL, "internal error")
