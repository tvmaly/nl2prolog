import json
import os
import shutil
import subprocess

import pytest

from helpers import adj, binop, exists, forall, trans
from prolog_emitter import EmitError, formula_to_prolog, quote_atom, to_prolog
from variable_binding import normalize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADOWED = forall("x", binop("And", binop("And", adj("p", "x"), exists("x", trans("q", "x", "Alice"))),
                             adj("r", "x")))
swipl = pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog not installed")


def run_swipl(goal, *files):
    load = ", ".join("consult('%s')" % f for f in files)
    result = subprocess.run(["swipl", "-q", "-g", f"{load}, {goal}", "-t", "halt"],
                            capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def test_quote_atom():
    assert quote_atom("alice") == "alice"
    assert quote_atom("Alice") == "'Alice'"
    assert quote_atom("it's") == "'it\\'s'"


def test_file_layout():
    doc = normalize(forall("x", trans("love", "x", "z")))
    doc["source"] = "Everyone\nloves z"
    text = to_prolog(doc)
    lines = text.splitlines()
    assert lines[1] == "% source: Everyone loves z"
    assert lines[2].startswith("% warning [unbound_variable_like] s1:")
    assert lines[-1] == "fol(s1, forall(X, love(X, z)))."
    assert to_prolog(doc, functor="axiom", diagnostics=False).splitlines()[-1].startswith("axiom(s1, ")


def test_free_variable_is_rejected():
    formula = {"type": "atom", "pred": "p", "args": [{"type": "var", "name": "x", "prolog": "X"}]}
    with pytest.raises(EmitError, match="free variable X"):
        formula_to_prolog(formula)


def test_same_name_bound_twice_in_nested_scopes_is_rejected():
    var = {"type": "var", "name": "x", "prolog": "X"}
    inner = {"type": "exists", "var": var, "body": {"type": "atom", "pred": "p", "args": [var]}}
    with pytest.raises(EmitError, match="bound twice"):
        formula_to_prolog({"type": "forall", "var": var, "body": inner})


@swipl
def test_emitted_file_consults_cleanly_and_shares_variables(tmp_path):
    doc = normalize({"node_type": "RelationalLogic", "original_sentence": "t",
                     "sentences": [SHADOWED, forall("x", adj("happy", "Ani"))]})
    path = tmp_path / "out.pl"
    path.write_text(to_prolog(doc))
    goal = ("fol(s1, forall(X, and(and(p(A), exists(Y, q(B, C))), r(D)))), "
            "A == X, D == X, B == Y, X \\== Y, C == alice, "
            "fol(s2, forall(Z, happy(ani))), var(Z), write(ok)")
    code, out, err = run_swipl(goal, str(path))
    assert (code, out, err) == (0, "ok", "")  # empty stderr: no singleton warnings


@swipl
def test_fol_json_loader_agrees_with_emitter(tmp_path):
    doc = normalize(SHADOWED)
    json_path, pl_path = tmp_path / "out.json", tmp_path / "out.pl"
    json_path.write_text(json.dumps(doc))
    pl_path.write_text(to_prolog(doc))
    goal = (f"load_fol_json('{json_path}', [s1-F]), fol(s1, G), "
            "(F =@= G -> write(same) ; write(different))")
    code, out, err = run_swipl(goal, os.path.join(ROOT, "fol_json.pl"), str(pl_path))
    assert (code, out, err) == (0, "same", "")


@swipl
def test_fol_json_loader_uses_lexical_scope_even_with_reused_names(tmp_path):
    # Hand-written JSON that reuses "X" for a nested binder: innermost must win.
    var = {"type": "var", "name": "x", "prolog": "X"}
    doc = {"formulas": [{"id": "s1", "formula": {
        "type": "forall", "var": var, "body": {"type": "and", "args": [
            {"type": "exists", "var": var, "body": {"type": "atom", "pred": "q", "args": [var]}},
            {"type": "atom", "pred": "r", "args": [var]}]}}}]}
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(doc))
    goal = (f"load_fol_json('{path}', [s1-forall(X, and(exists(Y, q(A)), r(B)))]), "
            "A == Y, B == X, X \\== Y, write(ok)")
    code, out, err = run_swipl(goal, os.path.join(ROOT, "fol_json.pl"))
    assert (code, out, err) == (0, "ok", "")
