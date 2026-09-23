"""Constraint expressions: a tiny grammar that is parsed, never evaluated as code.

    expr  := or
    or    := and ("or" and)*
    and   := not ("and" not)*
    not   := "not" not | "(" expr ")" | atom
    atom  := dim "==" option | dim "!=" option
           | dim "in" "[" option ("," option)* "]"
           | dim "not" "in" "[" option ("," option)* "]"

A dimension that does not apply to a variant has no value: `==` and `in` are
false for it, `!=` and `not in` are true.
"""

import difflib
import re
from dataclasses import dataclass

__all__ = ["ExprError", "Atom", "And", "Or", "Not", "parse", "validate"]

_TOKEN = re.compile(r"\s*(==|!=|\(|\)|\[|\]|,|[A-Za-z0-9_][A-Za-z0-9_.-]*|\S)")


class ExprError(ValueError):
    pass


@dataclass(frozen=True)
class Atom:
    dim: str
    op: str  # "==", "!=", "in", "not in"
    values: tuple

    def evaluate(self, env):
        value = env.get(self.dim)
        hit = value is not None and value in self.values
        return hit if self.op in ("==", "in") else not hit

    def atoms(self, negated=False):
        yield self, negated

    def __str__(self):
        if self.op in ("==", "!="):
            return f"{self.dim} {self.op} {self.values[0]}"
        return f"{self.dim} {self.op} [{', '.join(self.values)}]"


@dataclass(frozen=True)
class Not:
    item: object

    def evaluate(self, env):
        return not self.item.evaluate(env)

    def atoms(self, negated=False):
        yield from self.item.atoms(not negated)

    def __str__(self):
        inner = str(self.item)
        return f"not {inner}" if isinstance(self.item, Atom) else f"not ({inner})"


@dataclass(frozen=True)
class And:
    items: tuple

    def evaluate(self, env):
        return all(item.evaluate(env) for item in self.items)

    def atoms(self, negated=False):
        for item in self.items:
            yield from item.atoms(negated)

    def __str__(self):
        return " and ".join(f"({i})" if isinstance(i, Or) else str(i) for i in self.items)


@dataclass(frozen=True)
class Or:
    items: tuple

    def evaluate(self, env):
        return any(item.evaluate(env) for item in self.items)

    def atoms(self, negated=False):
        for item in self.items:
            yield from item.atoms(negated)

    def __str__(self):
        return " or ".join(str(i) for i in self.items)


def _tokenize(text):
    tokens = []
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            break
        tokens.append(match.group(1))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, text):
        self.text = text
        self.tokens = _tokenize(text)
        self.pos = 0

    def peek(self, offset=0):
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else None

    def take(self, expected=None):
        token = self.peek()
        if token is None:
            raise ExprError(f"unexpected end of expression in {self.text!r}")
        if expected is not None and token != expected:
            raise ExprError(f"expected {expected!r} but found {token!r} in {self.text!r}")
        self.pos += 1
        return token

    def parse(self):
        if not self.tokens:
            raise ExprError("empty expression")
        node = self.or_()
        if self.peek() is not None:
            raise ExprError(f"unexpected {self.peek()!r} in {self.text!r}")
        return node

    def or_(self):
        items = [self.and_()]
        while self.peek() == "or":
            self.take()
            items.append(self.and_())
        return items[0] if len(items) == 1 else Or(tuple(items))

    def and_(self):
        items = [self.not_()]
        while self.peek() == "and":
            self.take()
            items.append(self.not_())
        return items[0] if len(items) == 1 else And(tuple(items))

    def not_(self):
        if self.peek() == "not":
            self.take()
            return Not(self.not_())
        if self.peek() == "(":
            self.take()
            node = self.or_()
            self.take(")")
            return node
        return self.atom()

    def ident(self, what):
        token = self.take()
        if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$", token) or token in ("and", "or", "not", "in"):
            raise ExprError(f"expected {what} but found {token!r} in {self.text!r}")
        return token

    def atom(self):
        dim = self.ident("a dimension name")
        op = self.take()
        if op == "=":
            raise ExprError(f"use '==' instead of '=' in {self.text!r}")
        if op in ("==", "!="):
            return Atom(dim, op, (self.ident("an option name"),))
        if op == "not" and self.peek() == "in":
            self.take()
            op = "not in"
        elif op != "in":
            raise ExprError(f"expected '==', '!=', 'in' or 'not in' after {dim!r} in {self.text!r}")
        self.take("[")
        values = [self.ident("an option name")]
        while self.peek() == ",":
            self.take()
            values.append(self.ident("an option name"))
        self.take("]")
        return Atom(dim, op, tuple(values))


def parse(text):
    """Parse an expression string into an AST, raising ExprError on bad syntax."""
    if not isinstance(text, str):
        raise ExprError(f"expected an expression string, got {text!r}")
    return _Parser(text).parse()


def _hint(word, candidates):
    close = difflib.get_close_matches(word, list(candidates), n=1, cutoff=0.6)
    return f" (did you mean {close[0]!r}?)" if close else ""


def validate(node, dimensions):
    """Return a list of problems for unknown dimensions or options.

    `dimensions` maps dimension id to an iterable of option ids.
    """
    problems = []
    for atom, _ in node.atoms():
        if atom.dim not in dimensions:
            problems.append(f"unknown dimension {atom.dim!r}{_hint(atom.dim, dimensions)}")
            continue
        options = list(dimensions[atom.dim])
        for value in atom.values:
            if value not in options:
                problems.append(
                    f"unknown option {value!r} for dimension {atom.dim!r}{_hint(value, options)}"
                    f"; options are: {', '.join(options)}"
                )
    return problems
