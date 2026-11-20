/*  Load normalized NL2Logic JSON (schema nl2logic-prolog/1) into SWI-Prolog.

    ?- use_module(fol_json).
    ?- load_fol_json('out.json', Formulas).
    Formulas = [s1-forall(X, implies(love(X, books), kind(X)))].

    Quantified variables become fresh Prolog variables shared between the
    binder and its occurrences.  Lookup is innermost-first, so nested and
    shadowed quantifiers resolve by lexical scope.
*/
:- module(fol_json, [load_fol_json/2, fol_json_formulas/2]).
:- use_module(library(http/json)).
:- use_module(library(apply)).
:- use_module(library(lists)).

%!  load_fol_json(+File, -Formulas) is det.
%   Formulas is a list of Id-Formula pairs.
load_fol_json(File, Formulas) :-
    setup_call_cleanup(
        open(File, read, In, [encoding(utf8)]),
        json_read_dict(In, Doc),
        close(In)),
    fol_json_formulas(Doc, Formulas).

%!  fol_json_formulas(+Doc:dict, -Formulas) is det.
fol_json_formulas(Doc, Formulas) :-
    get_dict(formulas, Doc, Entries),
    maplist(entry, Entries, Formulas).

entry(Entry, Id-Formula) :-
    get_dict(id, Entry, IdText),
    get_dict(formula, Entry, Node),
    atom_string(Id, IdText),
    formula(Node, [], Formula).

formula(Node, Env, Formula) :-
    get_dict(type, Node, TypeText),
    atom_string(Type, TypeText),
    (   formula(Type, Node, Env, Formula)
    ->  true
    ;   throw(error(domain_error(fol_formula, Node), _))
    ).

formula(Quantifier, Node, Env, Formula) :-
    memberchk(Quantifier, [forall, exists]),
    get_dict(var, Node, VarNode),
    get_dict(prolog, VarNode, NameText),
    atom_string(Name, NameText),
    get_dict(body, Node, BodyNode),
    formula(BodyNode, [Name-Var|Env], Body),      % child scope for the body only
    Formula =.. [Quantifier, Var, Body].
formula(Connective, Node, Env, Formula) :-
    memberchk(Connective, [and, or, implies, iff]),
    get_dict(args, Node, [LeftNode, RightNode]),
    formula(LeftNode, Env, Left),
    formula(RightNode, Env, Right),
    Formula =.. [Connective, Left, Right].
formula(not, Node, Env, not(Arg)) :-
    get_dict(arg, Node, ArgNode),
    formula(ArgNode, Env, Arg).
formula(atom, Node, Env, Atom) :-
    get_dict(pred, Node, PredText),
    atom_string(Pred, PredText),
    get_dict(args, Node, ArgNodes),
    maplist(term(Env), ArgNodes, Args),
    Atom =.. [Pred|Args].

term(Env, Node, Term) :-
    get_dict(type, Node, TypeText),
    (   TypeText == "var"
    ->  get_dict(prolog, Node, NameText),
        atom_string(Name, NameText),
        (   memberchk(Name-Var, Env)              % innermost binding wins
        ->  Term = Var
        ;   throw(error(existence_error(bound_variable, Name), _))
        )
    ;   TypeText == "const"
    ->  get_dict(atom, Node, AtomText),
        atom_string(Term, AtomText)
    ;   throw(error(domain_error(fol_term, Node), _))
    ).
