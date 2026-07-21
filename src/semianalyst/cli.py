"""Thin CLI over the semianalyst library.

ARCHITECTURAL BOUNDARY: this file parses arguments and calls library functions —
nothing else. Zero business logic lives here. Every command delegates to a
library entry point that a web UI could call identically. If you find yourself
writing a loop, a query, or a transformation in this file, it belongs in a
library module instead.
"""

from __future__ import annotations

import typer

from . import store
from .analyze import run_analysis
from .config import load_config
from .extract.pipeline import run_extract
from .ingest.pipeline import run_ingest

app = typer.Typer(
    help="semianalyst — ingest semiconductor releases and extract quantitative claims.",
    no_args_is_help=True,
    add_completion=False,
)

db_app = typer.Typer(help="Database management.", no_args_is_help=True)
app.add_typer(db_app, name="db")


@db_app.command("init")
def db_init() -> None:
    """Create the SQLite schema by applying pending migrations (idempotent)."""
    config = load_config()
    path = store.init_db(config)
    typer.echo(f"Initialized database at {path}")
    for table, count in store.report_counts(config).items():
        typer.echo(f"  {table}: {count}")


@app.command()
def ingest() -> None:
    """Fetch sources from the watchlist and store raw docs content-addressed by sha256."""
    report = run_ingest(load_config())
    if report.note:
        typer.echo(report.note)
    typer.echo(f"fetched: {len(report.fetched)}  skipped: {len(report.skipped)}")
    for name in report.skipped:
        typer.echo(f"  skipped: {name}")


@app.command()
def extract() -> None:
    """Extract claims from ingested raw docs into the canonical schema."""
    try:
        run_extract(load_config())
    except NotImplementedError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)


@app.command()
def report() -> None:
    """Print cross-source corroboration and divergence per entity + metric."""
    analysis = run_analysis(load_config())
    if not analysis.assessments:
        typer.echo("no claims in the store — nothing to corroborate yet.")
        return
    for entity_id, info in analysis.entities_reconciled.items():
        typer.echo(f"{entity_id}  aliases={info['aliases']}")
    for a in analysis.assessments:
        line = f"  [{a.status}] {a.metric}"
        if a.baseline_entity:
            line += f" vs {a.baseline_entity}"
        line += f"  range={a.value_range} tiers={a.tiers} confidence={a.confidence}"
        if a.flags:
            line += f" flags={a.flags}"
        typer.echo(line)


if __name__ == "__main__":
    app()
