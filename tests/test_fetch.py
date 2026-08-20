"""WS-2b fetcher: transport policy, run_ingest wiring, and the ingest->extract
E2E over a LOCAL http.server — zero real network, zero API key.

The test seam (fetch.py module docstring): the PUBLIC fetch_url is permanently
https-only with no override, so https refusals are tested directly against it
with no server at all. Transport behaviors (redirect walking, caps, magic
bytes) are tested through the internal policy engine `fetch._fetch` with an
injected transport that rewrites https->http strictly BELOW the policy
boundary — the scheme checks, redirect loop, and caps under test are the real
production code paths; only the byte-mover differs (a local plaintext server
cannot present certificates, and a public insecure flag would be a backdoor).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from semianalyst import store
from semianalyst.analyze import run_analysis
from semianalyst.config import Config, ModelConfig, PathsConfig, RateLimits, Source
from semianalyst.extract import AnthropicExtractor, ReplayModelClient, run_extract
from semianalyst.ingest import (
    SIDECAR_SUFFIX,
    FetchError,
    FoundryFetcher,
    fetch_url,
    looks_like_pdf,
    run_ingest,
    url_doc_id,
)
from semianalyst.ingest import fetch as fetchmod

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CASE_DIR = FIXTURES_DIR / "tsmc_n2_2025"

PDF = b"%PDF-1.4 fetched test document\n"
DOC_ID_120 = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")  # store.models.DocId120


# --------------------------------------------------------------------------
# Local server + the transport seam
# --------------------------------------------------------------------------
@dataclass
class _Served:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    content_length: bool = True  # False = close-delimited body (header absent)


class _Handler(BaseHTTPRequestHandler):
    # protocol_version stays HTTP/1.0 (the BaseHTTPRequestHandler default) so a
    # route with content_length=False is honestly close-delimited.
    def do_GET(self):  # noqa: N802 (http.server API)
        self.server.hits.append(self.path)
        route = self.server.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(route.status)
        for key, value in route.headers.items():
            self.send_header(key, value)
        if route.content_length and "Content-Length" not in route.headers:
            self.send_header("Content-Length", str(len(route.body)))
        self.end_headers()
        self.wfile.write(route.body)

    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.routes = {}
    httpd.hits = []
    # small poll_interval: shutdown() blocks up to one poll, and every test owns a server
    threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.02), daemon=True).start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _https(server, path: str) -> str:
    """Tests speak https to the policy layer; _local_transport moves the bytes
    over local plaintext underneath it."""
    return f"https://127.0.0.1:{server.server_address[1]}{path}"


def _local_transport(url: str, timeout: float):
    """The seam: the policy engine already approved `url` as https; rewrite the
    scheme below the policy boundary and reuse the REAL transport (no-redirect
    opener, socket timeout) against the local server."""
    assert url.startswith("https://")  # the policy layer never hands us anything else
    return fetchmod._transport("http://" + url[len("https://"):], timeout)


def _fetch_local(url: str, *, max_bytes: int = 50_000_000, max_redirects: int = 5,
                 timeout: float = 5.0):
    return fetchmod._fetch(url, max_bytes=max_bytes, max_redirects=max_redirects,
                           timeout=timeout, transport=_local_transport)


def _no_sleep(_seconds: float) -> None:
    pass


def _cfg(tmp_path: Path, *sources: Source, rpm: int = 10) -> Config:
    """tmp_config's pattern (tests/test_rebuild.py) plus a live watchlist."""
    return Config(
        model=ModelConfig(name="test-model", prompt_version="extract_foundry_v1"),
        paths=PathsConfig(data_dir=tmp_path, raw_dir=tmp_path / "raw",
                          db_path=tmp_path / "semianalyst.db"),
        rate_limits=RateLimits(requests_per_minute=rpm, max_concurrency=1),
        sources=tuple(sources),
    )


def _source(name: str, *documents: str, publisher: str | None = None) -> Source:
    return Source(name=name, url="https://example.test/index", publisher=publisher,
                  doc_type="foundry_announcement", source_tier=2, documents=documents)


def _run(config: Config, sleeper=_no_sleep):
    return run_ingest(config, fetcher=FoundryFetcher(fetch_fn=_fetch_local), sleeper=sleeper)


def _sidecar(config: Config, sha256: str) -> dict:
    return json.loads((config.paths.raw_dir / f"{sha256}{SIDECAR_SUFFIX}").read_text())


# --------------------------------------------------------------------------
# Scheme policy — PUBLIC surface, no server, no transport injection
# --------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "http://example.test/doc.pdf",
    "ftp://example.test/doc.pdf",
    "file:///etc/passwd",
])
def test_https_scheme_required(url):
    with pytest.raises(FetchError, match="non-https URL before any request"):
        fetch_url(url)


