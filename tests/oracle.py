"""Reference brute-force POSIX matcher used by the differential tests.

This is deliberately slow and used only on tiny random patterns/texts.
It enumerates every way an AST can match at a given position and keeps
the POSIX best candidate:

  1. largest ending offset (longest whole match);
  2. for groups in opening-parenthesis order, a group that matched
     beats one that did not; a longer group match beats a shorter one,
     and ties are broken by the earlier start.

The comparison rules here mirror engine._rank_group exactly.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from posixre import ast_nodes as ast

Candidate = Optional[Tuple[int, Tuple[Optional[Tuple[int, int]], ...]]]


def _better(c1, c2) -> bool:
    """True if candidate c1 is POSIX-better than c2 at the same start."""
    if c2 is None:
        return True
    if c1 is None:
        return False
    e1, spans1 = c1
    e2, spans2 = c2
    if e1 != e2:
        return e1 > e2
    for s1, s2 in zip(spans1, spans2):
        r = _span_rank(s1, s2)
        if r != 0:
            return r < 0
    return False


def _span_rank(s1, s2) -> int:
    if s1 is None and s2 is None:
        return 0
    if s1 is None:
        return 1
    if s2 is None:
        return -1
    l1, l2 = s1[1] - s1[0], s2[1] - s2[0]
    if l1 != l2:
        return -1 if l1 > l2 else 1
    if s1[0] != s2[0]:
        return -1 if s1[0] < s2[0] else 1
    return 0


def _merge_spans(a, b):
    """Merge disjoint span rows (concat / alternatives that did not
    both capture the same group).  If both captured a group (this can
    happen for nested repeats) keep the POSIX-better span."""
    out = []
    for x, y in zip(a, b):
        if x is None:
            out.append(y)
        elif y is None:
            out.append(x)
        else:
            out.append(x if _span_rank(x, y) <= 0 else y)
    return tuple(out)


def _merge_iteration(previous, latest):
    """Combine spans accumulated across repeat iterations.

    A capturing group inside a repeated subexpression refers to its
    LAST iteration: whenever the latest iteration captured the group,
    that value overwrites the one from earlier iterations; when the
    latest iteration did not enter the group (None), the previously
    recorded value stays (an absent optional body does not clear it).
    """
    out = []
    for x, y in zip(previous, latest):
        out.append(y if y is not None else x)
    return tuple(out)


class Oracle:
    def __init__(self, tree: ast.Node, groups: int, text: str) -> None:
        self.tree = tree
        self.groups = groups
        self.text = text
        self.n = len(text)
        self.empty = (None,) * groups
        self.memo: Dict = {}
        self._budget = 20000
        self.calls = 0

    def match_at(self, node: ast.Node, p: int) -> List[Candidate]:
        self.calls += 1
        if self.calls > self._budget:
            raise RuntimeError("oracle budget exceeded")
        key = (id(node), p)
        if key in self.memo:
            return self.memo[key]
        self.memo[key] = result = self._compute(node, p)
        return result

    def _empty_cand(self, p: int) -> Candidate:
        return (p, self.empty)

    def _compute(self, node: ast.Node, p: int) -> List[Candidate]:
        if isinstance(node, ast.Empty):
            return [self._empty_cand(p)]

        if isinstance(node, ast.Char):
            if p < self.n and node.set.member(self.text[p]):
                return [(p + 1, self.empty)]
            return []

        if isinstance(node, ast.Assertion):
            if self._assertion(node.kind, p):
                return [self._empty_cand(p)]
            return []

        if isinstance(node, ast.Alt):
            out: List[Candidate] = []
            for br in node.branches:
                out.extend(self.match_at(br, p))
            return out

        if isinstance(node, ast.Concat):
            return self._concat(node.nodes, 0, p)

        if isinstance(node, ast.Group):
            if node.index == 0:
                return self.match_at(node.node, p)
            out = []
            for end, spans in self.match_at(node.node, p):
                spans = list(spans)
                spans[node.index - 1] = (p, end)
                out.append((end, tuple(spans)))
            return out

        if isinstance(node, ast.Repeat):
            return self._repeat(node, p)

        raise AssertionError(type(node))

    def _concat(self, nodes: List[ast.Node], idx: int, p: int) -> List[Candidate]:
        if idx == len(nodes):
            return [self._empty_cand(p)]
        out: List[Candidate] = []
        for mid, spans1 in self.match_at(nodes[idx], p):
            for end, spans2 in self._concat(nodes, idx + 1, mid):
                out.append((end, _merge_spans(spans1, spans2)))
        return out

    def _repeat(self, node: ast.Repeat, p: int) -> List[Candidate]:
        lo, hi = node.lo, node.hi
        max_iters = self.n - p + (1 if hi is None else 0)
        if hi is not None:
            max_iters = min(hi, max_iters)
        if max_iters < lo:
            return []

        # states maps a reached end-position -> (fewest iterations used
        # to reach it, best spans).  Tracking the iteration count (not
        # just position) is what makes a zero-width body safe: it costs
        # one iteration while consuming no characters.
        states: Dict[int, Tuple[int, tuple]] = {p: (0, self.empty)}
        results: Dict[int, tuple] = {}
        while True:
            for e, (iters, spans) in list(states.items()):
                if iters < lo:
                    continue
                cur = results.get(e)
                if cur is None or _better((e, spans), (e, cur)):
                    results[e] = spans
            if not states:
                break
            min_iters = min(iters for iters, _ in states.values())
            if min_iters >= max_iters:
                break
            nxt: Dict[int, Tuple[int, tuple]] = {}
            for e, (iters, spans0) in states.items():
                if iters >= max_iters:
                    continue
                for e2, spans1 in self.match_at(node.node, e):
                    merged = _merge_iteration(spans0, spans1)
                    new_iters = iters + 1
                    old = nxt.get(e2)
                    if old is None:
                        nxt[e2] = (new_iters, merged)
                    else:
                        old_iters, old_spans = old
                        if new_iters < old_iters:
                            nxt[e2] = (new_iters, merged)
                        elif new_iters == old_iters and _better(
                            (e2, merged), (e2, old_spans)
                        ):
                            nxt[e2] = (new_iters, merged)
            states = nxt
        return [(e, spans) for e, spans in results.items()]

    def _assertion(self, kind: str, p: int) -> bool:
        if kind == "bol":
            return p == 0
        if kind == "eol":
            return p == self.n
        wchars = set(
            "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
        )
        before = p > 0 and self.text[p - 1] in wchars
        after = p < self.n and self.text[p] in wchars
        boundary = before != after
        if kind == "wb":
            return boundary
        if kind == "nwb":
            return not boundary
        raise AssertionError(kind)


def search(tree: ast.Node, groups: int, text: str, from_pos: int = 0):
    """Leftmost-longest search via the brute-force oracle.

    Returns ``(start, end, spans)`` or ``None``.  Only candidates whose
    start is at least *from_pos* are considered.
    """
    oracle = Oracle(tree, groups, text)
    best = None
    best_start = -1
    best_end = -1
    for p in range(from_pos, len(text) + 1):
        if best is not None:
            break  # leftmost start already found; its longest was kept
        for end, spans in oracle.match_at(tree, p):
            cand = (end, spans)
            if best is None or _better(cand, best):
                best = cand
                best_start = p
                best_end = end
    if best is None:
        return None
    return best_start, best_end, best[1]
