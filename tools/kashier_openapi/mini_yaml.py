#################################################################################
# Author      : mediafish(<https://www.mediafish.agency>)
# Copyright(c): 2010-Present mediafish
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://www.mediafish.agency/license.html/>
#################################################################################
"""A strict reader for the subset of YAML that OpenAPI documents use. Standard library only.

Supported: block mappings and sequences, plain / single-quoted / double-quoted scalars (also on several
lines), literal (`|`) and folded (`>`) block scalars with chomping and indentation indicators, flow
sequences and mappings (`[a, b]`, `{a: b}`) and comments. Scalars resolve like the YAML 1.2 core schema
(`true`, `false`, `null`, `~`, integers, floats); timestamps stay strings. Anchors, aliases, tags,
directives, several documents and explicit (`?`) keys are refused with a `YamlError`.
"""

import re

__all__ = ["YamlError", "loads"]


class YamlError(ValueError):
    """The document uses YAML this reader does not support, or is not valid YAML."""

    def __init__(self, message, line=None):
        super().__init__(f"line {line}: {message}" if line else message)
        self.line = line


_INT = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")
_INT_OCT = re.compile(r"^0o[0-7]+$")
_INT_HEX = re.compile(r"^0x[0-9a-fA-F]+$")
_FLOAT = re.compile(r"^[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?$")
_SPECIAL_FLOATS = {".inf": float("inf"), "+.inf": float("inf"), "-.inf": float("-inf"), ".nan": float("nan")}
_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
    "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": " ",
    "P": " ",
}


