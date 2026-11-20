"""Builders for NL2Logic to_dict()-shaped JSON, as upstream emits it:
every relation argument is a Constant, even under a quantifier."""


def const(name):
    return {"node_type": "Constant", "name": name}


def adj(adjective, obj):
    return {"node_type": "RelationAdjective", "adjective": adjective, "obj": const(obj)}


def intrans(verb, subject):
    return {"node_type": "RelationIntransitiveVerb", "verb": verb, "subject": const(subject)}


def trans(verb, subject, obj):
    return {"node_type": "RelationTransitiveVerb", "verb": verb,
            "subject": const(subject), "obj": const(obj)}


def ditrans(verb, subject, indirect_obj, direct_obj):
    return {"node_type": "RelationDitransitiveVerb", "verb": verb, "subject": const(subject),
            "direct_obj": const(direct_obj), "indirect_obj": const(indirect_obj)}


def q(quantifier, variable, sentence):
    return {"node_type": "QuantifiedSentence", "quantifier": quantifier,
            "variable": {"node_type": "Variable", "name": variable}, "sentence": sentence}


def forall(variable, sentence):
    return q("ForAll", variable, sentence)


def exists(variable, sentence):
    return q("ThereExists", variable, sentence)


def binop(operator, left, right):
    return {"node_type": "BinaryOperator", "operator": operator, "left": left, "right": right}


def neg(sentence):
    return {"node_type": "UnaryOperator", "operator": "Not", "sentence": sentence}


class ScriptedLLM:
    """Returns canned structured outputs in order, checking the expected type."""

    def __init__(self, *steps):
        self.steps = list(steps)

    def generate(self, text, fmt):
        expected = self.steps.pop(0)
        assert isinstance(expected, fmt), f"pipeline asked for {fmt.__name__}, script has {expected!r}"
        return expected
