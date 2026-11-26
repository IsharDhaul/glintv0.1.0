from fastapi import APIRouter

from glint.api.deps import Builds
from glint.contracts.api import HealthResponse

router = APIRouter(tags=["meta"])


@router.get("/api/health")
def health(builds: Builds) -> HealthResponse:
    """Always 200 while the process is up, with or without a build."""
    return HealthResponse(build_id=builds.build_id())
