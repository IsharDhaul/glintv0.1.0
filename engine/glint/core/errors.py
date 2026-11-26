"""Error types. Expected states carry a stable `code`; only real failures become 500s."""


class GlintError(Exception):
    """Base class for every Glint error."""

    code = "GLINT_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class SourceError(GlintError):
    """An external source (SEC, a price provider) failed or refused us."""

    code = "SOURCE_ERROR"

    def __init__(self, source: str, message: str, *, status: int | None = None) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source
        self.status = status


class NotCoveredError(GlintError):
    """The thing asked for is outside Glint's coverage (unknown ticker, excluded kind, …)."""

    code = "NOT_COVERED"


class ContractError(GlintError):
    """Data or a request doesn't match a contract (schema version, DSL, registry)."""

    code = "CONTRACT_ERROR"
