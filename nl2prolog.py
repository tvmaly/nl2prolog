#!/usr/bin/env python3
"""Command-line entry point for the fork.

    python nl2prolog.py translate "Everyone who loves books is kind" --model openai/gpt-4o
    python nl2prolog.py normalize ast.json            # NL2Logic to_dict() JSON -> normalized JSON
    python nl2prolog.py normalize ast.json --format prolog

Output goes to stdout: normalized JSON by default, Prolog with --format prolog,
or {"json": ..., "prolog": ...} with --format both.  Exit status is 0 on
success, 1 on error, and 2 with --strict when the pass reported warnings.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from prolog_emitter import to_prolog
from variable_binding import normalize


def _emit(doc, fmt):
    if fmt == "prolog":
        sys.stdout.write(to_prolog(doc))
    elif fmt == "both":
        json.dump({"json": doc, "prolog": to_prolog(doc)}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        json.dump(doc, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--format", choices=["json", "prolog", "both"], default="json")
    shared.add_argument("--case-insensitive", action="store_true",
                        help="let 'X' bind to a quantifier's 'x'")
    shared.add_argument("--only-if", choices=["standard", "upstream"], default="standard",
                        help="'P only if Q' as implies(P,Q) [standard] or implies(Q,P) [upstream Z3]")
    shared.add_argument("--strict", action="store_true",
                        help="exit 2 if the pass reported any warning")

    t = sub.add_parser("translate", parents=[shared], help="natural language -> JSON/Prolog (calls the LLM)")
    t.add_argument("text")
    t.add_argument("--llm", default="openai", choices=["openai", "openai-responses", "openrouter", "ollama", "vllm"])
    t.add_argument("--base-url", help="Chat Completions endpoint (default: $OPENAI_BASE_URL)")
    t.add_argument("--stream", action="store_true", help="receive each Chat Completion as a stream")
    t.add_argument("--model",
                   help="model id (default: $NL2LOGIC_MODEL)")
    t.add_argument("--no-rephrase", action="store_true")
    t.add_argument("--verbose", action="store_true", help="print the parse trace to stderr")

    n = sub.add_parser("normalize", parents=[shared], help="NL2Logic AST JSON -> normalized JSON/Prolog (no LLM)")
    n.add_argument("file", nargs="?", default="-", help="AST JSON file, or - for stdin")

    args = parser.parse_args(argv)
    options = dict(case_sensitive=not args.case_insensitive, only_if=args.only_if)
    try:
        if args.command == "translate":
            from pipeline import Pipeline
            model = args.model or os.getenv("NL2LOGIC_MODEL")
            if not model:
                parser.error("--model (or $NL2LOGIC_MODEL) is required")
            backend_options = {}
            if args.llm == "openai":
                backend_options.update(base_url=args.base_url, stream=args.stream)
                if args.verbose:
                    backend_options["metadata_callback"] = lambda data: print(json.dumps(data), file=sys.stderr)
            elif args.base_url or args.stream:
                parser.error("--base-url and --stream require --llm openai")
            pipeline = Pipeline(llm=args.llm, model=model, logging=args.verbose, **backend_options)
            try:
                if args.verbose:
                    pipeline.log = lambda text: print(text, file=sys.stderr)
                doc = pipeline.translate(args.text, rephrase=not args.no_rephrase, **options)
            finally:
                if args.llm == "openai":
                    pipeline.llm.close()
        else:
            if args.file == "-":
                ast = json.load(sys.stdin)
            else:
                with open(args.file, encoding="utf-8") as handle:
                    ast = json.load(handle)
            doc = normalize(ast, **options)
        _emit(doc, args.format)
    except Exception as exc:  # report as JSON so callers can parse failures too
        json.dump({"error": type(exc).__name__, "message": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        return 1
    if args.strict and any(d["severity"] == "warning" for d in doc["diagnostics"]):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
