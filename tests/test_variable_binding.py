import copy

import pytest

from helpers import adj, binop, const, ditrans, exists, forall, intrans, neg, trans
from prolog_emitter import formula_to_prolog
from variable_binding import NormalizationError, normalize


def prolog(ast, **options):
    doc = normalize(ast, **options)
    return formula_to_prolog(doc["formulas"][0]["formula"])


def codes(doc):
    return [d["code"] for d in doc["diagnostics"]]


def test_argument_matching_quantified_variable_becomes_variable():
    ast = forall("x", binop("If", trans("love", "x", "books"), adj("kind", "x")))
    doc = normalize(ast)
    body = doc["formulas"][0]["formula"]["body"]
    assert body["args"][0]["args"] == [
        {"type": "var", "name": "x", "prolog": "X"},
        {"type": "const", "name": "books", "atom": "books"},
    ]
    assert prolog(ast) == "forall(X, implies(love(X, books), kind(X)))"
    assert doc["diagnostics"] == []


def test_constants_are_preserved():
    ast = forall("x", binop("If", trans("love", "x", "Alice"), trans("love", "Alice", "x")))
    assert prolog(ast) == "forall(X, implies(love(X, alice), love(alice, X)))"
    doc = normalize(ast)
    assert doc["signature"]["constants"] == [{"atom": "alice", "names": ["Alice"]}]


def test_no_quantifier_means_no_variables():
    doc = normalize(trans("love", "Alice", "Bob"))
    assert formula_to_prolog(doc["formulas"][0]["formula"]) == "love(alice, bob)"
    assert doc["diagnostics"] == []


def test_nested_quantifiers_bind_independently():
    ast = forall("x", exists("y", trans("love", "x", "y")))
    assert prolog(ast) == "forall(X, exists(Y, love(X, Y)))"


def test_inner_scope_sees_outer_variable():
    ast = forall("x", binop("If", adj("person", "x"),
                            exists("y", binop("And", adj("book", "y"), trans("read", "x", "y")))))
    assert prolog(ast) == "forall(X, implies(person(X), exists(Y, and(book(Y), read(X, Y)))))"


def test_shadowing_binds_to_innermost_and_renames():
    # forall x. (p(x) and exists x. q(x)) and after the inner scope: r(x)
    inner = exists("x", adj("q", "x"))
    ast = forall("x", binop("And", binop("And", adj("p", "x"), inner), adj("r", "x")))
    doc = normalize(ast)
    assert prolog(ast) == "forall(X, and(and(p(X), exists(X_2, q(X_2))), r(X)))"
    shadow = [d for d in doc["diagnostics"] if d["code"] == "shadowed_variable"]
    assert len(shadow) == 1 and shadow[0]["severity"] == "info"
    assert shadow[0]["path"] == "/formulas/0/formula/body/args/0/args/1/var"


def test_variable_is_out_of_scope_after_its_quantifier():
    # (exists y. p(y)) and q(y): the second y is NOT bound
    ast = binop("And", exists("y", adj("p", "y")), adj("q", "y"))
    doc = normalize(ast)
    assert prolog(ast) == "and(exists(Y, p(Y)), q(y))"
    assert codes(doc) == ["unbound_variable_like"]
    assert doc["diagnostics"][0]["path"] == "/formulas/0/formula/args/1/args/0"
    right = doc["formulas"][0]["formula"]["args"][1]["args"][0]
    assert right == {"type": "const", "name": "y", "atom": "y"}


def test_sibling_quantifiers_reusing_a_name_get_distinct_variables():
    ast = binop("And", forall("x", adj("p", "x")), exists("x", adj("q", "x")))
    doc = normalize(ast)
    assert prolog(ast) == "and(forall(X, p(X)), exists(X_2, q(X_2)))"
    assert "shadowed_variable" not in codes(doc)  # siblings do not shadow


def test_triple_shadowing():
    ast = forall("x", binop("And", adj("a", "x"),
                            exists("x", binop("And", adj("b", "x"), forall("x", adj("c", "x"))))))
    assert prolog(ast) == "forall(X, and(a(X), exists(X_2, and(b(X_2), forall(X_3, c(X_3))))))"


def test_generated_name_does_not_collide_with_explicit_one():
    ast = forall("x_2", forall("x", exists("x", trans("r", "x", "x_2"))))
    out = prolog(ast)
    assert out == "forall(X_2, forall(_X, exists(X_3, r(X_3, X_2))))"


def test_unbound_variable_like_stays_constant_with_warning():
    doc = normalize(forall("x", trans("love", "x", "z")))
    assert formula_to_prolog(doc["formulas"][0]["formula"]) == "forall(X, love(X, z))"
    assert codes(doc) == ["unbound_variable_like"]
    assert doc["diagnostics"][0]["severity"] == "warning"


def test_tagged_variable_without_binder_stays_constant_with_warning():
    ast = trans("love", "Alice", "x")
    ast["obj"] = {"node_type": "Variable", "name": "x"}
    doc = normalize(ast)
    assert formula_to_prolog(doc["formulas"][0]["formula"]) == "love(alice, x)"
    assert codes(doc) == ["unbound_variable"]


def test_case_mismatch_is_constant_by_default_and_bound_on_request():
    ast = forall("x", adj("kind", "X"))
    doc = normalize(ast)
    assert codes(doc) == ["case_mismatch", "unused_quantifier"]
    assert prolog(ast) == "forall(_X, kind(x))"
    relaxed = normalize(ast, case_sensitive=False)
    assert relaxed["diagnostics"] == []
    assert prolog(ast, case_sensitive=False) == "forall(X, kind(X))"