def test_redirect_to_http_refused_mid_chain(server):
    """A compromised/MITM'd site bouncing us off https is refused AT THE HOP —
    the downgraded target is never requested."""
    port = server.server_address[1]
    server.routes["/bounce"] = _Served(
        status=302, headers={"Location": f"http://127.0.0.1:{port}/loot.pdf"})
    server.routes["/loot.pdf"] = _Served(body=PDF)
    with pytest.raises(FetchError, match="non-https URL at redirect hop 1"):
        _fetch_local(_https(server, "/bounce"))
    assert server.hits == ["/bounce"]  # the http:// target was never touched


def test_redirect_cap_enforced(server):
    server.routes["/loop"] = _Served(status=302, headers={"Location": "/loop"})
    with pytest.raises(FetchError, match="too many redirects"):
        _fetch_local(_https(server, "/loop"), max_redirects=5)
    assert server.hits == ["/loop"] * 6  # initial request + 5 followed redirects


def test_relative_redirect_resolved(server):
    """A relative Location resolves against the CURRENT hop's URL — and the
    post-redirect final_url is reported for the sidecar audit trail."""
    server.routes["/a/rel"] = _Served(status=302, headers={"Location": "b.pdf"})
    server.routes["/a/b.pdf"] = _Served(body=PDF)
    doc = _fetch_local(_https(server, "/a/rel"))
    assert doc.content == PDF
    assert doc.final_url == _https(server, "/a/b.pdf")


# --------------------------------------------------------------------------
# Size cap — streamed enforcement; Content-Length absent or lying
# --------------------------------------------------------------------------
def test_size_cap_aborts_streaming(server):
    """No Content-Length at all (close-delimited body): the streamed count is
    the enforcement, not the header."""
    server.routes["/big.pdf"] = _Served(body=PDF + b"x" * 5000, content_length=False)
    with pytest.raises(FetchError, match="size cap exceeded .* streamed"):
        _fetch_local(_https(server, "/big.pdf"), max_bytes=1000)


def test_size_cap_on_declared_content_length(server):
    """A header DECLARING an oversize body aborts before the read — the
    courtesy fast path of the same cap."""
    server.routes["/huge.pdf"] = _Served(body=PDF, headers={"Content-Length": "99999999"})
    with pytest.raises(FetchError, match="declared Content-Length"):
        _fetch_local(_https(server, "/huge.pdf"), max_bytes=1000)


def test_looks_like_pdf():
    assert looks_like_pdf(b"%PDF-1.7 ...")
    assert not looks_like_pdf(b"<html>not a pdf</html>")
    assert not looks_like_pdf(b"")


# --------------------------------------------------------------------------
# doc_id slug — deterministic identity from the REQUESTED URL
# --------------------------------------------------------------------------
def test_url_doc_id_slug():
    assert (url_doc_id("https://PR.TSMC.com/English/News/N2-Update.pdf")
            == "pr_tsmc_com_english_news_n2_update_pdf")
    # runs of non-[a-z0-9] collapse to one '_'; leading/trailing stripped
    assert url_doc_id("https://a.com//x..y/") == "a_com_x_y"
    # host+path only: the query is not identity (distinct-URL conflation is the
    # accepted residual behind analyze's possible_slug_collision advisory, J)
    assert url_doc_id("https://a.com/x.pdf?v=2") == url_doc_id("https://a.com/x.pdf")


def test_url_doc_id_truncation_hash():
    long_a = "https://example.com/reports/" + "a" * 150 + "/final.pdf"
    long_b = "https://example.com/reports/" + "a" * 150 + "/draft.pdf"
    doc_a, doc_b = url_doc_id(long_a), url_doc_id(long_b)
    for url, doc_id in ((long_a, doc_a), (long_b, doc_b)):
        assert len(doc_id) == 120 and DOC_ID_120.fullmatch(doc_id)
        assert doc_id.endswith("_" + hashlib.sha256(url.encode()).hexdigest()[:8])
    # the two URLs share their first 111 slug chars — only the hash separates them
    assert doc_a[:112] == doc_b[:112] and doc_a != doc_b


