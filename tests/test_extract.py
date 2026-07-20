"""Offline coverage of extract/base.py branches — the ModelClient seam lets us
exercise the JSON-parse fallback and the refusal/empty guards with a fake client,
no network and no key."""

from __future__ import annotations

import pytest

from semianalyst.extract import ExtractionError
from semianalyst.extract.base import AnthropicModelClient, _parse_proposal


def test_parse_proposal_plain_json():
    assert _parse_proposal('{"entities": [], "claims": []}') == {"entities": [], "claims": []}


def test_parse_proposal_strips_prose_and_code_fence():
    fenced = "Here is the result:\n```json\n{\"entities\": [], \"claims\": []}\n```"
    assert _parse_proposal(fenced) == {"entities": [], "claims": []}


def test_parse_proposal_rejects_non_json():
    with pytest.raises(ExtractionError):
        _parse_proposal("I cannot help with that.")


class _Block:
    def __init__(self, type_: str, text: str) -> None:
        self.type = type_
        self.text = text


class _Resp:
    def __init__(self, stop_reason: str, content: list) -> None:
        self.stop_reason = stop_reason
        self.content = content


class _FakeMessages:
    def __init__(self, resp: _Resp) -> None:
        self._resp = resp

    def create(self, **kwargs) -> _Resp:
        return self._resp


class _FakeClient:
    def __init__(self, resp: _Resp) -> None:
        self.messages = _FakeMessages(resp)


def test_model_client_returns_text():
    resp = _Resp("end_turn", [_Block("text", '{"entities":[],"claims":[]}')])
    client = AnthropicModelClient("m", client=_FakeClient(resp))
    assert client.complete("sys", "doc") == '{"entities":[],"claims":[]}'


def test_model_client_raises_on_refusal():
    client = AnthropicModelClient("m", client=_FakeClient(_Resp("refusal", [])))
    with pytest.raises(ExtractionError):
        client.complete("sys", "doc")


def test_model_client_raises_on_empty_text():
    client = AnthropicModelClient("m", client=_FakeClient(_Resp("end_turn", [])))
    with pytest.raises(ExtractionError):
        client.complete("sys", "doc")
