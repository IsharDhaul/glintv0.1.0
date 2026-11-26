from datetime import date

from glint.contracts.api import ErrorCode, ErrorResponse, HealthResponse, SourceFiling


def test_error_model_shape() -> None:
    e = ErrorResponse(build_id=None, error=ErrorCode.NOT_IMPLEMENTED, message="later")
    assert e.model_dump() == {
        "build_id": None,
        "error": "NOT_IMPLEMENTED",
        "message": "later",
        "path": None,
    }


def test_health_default() -> None:
    assert HealthResponse(build_id="b1").status == "ok"


def test_source_filing_form_is_nullable_but_present() -> None:
    """No build table records a filing's form: null, never invented (principle 3)."""
    s = SourceFiling(
        accn="0000320193-25-000079",
        form=None,
        filed=date(2025, 10, 31),
        url="https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/",
    )
    assert s.model_dump(mode="json")["form"] is None
    assert "form" in SourceFiling.model_json_schema()["required"]
