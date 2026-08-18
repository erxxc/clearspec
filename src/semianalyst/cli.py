"""Thin CLI over the semianalyst library.

ARCHITECTURAL BOUNDARY: this file parses arguments and calls library functions —
nothing else. Zero business logic lives here. Every command delegates to a
library entry point that a web UI could call identically. If you find yourself
writing a loop, a query, or a transformation in this file, it belongs in a
library module instead.

The one thing that DOES live here is terminal output encoding (`_ansi_safe`):
sanitizing DB-derived strings against ANSI/OSC escapes is a display-edge concern
specific to a terminal sink — a web UI would HTML-escape the same values instead,
so it is not a shared library capability. It guards the day live extraction feeds
proposal-controlled strings (metric, baseline_entity, aliases) into `report`.
"""

from __future__ import annotations

import re
import unicodedata

import typer

from . import store
from .analyze import run_analysis
from .config import load_config
from .extract.pipeline import run_extract, run_rebuild
from .ingest import SidecarCollision
from .ingest.pipeline import forget, ingest_file, run_ingest

app = typer.Typer(
    help="semianalyst — ingest semiconductor releases and extract quantitative claims.",
    no_args_is_help=True,
    add_completion=False,
)

db_app = typer.Typer(help="Database management.", no_args_is_help=True)
app.add_typer(db_app, name="db")

