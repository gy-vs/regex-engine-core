"""Character classes used inside and outside bracket expressions.

The engine works on Python ``str`` and matches full Unicode code
points.  A *set* is a list of items, each a tagged tuple:

* ``("cp", lo, hi)``     -- an inclusive code-point range;
* ``("sw", name, neg)``  -- a backslash shorthand ``\\d``, ``\\w``,
  ``\\s`` (*name* is ``d``/``w``/``s``); *neg* marks the uppercase
  negated variants.

The shorthands follow Python's Unicode definitions (``isdecimal``,
``isalnum`` plus underscore, and the Unicode whitespace set reported by
``str.isspace``).  A top-level *negated* flag flips the whole set and
implements ``[^...]``.
"""

from __future__ import annotations

from typing import List, Tuple

Item = Tuple


def shorthand_members(name: str, ch: str) -> bool:
    if name == "d":
        # isdecimal covers decimal digits beyond ASCII (e.g. Arabic).
        return ch.isdecimal()
    if name == "w":
        return ch == "_" or (ch.isalnum())
    # name == "s"
    return ch.isspace()


class CharSet:
    """A bracket expression, a single literal or a backslash shorthand."""

    __slots__ = ("items", "negated")

    def __init__(self, items: List[Item], negated: bool = False) -> None:
        self.items = items
        self.negated = negated

    @classmethod
    def dot(cls) -> "CharSet":
        return cls([("cp", 0, 0x10FFFF)], negated=False)

    @classmethod
    def literal(cls, ch: str) -> "CharSet":
        cp = ord(ch)
        return cls([("cp", cp, cp)])

    @classmethod
    def shorthand(cls, name: str) -> "CharSet":
        # *name* includes the backslash, e.g. r"\d" or r"\D".
        ch = name[1]
        return cls([("sw", ch.lower(), ch.isupper())], negated=False)

    def member(self, ch: str) -> bool:
        cp = ord(ch)
        hit = False
        for item in self.items:
            if item[0] == "cp":
                _, lo, hi = item
                if lo <= cp <= hi:
                    hit = True
                    break
            else:
                _, name, neg = item
                if shorthand_members(name, ch) != neg:
                    hit = True
                    break
        return hit != self.negated
