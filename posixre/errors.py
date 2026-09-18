"""Compilation errors for the :mod:`posixre` engine."""

from __future__ import annotations


class error(Exception):
    """Raised at compile time when a pattern is malformed or uses a
    feature that is outside the supported grammar (backreferences and
    look-around).

    Attributes:
        pos: Zero-based offset of the offending character in the
            pattern.  ``pos + 1`` is the "第几个字符" number used in the
            human readable message.
    """

    def __init__(self, message: str, pos: int) -> None:
        self.pos = pos
        super().__init__(f"{message} (at pattern character {pos + 1})")
