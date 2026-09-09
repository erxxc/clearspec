"""GEI-14: curated NVD/GHSA/CISA KEV JSON ingest — offline mocked HTTPS.

Zero real network. Reuses the WS-2b test seam from test_fetch.py:
ThreadingHTTPServer + `_local_transport` rewriting https→http BELOW policy.
Proves HTTPS-only / redirect-to-http / size / redirect caps for JSON fetches,
sidecar without source_record_kind, extract stamps attested kind, self-attest
ignored, forget→watchlist re-ingest refuses revival.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from semianalyst import store
from semianalyst.config import Config, ModelConfig, PathsConfig, RateLimits, Source
from semianalyst.extract import AnthropicExtractor, ReplayModelClient, run_extract
from semianalyst.ingest import (
    SIDECAR_SUFFIX,
    FetchError,
    WatchlistFetcher,
    fetch_url,
    identity_doc_id,
    looks_like_json,
    run_ingest,
)
from semianalyst.ingest import fetch as fetchmod
from semianalyst.ingest.pipeline import forget
from semianalyst.store.attestation import attested_kind, kind_from_operator_sidecar

FIXTURES = Path(__file__).parent / "fixtures" / "advisory_json"
ADVISORY_GOLDEN = Path(__file__).parent / "fixtures" / "advisory_golden"


@dataclass
class _Served:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    content_length: bool = True


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
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

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.routes = {}
    httpd.hits = []
    threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.02), daemon=True).start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _https(server, path: str) -> str:
    return f"https://127.0.0.1:{server.server_address[1]}{path}"


def _local_transport(url: str, timeout: float):
    assert url.startswith("https://")
    return fetchmod._transport("http://" + url[len("https://"):], timeout)


def _fetch_local(url: str, *, max_bytes: int = 50_000_000, max_redirects: int = 5,
                 timeout: float = 5.0):
    return fetchmod._fetch(
        url, max_bytes=max_bytes, max_redirects=max_redirects,
        timeout=timeout, transport=_local_transport,
    )


def _no_sleep(_seconds: float) -> None:
    pass


def _cfg(tmp_path: Path, *sources: Source, rpm: int = 60) -> Config:
    return Config(
        model=ModelConfig(name="test-model", prompt_version="extract_advisory_v1"),
        paths=PathsConfig(
            data_dir=tmp_path, raw_dir=tmp_path / "raw",
            db_path=tmp_path / "semianalyst.db",
        ),
        rate_limits=RateLimits(requests_per_minute=rpm, max_concurrency=1),
        sources=tuple(sources),
    )


def _run(config: Config):
    return run_ingest(
        config, fetcher=WatchlistFetcher(fetch_fn=_fetch_local), sleeper=_no_sleep,
    )


def _sidecar(config: Config, sha256: str) -> dict:
    return json.loads((config.paths.raw_dir / f"{sha256}{SIDECAR_SUFFIX}").read_text())


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --------------------------------------------------------------------------
# Magic / policy — JSON path under the same WS-2b engine
# --------------------------------------------------------------------------
def test_looks_like_json_accepts_object_and_array():
    assert looks_like_json(b'{"a":1}')
    assert looks_like_json(b"  [1, 2]\n")
    assert not looks_like_json(b"%PDF-1.4")
    assert not looks_like_json(b"<html>nope</html>")
    assert not looks_like_json(b"{not json")


@pytest.mark.parametrize("url", [
    "http://example.test/cve.json",
    "ftp://example.test/cve.json",
    "file:///etc/passwd",
])
def test_json_fetch_https_scheme_required(url):
    with pytest.raises(FetchError, match="non-https URL before any request"):
        fetch_url(url)


def test_json_redirect_to_http_refused(server):
    body = _fixture("cisa-kev-subset.json")
    port = server.server_address[1]
    server.routes["/bounce"] = _Served(
        status=302, headers={"Location": f"http://127.0.0.1:{port}/kev.json"})
    server.routes["/kev.json"] = _Served(body=body)
    with pytest.raises(FetchError, match="non-https URL at redirect hop 1"):
        _fetch_local(_https(server, "/bounce"))
    assert server.hits == ["/bounce"]


def test_json_redirect_cap_enforced(server):
    server.routes["/loop"] = _Served(status=302, headers={"Location": "/loop"})
    with pytest.raises(FetchError, match="too many redirects"):
        _fetch_local(_https(server, "/loop"), max_redirects=5)
    assert server.hits == ["/loop"] * 6


def test_json_size_cap_aborts_streaming(server):
    server.routes["/big.json"] = _Served(
        body=b'{"x":"' + b"y" * 5000 + b'"}', content_length=False)
    with pytest.raises(FetchError, match="size cap exceeded .* streamed"):
        _fetch_local(_https(server, "/big.json"), max_bytes=1000)


def test_non_json_refused_per_doc(server, tmp_path):
    server.routes["/page.html"] = _Served(body=b"<html>index</html>")
    json_body = _fixture("ghsa-GHSA-jfh8-c2jp-5v3q.json")
    server.routes["/adv.json"] = _Served(body=json_body)
    html_url, json_url = _https(server, "/page.html"), _https(server, "/adv.json")
    config = _cfg(
        tmp_path,
        Source(
            name="GHSA", url="https://api.github.com/advisories",
            publisher="GitHub", doc_type="ghsa", source_tier=3,
            parser_role="reviewed", documents=(html_url, json_url),
        ),
    )
    report = _run(config)
    assert report.errors == [(html_url, "not JSON (UTF-8 object/array parse failed)")]
    kind = attested_kind("ghsa", "reviewed")
    assert report.fetched == [identity_doc_id(json_url, kind.value)]


# --------------------------------------------------------------------------
# Curated ingest → sidecar without kind → extract stamps attested kind
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stem,doc_type,parser_role,publisher,path", [
    ("nvd-cve-2024-3400.json", "nvd_record", "cpe", "NVD", "/nvd/cve.json"),
    ("ghsa-GHSA-jfh8-c2jp-5v3q.json", "ghsa", "reviewed", "GitHub", "/ghsa/adv.json"),
    ("cisa-kev-subset.json", "cisa_kev", "kev", "CISA", "/cisa/kev.json"),
])
def test_curated_json_ingest_sidecar_no_kind(
    server, tmp_path, stem, doc_type, parser_role, publisher, path,
):
    body = _fixture(stem)
    assert looks_like_json(body)
    # Fixtures deliberately self-attest high-weight kinds — must not land in sidecar.
    assert b"source_record_kind" in body
    server.routes[path] = _Served(body=body, headers={"Content-Type": "application/json"})
    url = _https(server, path)
    kind = attested_kind(doc_type, parser_role)
    doc_id = identity_doc_id(url, kind.value)
    config = _cfg(
        tmp_path,
        Source(
            name=publisher, url="https://example.test/",
            publisher=publisher, doc_type=doc_type, source_tier=3,
            parser_role=parser_role, documents=(url,),
        ),
    )
    report = _run(config)
    assert report.errors == []
    assert report.fetched == [doc_id]
    meta = _sidecar(config, hashlib.sha256(body).hexdigest())
    assert meta["doc_id"] == doc_id
    assert meta["doc_type"] == doc_type
    assert meta["publisher"] == publisher
    assert meta["parser_role"] == parser_role
    assert "source_record_kind" not in meta
    assert kind_from_operator_sidecar(meta) == kind


def test_nvd_cna_vs_cpe_distinct_identity(server, tmp_path):
    """Same curated NVD URL with different parser_role mints distinct doc_ids."""
    body = _fixture("nvd-cve-2024-3400.json")
    server.routes["/nvd.json"] = _Served(body=body)
    url = _https(server, "/nvd.json")
    cna_id = identity_doc_id(url, attested_kind("nvd_record", "cna").value)
    cpe_id = identity_doc_id(url, attested_kind("nvd_record", "cpe").value)
    assert cna_id != cpe_id
    # Ingest as CPE first (watchlist one role per source).
    config = _cfg(
        tmp_path,
        Source(
            name="NVD", url="https://services.nvd.nist.gov/",
            publisher="NVD", doc_type="nvd_record", source_tier=3,
            parser_role="cpe", documents=(url,),
        ),
    )
    assert _run(config).fetched == [cpe_id]
    meta = _sidecar(config, hashlib.sha256(body).hexdigest())
    assert meta["doc_id"] == cpe_id and meta["parser_role"] == "cpe"


def test_self_attest_in_json_ignored_through_extract(server, tmp_path):
    """JSON body + poisoned fields do not become the stamped claim kind."""
    # Use a tiny advisory-shaped payload + GEI-10 golden proposal for extract.
    golden = json.loads((ADVISORY_GOLDEN / "cve-2024-21626-nvd.json").read_text())
    payload = {
        "text": golden["source_text"],
        "source_record_kind": "ghsa_reviewed",
        "nvd_cna": True,
        "cisa_kev": True,
        "ghsa_reviewed": True,
    }
    body = json.dumps(payload).encode()
    server.routes["/nvd.json"] = _Served(body=body)
    url = _https(server, "/nvd.json")
    kind = attested_kind("nvd_record", "cpe")
    doc_id = identity_doc_id(url, kind.value)
    config = _cfg(
        tmp_path,
        Source(
            name="NVD", url="https://nvd.nist.gov/",
            publisher="NVD", doc_type="nvd_record", source_tier=3,
            parser_role="cpe", documents=(url,),
        ),
    )
    store.init_db(config)
    assert _run(config).fetched == [doc_id]
    meta = _sidecar(config, hashlib.sha256(body).hexdigest())
    assert "source_record_kind" not in meta

    extractor = AnthropicExtractor(ReplayModelClient(json.dumps(golden["proposal"])))
    report = run_extract(config, extractor=extractor)
    assert report.errors == []
    assert doc_id in report.extracted
    conn = store.connect(config.paths.db_path)
    try:
        kinds = {r["source_record_kind"] for r in conn.execute(
            "SELECT source_record_kind FROM claim")}
    finally:
        conn.close()
    assert kinds == {"nvd_cpe"}
    assert "ghsa_reviewed" not in kinds


def test_forget_then_json_watchlist_refuses_revival(server, tmp_path):
    body = _fixture("cisa-kev-subset.json")
    server.routes["/kev.json"] = _Served(body=body)
    url = _https(server, "/kev.json")
    kind = attested_kind("cisa_kev", "kev")
    doc_id = identity_doc_id(url, kind.value)
    config = _cfg(
        tmp_path,
        Source(
            name="CISA KEV", url="https://www.cisa.gov/",
            publisher="CISA", doc_type="cisa_kev", source_tier=3,
            parser_role="kev", documents=(url,),
        ),
    )
    store.init_db(config)
    assert _run(config).fetched == [doc_id]
    assert forget(config, doc_id).quarantined

    again = _run(config)
    assert again.fetched == [] and again.unchanged == []
    assert len(again.errors) == 1
    key, reason = again.errors[0]
    assert key == url and "retracted by forget" in reason
    sha = hashlib.sha256(body).hexdigest()
    assert not (config.paths.raw_dir / f"{sha}{SIDECAR_SUFFIX}").exists()
    assert (config.paths.raw_dir / sha).exists()


def test_foundry_pdf_path_still_works_alongside_json(server, tmp_path):
    """WatchlistFetcher routes PDF foundry + JSON advisory without breaking PDF."""
    pdf = b"%PDF-1.4 foundry\n"
    jbody = _fixture("ghsa-GHSA-jfh8-c2jp-5v3q.json")
    server.routes["/n2.pdf"] = _Served(body=pdf)
    server.routes["/g.json"] = _Served(body=jbody)
    pdf_url, json_url = _https(server, "/n2.pdf"), _https(server, "/g.json")
    from semianalyst.ingest import url_doc_id
    config = _cfg(
        tmp_path,
        Source(
            name="TSMC", url="https://pr.tsmc.com/",
            doc_type="foundry_announcement", source_tier=2, documents=(pdf_url,),
        ),
        Source(
            name="GHSA", url="https://api.github.com/advisories",
            publisher="GitHub", doc_type="ghsa", source_tier=3,
            parser_role="reviewed", documents=(json_url,),
        ),
    )
    report = _run(config)
    assert report.errors == []
    assert url_doc_id(pdf_url) in report.fetched
    assert identity_doc_id(
        json_url, attested_kind("ghsa", "reviewed").value
    ) in report.fetched


def test_advisory_documents_without_parser_role_refused(server, tmp_path):
    body = _fixture("cisa-kev-subset.json")
    server.routes["/kev.json"] = _Served(body=body)
    url = _https(server, "/kev.json")
    config = _cfg(
        tmp_path,
        Source(
            name="CISA", url="https://www.cisa.gov/",
            doc_type="cisa_kev", source_tier=3, documents=(url,),
            # parser_role intentionally omitted
        ),
    )
    report = _run(config)
    assert report.fetched == []
    assert len(report.errors) == 1
    assert "parser_role is required" in report.errors[0][1]
    assert server.hits == []  # refused before fetch


@pytest.mark.live
def test_live_curated_urls_gated():
    """Optional live smoke — skipped unless --run-live. Does not run in plain pytest."""
    pytest.skip("live curated NVD/GHSA/KEV fetch is gated; not claimed in offline suite")
