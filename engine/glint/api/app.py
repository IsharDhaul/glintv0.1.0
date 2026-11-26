"""FastAPI app factory. Every §5.5 router is registered here (WT-00); WT-08/12/13 fill the router
modules and never edit the router list."""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

import glint
from glint.api.build import BuildManager
from glint.api.deps import response_build_id
from glint.api.errors import install_error_handlers
from glint.api.routers import catalog, companies, health, meta, nl, saved, screen
from glint.contracts.api import ErrorResponse
from glint.core.log import get_logger, log_event

log = get_logger("glint.api.request")

# The web dev servers (ports 30NN, one per worktree; §8.5). No other origin may call the API.
CORS_ORIGIN_REGEX = r"^http://localhost:30\d\d$"
BUILD_HEADER = "X-Glint-Build-Id"

ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": ErrorResponse, "description": desc}
    for status, desc in [
        (404, "UNKNOWN_TICKER / UNKNOWN_PRESET / UNKNOWN_METRIC"),
        (422, "INVALID_SCREEN / INVALID_REQUEST, with the field path"),
        (500, "INTERNAL"),
        (501, "NOT_IMPLEMENTED"),
        (503, "NO_BUILD / SCHEMA_MISMATCH"),
    ]
}


def create_app(builds: BuildManager | None = None) -> FastAPI:
    app = FastAPI(
        title="Glint API",
        separate_input_output_schemas=False,
        version=glint.__version__,
        description=(
            "Fundamentals-first US stock screener. Educational tool. Not investment advice."
        ),
    )
    manager = builds or BuildManager()
    app.state.builds = manager
    install_error_handlers(app)
    for module in (health, meta, catalog, screen, companies, saved, nl):
        app.include_router(module.router, responses=ERROR_RESPONSES)

    @app.middleware("http")
    async def _request_log(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        build_id = response_build_id(request)
        if build_id is not None:
            response.headers[BUILD_HEADER] = build_id
        log_event(
            log,
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.perf_counter() - start) * 1000, 1),
            build=build_id,
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=CORS_ORIGIN_REGEX,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["content-type"],
        expose_headers=[BUILD_HEADER, "content-disposition"],
    )
    return app