# --------------------------------------------------------------------------
# run_ingest — report shape, isolation, idempotency, pacing, sidecars
# --------------------------------------------------------------------------
def test_run_ingest_skips_sources_without_documents(tmp_path):
    """The unchanged stock config shape (no documents lists) stays valid: every
    source is skipped, nothing is fetched, and the note names the WS-3 deferral.
    Uses the DEFAULT fetcher — with no documents it makes no request."""
    config = _cfg(tmp_path, Source(name="TSMC Technology", url="https://pr.tsmc.com/english/news",
                                   doc_type="foundry_announcement", source_tier=2))
    report = run_ingest(config, sleeper=_no_sleep)
    assert report.skipped == ["TSMC Technology"]
    assert report.fetched == [] and report.unchanged == [] and report.errors == []
    assert "WS-3" in report.note


def test_non_pdf_magic_refused_per_doc(server, tmp_path):
    server.routes["/page.html"] = _Served(body=b"<html>an index page</html>")
    server.routes["/real.pdf"] = _Served(body=PDF)
    html_url, pdf_url = _https(server, "/page.html"), _https(server, "/real.pdf")
    config = _cfg(tmp_path, _source("TSMC", html_url, pdf_url))

    report = _run(config)
    assert report.errors == [(html_url, "not a PDF (magic bytes %PDF- missing)")]
    assert report.fetched == [url_doc_id(pdf_url)]  # the batch continued
    # refused bytes never landed content-addressed
    stored = {p.name for p in config.paths.raw_dir.iterdir()}
    assert stored == {hashlib.sha256(PDF).hexdigest(),
                      hashlib.sha256(PDF).hexdigest() + SIDECAR_SUFFIX}


def test_fetch_error_isolated(server, tmp_path):
    """One bad URL (404 -> FetchError) doesn't sink the batch — and the error
    reason is fixed text, no server body."""
    server.routes["/good.pdf"] = _Served(body=PDF)
    missing_url, good_url = _https(server, "/gone.pdf"), _https(server, "/good.pdf")
    config = _cfg(tmp_path, _source("TSMC", missing_url, good_url))

    report = _run(config)
    assert report.fetched == [url_doc_id(good_url)]
    assert len(report.errors) == 1
    key, reason = report.errors[0]
    assert key == missing_url and "http error status 404" in reason


def test_idempotent_refetch_unchanged(server, tmp_path):
    server.routes["/n2.pdf"] = _Served(body=PDF)
    url = _https(server, "/n2.pdf")
    config = _cfg(tmp_path, _source("TSMC", url))

    first = _run(config)
    assert first.fetched == [url_doc_id(url)] and first.unchanged == []
    second = _run(config)  # identical bytes: the honest no-op, distinct from fetched
    assert second.fetched == [] and second.unchanged == [url_doc_id(url)]
    assert second.errors == []


def test_rate_pacing_recorded(server, tmp_path):
    """Min-interval pacing spans the WHOLE run (across sources): N requests,
    N-1 sleeps of 60/rpm seconds, none before the first request."""
    for i in range(4):
        server.routes[f"/p{i}.pdf"] = _Served(body=PDF + str(i).encode())
    config = _cfg(
        tmp_path,
        _source("A", _https(server, "/p0.pdf"), _https(server, "/p1.pdf"), _https(server, "/p2.pdf")),
        _source("B", _https(server, "/p3.pdf")),
        rpm=10,
    )
    sleeps: list[float] = []
    report = _run(config, sleeper=sleeps.append)
    assert len(report.fetched) == 4 and report.errors == []
    assert sleeps == [6.0, 6.0, 6.0]  # 60/10 between consecutive requests


def test_sidecar_fields_correct(server, tmp_path):
    port = server.server_address[1]
    # doc A sits behind a redirect: requested-url identity, final-url audit
    server.routes["/move"] = _Served(status=302, headers={"Location": "/docs/n2_update.pdf"})
    server.routes["/docs/n2_update.pdf"] = _Served(body=PDF)
    server.routes["/b.pdf"] = _Served(body=PDF + b"b")  # distinct bytes: no S1 collision
    requested_a = _https(server, "/move")
    config = _cfg(
        tmp_path,
        _source("TSMC Technology", requested_a),                     # publisher falls back to name
        _source("Samsung Foundry", _https(server, "/b.pdf"), publisher="Samsung"),
    )

    report = _run(config)
    assert report.errors == []

    meta_a = _sidecar(config, hashlib.sha256(PDF).hexdigest())
    assert meta_a["doc_id"] == url_doc_id(requested_a) == f"127_0_0_1_{port}_move"
    assert meta_a["url"] == _https(server, "/docs/n2_update.pdf")  # FINAL post-redirect URL
    assert meta_a["title"] == "move"  # requested-URL path basename (display data)
    assert meta_a["publisher"] == "TSMC Technology"  # fallback to source name
    assert meta_a["doc_type"] == "foundry_announcement" and meta_a["source_tier"] == 2
    assert meta_a["publish_date"] is None  # never guessed from untrusted headers
    assert meta_a["ingest_date"] == dt.date.today().isoformat()
    assert meta_a["file_sha256"] == hashlib.sha256(PDF).hexdigest()

    meta_b = _sidecar(config, hashlib.sha256(PDF + b"b").hexdigest())
    assert meta_b["publisher"] == "Samsung"  # explicit publisher wins over name


