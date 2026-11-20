"""Original English inputs and accepted readings, written independently of parser replies."""

INPUTS = {
    "A": "For each reviewer, there is at least one report that the reviewer reads.",
    "B": "There is a report that every reviewer reads.",
    "C": "Not every reviewer reads Atlas.",
    "D": "A reviewer approves Atlas only if that reviewer has read Atlas and trusts Mira.",
    "E-active": "If Mira calls Noor, Noor thanks Pip.",
    "E-passive": "If Mira calls Noor, Pip is thanked by Noor.",
    "F": "Mira smiles if and only if Noor sings or Pip dances.",
}

reviewer = ("reviewer", "X")
report = ("report", "Y")
read = ("read", "X", "Y")
atlas = ("read", "X", "atlas")
approve = ("approve", "X", "atlas")
conditions = ("and", atlas, ("trust", "X", "mira"))
call = ("call", "mira", "noor")
thanks = ("thank", "noor", "pip")
music = ("or", ("sing", "noor"), ("dance", "pip"))

READINGS = {
    "A": [("forall", "X", ("implies", reviewer, ("exists", "Y", ("and", report, read))))],
    "B": [("exists", "Y", ("and", report, ("forall", "X", ("implies", reviewer, read))))],
    "C": [("not", ("forall", "X", ("implies", reviewer, atlas))),
          ("exists", "X", ("and", reviewer, ("not", atlas)))],
    "D": [("forall", "X", ("implies", ("and", reviewer, approve), conditions)),
          ("forall", "X", ("implies", reviewer, ("implies", approve, conditions)))],
    "E": [("implies", call, thanks)],
    "F": [("iff", ("smile", "mira"), music)],
}

WRONG = {
    "A": READINGS["B"][0],
    "B": READINGS["A"][0],
    "C": ("forall", "X", ("implies", reviewer, ("not", atlas))),
    "D": ("forall", "X", ("implies", reviewer, ("implies", conditions, approve))),
    "E": ("implies", call, ("thank", "pip", "noor")),
    "F": ("implies", ("smile", "mira"), music),
}
