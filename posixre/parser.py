"""Recursive-descent parser turning a pattern string into an AST.

The grammar (highest precedence last):

    pattern := alternation
    alternation := sequence ('|' sequence)*
    sequence := atom_with_quantifier*
    atom_with_quantifier := atom quantifier?
    quantifier := '*' | '+' | '?' | count
    count := '{' digits '}' | '{' digits ',' '}' | '{' digits ',' digits '}'
    atom := '(' pattern ')' | '(?:' pattern ')' | '[' class ']'
            | '.' | '^' | '$' | escape | literal

Backreferences (``\\1`` ... ``\\9``, ``\\k<...>``) and look-around
(``(?=``, ``(?!``, ``(?<=``, ``(?<!``) are rejected here at compile
time and the reported position points at the offending character.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import ast_nodes as ast
from .charsets import CharSet, Item
from .errors import error


# Upper bound on how many body copies a counted quantifier (or nested
# counted quantifiers) may contribute to the NFA.  The engine is linear
# in the compiled program size, so the program itself must be bounded.
MAX_EXPANSIONS = 1000

_SIMPLE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "f": "\f",
    "v": "\v",
    "a": "\a",
}


class Parser:
    def __init__(self, pattern: str) -> None:
        self.s = pattern
        self.n = len(pattern)
        self.i = 0
        self.groups = 0

    # -- entry point ------------------------------------------------------

    def parse(self) -> Tuple[ast.Node, int]:
        node = self._alternation()
        if self.i < self.n:
            ch = self.s[self.i]
            if ch == ")":
                raise error("unbalanced ')'", self.i)
            raise error(f"unexpected character {ch!r}", self.i)
        return node, self.groups

    # -- grammar ----------------------------------------------------------

    def _alternation(self) -> ast.Node:
        branches: List[ast.Node] = [self._sequence()]
        while self._peek() == "|":
            self.i += 1
            branches.append(self._sequence())
        if len(branches) == 1:
            return branches[0]
        return ast.Alt(branches)

    def _sequence(self) -> ast.Node:
        nodes: List[ast.Node] = []
        while True:
            ch = self._peek()
            if ch is None or ch in ")|":
                break
            nodes.append(self._repeated())
        nodes = [x for x in nodes if not isinstance(x, ast.Empty)]
        if not nodes:
            return ast.Empty()
        if len(nodes) == 1:
            return nodes[0]
        return ast.Concat(nodes)

    def _repeated(self) -> ast.Node:
        atom_pos = self.i
        node = self._atom()
        q = self._quantifier_suffix()
        if q is None:
            return node
        lo, hi, qpos = q
        if isinstance(node, ast.Assertion):
            raise error("a quantifier may not be applied to an anchor", qpos)
        if isinstance(node, ast.Empty):
            raise error("nothing to repeat", qpos)
        if isinstance(node, ast.Repeat):
            raise error("multiple quantifiers cannot be stacked", qpos)
        rep = ast.Repeat(node, lo, hi)
        rep.pos = qpos  # type: ignore[attr-defined]
        # A second quantifier immediately following the first (e.g.
        # "a{2}{3}" or "a**") is always an error.
        if self._starts_quantifier():
            raise error("multiple quantifiers cannot be stacked", self.i)
        # Greediness modifiers are part of backtracking semantics; the
        # engine is POSIX longest, so reject rather than silently ignore.
        nxt = self._peek()
        if nxt == "?":
            raise error("lazy quantifiers are not supported (POSIX is always longest)", self.i)
        if nxt == "+":
            raise error("possessive quantifiers are not supported", self.i)
        self._check_expansion(rep, atom_pos)
        return rep

    def _starts_quantifier(self) -> bool:
        ch = self._peek()
        if ch is None:
            return False
        if ch in "*+?":
            return True
        if ch == "{":
            return self._count_at(self.i) is not None
        return False

    def _quantifier_suffix(self) -> Optional[Tuple[int, Optional[int], int]]:
        ch = self._peek()
        pos = self.i
        if ch == "*":
            self.i += 1
            return (0, None, pos)
        if ch == "+":
            self.i += 1
            return (1, None, pos)
        if ch == "?":
            self.i += 1
            return (0, 1, pos)
        if ch == "{":
            parsed = self._count_at(pos)
            if parsed is not None:
                lo, hi, end = parsed
                self.i = end
                return (lo, hi, pos)
        return None

    def _count_at(self, pos: int) -> Optional[Tuple[int, Optional[int], int]]:
        """Try to parse a count quantifier starting at *pos*.

        Returns ``(lo, hi, index_after)`` or ``None`` when the braces do
        not form a well-formed count (in which case ``{`` is a literal).
        Does not modify ``self.i``.
        """
        j = pos + 1
        start = j
        while j < self.n and self.s[j].isdigit():
            j += 1
        if j == start:
            return None
        m = int(self.s[start:j])
        hi: Optional[int]
        if j < self.n and self.s[j] == "}":
            hi = m
            j += 1
        elif j < self.n and self.s[j] == ",":
            j += 1
            dstart = j
            while j < self.n and self.s[j].isdigit():
                j += 1
            if j >= self.n or self.s[j] != "}":
                return None
            if dstart == j:
                hi = None
            else:
                hi = int(self.s[dstart:j])
                if hi < m:
                    raise error(f"counted quantifier range {{{m},{hi}}} is reversed", pos)
            j += 1
        else:
            return None
        return (m, hi, j)

    def _atom(self) -> ast.Node:
        ch = self._peek()
        if ch is None:
            return ast.Empty()
        if ch == "(":
            return self._group()
        if ch == "[":
            return self._char_class()
        if ch == ".":
            self.i += 1
            return ast.Char(CharSet.dot())
        if ch == "^":
            self.i += 1
            return ast.Assertion("bol")
        if ch == "$":
            self.i += 1
            return ast.Assertion("eol")
        if ch == "\\":
            return self._escape(outside_class=True)
        if ch in "*+?":
            raise error("nothing to repeat", self.i)
        # '{' that is not a valid count, '}', and ordinary chars.
        self.i += 1
        return ast.Char(CharSet.literal(ch))

    def _group(self) -> ast.Node:
        open_pos = self.i
        assert self.s[self.i] == "("
        self.i += 1
        index = 0
        if self._peek() == "?":
            marker = self.i  # '?' is at the current index
            kind = self._peek_at(self.i + 1)
            if kind == ":":
                self.i += 2
            else:
                n2 = self._peek_at(self.i + 2)
                if kind == "=" or kind == "!":
                    raise error("look-around assertions are not supported", marker)
                if kind == "<" and n2 in ("=", "!"):
                    raise error("look-around assertions are not supported", marker)
                if kind == ">":
                    raise error("atomic groups are not supported", marker)
                if kind == "#":
                    raise error("inline comments are not supported", marker)
                if kind == "P" or (kind == "<" and n2 is not None):
                    raise error("named groups/backreferences are not supported", marker)
                if kind is not None and kind.isalpha():
                    raise error("inline flag groups are not supported", marker)
                raise error("unknown group syntax", open_pos)
        else:
            self.groups += 1
            index = self.groups
        inner = self._alternation()
        if self._peek() != ")":
            raise error("missing closing ')' for group", open_pos)
        self.i += 1
        return ast.Group(inner, index)

    # -- escapes ----------------------------------------------------------

    def _escape(self, outside_class: bool) -> ast.Node:
        """Consume a backslash escape starting at ``self.i``; return its node."""
        bs = self.i
        assert self.s[self.i] == "\\"
        if self.i + 1 >= self.n:
            raise error("dangling backslash at end of pattern", self.i)
        ch = self.s[self.i + 1]

        if ch in "dDwWsS":
            self.i += 2
            return ast.Char(CharSet.shorthand("\\" + ch))
        if ch in "nrtfva":
            self.i += 2
            return ast.Char(CharSet.literal(_SIMPLE_ESCAPES[ch]))
        if ch == "0":
            self.i += 2
            return ast.Char(CharSet.literal("\x00"))
        if not outside_class and ch in "1234567":
            # Inside a bracket class there are no backreferences; a
            # leading-backslash digit is an octal escape (\0..\377).
            value, consumed = self._octal_escape(bs)
            self.i = consumed
            return ast.Char(CharSet.literal(chr(value)))
        if ch == "x":
            value = self._hex_escape(bs)
            return ast.Char(CharSet.literal(chr(value)))
        if ch == "b" or ch == "B":
            if not outside_class:
                # Inside a class \b means backspace (ASCII tradition).
                self.i += 2
                return ast.Char(CharSet.literal("\b"))
            self.i += 2
            return ast.Assertion("wb" if ch == "b" else "nwb")
        if outside_class and ch in "123456789":
            raise error("backreferences are not supported", bs)
        if outside_class and ch == "k":
            raise error("backreferences are not supported", bs)
        # Any other escaped character stands for itself.  This covers
        # \. \\ \( \) \[ \] \^ \$ \| \* \+ \? \{ \} \- and so on.
        self.i += 2
        return ast.Char(CharSet.literal(ch))

    def _hex_escape(self, bs: int) -> int:
        # Position of 'x' is bs+1; need exactly two hex digits.
        if self.i + 3 >= self.n:
            raise error("incomplete \\x escape (need two hex digits)", bs)
        hexd = self.s[self.i + 2 : self.i + 4]
        if len(hexd) != 2 or not all(c in "0123456789abcdefABCDEF" for c in hexd):
            raise error("malformed \\x escape (need two hex digits)", bs)
        self.i += 4
        return int(hexd, 16)

    def _octal_escape(self, bs: int) -> Tuple[int, int]:
        """Parse up to three octal digits after a backslash.

        Used only inside bracket classes, where backslash-digit is an
        octal character value rather than a backreference.
        """
        j = bs + 1
        digits = ""
        while j < self.n and self.s[j] in "01234567" and len(digits) < 3:
            digits += self.s[j]
            j += 1
        value = int(digits, 8)
        if value > 0xFF:
            raise error("octal escape exceeds 255", bs)
        return value, j

    # -- bracket classes --------------------------------------------------

    def _char_class(self) -> ast.Node:
        open_pos = self.i
        assert self.s[self.i] == "["
        self.i += 1
        negated = False
        if self._peek() == "^":
            negated = True
            self.i += 1
        items: List[Item] = []
        # A ']' immediately after '[' or '[^' is a literal, not a
        # closing bracket.
        allow_close = False
        while True:
            ch = self._peek()
            if ch is None:
                raise error("unterminated character class", open_pos)
            if ch == "]" and allow_close:
                self.i += 1
                break
            allow_close = True
            node = self._class_atom()
            assert isinstance(node, ast.Char)
            if self._peek() == "-" and self._peek_at(self.i + 1) not in (None, "]"):
                lo = self._single_cp(node, open_pos)
                self.i += 1  # consume '-'
                hi_node = self._class_atom()
                hi = self._single_cp(hi_node, open_pos)
                if lo > hi:
                    raise error(
                        f"bad character range {chr(lo)!r}-{chr(hi)!r}", open_pos
                    )
                items.append(("cp", lo, hi))
            else:
                items.extend(node.set.items)
        return ast.Char(CharSet(items, negated=negated))

    def _class_atom(self) -> ast.Char:
        ch = self._peek()
        if ch == "\\":
            node = self._escape(outside_class=False)
            assert isinstance(node, ast.Char)
            return node
        if ch is None:
            raise error("unterminated character class", self.i)
        self.i += 1
        return ast.Char(CharSet.literal(ch))

    @staticmethod
    def _single_cp(node: ast.Node, open_pos: int) -> int:
        """A range endpoint must be one literal code point."""
        if not isinstance(node, ast.Char) or node.set.negated:
            raise error("bad character range endpoint", open_pos)
        items = node.set.items
        if len(items) == 1 and items[0][0] == "cp":
            _, lo, hi = items[0]
            if lo == hi:
                return lo
        raise error("shorthand classes may not be used as a range endpoint", open_pos)

    # -- helpers ----------------------------------------------------------

    def _peek(self) -> Optional[str]:
        if self.i >= self.n:
            return None
        return self.s[self.i]

    def _peek_at(self, j: int) -> Optional[str]:
        if j >= self.n:
            return None
        return self.s[j]

    def _check_expansion(self, rep: ast.Repeat, pos: int) -> None:
        if expansion_cost(rep) > MAX_EXPANSIONS:
            raise error(
                "counted quantifier expands to more than "
                f"{MAX_EXPANSIONS} instructions",
                pos,
            )


def expansion_cost(node: ast.Node) -> int:
    """Worst-case number of body copies the counted quantifiers produce."""
    if isinstance(node, ast.Char) or isinstance(node, ast.Assertion):
        return 1
    if isinstance(node, ast.Empty):
        return 0
    if isinstance(node, ast.Concat):
        return sum(expansion_cost(x) for x in node.nodes)
    if isinstance(node, ast.Alt):
        return sum(expansion_cost(x) for x in node.branches)
    if isinstance(node, ast.Group):
        return expansion_cost(node.node)
    if isinstance(node, ast.Repeat):
        copies = node.lo + (1 if node.hi is None else node.hi - node.lo)
        return copies * expansion_cost(node.node)
    raise AssertionError(type(node))
