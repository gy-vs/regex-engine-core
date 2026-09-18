"""Public API: :func:`compile`, :func:`match`, :func:`scan`.

This package deliberately has no command-line entry point.
"""

from __future__ import annotations

from typing import Iterator, List, Optional, Tuple, Union

from . import engine
from .errors import error
from .nfa import compile_machine
from .parser import Parser

__all__ = ["compile", "match", "scan", "Pattern", "Match", "error"]


class Match:
    """The result of one successful search.

    ``span()`` gives the whole match; ``span(g)``/``group(g)`` give
    capturing group *g* (numbered from 1).  A group that did not
    participate returns ``None`` from both.  ``groups()`` returns the
    tuple of all group substrings.
    """

    def __init__(
        self,
        text: str,
        start: int,
        end: int,
        spans: List[Optional[Tuple[int, int]]],
    ) -> None:
        self._text = text
        self._start = start
        self._end = end
        self._spans = spans

    def span(self, group: int = 0) -> Optional[Tuple[int, int]]:
        if group == 0:
            return (self._start, self._end)
        return self._spans[group - 1]

    def start(self, group: int = 0) -> Optional[int]:
        sp = self.span(group)
        return None if sp is None else sp[0]

    def end(self, group: int = 0) -> Optional[int]:
        sp = self.span(group)
        return None if sp is None else sp[1]

    def group(self, group: int = 0) -> Optional[str]:
        sp = self.span(group)
        if sp is None:
            return None
        return self._text[sp[0] : sp[1]]

    def groups(self) -> Tuple[Optional[str], ...]:
        return tuple(self.group(g) for g in range(1, len(self._spans) + 1))

    def groupspans(self) -> Tuple[Optional[Tuple[int, int]], ...]:
        return tuple(self._spans)

    def __getitem__(self, group: int) -> Optional[str]:
        return self.group(group)

    def __repr__(self) -> str:
        return (
            f"Match(match={self.group()!r}, span={(self._start, self._end)}, "
            f"groups={self.groups()!r})"
        )


class Pattern:
    """A compiled regular expression."""

    def __init__(self, source: str) -> None:
        self.pattern = source
        tree, group_count = Parser(source).parse()
        self.groups = group_count
        self._machine = compile_machine(tree, group_count)

    def _search(
        self, text: str, anchored: bool, pos: int
    ) -> Optional[Match]:
        result = engine.run(self._machine, text, anchored=anchored, pos=pos)
        if result is None:
            return None
        asgn = result.assignment
        start = asgn[0]
        end = result.end
        spans: List[Optional[Tuple[int, int]]] = []
        for g in range(1, self.groups + 1):
            o = asgn[2 * g]
            c = asgn[2 * g + 1]
            if o == -1:
                spans.append(None)
            else:
                spans.append((o, c))
        return Match(text, start, end, spans)

    def match(
        self, text: str, pos: int = 0, anchored: bool = False
    ) -> Optional[Match]:
        """Return the POSIX leftmost-longest match, or ``None``.

        By default the search is unanchored: the pattern may start at
        any position in *text*.  ``anchored=True`` restricts it to start
        at *pos* (use a ``^`` in the pattern to anchor to position 0).
        """
        return self._search(text, anchored, pos)

    def scan(self, text: str) -> Iterator[Match]:
        """Scan *text* and yield all non-overlapping matches in order.

        Advancement rules (relied upon so empty matches cannot stall the
        scan):

        * after a non-empty match, the next search starts at the match
          end.  If the pattern only matches the empty string there, that
          empty match is **skipped** (it shares its position with the
          previous match's end) and the cursor advances one more
          character before searching again;
        * after an **empty** match that was actually yielded, the cursor
          advances by exactly one character; an empty match at the end
          of the text is yielded last and the scan stops;
        * therefore two consecutive matches never occupy the same
          position, and each character is skipped at most once.
        """
        p = 0
        n = len(text)
        last_end = -1
        while p <= n:
            m = self._search(text, anchored=False, pos=p)
            if m is None:
                return
            if m.end() == m.start() and m.start() == last_end:
                # Empty match sitting exactly on the previous match's
                # end: skip it and move one character forward.
                if p == n:
                    return
                p += 1
                continue
            yield m
            last_end = m.end()
            if m.end() > m.start():
                p = m.end()
            else:
                # Yielded empty match: one character of progress, or
                # stop after yielding the empty match at the end.
                if p == n:
                    return
                p += 1


def compile(pattern: Union[str, Pattern]) -> Pattern:
    """Compile *pattern* (or return it unchanged if already compiled)."""
    if isinstance(pattern, Pattern):
        return pattern
    return Pattern(pattern)


def match(
    pattern: Union[str, Pattern], text: str, anchored: bool = False
) -> Optional[Match]:
    """Compile *pattern* and return its single leftmost-longest match."""
    return compile(pattern).match(text, anchored=anchored)


def scan(pattern: Union[str, Pattern], text: str) -> Iterator[Match]:
    """Compile *pattern* and iterate over all non-overlapping matches."""
    return compile(pattern).scan(text)
