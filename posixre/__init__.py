"""posixre -- a predictable, non-backtracking regex engine.

The engine supports literals, ``.``, bracket classes with ranges and
negation, concatenation, ``|``, ``* + ?``, counted quantifiers
``{m}``/``{m,}``/``{m,n}``, capturing ``(...)`` and non-capturing
``(?:...)`` groups, the ``^`` and ``$`` anchors, ``\\b``/``\\B`` word
boundaries and backslash escapes.  Backreferences and look-around are
not supported and are rejected at compile time.

Semantics and complexity:

* Matching is a tagged Thompson-NFA simulation with no backtracking.
  Match time is ``O(len(text) * program size)`` for a fixed pattern;
  nested quantifiers cannot make it exponential.
* Match choice and capture groups follow POSIX **leftmost-longest**
  rules, including group capture positions.
* :meth:`Pattern.scan` returns all non-overlapping matches; empty
  matches advance the scan by exactly one character (see its
  docstring).

Public surface: :func:`compile`, :func:`match`, :func:`scan`.
"""

from .api import Match, Pattern, compile, error, match, scan

__all__ = ["compile", "match", "scan", "Pattern", "Match", "error"]
__version__ = "1.0.0"
