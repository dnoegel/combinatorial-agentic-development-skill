"""A small, dependency-free reader and writer for the YAML subset CAD uses.

Supported: block mappings, block sequences, flow lists and maps on a single
line, plain / single-quoted / double-quoted scalars, literal (|) and folded (>)
block scalars, and comments. Plain scalars follow YAML 1.2 core rules:
true/false are booleans, null/~/empty are null, integers and floats are
numbers, everything else is a string (so `none`, `off` and `no` stay strings).

Anchors, aliases, tags, multi-document streams and multi-line flow
collections are not supported and raise YamlError.
"""

import re

__all__ = ["YamlError", "loads", "dumps"]


class YamlError(ValueError):
    def __init__(self, message, line=None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


_INT = re.compile(r"^[-+]?[0-9]+$")
_FLOAT = re.compile(r"^[-+]?([0-9]+\.[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?$")


def _resolve_plain(text):
    if text in ("", "~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if _INT.match(text):
        return int(text)
    if _FLOAT.match(text):
        return float(text)
    return text


def _strip_comment(text):
    """Remove a trailing comment that is outside of quotes."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    continue
                quote = None
            elif ch == "\\" and quote == '"':
                continue
        elif ch in "'\"" and (i == 0 or text[i - 1] in " \t[{,:"):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
    return text.rstrip()


def _unquote_double(body, line):
    out = []
    i = 0
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "0": "\0", "r": "\r"}
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            if i + 1 >= len(body):
                raise YamlError("dangling backslash in double-quoted string", line)
            nxt = body[i + 1]
            if nxt in escapes:
                out.append(escapes[nxt])
                i += 2
                continue
            if nxt == "u" and i + 5 < len(body) + 1:
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
                continue
            raise YamlError(f"unsupported escape \\{nxt}", line)
        out.append(ch)
        i += 1
    return "".join(out)


class _Flow:
    """Parser for single-line flow collections and quoted scalars."""

    def __init__(self, text, line):
        self.text = text
        self.pos = 0
        self.line = line

    def error(self, message):
        raise YamlError(f"{message} in {self.text!r}", self.line)

    def ws(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1

    def value(self, in_map_key=False):
        self.ws()
        if self.pos >= len(self.text):
            self.error("unexpected end of flow value")
        ch = self.text[self.pos]
        if ch == "[":
            return self.seq()
        if ch == "{":
            return self.map()
        if ch in "'\"":
            return self.quoted()
        return self.plain(in_map_key)

    def seq(self):
        self.pos += 1
        items = []
        self.ws()
        if self.peek() == "]":
            self.pos += 1
            return items
        while True:
            items.append(self.value())
            self.ws()
            ch = self.peek()
            if ch == ",":
                self.pos += 1
                self.ws()
                if self.peek() == "]":
                    self.pos += 1
                    return items
                continue
            if ch == "]":
                self.pos += 1
                return items
            self.error("expected ',' or ']'")

    def map(self):
        self.pos += 1
        result = {}
        self.ws()
        if self.peek() == "}":
            self.pos += 1
            return result
        while True:
            key = self.value(in_map_key=True)
            self.ws()
            if self.peek() != ":":
                self.error("expected ':' in flow mapping")
            self.pos += 1
            self.ws()
            if self.peek() in (",", "}"):
                val = None
            else:
                val = self.value()
            key = "" if key is None else str(key)
            if key in result:
                self.error(f"duplicate key {key!r}")
            result[key] = val
            self.ws()
            ch = self.peek()
            if ch == ",":
                self.pos += 1
                self.ws()
                if self.peek() == "}":
                    self.pos += 1
                    return result
                continue
            if ch == "}":
                self.pos += 1
                return result
            self.error("expected ',' or '}'")

    def quoted(self):
        quote = self.text[self.pos]
        start = self.pos + 1
        i = start
        while i < len(self.text):
            ch = self.text[i]
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                if quote == "'" and i + 1 < len(self.text) and self.text[i + 1] == "'":
                    i += 2
                    continue
                body = self.text[start:i]
                self.pos = i + 1
                if quote == "'":
                    return body.replace("''", "'")
                return _unquote_double(body, self.line)
            i += 1
        self.error("unterminated quoted string")

    def plain(self, in_map_key):
        start = self.pos
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch in ",]}":
                break
            if ch == ":" and in_map_key:
                break
            self.pos += 1
        return _resolve_plain(self.text[start:self.pos].strip())

    def peek(self):
        return self.text[self.pos] if self.pos < len(self.text) else ""


def _parse_inline(text, line):
    """Parse a scalar or flow collection that fills the rest of a line."""
    text = text.strip()
    if not text:
        return None
    if text[0] in "[{'\"":
        flow = _Flow(text, line)
        value = flow.value()
        flow.ws()
        if flow.pos != len(text):
            raise YamlError(f"unexpected trailing text {text[flow.pos:]!r}", line)
        return value
    if text[0] in "&*!%@`":
        raise YamlError(f"unsupported YAML feature at {text!r} (anchors, aliases and tags are not supported)", line)
    if text in ("|", ">", "|-", ">-", "|+", ">+"):
        raise YamlError("block scalar indicator in unexpected position", line)
    return _resolve_plain(text)


def _split_key(content, line):
    """Return (key, rest) if the line is a mapping entry, else None."""
    if content[0] in "'\"":
        flow = _Flow(content, line)
        key = flow.quoted()
        rest = content[flow.pos:]
        if rest.startswith(":") and (len(rest) == 1 or rest[1] in " \t"):
            return key, rest[1:].strip()
        return None
    if content[0] in "[{":
        return None
    idx = 0
    while True:
        idx = content.find(":", idx)
        if idx == -1:
            return None
        if idx + 1 == len(content) or content[idx + 1] in " \t":
            return content[:idx].strip(), content[idx + 1:].strip()
        idx += 1


class _Parser:
    def __init__(self, text):
        if "\t" in "".join(l[: len(l) - len(l.lstrip(" \t"))] for l in text.splitlines()):
            raise YamlError("tabs are not allowed for indentation")
        self.lines = text.splitlines()
        self.i = 0

    def meaningful(self):
        """Advance to the next non-blank, non-comment line and describe it."""
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            stripped = raw.strip()
            if stripped and not stripped.startswith("#"):
                if stripped in ("---", "..."):
                    if self.i == 0 or stripped == "...":
                        self.i += 1
                        continue
                    raise YamlError("multiple documents are not supported", self.i + 1)
                indent = len(raw) - len(raw.lstrip(" "))
                return indent, _strip_comment(raw[indent:]), self.i + 1
            self.i += 1
        return None

    def parse(self):
        head = self.meaningful()
        if head is None:
            return None
        value = self.node(head[0])
        tail = self.meaningful()
        if tail is not None:
            raise YamlError("unexpected content (check indentation)", tail[2])
        return value

    def node(self, indent):
        head = self.meaningful()
        content = head[1]
        if content == "-" or content.startswith("- "):
            return self.seq(indent)
        if _split_key(content, head[2]) is not None:
            return self.map(indent)
        self.i += 1
        return _parse_inline(content, head[2])

    def seq(self, indent):
        items = []
        while True:
            head = self.meaningful()
            if head is None or head[0] < indent:
                return items
            ind, content, line = head
            if ind > indent:
                raise YamlError("unexpected indentation", line)
            if not (content == "-" or content.startswith("- ")):
                if _split_key(content, line) is not None:
                    raise YamlError("mapping key found where a list item was expected", line)
                raise YamlError("expected a list item starting with '- '", line)
            rest = content[1:]
            offset = len(rest) - len(rest.lstrip(" "))
            rest = rest.strip()
            if not rest:
                self.i += 1
                nxt = self.meaningful()
                if nxt is not None and nxt[0] > indent:
                    items.append(self.node(nxt[0]))
                else:
                    items.append(None)
                continue
            child_indent = indent + 1 + offset
            if rest == "-" or rest.startswith("- ") or _split_key(rest, line) is not None:
                self.lines[self.i] = " " * child_indent + rest
                items.append(self.node(child_indent))
                continue
            if rest[0] in "|>":
                items.append(self.block_scalar(rest, indent, line))
                continue
            self.i += 1
            items.append(_parse_inline(rest, line))

    def map(self, indent):
        result = {}
        while True:
            head = self.meaningful()
            if head is None or head[0] < indent:
                return result
            ind, content, line = head
            if ind > indent:
                raise YamlError("unexpected indentation", line)
            if content == "-" or content.startswith("- "):
                raise YamlError("list item found where a mapping key was expected", line)
            split = _split_key(content, line)
            if split is None:
                raise YamlError(f"expected 'key: value', got {content!r}", line)
            key, rest = split
            if key in result:
                raise YamlError(f"duplicate key {key!r}", line)
            if rest and rest[0] in "|>":
                result[key] = self.block_scalar(rest, indent, line)
                continue
            self.i += 1
            if rest:
                result[key] = _parse_inline(rest, line)
                continue
            nxt = self.meaningful()
            if nxt is not None and nxt[0] > indent:
                result[key] = self.node(nxt[0])
            elif nxt is not None and nxt[0] == indent and (nxt[1] == "-" or nxt[1].startswith("- ")):
                result[key] = self.seq(indent)
            else:
                result[key] = None

    def block_scalar(self, header, parent_indent, line):
        style = header[0]
        chomp = header[1:].strip()
        if chomp not in ("", "-", "+"):
            raise YamlError(f"unsupported block scalar header {header!r}", line)
        self.i += 1
        body = []
        block_indent = None
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            if raw.strip() == "":
                body.append("")
                self.i += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if ind <= parent_indent:
                break
            if block_indent is None:
                block_indent = ind
            if ind < block_indent:
                break
            body.append(raw[block_indent:])
            self.i += 1
        trailing = 0
        while body and body[-1] == "":
            body.pop()
            trailing += 1
        if style == "|":
            text = "\n".join(body)
        else:
            paragraphs, current = [], []
            for row in body:
                if row == "":
                    paragraphs.append(" ".join(current))
                    current = []
                else:
                    current.append(row)
            paragraphs.append(" ".join(current))
            text = "\n".join(paragraphs)
        if not body:
            return ""
        if chomp == "-":
            return text
        if chomp == "+":
            return text + "\n" * (trailing + 1)
        return text + "\n"


def loads(text):
    """Parse YAML text in the supported subset into Python objects."""
    return _Parser(text).parse()


_NEEDS_QUOTES = re.compile(r"^[-?:,\[\]{}#&*!|>'\"%@`]|: |\s#|^\s|\s$|:$")


def _scalar(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if text == "" or _NEEDS_QUOTES.search(text) or _resolve_plain(text) != text or "\n" in text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return text


def _key(key):
    return _scalar(str(key))


def dumps(value, indent=0):
    """Serialize dicts, lists and scalars as block-style YAML."""
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return pad + "{}\n"
        out = []
        for key, item in value.items():
            if isinstance(item, dict) and item:
                out.append(f"{pad}{_key(key)}:\n{dumps(item, indent + 2)}")
            elif isinstance(item, list) and item:
                out.append(f"{pad}{_key(key)}:\n{dumps(item, indent + 2)}")
            elif isinstance(item, dict):
                out.append(f"{pad}{_key(key)}: {{}}\n")
            elif isinstance(item, list):
                out.append(f"{pad}{_key(key)}: []\n")
            else:
                out.append(f"{pad}{_key(key)}: {_scalar(item)}\n")
        return "".join(out)
    if isinstance(value, list):
        if not value:
            return pad + "[]\n"
        out = []
        for item in value:
            if isinstance(item, (dict, list)) and item:
                nested = dumps(item, indent + 2)
                out.append(f"{pad}- {nested[indent + 2:]}")
            else:
                out.append(f"{pad}- {_scalar(item) if not isinstance(item, (dict, list)) else ('{}' if isinstance(item, dict) else '[]')}\n")
        return "".join(out)
    return pad + _scalar(value) + "\n"
