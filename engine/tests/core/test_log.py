import logging

from glint.core.log import LogfmtFormatter


def test_logfmt_line_has_fields() -> None:
    record = logging.LogRecord("glint.x", logging.INFO, __file__, 1, "stage_done", None, None)
    record.stage = "extract facts"
    record.rows = 10
    line = LogfmtFormatter().format(record)
    assert "level=info" in line
    assert "event=stage_done" in line
    assert 'stage="extract facts"' in line
    assert "rows=10" in line