# ANSI/OSC + control-char stripping for untrusted, DB-derived display strings.
# OSC (ESC ] ... BEL/ST) first, then CSI/other ESC sequences, then any residual
# control bytes (bare ESC and the C1 CSI introducer 0x9b) so a partial sequence
# can't survive as a live escape.
_ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_CSI = re.compile(r"\x1b[@-_][0-?]*[ -/]*[@-~]")
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _ansi_safe(text: str) -> str:
    """Neutralize terminal escape sequences AND Unicode format characters in an
    untrusted display string. The Cf pass (2026-08-18 gate, §2.8) is a CATEGORY
    test, not an enumerated list: bidi overrides (U+202A-202E, U+2066-2069),
    zero-widths (U+200B..200D), and BOM (U+FEFF) all sit above \\x9f and render
    natively — the Trojan-Source class — and any future format codepoint fails
    safe by category."""
    text = _ANSI_OSC.sub("", text)
    text = _ANSI_CSI.sub("", text)
    text = _CTRL.sub("", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


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


@app.command("ingest-file")
def ingest_file_cmd(
    path: str = typer.Argument(..., help="Local file to ingest (e.g. a PDF)."),
    doc_id: str = typer.Option(..., help="Stable id for this document."),
    title: str = typer.Option(...),
    publisher: str = typer.Option(...),
    doc_type: str = typer.Option(..., help="Schema DocType, e.g. foundry_announcement."),
    source_tier: int = typer.Option(..., help="1=conference, 2=foundry, 3=vendor."),
    url: str = typer.Option(...),
    publish_date: str = typer.Option(None, help="ISO date the source was published."),
) -> None:
    """Ingest a local file (content-addressed) and write its provenance sidecar."""
    try:
        raw = ingest_file(
            load_config(), path, doc_id=doc_id, title=title, publisher=publisher,
            doc_type=doc_type, source_tier=source_tier, url=url, publish_date=publish_date,
        )
    except SidecarCollision as exc:
        # An expected refusal, not a crash — no traceback (UAT A1).
        typer.echo(f"refused: {_ansi_safe(str(exc))}", err=True)
        raise typer.Exit(1) from exc
    suffix = "" if raw.is_new else "  (identical bytes already ingested — no-op)"
    typer.echo(f"ingested {raw.sha256[:12]}  doc_id={_ansi_safe(raw.meta['doc_id'])}{suffix}")


@app.command()
def extract() -> None:
    """Extract claims from ingested raw docs into the canonical schema."""
    try:
        report = run_extract(load_config())
    except store.StoreNotInitialized as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if report.note:
        typer.echo(report.note)
    typer.echo(
        f"extracted: {len(report.extracted)}  skipped: {len(report.skipped)}  "
        f"revised: {len(report.revised)}  errors: {len(report.errors)}"
    )
    for doc_id in report.extracted:
        typer.echo(f"  extracted: {_ansi_safe(doc_id)}")
    for doc_id in report.revised:  # loud: a source revision was extracted and folded in
        typer.echo(f"  REVISION (extracted + folded): {_ansi_safe(doc_id)}")
    for doc_id, reason in report.errors:
        typer.echo(f"  ERROR {_ansi_safe(doc_id)}: {_ansi_safe(reason)}")


@app.command("forget")
def forget_cmd(
    doc_id: str = typer.Argument(..., help="doc_id to retract (quarantine + refold)."),
) -> None:
    """Retract a document: quarantine its sidecar(s) + extraction artifact(s) under
    data/quarantine/ and rebuild the store without it. Raw blobs are retained."""
    try:
        report = forget(load_config(), doc_id)
    except ValueError as exc:
        # Unknown doc_id — an expected refusal, not a crash (UAT A1).
        typer.echo(f"refused: {_ansi_safe(str(exc))}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"quarantined: {len(report.quarantined)} file(s) for doc_id={_ansi_safe(report.doc_id)}")
    for name in report.quarantined:
        typer.echo(f"  quarantined: {_ansi_safe(name)}")
    rb = report.rebuild
    typer.echo(f"refolded: {len(rb.folded)}  superseded: {len(rb.superseded)}  errors: {len(rb.errors)}")
    for ident, reason in rb.errors:
        typer.echo(f"  ERROR {_ansi_safe(ident)}: {_ansi_safe(reason)}")


@db_app.command("rebuild")
def db_rebuild() -> None:
    """Rebuild the SQLite store as a deterministic fold over retained extraction artifacts."""
    report = run_rebuild(load_config())
    typer.echo(
        f"folded: {len(report.folded)}  superseded: {len(report.superseded)}  "
        f"errors: {len(report.errors)}"
    )
    for doc_id in report.folded:
        typer.echo(f"  folded: {_ansi_safe(doc_id)}")
    for doc_id in report.superseded:
        typer.echo(f"  superseded: {_ansi_safe(doc_id)}")
    for ident, reason in report.errors:
        typer.echo(f"  ERROR {_ansi_safe(ident)}: {_ansi_safe(reason)}")


@app.command()
def report() -> None:
    """Print cross-source corroboration and divergence per entity + metric."""
    try:
        analysis = run_analysis(load_config())
    except store.StoreNotInitialized as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if not analysis.assessments:
        typer.echo("no claims in the store — nothing to corroborate yet.")
        return
    for entity_id, info in analysis.entities_reconciled.items():
        aliases = [_ansi_safe(a) for a in info["aliases"]]
        typer.echo(f"{_ansi_safe(entity_id)}  aliases={aliases}")
    for a in analysis.assessments:
        line = f"  [{a.status}] {_ansi_safe(a.metric)}"
        if a.baseline_entity:
            line += f" vs {_ansi_safe(a.baseline_entity)}"
        line += f"  range={a.value_range} tiers={a.tiers} confidence={a.confidence}"
        if a.flags:
            line += f" flags={a.flags}"
        typer.echo(line)
    if analysis.conflicts:
        # The conflict record exists to be read by a human — which makes
        # offered/stored values the highest-incentive display payload in the
        # store (gate injection F3). Every field goes through _ansi_safe.
        typer.echo(f"conflicts: {len(analysis.conflicts)}")
        for c in analysis.conflicts:
            # Wording is refusal semantics (UAT C2): the store KEPT the stored
            # value and REFUSED the offer — never "stored -> offered", which
            # reads like an applied mutation.
            what = (f"kept {_ansi_safe(c.stored_value)}, refused {_ansi_safe(c.offered_value)}"
                    if c.stored_value is not None
                    else f"refused {_ansi_safe(c.offered_value)}")
            typer.echo(
                f"  [{_ansi_safe(c.kind.value)}] {_ansi_safe(c.entity_id)}"
                f"  {_ansi_safe(c.field)}: {what}"
                f" from {_ansi_safe(c.doc_id)}"
            )


if __name__ == "__main__":
    app()
