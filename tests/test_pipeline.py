"""Pipeline tests that never touch the network: a scripted LLM for the parse
flow, and an httpx mock transport under the real OpenRouter SDK."""
import io
import json
import sys

import pytest

import structured_output as so
from pipeline import OpenRouterWrapper, Pipeline


from helpers import ScriptedLLM


def kind_script():
    # "Someone who loves books is kind" -> forall x. (love(x, books) -> kind(x))
    return ScriptedLLM(
        so.Rephrased(rephrased="For every person x, if x loves books then x is kind"),
        so.ChooseParser(answer="B"),
        so.QuantifiedParser(quantifier="ForAll", variable="x",
                            sentence_without_quantifier="if x loves books then x is kind"),
        so.ChooseParser(answer="C"),
        so.BinaryLogicalParser(operator="If", left_operand="x loves books", right_operand="x is kind"),
        so.ChooseParser(answer="A"),
        so.ChooseRelation(answer="C"),
        so.TransitiveParser(subject="x", verb="love", obj="books"),
        so.ChooseParser(answer="A"),
        so.ChooseRelation(answer="A"),
        so.AdjectiveParser(adjective="kind", obj="x"),
    )


def test_upstream_ast_tags_variables_as_constants_and_translate_fixes_it():
    upstream_ast = Pipeline(llm=kind_script()).rephrase_and_parse("Someone who loves books is kind")
    as_json = json.loads(json.dumps(upstream_ast.to_dict()))  # to_dict() is JSON-serializable
    assert as_json["sentence"]["left"]["subject"] == {"node_type": "Constant", "name": "x"}

    doc = Pipeline(llm=kind_script()).translate("Someone who loves books is kind")
    assert doc["source"] == "Someone who loves books is kind"
    assert doc["formulas"][0]["formula"]["body"]["args"][0]["args"][0] == {
        "type": "var", "name": "x", "prolog": "X"}
    assert doc["diagnostics"] == []


def test_translate_to_prolog():
    text = Pipeline(llm=kind_script()).translate_to_prolog("Someone who loves books is kind")
    assert text.splitlines()[-1] == "fol(s1, forall(X, implies(love(X, books), kind(X))))."


def test_unknown_backend_and_missing_model(monkeypatch):
    monkeypatch.delenv("NL2LOGIC_MODEL", raising=False)
    with pytest.raises(ValueError):
        Pipeline(llm="nope", model="m")
    with pytest.raises(ValueError):
        Pipeline(llm="openrouter")


def test_openrouter_requires_api_key(monkeypatch):
    pytest.importorskip("openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterWrapper("some/model")


def _mock_client(replies, seen):
    httpx = pytest.importorskip("httpx")
    openrouter = pytest.importorskip("openrouter")

    def handler(request):
        seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={
            "id": "gen-1", "object": "chat.completion", "created": 1, "model": "m",
            "system_fingerprint": None,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": replies.pop(0)}}]})

    return openrouter.OpenRouter(api_key="test-key",
                                 client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("temperature_options", [{}, {"temperature": None}], ids=["default", "none"])
def test_openrouter_wrapper_sends_strict_json_schema_and_parses_reply(temperature_options):
    seen = []
    wrapper = OpenRouterWrapper("vendor/model", client=_mock_client(['{"answer": "B"}'], seen),
                                **temperature_options)
    result = wrapper.generate("classify this", so.ChooseParser)
    assert result == so.ChooseParser(answer="B")

    url, body = seen[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert body["model"] == "vendor/model"
    assert body["messages"] == [{"role": "user", "content": "classify this"}]
    assert "temperature" not in body
    assert body["stream"] is False
    assert body["provider"] == {"require_parameters": True}
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "ChooseParser" and fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema["additionalProperties"] is False and schema["required"] == ["answer"]


@pytest.mark.parametrize("temperature", [0, 0.7])
def test_openrouter_wrapper_sends_explicit_temperature(temperature):
    seen = []
    wrapper = OpenRouterWrapper("vendor/model", client=_mock_client(['{"answer": "A"}'], seen),
                                temperature=temperature)
    assert wrapper.generate("classify this", so.ChooseParser) == so.ChooseParser(answer="A")
    assert seen[0][1]["temperature"] == temperature


def test_openrouter_wrapper_tolerates_fences_and_retries_bad_output():
    seen = []
    client = _mock_client(["not json at all", '```json\n{"answer": "D"}\n```'], seen)
    wrapper = OpenRouterWrapper("vendor/model", client=client, require_parameters=False)
    assert wrapper.generate("x", so.ChooseParser).answer == "D"
    assert len(seen) == 2 and "provider" not in seen[0][1]


def test_openrouter_wrapper_gives_up_after_attempts():
    client = _mock_client(['{"answer": "Z"}', '{"answer": "Z"}'], [])
    with pytest.raises(ValueError, match="did not return valid ChooseParser"):
        OpenRouterWrapper("vendor/model", client=client).generate("x", so.ChooseParser)


def test_cli_normalize(monkeypatch, capsys):
    import nl2prolog
    from helpers import adj, forall, trans

    ast = forall("x", trans("love", "x", "z"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(ast)))
    assert nl2prolog.main(["normalize", "-", "--strict"]) == 2  # warning: unbound 'z'
    assert json.loads(capsys.readouterr().out)["schema"] == "nl2logic-prolog/1"

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(forall("x", adj("kind", "x")))))
    assert nl2prolog.main(["normalize", "--format", "prolog"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "fol(s1, forall(X, kind(X)))."

    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert nl2prolog.main(["normalize"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "NormalizationError"