def test_whitespace_around_argument_is_ignored():
    assert prolog(forall("x", adj("kind", " x "))) == "forall(X, kind(X))"


def test_variable_embedded_in_a_phrase_is_reported_not_bound():
    ast = forall("x", trans("love", "x", "the mother of x"))
    doc = normalize(ast)
    assert prolog(ast) == "forall(X, love(X, the_mother_of_x))"
    assert codes(doc) == ["embedded_variable"]


def test_unused_quantifier_is_reported():
    doc = normalize(forall("x", adj("happy", "Ani")))
    assert codes(doc) == ["unused_quantifier"]
    assert formula_to_prolog(doc["formulas"][0]["formula"]) == "forall(_X, happy(ani))"


def test_empty_variable_name_defaults_to_x():
    doc = normalize(forall("", adj("kind", "x")))
    assert formula_to_prolog(doc["formulas"][0]["formula"]) == "forall(X, kind(X))"
    assert codes(doc) == ["empty_variable_name"]


def test_connectives_and_negation():
    a, b = intrans("sing", "Alice"), intrans("dance", "Bob")
    assert prolog(binop("And", a, b)) == "and(sing(alice), dance(bob))"
    assert prolog(binop("Or", a, b)) == "or(sing(alice), dance(bob))"
    assert prolog(binop("IfAndOnlyIf", a, b)) == "iff(sing(alice), dance(bob))"
    assert prolog(neg(a)) == "not(sing(alice))"


def test_only_if_standard_and_upstream():
    ast = forall("x", binop("OnlyIf", adj("even", "x"), adj("divisible by two", "x")))
    assert prolog(ast) == "forall(X, implies(even(X), divisible_by_two(X)))"
    assert prolog(ast, only_if="upstream") == "forall(X, implies(divisible_by_two(X), even(X)))"


def test_only_if_upstream_keeps_diagnostic_paths_pointing_at_the_right_node():
    ast = binop("OnlyIf", adj("even", "z"), adj("odd", "Bob"))
    doc = normalize(ast, only_if="upstream")
    (diag,) = doc["diagnostics"]
    node = doc["formulas"][0]["formula"]
    for part in diag["path"].split("/")[4:]:
        node = node[int(part)] if part.isdigit() else node[part]
    assert node == {"type": "const", "name": "z", "atom": "z"}


def test_ditransitive_argument_order_and_roles():
    doc = normalize(forall("x", ditrans("give", "x", "Mary", "a book")))
    atom = doc["formulas"][0]["formula"]["body"]
    assert atom["roles"] == ["subject", "indirect_obj", "direct_obj"]
    assert formula_to_prolog(doc["formulas"][0]["formula"]) == "forall(X, give(X, mary, a_book))"


def test_symbols_become_prolog_safe_atoms_and_keep_their_source_text():
    doc = normalize(trans("Look At", "José", "42 things"))
    atom = doc["formulas"][0]["formula"]
    assert atom["pred"] == "look_at" and atom["source"]["text"] == "Look At"
    assert [t["atom"] for t in atom["args"]] == ["jose", "c_42_things"]
    assert atom["args"][0]["name"] == "José"


def test_reserved_predicate_is_renamed():
    doc = normalize(intrans("exists", "God"))
    assert doc["formulas"][0]["formula"]["pred"] == "exists_p"
    assert codes(doc) == ["reserved_predicate"]


def test_signature_lists_predicates_with_arity():
    ast = forall("x", binop("If", trans("love", "x", "books"), adj("kind", "x")))
    assert normalize(ast)["signature"]["predicates"] == [
        {"name": "kind", "arity": 1, "sources": ["kind"]},
        {"name": "love", "arity": 2, "sources": ["love"]},
    ]


def test_relational_logic_root_scopes_each_sentence_separately():
    root = {"node_type": "RelationalLogic", "original_sentence": "two sentences",
            "sentences": [forall("x", adj("p", "x")), adj("q", "x")]}
    doc = normalize(root)
    assert doc["source"] == "two sentences"
    assert [f["id"] for f in doc["formulas"]] == ["s1", "s2"]
    assert formula_to_prolog(doc["formulas"][1]["formula"]) == "q(x)"
    assert [(d["formula"], d["code"]) for d in doc["diagnostics"]] == [("s2", "unbound_variable_like")]


def test_bare_string_terms_are_accepted():
    ast = forall("x", {"node_type": "RelationAdjective", "adjective": "kind", "obj": "x"})
    assert prolog(ast) == "forall(X, kind(X))"


def test_input_is_not_mutated():
    ast = forall("x", binop("If", trans("love", "x", "books"), adj("kind", "x")))
    before = copy.deepcopy(ast)
    normalize(ast)
    assert ast == before


def test_malformed_input_raises_with_a_path():
    with pytest.raises(NormalizationError, match="/formulas/0/formula/body"):
        normalize(forall("x", {"node_type": "Mystery"}))
    with pytest.raises(NormalizationError):
        normalize(binop("Xor", adj("p", "a"), adj("q", "b")))


def test_accepts_upstream_pydantic_ast():
    from ast_rl import (BinaryOperator, Constant, QuantifiedSentence, RelationAdjective,
                        RelationTransitiveVerb, Variable)

    ast = QuantifiedSentence(
        quantifier="ForAll", variable=Variable(name="x"),
        sentence=BinaryOperator(
            operator="If",
            left=RelationTransitiveVerb(verb="love", subject=Constant(name="x"), obj=Constant(name="books")),
            right=RelationAdjective(adjective="kind", obj=Constant(name="x"))))
    assert prolog(ast) == "forall(X, implies(love(X, books), kind(X)))"
