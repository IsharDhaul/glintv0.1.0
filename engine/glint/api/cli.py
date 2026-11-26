"""`glint serve` (WT-08): run the API with uvicorn on GLINT_API_PORT."""

from typing import Annotated

import typer

from glint.core.log import configure_logging
from glint.core.settings import get_settings

APP_FACTORY = "glint.api.app:create_app"
DEFAULT_HOST = "127.0.0.1"  # local only: the API has no auth

app = typer.Typer(help="Run the API (uvicorn) on GLINT_API_PORT.")


@app.callback(invoke_without_command=True)
def serve(
    port: Annotated[
        int | None, typer.Option(help="Port (default: GLINT_API_PORT, else 8000)")
    ] = None,
    host: Annotated[str, typer.Option(help="Interface to bind")] = DEFAULT_HOST,
    reload: Annotated[
        bool, typer.Option("--reload/--no-reload", help="Restart on code changes (dev)")
    ] = True,
) -> None:
    import uvicorn  # noqa: PLC0415 (only this command needs it)

    configure_logging()
    uvicorn.run(
        APP_FACTORY,
        factory=True,
        host=host,
        port=port if port is not None else get_settings().api_port,
        reload=reload,
        log_config=None,  # keep Glint's structured request lines, not uvicorn's access log
        access_log=False,
    )
