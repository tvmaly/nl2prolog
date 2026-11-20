import pytest

from pipeline import Pipeline
from prolog_emitter import formula_to_prolog
from scripted_translations import script
from helpers import ScriptedLLM
from translation_cases import INPUTS, READINGS, WRONG


def formula_tree(node):
    kind = node["type"]
    if kind in ("forall", "exists"):
        return kind, node["var"]["prolog"], formula_tree(node["body"])
    if kind == "not":
        return "not", formula_tree(node["arg"])
    if kind == "atom":
        args = [t["prolog"] if t["type"] == "var" else t["atom"] for t in node["args"]]
        return (node["pred"], *args)
    return (kind, *(formula_tree(arg) for arg in node["args"]))


def canonical(term, scope=()):
    if isinstance(term, str):
        if term in scope:
            return ("bound", scope.index(term))
        return ("constant", term)
    head, *args = term
    if head in ("exists", "forall"):
        var, body = args
        return head, canonical(body, (var, *scope))
    children = [canonical(arg, scope) for arg in args]
    if head in ("and", "or"):
        children.sort()
    return (head, *children)


def matches(case, term):
    return any(canonical(term) == canonical(ref) for ref in READINGS[case])


def check_document(case_id, doc):
    assert len(doc["formulas"]) == 1, doc
    formula = doc["formulas"][0]["formula"]
    case = case_id.split("-")[0]
    assert matches(case, formula_tree(formula)), (
        f"Input: {INPUTS[case_id]}\nExpected one of: {READINGS[case]}\n"
        f"Actual: {formula_to_prolog(formula)}\nDiagnostics: {doc['diagnostics']}"
    )


@pytest.mark.parametrize("case", WRONG)
def test_reject_wrong_meaning(case):
    assert not matches(case, WRONG[case])


@pytest.mark.parametrize("case", INPUTS)
def test_scripted_translation(case):
    backend = ScriptedLLM(*script(case))
    check_document(case, Pipeline(llm=backend).translate(INPUTS[case]))
    assert not backend.steps


def test_negated_universal_accepts_existential_counterexample():
    assert matches("C", ("exists", "Z", ("and", ("not", ("read", "Z", "atlas")),
                                         ("reviewer", "Z"))))


def test_disjunct_order_and_bound_variable_spelling():
    assert matches("F", ("iff", ("smile", "mira"), ("or", ("dance", "pip"), ("sing", "noor"))))
    assert matches("D", ("forall", "P", ("implies", ("reviewer", "P"),
                        ("implies", ("approve", "P", "atlas"), ("and", ("trust", "P", "mira"),
                                                                   ("read", "P", "atlas"))))))


@pytest.mark.live
@pytest.mark.parametrize("case", INPUTS)
def test_live_translation(case):
    pipeline = Pipeline()
    try:
        doc = pipeline.translate(INPUTS[case])
    finally:
        pipeline.llm.close()
    check_document(case, doc)