def test_sidecar_collision_isolated(server, tmp_path):
    """Same bytes served at two URLs: the second sidecar write is an S1
    collision — reported per-document, first binding intact, batch continues."""
    server.routes["/a.pdf"] = _Served(body=PDF)
    server.routes["/dup.pdf"] = _Served(body=PDF)          # identical bytes
    server.routes["/c.pdf"] = _Served(body=PDF + b"c")     # distinct third doc
    url_a, url_dup, url_c = (_https(server, p) for p in ("/a.pdf", "/dup.pdf", "/c.pdf"))
    config = _cfg(tmp_path, _source("TSMC", url_a, url_dup, url_c))

    report = _run(config)
    assert report.fetched == [url_doc_id(url_a), url_doc_id(url_c)]  # batch continued past the collision
    assert len(report.errors) == 1
    key, reason = report.errors[0]
    assert key == url_doc_id(url_dup) and "refusing to rebind" in reason
    # the first ingest's identity binding is intact
    assert _sidecar(config, hashlib.sha256(PDF).hexdigest())["doc_id"] == url_doc_id(url_a)


# --------------------------------------------------------------------------
# E2E: run_ingest -> run_extract (replay) -> revision -> supersession
# --------------------------------------------------------------------------
def _counts(config: Config) -> dict[str, int]:
    conn = store.connect(config.paths.db_path)
    try:
        return store.table_counts(conn)
    finally:
        conn.close()


def _stored_shas(config: Config) -> dict[str, str]:
    conn = store.connect(config.paths.db_path)
    try:
        return store.stored_doc_shas(conn)
    finally:
        conn.close()


def test_revision_changed_bytes_supersedes_e2e(server, tmp_path):
    """The full live chain over the REAL run_ingest + run_extract: fetch ->
    sidecar -> extract (replay), then the server silently revises the bytes at
    the same URL -> re-ingest needs no special handling (new blob, same
    doc_id) -> run_extract's revision path supersedes via refold — the store
    reflects ONLY the revision."""
    v1 = (CASE_DIR / "raw.pdf").read_bytes()
    server.routes["/tsmc/raw.pdf"] = _Served(body=v1)
    url = _https(server, "/tsmc/raw.pdf")
    doc_id = url_doc_id(url)
    config = _cfg(tmp_path, _source("TSMC Technology", url, publisher="TSMC"))
    store.init_db(config)

    assert _run(config).fetched == [doc_id]
    rep = run_extract(config, extractor=AnthropicExtractor(
        ReplayModelClient((CASE_DIR / "llm_response.json").read_text())))
    assert rep.extracted == [doc_id] and rep.errors == []
    assert run_analysis(config).assessments[0].value_range == [1.15, 1.15]

    # The source revises the document in place: changed bytes, same URL (same
    # identity), appended junk parses to identical text; the recorded value
    # changes so the fold winner is observable.
    v2 = v1 + b"%% corrected\n"
    server.routes["/tsmc/raw.pdf"] = _Served(body=v2)
    again = _run(config)
    assert again.fetched == [doc_id] and again.unchanged == []  # new bytes ARE a fetch
    recorded = json.loads((CASE_DIR / "llm_response.json").read_text())
    recorded["claims"][0]["value"] = 1.30  # quote_span unchanged, still grounded
    rep = run_extract(config, extractor=AnthropicExtractor(ReplayModelClient(json.dumps(recorded))))
    assert rep.revised == [doc_id] and rep.extracted == [] and rep.errors == []

    # Only the revision survives the fold.
    assert _counts(config)["document"] == 1 and _counts(config)["claim"] == 1
    assert _stored_shas(config)[doc_id] == hashlib.sha256(v2).hexdigest()
    assert run_analysis(config).assessments[0].value_range == [1.30, 1.30]

    # Steady state: re-fetch is unchanged, re-extract skips both byte-states
    # (v1's retained artifact is an honest skip — anti-ping-pong).
    third = _run(config)
    assert third.fetched == [] and third.unchanged == [doc_id]
    rep = run_extract(config, extractor=AnthropicExtractor(ReplayModelClient(json.dumps(recorded))))
    assert rep.extracted == [] and rep.revised == [] and rep.errors == []
    assert rep.skipped.count(doc_id) == 2
