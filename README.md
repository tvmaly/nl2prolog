# nl2prolog: Turn plain English into facts and rules computers can check

What if a computer could do more than just read your documentation? What if it could understand the relationships and rules you've written down, answer questions about them, and help find information that doesn't agree?

nl2prolog uses AI to turn everyday English into structured facts and rules that software can work with. Instead of relying only on an AI model to interpret information each time, you can turn that information into a logical structure that can be inspected, reused, and checked.

## What can you use it for?

Understand how systems connect. Describe your applications, databases, and their dependencies in plain English. Then use the resulting logic to help answer questions like "Which systems depend on this database?"

Check business rules. Convert written policies or requirements into rules that a computer can evaluate. For example, "Only managers can approve expenses over $5,000."

Find conflicting information. If one document says a customer must be 18 to open an account and another says the minimum age is 21, structured logic can help identify the disagreement when appropriate checks are applied.

Make AI agents more reliable. Give AI agents a structured set of facts and rules they can consult instead of relying entirely on their ability to interpret text or remember earlier instructions.

## How does it work?

nl2prolog uses a large language model (LLM) to translate English into a structured form of logic. It can produce JSON for use in other programs or Prolog terms for working with a logic programming system.

Prolog is a programming language designed to work with facts, relationships, and rules. It lets you ask questions and check whether conclusions follow from the information you've provided.

The goal is to combine two strengths: AI's ability to understand everyday language and logic programming's ability to reason through explicit rules.

AI-generated translations still need to be reviewed. Turning text into logic makes information easier to check, but it doesn't guarantee that the original information or its translation is correct.

## Project background

