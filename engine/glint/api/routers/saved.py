"""v1 (WT-12): saved screens, run diffs and watchlists. 501 until WT-12."""

from fastapi import APIRouter

from glint.api.errors import not_implemented
from glint.contracts.api import (
    SavedScreen,
    SavedScreenIn,
    SavedScreenListResponse,
    ScreenRunDiffResponse,
    WatchlistItemIn,
    WatchlistResponse,
)

router = APIRouter(tags=["v1"])


@router.get("/api/screens")
def list_screens() -> SavedScreenListResponse:
    raise not_implemented("WT-12")


@router.post("/api/screens")
def create_screen(body: SavedScreenIn) -> SavedScreen:
    raise not_implemented("WT-12")


@router.get("/api/screens/{screen_id}")
def get_screen(screen_id: str) -> SavedScreen:
    raise not_implemented("WT-12")


@router.put("/api/screens/{screen_id}")
def update_screen(screen_id: str, body: SavedScreenIn) -> SavedScreen:
    raise not_implemented("WT-12")


@router.delete("/api/screens/{screen_id}", status_code=204)
def delete_screen(screen_id: str) -> None:
    raise not_implemented("WT-12")


@router.get("/api/screens/{screen_id}/diff")
def screen_diff(screen_id: str) -> ScreenRunDiffResponse:
    raise not_implemented("WT-12")


@router.get("/api/watchlists/{watchlist_id}")
def get_watchlist(watchlist_id: str) -> WatchlistResponse:
    raise not_implemented("WT-12")


@router.post("/api/watchlists/{watchlist_id}/items")
def add_watchlist_item(watchlist_id: str, body: WatchlistItemIn) -> WatchlistResponse:
    raise not_implemented("WT-12")


@router.delete("/api/watchlists/{watchlist_id}/items/{ticker}")
def remove_watchlist_item(watchlist_id: str, ticker: str) -> WatchlistResponse:
    raise not_implemented("WT-12")
