"""Variable-binding normalization pass (fork addition).

Sits between NL2Logic's JSON AST and Prolog.

Upstream NL2Logic wraps *every* relation argument in ``Constant`` -- including
the ``x`` in ``forall x. kind(x)`` -- because the atomic parsers never see the
enclosing quantifier.  This pass repairs that:

* walks the AST, tracking the variables introduced by quantifiers;
* turns a relation argument into a variable when (and only when) it matches a
  variable that is in scope at that point;
* leaves every other argument as a constant;
* resolves nested quantifiers and shadowing by proper lexical scope: each
  quantifier opens a child scope, lookup goes innermost-first, and a scope ends
  where its quantifier's body ends.

Each binder gets a Prolog variable name that is unique within its formula
(``X``, ``X_2``, ...), so a shadowed ``x`` and the outer ``x`` can never be
confused downstream.

The pass never guesses.  Arguments that merely *look* like variables but are
not bound stay constants and are reported in ``diagnostics``.

Standard library only; the input is never mutated.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "nl2logic-prolog/1"

#: Functors the Prolog emitter uses for connectives and quantifiers.  A
#: predicate with one of these names is renamed so it cannot be mistaken for one.
RESERVED_PREDICATES = frozenset(
    {"forall", "exists", "and", "or", "implies", "iff", "not"}
)

_QUANTIFIERS = {"ForAll": "forall", "ThereExists": "exists"}
_BINARY = {"And": "and", "Or": "or", "If": "implies", "IfAndOnlyIf": "iff"}

# (predicate field, [(role, field), ...]) per upstream relation node.  Argument
# order follows upstream's ``__str__`` / Z3 output.
_RELATIONS: Dict[str, Tuple[str, List[str]]] = {
    "RelationAdjective": ("adjective", ["obj"]),
    "RelationIntransitiveVerb": ("verb", ["subject"]),
    "RelationTransitiveVerb": ("verb", ["subject", "obj"]),
    "RelationDitransitiveVerb": ("verb", ["subject", "indirect_obj", "direct_obj"]),
}

# "x", "y2", "z'" -- the shape the upstream prompts ask the LLM to use.
_VARIABLE_LIKE = re.compile(r"^[a-z]\d*'*$")
_TOKEN = re.compile(r"[A-Za-z0-9_']+")


class NormalizationError(ValueError):
    """The input is not a well-formed NL2Logic AST."""


# --------------------------------------------------------------------------- #
# Lexical scope
# --------------------------------------------------------------------------- #
@dataclass
class Binding:
    """One variable introduced by one quantifier."""

    name: str        # as written in the AST, e.g. "x"
    key: str         # what arguments are matched against
    prolog: str      # Prolog variable name, unique within the formula
    quantifier: str  # "forall" | "exists"
    path: str        # where the binder sits in the output
    uses: int = 0


class Scope:
    """Immutable chain of bindings; a child never alters its parent."""

    __slots__ = ("parent", "binding")

    def __init__(self, parent: Optional["Scope"] = None,
                 binding: Optional[Binding] = None) -> None:
        self.parent = parent
        self.binding = binding

    def child(self, binding: Binding) -> "Scope":
        return Scope(self, binding)

    def lookup(self, key: str) -> Optional[Binding]:
        """Innermost binding for ``key``, or None."""
        scope: Optional[Scope] = self
        while scope is not None:
            if scope.binding is not None and scope.binding.key == key:
                return scope.binding
            scope = scope.parent
        return None

    def visible(self) -> List[Binding]:
        """Bindings visible here, innermost first, shadowed ones omitted."""
        seen, out = set(), []
        scope: Optional[Scope] = self
        while scope is not None:
            b = scope.binding
            if b is not None and b.key not in seen:
                seen.add(b.key)
                out.append(b)
            scope = scope.parent
        return out


# --------------------------------------------------------------------------- #
# Symbol helpers
# --------------------------------------------------------------------------- #
def to_atom(text: str, prefix: str) -> str:
    """Map free text to an unquoted Prolog atom (``[a-z][a-z0-9_]*``).

    "Alice" -> alice, "very tired" -> very_tired, "to read a book" ->
    to_read_a_book.  ``prefix`` is used when the result would otherwise be
    empty or start with a digit.
    """
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    atom = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    if not atom:
        return f"{prefix}_unnamed"
    if not atom[0].isalpha():
        return f"{prefix}_{atom}"
    return atom


def _prolog_var_base(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
    if not base or not base[0].isalpha():
        base = "V" + base
    return base[0].upper() + base[1:]


def _plain(node: Any) -> Any:
    """Accept upstream pydantic nodes as well as plain dicts."""
    if isinstance(node, dict):
        return node
    to_dict = getattr(node, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return node


def _term_name(term: Any, path: str) -> Tuple[str, bool]:
    """Return (name, tagged_as_variable) for a Constant/Variable/str term."""
    term = _plain(term)
    if isinstance(term, str):
        return term, False
    if isinstance(term, dict) and isinstance(term.get("name"), str):
        return term["name"], term.get("node_type") == "Variable"
    raise NormalizationError(f"{path}: expected a Constant or Variable, got {term!r}")


# --------------------------------------------------------------------------- #
# The pass
# --------------------------------------------------------------------------- #
@dataclass
class _Normalizer:
    case_sensitive: bool = True
    only_if: str = "standard"
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    predicates: Dict[Tuple[str, int], set] = field(default_factory=dict)
    constants: Dict[str, set] = field(default_factory=dict)
    _formula_id: str = ""
    _used_vars: set = field(default_factory=set)

    # -- bookkeeping -------------------------------------------------------- #
    def _diag(self, severity: str, code: str, path: str, message: str) -> None:
        self.diagnostics.append({
            "severity": severity,
            "code": code,
            "formula": self._formula_id,
            "path": path,
            "message": message,
        })

    def _key(self, name: str) -> str:
        key = name.strip()
        return key if self.case_sensitive else key.casefold()

    def _fresh_var(self, name: str) -> str:
        base = _prolog_var_base(name)
        candidate, n = base, 1
        while candidate in self._used_vars:
            n += 1
            candidate = f"{base}_{n}"
        self._used_vars.add(candidate)
        return candidate

    # -- entry point -------------------------------------------------------- #
    def formula(self, node: Any, formula_id: str, path: str) -> Dict[str, Any]:
        self._formula_id = formula_id
        self._used_vars = set()  # Prolog variables are scoped to one clause
        return self._sentence(node, Scope(), path)

    # -- sentences ---------------------------------------------------------- #
    def _sentence(self, node: Any, scope: Scope, path: str) -> Dict[str, Any]:
        node = _plain(node)
        if not isinstance(node, dict):
            raise NormalizationError(f"{path}: expected an AST node, got {node!r}")
        kind = node.get("node_type")
        if kind == "QuantifiedSentence":
            return self._quantified(node, scope, path)
        if kind == "BinaryOperator":
            return self._binary(node, scope, path)
        if kind == "UnaryOperator":
            if node.get("operator") != "Not":
                raise NormalizationError(
                    f"{path}: unknown unary operator {node.get('operator')!r}")
            return {"type": "not",
                    "arg": self._sentence(node.get("sentence"), scope, path + "/arg")}
        if kind in _RELATIONS:
            return self._relation(node, kind, scope, path)
        raise NormalizationError(f"{path}: unknown node_type {kind!r}")

    def _quantified(self, node: Dict[str, Any], scope: Scope, path: str) -> Dict[str, Any]:
        try:
            quantifier = _QUANTIFIERS[node.get("quantifier")]
        except KeyError:
            raise NormalizationError(
                f"{path}: unknown quantifier {node.get('quantifier')!r}") from None
        name, _ = _term_name(node.get("variable"), path + "/var")
        name = name.strip()
        if not name:
            name = "x"  # same default upstream's pipeline applies
            self._diag("warning", "empty_variable_name", path + "/var",
                       "Quantifier had no variable name; using 'x'.")
        key = self._key(name)

        outer = scope.lookup(key)
        binding = Binding(name=name, key=key, prolog=self._fresh_var(name),
                          quantifier=quantifier, path=path)
        if outer is not None:
            self._diag("info", "shadowed_variable", path + "/var",
                       f"'{name}' ({binding.prolog}) shadows the '{outer.name}' "
                       f"bound at {outer.path} ({outer.prolog}) inside this quantifier.")

        # The child scope exists only for the body: once we return, the caller
        # still holds `scope`, so the variable is out of scope for siblings.
        body = self._sentence(node.get("sentence"), scope.child(binding), path + "/body")

        if binding.uses == 0:
            self._diag("warning", "unused_quantifier", path + "/var",
                       f"Variable '{name}' ({binding.prolog}) is never used in the "
                       "body of its quantifier.")
        return {
            "type": quantifier,
            "var": {"type": "var", "name": name, "prolog": binding.prolog},
            "body": body,
        }

    def _binary(self, node: Dict[str, Any], scope: Scope, path: str) -> Dict[str, Any]:
        operator = node.get("operator")
        left = self._sentence(node.get("left"), scope, path + "/args/0")
        right = self._sentence(node.get("right"), scope, path + "/args/1")
        if operator == "OnlyIf":
            # "P only if Q" (left = P, right = Q) is P -> Q.  Upstream's Z3
            # backend emits Implies(Q, P) instead; only_if="upstream" mirrors it.
            if self.only_if == "upstream":
                # Operands swap after the walk, so diagnostics already recorded
                # under this node must follow them to their new position.
                self._swap_paths(path)
                left, right = right, left
            return {"type": "implies", "args": [left, right],
                    "source_operator": "OnlyIf"}
        if operator not in _BINARY:
            raise NormalizationError(f"{path}: unknown binary operator {operator!r}")
        return {"type": _BINARY[operator], "args": [left, right]}

    def _swap_paths(self, path: str) -> None:
        a, b = path + "/args/0", path + "/args/1"
        for d in self.diagnostics:
            if d["formula"] != self._formula_id:
                continue
            for old, new in ((a, b), (b, a)):
                if d["path"] == old or d["path"].startswith(old + "/"):
                    d["path"] = new + d["path"][len(old):]
                    break

    # -- relations and terms ------------------------------------------------ #
    def _relation(self, node: Dict[str, Any], kind: str, scope: Scope,
                  path: str) -> Dict[str, Any]:
        pred_field, roles = _RELATIONS[kind]
        text = node.get(pred_field)
        if not isinstance(text, str):
            raise NormalizationError(f"{path}: missing '{pred_field}'")
        pred = to_atom(text, "p")
        if pred == "p_unnamed":
            self._diag("warning", "empty_symbol", path,
                       f"Predicate text {text!r} has no usable characters.")
        if pred in RESERVED_PREDICATES:
            self._diag("info", "reserved_predicate", path,
                       f"Predicate '{pred}' collides with a logical functor; "
                       f"renamed to '{pred}_p'.")
            pred += "_p"

        args = []
        for i, role in enumerate(roles):
            if role not in node:
                raise NormalizationError(f"{path}: missing '{role}'")
            args.append(self._term(node[role], scope, f"{path}/args/{i}"))

        self.predicates.setdefault((pred, len(args)), set()).add(text)
        return {"type": "atom", "pred": pred, "args": args, "roles": list(roles),
                "source": {"node_type": kind, "text": text}}

    def _term(self, term: Any, scope: Scope, path: str) -> Dict[str, Any]:
        name, tagged_variable = _term_name(term, path)
        key = self._key(name)

        binding = scope.lookup(key)
        if binding is not None:
            binding.uses += 1
            return {"type": "var", "name": binding.name, "prolog": binding.prolog}

        # Not bound here: it stays a constant.  Report near-misses.
        visible = scope.visible()
        folded = key.casefold()
        tokens = {self._key(t) for t in _TOKEN.findall(name)}
        case_twin = next((b for b in visible if b.key.casefold() == folded), None)
        if tagged_variable:
            self._diag("warning", "unbound_variable", path,
                       f"'{name}' is tagged as a variable but no enclosing "
                       "quantifier binds it; kept as a constant.")
        elif case_twin is not None:
            self._diag("warning", "case_mismatch", path,
                       f"'{name}' differs only by case from in-scope variable "
                       f"'{case_twin.name}'; kept as a constant "
                       "(use case_sensitive=False to bind it).")
        elif _VARIABLE_LIKE.match(key):
            self._diag("warning", "unbound_variable_like", path,
                       f"'{name}' looks like a variable but no enclosing "
                       "quantifier binds it; kept as a constant.")
        else:
            inside = [b.name for b in visible if b.key in tokens]
            if inside:
                self._diag("warning", "embedded_variable", path,
                           f"Constant '{name}' mentions in-scope variable(s) "
                           f"{', '.join(repr(n) for n in inside)}; kept as one "
                           "opaque constant, so that reference is not bound.")

        atom = to_atom(name, "c")
        if atom == "c_unnamed":
            self._diag("warning", "empty_symbol", path,
                       f"Constant text {name!r} has no usable characters.")
        self.constants.setdefault(atom, set()).add(name)
        return {"type": "const", "name": name, "atom": atom}


def normalize(ast: Any, *, case_sensitive: bool = True,
              only_if: str = "standard") -> Dict[str, Any]:
    """Normalize an NL2Logic AST into Prolog-oriented JSON.

    ``ast`` is a sentence node or a ``RelationalLogic`` node, either as the
    dict produced by ``to_dict()`` or as the upstream pydantic object.

    case_sensitive
        ``True`` (default): an argument binds only if it equals the variable
        name exactly (surrounding whitespace ignored).  ``False``: ``X`` also
        binds to a quantifier's ``x``.
    only_if
        ``"standard"`` (default): "P only if Q" becomes ``implies(P, Q)``.
        ``"upstream"``: ``implies(Q, P)``, matching upstream's Z3 output.
    """
    if only_if not in ("standard", "upstream"):
        raise ValueError("only_if must be 'standard' or 'upstream'")
    ast = _plain(ast)
    if not isinstance(ast, dict):
        raise NormalizationError(f"expected an AST node, got {ast!r}")

    if ast.get("node_type") == "RelationalLogic":
        source = ast.get("original_sentence")
        sentences = ast.get("sentences")
        if not isinstance(sentences, list):
            raise NormalizationError("RelationalLogic: 'sentences' must be a list")
    else:
        source, sentences = None, [ast]

    n = _Normalizer(case_sensitive=case_sensitive, only_if=only_if)
    formulas = []
    for i, sentence in enumerate(sentences):
        formula_id = f"s{i + 1}"
        formulas.append({
            "id": formula_id,
            "formula": n.formula(sentence, formula_id, f"/formulas/{i}/formula"),
        })

    return {
        "schema": SCHEMA,
        "source": source,
        "formulas": formulas,
        "signature": {
            "predicates": [
                {"name": name, "arity": arity, "sources": sorted(texts)}
                for (name, arity), texts in sorted(n.predicates.items())
            ],
            "constants": [
                {"atom": atom, "names": sorted(names)}
                for atom, names in sorted(n.constants.items())
            ],
        },
        "diagnostics": n.diagnostics,
    }