def resolve_plain(text):
    """Return the value of a plain (unquoted) scalar, YAML 1.2 core schema; timestamps stay strings."""
    if text in ("", "~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if _INT.match(text):
        return int(text)
    if _INT_OCT.match(text):
        return int(text[2:], 8)
    if _INT_HEX.match(text):
        return int(text[2:], 16)
    if text.lower() in _SPECIAL_FLOATS:
        return _SPECIAL_FLOATS[text.lower()]
    if _FLOAT.match(text) and any(char.isdigit() for char in text):
        return float(text)
    return text


class _Line:
    __slots__ = ("indent", "number", "raw", "text")

    def __init__(self, number, raw):
        self.number = number
        self.raw = raw
        stripped = raw.lstrip(" ")
        self.indent = len(raw) - len(stripped)
        self.text = stripped


def _strip_comment(text):
    """Remove a trailing comment from a structural line, outside quotes."""
    quote = None
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                if quote == "'" and text[index + 1:index + 2] == "'":
                    continue
                if quote == '"' and _escaped(text, index):
                    continue
                quote = None
        elif char in ("'", '"') and (index == 0 or text[index - 1] in " \t[{,:-"):
            quote = char
        elif char == "#" and (index == 0 or text[index - 1] in " \t"):
            return text[:index].rstrip()
    return text.rstrip()


def _escaped(text, index):
    backslashes = 0
    position = index - 1
    while position >= 0 and text[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


class _Parser:

    def __init__(self, source):
        if "\t" in "".join(line[:len(line) - len(line.lstrip())] for line in source.splitlines()):
            raise YamlError("tabs are not allowed in indentation")
        self.lines = [_Line(number, raw.rstrip("\r")) for number, raw in enumerate(source.split("\n"), 1)]
        self.position = 0

    # === Lines === #

    def _is_blank(self, line):
        return not line.text or line.text.startswith("#")

    def _skip_blank(self):
        while self.position < len(self.lines) and self._is_blank(self.lines[self.position]):
            self.position += 1

    def _current(self):
        self._skip_blank()
        return self.lines[self.position] if self.position < len(self.lines) else None

    # === Document === #

    def parse(self):
        line = self._current()
        if line is None:
            return None
        for marker in ("%", "---", "..."):
            if line.text.startswith(marker):
                raise YamlError("directives and document markers are not supported", line.number)
        value = self._parse_block(line.indent)
        rest = self._current()
        if rest is not None:
            raise YamlError(f"unexpected content {rest.text[:40]!r}", rest.number)
        return value

    def _parse_block(self, indent):
        line = self._current()
        if line is None or line.indent < indent:
            return None
        if line.text.startswith("- ") or line.text == "-":
            return self._parse_sequence(line.indent)
        return self._parse_mapping(line.indent)

    # === Sequences === #

    def _parse_sequence(self, indent):
        items = []
        while True:
            line = self._current()
            if line is None or line.indent != indent or not (line.text.startswith("- ") or line.text == "-"):
                if line is not None and line.indent > indent:
                    raise YamlError(f"bad indentation {line.text[:40]!r}", line.number)
                return items
            rest = line.text[1:].lstrip(" ")
            content_indent = indent + (len(line.text) - len(rest)) if rest else indent + 2
            if not rest or rest.startswith("#"):
                self.position += 1
                child = self._current()
                items.append(self._parse_block(child.indent) if child is not None and child.indent > indent else None)
                continue
            if rest.startswith("- ") or rest == "-":
                # A sequence nested on the same line: re-read it at its own column.
                self.lines[self.position] = _Line(line.number, " " * content_indent + rest)
                items.append(self._parse_sequence(content_indent))
                continue
            if self._looks_like_mapping_entry(rest):
                self.lines[self.position] = _Line(line.number, " " * content_indent + rest)
                items.append(self._parse_mapping(content_indent))
                continue
            self.lines[self.position] = _Line(line.number, " " * content_indent + rest)
            items.append(self._parse_scalar_value(rest, content_indent, indent))

    # === Mappings === #

    def _looks_like_mapping_entry(self, text):
        try:
            self._split_key(text, None)
        except YamlError:
            return False
        return True

    def _split_key(self, text, number):
        """Return (key, rest) for `key: rest`; raise if the line is not a mapping entry."""
        if text.startswith("?"):
            raise YamlError("explicit keys are not supported", number)
        if text[:1] in ("&", "*", "!"):
            raise YamlError("anchors, aliases and tags are not supported", number)
        if text[:1] in ("'", '"'):
            key, end = self._read_quoted(text, 0, number)
            after = text[end:].lstrip(" ")
            if not after.startswith(":"):
                raise YamlError(f"expected ':' after quoted key in {text[:40]!r}", number)
            return key, after[1:].lstrip(" ")
        match = re.search(r":(\s|$)", text)
        if not match or (text[:1] in ("[", "{", "-") and not text.startswith("-")) or text.startswith(("[", "{")):
            raise YamlError(f"not a mapping entry: {text[:40]!r}", number)
        key_text = text[:match.start()].rstrip()
        if not key_text or ("#" in key_text and re.search(r"\s#", key_text)):
            raise YamlError(f"not a mapping entry: {text[:40]!r}", number)
        return resolve_plain(key_text), text[match.end():].lstrip(" ")

    def _parse_mapping(self, indent):
        mapping = {}
        while True:
            line = self._current()
            if line is None or line.indent < indent:
                return mapping
            if line.indent > indent:
                raise YamlError(f"bad indentation {line.text[:40]!r}", line.number)
            if line.text.startswith("- ") or line.text == "-":
                return mapping
            key, rest = self._split_key(line.text, line.number)
            if key in mapping:
                raise YamlError(f"duplicate key {key!r}", line.number)
            rest_clean = _strip_comment(rest)
            if not rest_clean:
                self.position += 1
                child = self._current()
                if child is not None and (child.indent > indent or (
                    child.indent == indent and (child.text.startswith("- ") or child.text == "-")
                )):
                    mapping[key] = self._parse_block(child.indent)
                else:
                    mapping[key] = None
                continue
            mapping[key] = self._parse_scalar_value(rest, indent + 1, indent)

    # === Values on a line === #

    def _parse_scalar_value(self, rest, continuation_indent, parent_indent):
        """Parse the value that follows `key:` or `- ` on the current line (advances past it)."""
        line = self.lines[self.position]
        text = rest
        if text[:1] in ("&", "*", "!"):
            raise YamlError("anchors, aliases and tags are not supported", line.number)
        if text[:1] in ("|", ">"):
            header = _strip_comment(text)
            self.position += 1
            return self._parse_block_scalar(header, parent_indent, line.number)
        if text[:1] in ("[", "{"):
            return self._parse_flow_from_lines(text, line.number)
        if text[:1] in ("'", '"'):
            return self._parse_quoted_from_lines(text, line.number)
        # A plain scalar, possibly continued on more-indented lines.
        parts = [_strip_comment(text)]
        self.position += 1
        while self.position < len(self.lines):
            following = self.lines[self.position]
            if not following.text:
                parts.append("")
                self.position += 1
                continue
            if following.indent < continuation_indent or following.text.startswith("#"):
                break
            if self._looks_like_mapping_entry(following.text) or following.text.startswith("- "):
                break
            parts.append(_strip_comment(following.text))
            self.position += 1
        while parts and parts[-1] == "":
            parts.pop()
        if len(parts) == 1:
            return resolve_plain(parts[0])
        return _fold(parts)

    def _parse_block_scalar(self, header, parent_indent, number):
        match = re.fullmatch(r"([|>])([-+]?)([1-9]?)([-+]?)", header)
        if not match or (match.group(2) and match.group(4)):
            raise YamlError(f"bad block scalar header {header!r}", number)
        style, chomp = match.group(1), match.group(2) or match.group(4)
        explicit = int(match.group(3)) if match.group(3) else None
        raw_lines = []
        block_indent = parent_indent + explicit if explicit else None
        while self.position < len(self.lines):
            line = self.lines[self.position]
            if line.text == "" and line.raw.strip() == "":
                raw_lines.append("")
                self.position += 1
                continue
            if block_indent is None:
                if line.indent <= parent_indent:
                    break
                block_indent = line.indent
            if line.indent < block_indent:
                break
            raw_lines.append(line.raw[block_indent:])
            self.position += 1
        trailing = 0
        while raw_lines and raw_lines[-1] == "":
            raw_lines.pop()
            trailing += 1
        if style == "|":
            body = "\n".join(raw_lines)
        else:
            body = _fold_block(raw_lines)
        if not raw_lines:
            return "" if chomp != "+" else "\n" * trailing
        if chomp == "-":
            return body
        if chomp == "+":
            return body + "\n" + "\n" * trailing
        return body + "\n"

    def _parse_quoted_from_lines(self, text, number):
        source = text
        start_position = self.position
        while True:
            try:
                value, end = self._read_quoted(source, 0, number)
                break
            except _Unterminated:
                self.position += 1
                if self.position >= len(self.lines):
                    raise YamlError("unterminated quoted scalar", number) from None
                source += "\n" + self.lines[self.position].raw
        after = _strip_comment(source[end:])
        if after.strip():
            raise YamlError(f"unexpected text after a quoted scalar: {after.strip()[:40]!r}", number)
        self.position = max(self.position, start_position) + 1
        return value

    def _parse_flow_from_lines(self, text, number):
        source = _strip_comment(text)
        while True:
            try:
                value, end = _FlowParser(source, number).parse()
                break
            except _Unterminated:
                self.position += 1
                if self.position >= len(self.lines):
                    raise YamlError("unterminated flow collection", number) from None
                source += " " + _strip_comment(self.lines[self.position].text)
        if source[end:].strip():
            raise YamlError(f"unexpected text after a flow collection: {source[end:].strip()[:40]!r}", number)
        self.position += 1
        return value

    def _read_quoted(self, text, start, number):
        quote = text[start]
        index = start + 1
        chunks = []
        while index < len(text):
            char = text[index]
            if quote == "'":
                if char == "'":
                    if text[index + 1:index + 2] == "'":
                        chunks.append("'")
                        index += 2
                        continue
                    return _fold_quoted("".join(chunks)), index + 1
                chunks.append(char)
                index += 1
                continue
            if char == "\\":
                following = text[index + 1:index + 2]
                if following == "":
                    raise _Unterminated  # The escape continues on the next line.
                if following == "\n":
                    # An escaped line break joins the lines; the next line's indentation is dropped.
                    index += 2
                    while index < len(text) and text[index] in " \t":
                        index += 1
                    continue
                if following in _ESCAPES:
                    chunks.append(_ESCAPES[following])
                    index += 2
                    continue
                sizes = {"x": 2, "u": 4, "U": 8}
                if following in sizes:
                    digits = text[index + 2:index + 2 + sizes[following]]
                    if len(digits) != sizes[following] or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                        raise YamlError("bad escape in a double-quoted scalar", number)
                    chunks.append(chr(int(digits, 16)))
                    index += 2 + sizes[following]
                    continue
                raise YamlError(f"unknown escape \\{following}", number)
            if char == '"':
                return _fold_quoted("".join(chunks)), index + 1
            chunks.append(char)
            index += 1
        raise _Unterminated


class _Unterminated(Exception):
    pass


class _FlowParser:
    """Flow collections: [a, b], {a: b}, nested, with plain or quoted scalars."""

    def __init__(self, text, number):
        self.text = text
        self.index = 0
        self.number = number

    def parse(self):
        value = self._value()
        return value, self.index

    def _skip(self):
        while self.index < len(self.text) and self.text[self.index] in " \t\n":
            self.index += 1

    def _value(self):
        self._skip()
        if self.index >= len(self.text):
            raise _Unterminated
        char = self.text[self.index]
        if char == "[":
            return self._sequence()
        if char == "{":
            return self._mapping()
        if char in ("'", '"'):
            value, end = _Parser("")._read_quoted(self.text, self.index, self.number)
            self.index = end
            return value
        if char in ("&", "*", "!"):
            raise YamlError("anchors, aliases and tags are not supported", self.number)
        start = self.index
        while self.index < len(self.text) and self.text[self.index] not in ",]}":
            if self.text[self.index] == ":" and self.text[self.index + 1:self.index + 2] in (" ", ""):
                break
            self.index += 1
        return resolve_plain(self.text[start:self.index].strip())

    def _sequence(self):
        self.index += 1
        items = []
        while True:
            self._skip()
            if self.index >= len(self.text):
                raise _Unterminated
            if self.text[self.index] == "]":
                self.index += 1
                return items
            items.append(self._value())
            self._skip()
            if self.index >= len(self.text):
                raise _Unterminated
            if self.text[self.index] == ",":
                self.index += 1
            elif self.text[self.index] != "]":
                raise YamlError("expected ',' or ']' in a flow sequence", self.number)

    def _mapping(self):
        self.index += 1
        mapping = {}
        while True:
            self._skip()
            if self.index >= len(self.text):
                raise _Unterminated
            if self.text[self.index] == "}":
                self.index += 1
                return mapping
            key = self._value()
            self._skip()
            if self.text[self.index:self.index + 1] != ":":
                raise YamlError("expected ':' in a flow mapping", self.number)
            self.index += 1
            mapping[key] = self._value()
            self._skip()
            if self.index >= len(self.text):
                raise _Unterminated
            if self.text[self.index] == ",":
                self.index += 1
            elif self.text[self.index] != "}":
                raise YamlError("expected ',' or '}' in a flow mapping", self.number)


def _fold(parts):
    """Fold the lines of a multi-line plain scalar: single breaks become spaces, blank lines newlines."""
    result = []
    pending_newlines = 0
    for part in parts:
        if part == "":
            pending_newlines += 1
            continue
        if result:
            result.append("\n" * pending_newlines if pending_newlines else " ")
        result.append(part.strip())
        pending_newlines = 0
    return "".join(result)


def _fold_quoted(text):
    """Fold line breaks inside a quoted scalar the way YAML does."""
    if "\n" not in text:
        return text
    lines = text.split("\n")
    out = lines[0].rstrip(" \t")
    blanks = 0
    for line in lines[1:]:
        stripped = line.strip(" \t")
        if not stripped:
            blanks += 1
            continue
        out += "\n" * blanks if blanks else " "
        out += stripped if line is not lines[-1] else line.lstrip(" \t")
        blanks = 0
    return out


def _fold_block(lines):
    """Fold a `>` block scalar: lines join with spaces, blank lines and more-indented lines keep breaks."""
    out = []
    previous_more_indented = False
    for index, line in enumerate(lines):
        more_indented = line.startswith((" ", "\t"))
        if index == 0:
            out.append(line)
        elif line == "":
            out.append("\n")
        elif more_indented or previous_more_indented or out[-1] == "\n":
            out.append(("\n" if not out[-1].endswith("\n") else "") + line)
        else:
            out.append(" " + line)
        previous_more_indented = more_indented and line != ""
    return "".join(out)


def loads(source):
    """Parse a YAML document of the supported subset.

    :param str source: The YAML text.
    :return: The document: dicts, lists, strings, numbers, booleans and None.
    :raise YamlError: If the document uses unsupported YAML or is not valid.
    """
    return _Parser(source).parse()
