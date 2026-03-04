from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import typer

from scr.config import default_config_path, write_default_config
from scr.engine import EngineError, run_review
from scr.models import ReviewRequest, Severity
from scr.renderers import render_json, render_markdown
from scr.web import create_app

app = typer.Typer(help="Smart Code Reviewer")
review_app = typer.Typer(help="Run reviews")
config_app = typer.Typer(help="Config commands")
app.add_typer(review_app, name="review")
app.add_typer(config_app, name="config")


@review_app.callback(invoke_without_command=True)
def review_command(
    ctx: typer.Context,
    git: bool = typer.Option(False, "--git", help="Review git diff against base"),
    diff: Optional[str] = typer.Option(None, "--diff", help="Path to unified diff file"),
    paths: Optional[List[str]] = typer.Option(None, "--paths", help="Explicit file/dir paths"),
    base: Optional[str] = typer.Option(None, "--base", help="Base ref for git diff"),
    format: str = typer.Option("md", "--format", help="md|json|both"),
    out: Optional[str] = typer.Option(None, "--out", help="Output file path or prefix"),
    fail_on: Severity = typer.Option(Severity.HIGH, "--fail-on", case_sensitive=False),
    max_findings: int = typer.Option(12, "--max-findings"),
    max_per_file: int = typer.Option(3, "--max-per-file"),
    no_llm: bool = typer.Option(False, "--no-llm"),
) -> None:
    if ctx.invoked_subcommand:
        return

    selected = sum([1 if git else 0, 1 if diff else 0, 1 if bool(paths) else 0])
    if selected == 0:
        git = True
    elif selected > 1:
        typer.echo("Error: choose exactly one of --git, --diff, --paths", err=True)
        raise typer.Exit(code=2)

    mode = "git" if git else "diff" if diff else "paths"
    request = ReviewRequest(
        mode=mode,
        base=base,
        diff_text=diff,
        paths=paths,
        format=format,
        fail_on=fail_on,
        max_findings=max_findings,
        max_per_file=max_per_file,
        no_llm=no_llm,
    )

    try:
        report, summary = run_review(request)
    except EngineError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2)

    md = render_markdown(report)
    js = render_json(report)

    try:
        write_outputs(format, out, md, js)
    except OSError as exc:
        typer.echo(f"Error writing report: {exc}", err=True)
        raise typer.Exit(code=2)

    if not out and format in {"md", "both"}:
        typer.echo(md)
    elif not out and format == "json":
        typer.echo(js)

    raise typer.Exit(code=1 if summary.threshold_exceeded else 0)


@config_app.command("init")
def config_init(path: Optional[str] = typer.Option(None, "--path", help="Path to config file")) -> None:
    target = Path(path) if path else default_config_path()
    if target.exists():
        typer.echo(f"Config already exists at {target}")
        raise typer.Exit(code=0)
    write_default_config(target)
    typer.echo(f"Wrote default config to {target}")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(7331, "--port"),
    no_llm: bool = typer.Option(False, "--no-llm"),
) -> None:
    import uvicorn

    uvicorn.run(create_app(no_llm=no_llm), host=host, port=port)


def write_outputs(fmt: str, out: Optional[str], md: str, js: str) -> None:
    if fmt not in {"md", "json", "both"}:
        raise OSError("format must be md|json|both")
    if not out:
        return

    output = Path(out)
    if fmt == "md":
        output.write_text(md, encoding="utf-8")
    elif fmt == "json":
        output.write_text(js, encoding="utf-8")
    else:
        output.with_suffix(".md").write_text(md, encoding="utf-8")
        output.with_suffix(".json").write_text(js, encoding="utf-8")


def run() -> None:
    app()


if __name__ == "__main__":
    run()
