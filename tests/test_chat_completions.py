import json
import sys

import httpx
import openai
import pytest

import nl2prolog
from pipeline import Pipeline
from structured_output import ChooseParser


def mock_gateway(monkeypatch, handler):
    constructor = openai.OpenAI
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: constructor(
        **kw, http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    monkeypatch.setenv("OPENAI_API_KEY", "configured-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("NL2LOGIC_MODEL", "configured-model")


def success(content, **fields):
    message = {"role": "assistant", "content": content, **fields}
    return {"choices": [{"message": message, "finish_reason": "stop", "index": 0}]}


@pytest.mark.parametrize("endpoint,is_router", [
    ("https://openrouter.ai/api/v1/", True), ("https://gateway.example/v1", False)])
def test_request_and_metadata(monkeypatch, endpoint, is_router):
    seen, metadata = [], []
    replies = iter(["bad output", '{"answer":"B"}'])
    def handler(request):
        seen.append(json.loads(request.content))
        assert str(request.url) == endpoint.rstrip("/") + "/chat/completions"
        assert request.headers["authorization"] == "Bearer explicit"
        return httpx.Response(200, json=success(next(replies)), headers={
            "X-Spend-Input": "0.01", "Budget": "5", "Ignored": "abc"})
    mock_gateway(monkeypatch, handler)
    monkeypatch.setenv("NL2LOGIC_COST_HEADERS", "x-spend-*,budget")
    llm = Pipeline(model="explicit-model", base_url=endpoint, api_key="explicit",
                   temperature=0, metadata_callback=metadata.append).llm
    assert llm.generate("classify", ChooseParser).answer == "B"
    assert len(seen) == 2
    for body in seen:
        assert body["model"] == "explicit-model" and body["temperature"] == 0
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
        assert body.get("provider") == ({"require_parameters": True} if is_router else None)
    assert [r["attempt"] for r in metadata] == [1, 2]
    assert all(r["headers"] == {"x-spend-input":"0.01", "budget":"5"} for r in metadata)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_hard_errors(monkeypatch, status):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"error":{"message":"gateway denied request"}},
                              headers={"gateway-trace":"t123"})
    mock_gateway(monkeypatch, handler)
    monkeypatch.setenv("NL2LOGIC_TRACE_HEADERS", "gateway-trace")
    with pytest.raises(RuntimeError, match=f"HTTP {status}.*t123"):
        Pipeline().llm.generate("classify", ChooseParser)
    assert len(seen) == 1


@pytest.mark.parametrize("ending", ["stop", "length", None, "refusal"])
def test_stream_completion(monkeypatch, ending):
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] and "temperature" not in body
        events = []
        for content, reason in [('{"answer":', None), ('"A"}', None)]:
            events.append({"choices":[{"index":0, "delta":{"content":content}, "finish_reason":reason}]})
        if ending:
            delta = {"refusal":"declined"} if ending == "refusal" else {}
            events.append({"choices":[{"index":0, "delta":delta, "finish_reason":ending}]})
        data = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, text=data, headers={"content-type":"text/event-stream"})
    mock_gateway(monkeypatch, handler)
    llm = Pipeline(stream=True).llm
    if ending == "stop":
        assert llm.generate("classify", ChooseParser).answer == "A"
    else:
        with pytest.raises(RuntimeError):
            llm.generate("classify", ChooseParser)


def test_cli_translation(monkeypatch, capsys):
    replies = iter([{"answer":"A"}, {"answer":"A"}, {"adjective":"kind", "obj":"Alice"}])
    def handler(request):
        assert json.loads(request.content)["model"] == "configured-model"
        return httpx.Response(200, json=success(json.dumps(next(replies))))
    mock_gateway(monkeypatch, handler)
    assert nl2prolog.main(["translate", "Alice is kind", "--no-rephrase", "--verbose",
                           "--format", "prolog"]) == 0
    captured = capsys.readouterr()
    assert "fol(s1, kind(alice))." in captured.out
    assert '"schema": "AdjectiveParser"' in captured.err


def test_requires_explicit_endpoint(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        Pipeline(model="m")


@pytest.mark.parametrize("backend", ["ollama", "openrouter"])
def test_optional_dependency_message(monkeypatch, backend):
    monkeypatch.setitem(sys.modules, backend, None)
    with pytest.raises(ImportError, match=f"pip install {backend}"):
        Pipeline(llm=backend, model="m").llm.generate("classify", ChooseParser)
