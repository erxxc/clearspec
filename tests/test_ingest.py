"""Ingest: content-addressed raw storage is idempotent by sha256."""

from __future__ import annotations

from semianalyst.ingest import store_raw


def test_store_raw_is_idempotent(tmp_path):
    raw_dir = tmp_path / "raw"

    first = store_raw(b"TSMC N2 announcement bytes", raw_dir)
    assert first.is_new is True
    assert first.path.exists()
    assert first.path.read_bytes() == b"TSMC N2 announcement bytes"

    # Re-fetching identical bytes is a no-op landing at the same path.
    again = store_raw(b"TSMC N2 announcement bytes", raw_dir)
    assert again.is_new is False
    assert again.sha256 == first.sha256
    assert again.path == first.path


def test_store_raw_changed_bytes_new_hash(tmp_path):
    raw_dir = tmp_path / "raw"
    a = store_raw(b"version one", raw_dir)
    b = store_raw(b"version two", raw_dir)
    # A silent revision of the same URL produces a distinct sha256 / file.
    assert a.sha256 != b.sha256
    assert b.is_new is True
    assert a.path.exists() and b.path.exists()
