"""Placeholder sub-apps for commands a later worktree owns."""

from typing import Any

import typer
from typer.core import TyperGroup

STUB_EXIT_CODE = 2


class _AcceptAnyArgsGroup(TyperGroup):
    """Swallows whatever arguments the future command will take, so the stub always runs."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:  # typer vendors click
        if "--help" in args:
            return super().parse_args(ctx, args)
        return super().parse_args(ctx, [])


def stub_app(worktree: str, help_text: str) -> typer.Typer:
    """A sub-app that accepts any arguments, says who builds it, and exits with code 2."""
    app = typer.Typer(cls=_AcceptAnyArgsGroup, help=f"{help_text} (planned: {worktree})")

    @app.callback(invoke_without_command=True)
    def _stub(ctx: typer.Context) -> None:  # pyright: ignore[reportUnusedFunction]
        typer.echo(f"{ctx.command_path}: not implemented yet ({worktree})")
        raise typer.Exit(STUB_EXIT_CODE)

    return app
