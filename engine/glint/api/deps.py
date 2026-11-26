"""Request dependencies shared by the routers."""

from typing import Annotated

from fastapi import Depends, Request

from glint.api.build import Build, BuildManager


def builds(request: Request) -> BuildManager:
    return request.app.state.builds


def current_build(request: Request, manager: Annotated[BuildManager, Depends(builds)]) -> Build:
    """The build to serve; 503 NO_BUILD / SCHEMA_MISMATCH when there isn't a usable one.

    Remembered on the request, so the `X-Glint-Build-Id` header and error bodies name the
    build the request actually used, even if a swap lands while it runs."""
    build = manager.get()
    request.state.build_id = build.build_id
    return build


def response_build_id(request: Request) -> str | None:
    """The build this request used, else the manager's last known one (no re-check)."""
    used = getattr(request.state, "build_id", None)
    if isinstance(used, str):
        return used
    manager: BuildManager = request.app.state.builds
    return manager.last_build_id()


CurrentBuild = Annotated[Build, Depends(current_build)]
Builds = Annotated[BuildManager, Depends(builds)]
