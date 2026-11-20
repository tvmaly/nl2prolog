"""Scripted intermediate English and structured replies for the offline pipeline tests."""
import structured_output as so


def atom(text, relation, **fields):
    parser, option = {
        "adjective": (so.AdjectiveParser, "A"),
        "intransitive": (so.IntransitiveParser, "B"),
        "transitive": (so.TransitiveParser, "C"),
    }[relation]
    return text, [so.ChooseParser(answer="A"), so.ChooseRelation(answer=option), parser(**fields)]


def binary(text, operator, left, right):
    reply = so.BinaryLogicalParser(operator=operator, left_operand=left[0], right_operand=right[0])
    return text, [so.ChooseParser(answer="C"), reply, *left[1], *right[1]]


def quantified(text, quantifier, variable, body):
    reply = so.QuantifiedParser(quantifier=quantifier, variable=variable,
                                sentence_without_quantifier=body[0])
    return text, [so.ChooseParser(answer="B"), reply, *body[1]]


def negated(body):
    reply = so.UnaryLogicalParser(operator="Not", operand=body[0])
    return "It is not true that " + body[0], [so.ChooseParser(answer="D"), reply, *body[1]]


def script(case):
    reviewer = atom("r is a reviewer", "adjective", adjective="reviewer", obj="r")
    report = atom("s is a report", "adjective", adjective="report", obj="s")
    read = atom("r reads s", "transitive", verb="read", subject="r", obj="s")
    atlas = atom("r reads Atlas", "transitive", verb="read", subject="r", obj="Atlas")

    if case == "A":
        description = binary("r reads s and s is a report", "And", read, report)
        some_report = quantified("there is an s such that " + description[0],
                                 "ThereExists", "s", description)
        rule = binary("if r is a reviewer then " + some_report[0], "If", reviewer, some_report)
        root = quantified("for every r, " + rule[0], "ForAll", "r", rule)
    elif case == "B":
        rule = binary("if r is a reviewer then r reads s", "If", reviewer, read)
        all_read = quantified("for every r, " + rule[0], "ForAll", "r", rule)
        description = binary("s is a report and " + all_read[0], "And", report, all_read)
        root = quantified("there exists an s such that " + description[0],
                          "ThereExists", "s", description)
    elif case == "C":
        rule = binary("if r is a reviewer then r reads Atlas", "If", reviewer, atlas)
        root = negated(quantified("for every r, " + rule[0], "ForAll", "r", rule))
    elif case == "D":
        trust = atom("r trusts Mira", "transitive", subject="r", verb="trust", obj="Mira")
        approve = atom("r approves Atlas", "transitive", subject="r", verb="approve", obj="Atlas")
        conditions = binary("r reads Atlas and r trusts Mira", "And", atlas, trust)
        only_if = binary("r approves Atlas only if " + conditions[0], "OnlyIf", approve, conditions)
        rule = binary("if r is a reviewer then " + only_if[0], "If", reviewer, only_if)
        root = quantified("for every r, " + rule[0], "ForAll", "r", rule)
    elif case.startswith("E-"):
        call = atom("Mira calls Noor", "transitive", subject="Mira", verb="call", obj="Noor")
        text = "Pip is thanked by Noor" if case == "E-passive" else "Noor thanks Pip"
        thanks = atom(text, "transitive", subject="Noor", verb="thank", obj="Pip")
        root = binary("if Mira calls Noor then " + text, "If", call, thanks)
    elif case == "F":
        smile = atom("Mira smiles", "intransitive", subject="Mira", verb="smile")
        sing = atom("Noor sings", "intransitive", subject="Noor", verb="sing")
        dance = atom("Pip dances", "intransitive", subject="Pip", verb="dance")
        music = binary("Noor sings or Pip dances", "Or", sing, dance)
        root = binary("Mira smiles if and only if " + music[0], "IfAndOnlyIf", smile, music)
    else:
        raise ValueError(case)
    return [so.Rephrased(rephrased=root[0]), *root[1]]
