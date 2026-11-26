"""v2 (WT-13): natural-language screens. 501 until WT-13."""

from fastapi import APIRouter

from glint.api.errors import not_implemented
from glint.contracts.api import NlScreenRequest, NlScreenResponse

router = APIRouter(tags=["v2"])


@router.post("/api/nl-screen")
def nl_screen(body: NlScreenRequest) -> NlScreenResponse:
    raise not_implemented("WT-13")
