"""semianalyst — semiconductor technical-release ingestion and claim extraction.

Architecture (see CLAUDE.md for the full rules):
  ingest/   fetch raw releases, store content-addressed by sha256
  extract/  raw doc -> canonical schema records (LLM-backed; stubbed this phase)
  store/    the ONLY module permitted to touch SQLite
  analyze/  corroboration + divergence across sources (future work)
  cli.py    thin argument-parsing layer over the library

The library is UI-agnostic on purpose: cli.py is one caller; a web UI will be another.
"""

__version__ = "0.1.0"
