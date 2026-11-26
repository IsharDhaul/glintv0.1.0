from datetime import UTC, date, datetime

from glint.ingest.prices.models import Split
from glint.ingest.prices.provider import latest_requestable, market_today


def test_market_today_uses_new_york_date() -> None:
    # 03:00 UTC on 28 Oct is still 27 Oct in New York.
    assert market_today(datetime(2026, 10, 28, 3, 0, tzinfo=UTC)) == date(2026, 10, 27)
    assert market_today(datetime(2026, 10, 28, 5, 0, tzinfo=UTC)) == date(2026, 10, 28)


def test_latest_requestable_is_never_today() -> None:
    now = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)
    assert latest_requestable(now) == date(2026, 10, 27)
    assert latest_requestable(now) < market_today(now)


def test_split_ratio() -> None:
    assert Split("AAPL", date(2020, 8, 31), split_from=1, split_to=4).ratio == 4
    assert Split("X", date(2024, 1, 2), split_from=10, split_to=1).ratio == 0.1