nl2prolog is a fork of [NL2Logic](https://github.com/peng-gao-lab/nl2logic), which converts natural language into first-order logic (FOL), a way of representing facts, relationships, and rules mathematically.

This fork adds OpenRouter support for accessing language models, improvements to how logical variables are handled, and Prolog output.

See [Acknowledgments and license](#acknowledgments-and-license) for credit and license notices.

## From English to a Prolog term

Start with a statement:

> Everyone who loves books is kind.

An illustrative Prolog representation is:

```prolog
fol(s1, forall(X, implies(love(X, books), kind(X)))).
```

Read the inner formula as: “For every `X`, if `X` loves books, then `X` is kind.”

- `fol(s1, ...)` stores a formula with the identifier `s1`.
- `X` is a variable shared by the quantifier and both relationships.
- `love(X, books)` and `kind(X)` are predicates: statements about objects.
- `forall` represents “for every,” and `implies` represents “if … then …”.

The output stores the formula as data in Prolog. Applying its logical meaning requires
an evaluator, a rule compiler, or a reasoner you supply.

## Why this is useful

An English explanation can hide ambiguity about who a statement refers to or which
condition implies another. A structured formula makes those choices visible. You can
inspect the language model's interpretation, check variable bindings, and pass the
result to your own logic-processing code.

Use nl2prolog to learn how natural language maps to logic, prototype inputs for a Prolog
application, or experiment with a pipeline that combines LLM interpretation with explicit
symbolic representations. Review translations against the original text: valid structure
alone does not establish that a model captured the intended meaning.

## How the translation works

```text
English statement
  → LLM rephrasing and recursive parsing
  → abstract syntax tree (AST)
  → variable-binding normalization
  → JSON or Prolog terms
```

An **abstract syntax tree** represents the parts of a formula and how they fit together.
NL2Logic's parsers build that tree through several structured model responses. The
normalization pass then connects variable references to their quantifiers and prepares
names for Prolog. The final emitter renders the normalized structure as Prolog text.

Translation can make several model calls for one statement. Normalization and emission
run locally and use no model calls.

## Quick start

Translation requires **Python 3.10 or newer**, a bearer credential, and a Chat
Completions endpoint and model that accept strict JSON Schema. Install SWI-Prolog to
load the generated formulas.

### Install and configure

```bash
git clone https://github.com/tvmaly/nl2prolog.git
cd nl2prolog
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .

# Example using OpenRouter with the default OpenAI Python client
export OPENAI_BASE_URL="https://openrouter.ai/api/v1"
export OPENAI_API_KEY="$OPENROUTER_API_KEY"
export NL2LOGIC_MODEL="openai/gpt-6-luna"
```

For another compatible service, set its versioned base URL, bearer token, and model ID.
The client appends `/chat/completions` to the base URL. Translation also reads these
variables from a local `.env` file. Explicit arguments take precedence over environment
settings. The default client requires an explicit endpoint.

### Translate a statement

Installation adds the `nl2prolog` command and places the SWI-Prolog JSON loader under `share/nl2prolog/fol_json.pl` in the installation prefix. From the checkout, `python nl2prolog.py` runs the same CLI. The CLI prints normalized JSON by default:

```bash
python nl2prolog.py translate "Everyone who loves books is kind" --model "$NL2LOGIC_MODEL"
```

To save Prolog output:

```bash
python nl2prolog.py translate "Everyone who loves books is kind" \
  --model "$NL2LOGIC_MODEL" --format prolog > out.pl
```

To save JSON for the Prolog JSON loader:

```bash
python nl2prolog.py translate "Everyone who loves books is kind" \
  --model "$NL2LOGIC_MODEL" > out.json
```

Each translation command makes a separate model request sequence. Model interpretations,
predicate names, and formula shapes may vary; the examples here illustrate the format.

### Inspect the output in SWI-Prolog

Start `swipl` from the project directory, then load the emitted file and retrieve a formula:

```prolog
?- consult('out.pl').
?- fol(Id, Formula).
```

Alternatively, load the normalized JSON directly:

```prolog
?- use_module(fol_json).
?- load_fol_json('out.json', Formulas).
```

`Formulas` is a list of `Id-Formula` pairs. The loader creates Prolog variables shared
between each quantifier and its references, just as the text emitter does.

## Use from Python

Translate once, then inspect the JSON and render that same translation as Prolog:

```python
from pipeline import Pipeline
from prolog_emitter import to_prolog

p = Pipeline()  # uses the endpoint, credential, and model configured above
doc = p.translate("Everyone who loves books is kind")

print(doc["diagnostics"])
print(to_prolog(doc))
```

The existing pipeline methods are:

| Method | Result |
| --- | --- |
| `p.translate(text)` | A normalized JSON-compatible Python dictionary |
| `p.translate_to_prolog(text)` | Prolog text from a new translation |
| `p.rephrase_and_parse(text)` | The original NL2Logic AST for further processing |

Pass `rephrase=False` to either translation method to skip the initial rephrasing call.
Pass normalization options such as `case_sensitive=False` or `only_if="upstream"`
to control the behavior described below.

## Normalize an existing AST without an API call

If you already have an NL2Logic AST saved as JSON from `ast.to_dict()`, use:

```bash
python nl2prolog.py normalize ast.json
python nl2prolog.py normalize ast.json --format prolog
```

The `normalize` command also accepts standard input when the filename is omitted or `-`.
This path uses only the Python standard library and requires no API key.

In Python, `normalize` accepts either an AST dictionary or an NL2Logic AST object:

```python
from variable_binding import normalize
from prolog_emitter import to_prolog

# ast is an existing NL2Logic AST object or its to_dict() result.
doc = normalize(ast)
print(to_prolog(doc))
```

## Variable bindings and diagnostics

Variable binding connects an occurrence of `x` to the “for every x” or “there exists x”
that introduces it. This matters because Prolog treats lowercase `x` as a constant atom
and uppercase `X` as a variable.

Upstream's atomic parsers wrap relation arguments in `Constant`, including references to
quantified variables. This fork's normalization pass tracks which variables are in scope:

- An argument becomes a variable when it matches a visible quantifier's variable name.
- An inner quantifier takes precedence when it reuses an outer variable's name.
- Each binder gets a distinct Prolog variable name within its formula.
- Other arguments remain constants; suspicious references appear in `diagnostics`.

For example, the inner `x` below becomes `X_2`, while the final `r(x)` still uses the outer `X`:

```text
forall x. ((p(x) and exists x. q(x)) and r(x))
```

```prolog
fol(s1, forall(X, and(and(p(X), exists(X_2, q(X_2))), r(X)))).
```

| Diagnostic code | Severity | Meaning |
| --- | --- | --- |
| `unbound_variable_like` | warning | Looks like a variable, such as `y` or `x2`, but has no visible binder |
| `unbound_variable` | warning | Tagged as a variable in the input but has no visible binder |
| `case_mismatch` | warning | Differs in case from a binder; `case_sensitive=False` allows a match |
| `embedded_variable` | warning | A constant phrase mentions a bound variable, such as `the mother of x` |
| `unused_quantifier` | warning | The bound variable never occurs in its body |
| `empty_variable_name` | warning | An empty binder name was replaced with `x` |
| `empty_symbol` | warning | Predicate or constant text had no usable characters |
| `shadowed_variable` | info | An inner binder reuses an outer name |
| `reserved_predicate` | info | A predicate uses a connective's name; `_p` was appended |

Each diagnostic's `path` is a JSON pointer into the normalized document. Diagnostics help
you review the structure; they do not check the full meaning of the English statement.

## Normalized JSON reference

The schema identifier remains `nl2logic-prolog/1`. Here is the JSON representation of the
opening example:

```json
{
  "schema": "nl2logic-prolog/1",
  "source": "Everyone who loves books is kind",
  "formulas": [{"id": "s1", "formula": {
    "type": "forall",
    "var": {"type": "var", "name": "x", "prolog": "X"},
    "body": {"type": "implies", "args": [
      {"type": "atom", "pred": "love", "roles": ["subject", "obj"],
       "args": [{"type": "var", "name": "x", "prolog": "X"},
                {"type": "const", "name": "books", "atom": "books"}],
       "source": {"node_type": "RelationTransitiveVerb", "text": "love"}},
      {"type": "atom", "pred": "kind", "roles": ["obj"],
       "args": [{"type": "var", "name": "x", "prolog": "X"}],
       "source": {"node_type": "RelationAdjective", "text": "kind"}}]}}}],
  "signature": {"predicates": [{"name": "kind", "arity": 1, "sources": ["kind"]},
                               {"name": "love", "arity": 2, "sources": ["love"]}],
                "constants": [{"atom": "books", "names": ["books"]}]},
  "diagnostics": []
}
```

`signature` lists the predicates, their arities (argument counts), and constants used in
the document. Formula and term shapes are:

| Type | Fields |
| --- | --- |
| `forall`, `exists` | `var`, `body` |
| `and`, `or`, `implies`, `iff` | `args` containing two formulas |
| `not` | `arg` containing one formula |
| `atom` | `pred`, `args`; normalized atoms also retain `roles` and `source` |
| `var` | `name`, `prolog` (the Prolog variable name) |
| `const` | `name` (original text), `atom` (the Prolog-safe name) |

Predicate and constant names become lowercase ASCII with underscores: `Alice` becomes
`alice`, and `very tired` becomes `very_tired`. Names that normalize to the same atom merge;
`signature.constants[].names` retains their source spellings. Determiners remain part of
the name, so `a book` becomes `a_book`.

Ditransitive predicates take arguments in this order: subject, indirect object, direct object.

## CLI reference

Both `translate` and `normalize` support:

| Option | Behavior |
| --- | --- |
| `--format json\|prolog\|both` | JSON by default; `both` returns an object with `json` and `prolog` fields |
| `--case-insensitive` | Allows an argument `X` to match a binder `x` |
| `--only-if standard\|upstream` | Selects the interpretation of “P only if Q”; default is `standard` |
| `--strict` | Returns exit status 2 if normalization reports warnings; still emits output |

`translate` also supports `--llm`, `--model`, `--no-rephrase`, and `--verbose`.
For the default Chat Completions backend, use `--base-url` to override the endpoint or
`--stream` to receive each parser response in chunks. The CLI emits the completed translation.
`--model` defaults to the exported `NL2LOGIC_MODEL` environment variable. `--verbose`
writes the parse trace to standard error, leaving standard output available for the result.

Exit status is 0 on success, 1 for processing errors (reported as JSON on standard error),
and 2 for argument errors or warnings with `--strict`.

## Backends and compatibility

| Selector | API and setup |
| --- | --- |
| `openai` (default) | OpenAI-compatible Chat Completions. Configure `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `NL2LOGIC_MODEL`, or pass `base_url=`, `api_key=`, and `model=` to `Pipeline`. |
| `openai-responses` | OpenAI Responses API. Existing callers that relied on the former `openai` selector should use this name. |
| `openrouter` | Native OpenRouter SDK. Install with `python -m pip install '.[openrouter]'` and set `OPENROUTER_API_KEY`. |
| `ollama` | Install with `python -m pip install '.[ollama]'` and start an Ollama server. |
| `vllm` | OpenAI client for a running vLLM server. Python callers can pass the server endpoint with `url=`. |

Use `--llm` on the CLI or `llm=` in Python to select a backend. Python callers can
also supply an object implementing `generate(text, fmt)`.

The default Chat Completions client requires strict JSON Schema and validates each
parser response locally. For the official OpenRouter endpoint it also requests
`provider.require_parameters=true`. Temperature is omitted by default. Pass
`temperature=0` or another supported value to send it explicitly. The native
`llm="openrouter"` backend also accepts `strict=False` and `require_parameters=False`
for providers that need relaxed settings. The CLI's `--strict` concerns normalization warnings.

For gateway auditing, set `NL2LOGIC_TRACE_HEADERS` to a comma-separated list of
trace header names in priority order (default `x-request-id,x-trace-id`).
Set `NL2LOGIC_COST_HEADERS` to comma-separated response header names or glob patterns
for spend and budget values. With `--verbose`, each Chat Completions request reports
its model, schema, attempt, trace ID, and matching headers on stderr. Python callers
can pass `metadata_callback=` to receive the same dictionary. In streaming mode
(`stream=True`), the parser validates the assembled response after its stop event.
A rejected request includes the HTTP status and available trace ID. Only malformed
model output gets a second attempt.

Two details matter when comparing results with upstream:

- The fork's relation `to_dict()` methods serialize their terms so AST output can be
  written as JSON. The inherited Z3 conversion remains available on the original AST.
- “P only if Q” becomes `implies(P, Q)` by default. Upstream's Z3 conversion reverses those
  operands for the same node. Use `only_if="upstream"` in normalization or
  `--only-if upstream` on the CLI to reproduce that behavior in the Prolog representation.

## Tests

After installing the project dependencies:

```bash
python -m pip install -e '.[test]'
python -m pytest tests
```

The default suite runs without network access or an API key. To evaluate the seven English inputs against your configured Chat Completions model, run `python -m pytest --run-live -m live`. These requests use your provider account. Each case checks the formula against its listed structural readings, allowing bound variables to be renamed and conjunctions or disjunctions to be reordered.

The approved cases draw on [FOLIO](https://github.com/Yale-LILY/FOLIO), [quantifier scope research](https://github.com/esteng/ambiguous_parsing), and [COGS](https://aclanthology.org/2020.emnlp-main.731/). The offline versions use scripted model replies to exercise reconstruction. The offline tests cover variable bindings, nested
scopes, diagnostics, Prolog emission, the CLI, and the pipeline. OpenRouter tests use the
real SDK with a mocked HTTP transport and are skipped if the SDK is unavailable.
SWI-Prolog integration tests are skipped if `swipl` is not installed.

## Acknowledgments and license

nl2prolog builds on **NL2Logic**, created by **Rizky Ramadhana Putra, Raihan Sultan Pasha
Basuki, Yutong Cheng, and Peng Gao**. The original project provides the AST-guided
natural-language-to-FOL approach and parsing framework that make this fork possible.

- [Original project and documentation](https://github.com/peng-gao-lab/nl2logic)
- [NL2Logic paper](https://arxiv.org/abs/2602.13237)
- [Original MIT license and copyright notice](LICENSE.txt): Copyright (c) 2026 Rizky Ramadhana Putra
- [Fork MIT license and copyright notice](LICENSE): Copyright (c) 2026 Tyson Maly

This fork's additions include the OpenRouter backend, variable-binding normalization,
and JSON-to-Prolog loading and emission. Both MIT license notices are retained in this
repository. When redistributing copies or substantial portions of the software, include
the applicable copyright and permission notices.

If you use the NL2Logic approach in research, please cite the original authors' paper:

```bibtex
@inproceedings{nl2logic,
    title = "NL2Logic: AST-Guided Translation of Natural Language into First-Order Logic with Large Language Models",
    author = "Putra, Rizky Ramadhana  and
      Pasha Basuki, Raihan Sultan  and
      Cheng, Yutong  and
      Gao, Peng",
    booktitle = "Findings of the Association for Computational Linguistics: EACL 2026",
    month = mar,
    year = "2026",
    address = "Rabat, Morocco",
    publisher = "Association for Computational Linguistics"
}
```
