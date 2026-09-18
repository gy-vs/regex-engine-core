"""Tagged NFA simulation with no backtracking.

The input is processed one character at a time by an epsilon-closure /
consume step over a fixed NFA, so matching time is bounded by
``O(len(text) * program size * f(G))`` (f a small factor in the number
of capturing groups) and cannot grow exponentially when quantifiers
nest.  ``(a|aa)*b`` compiles to a tiny loop and each 'a' walks around
that loop once.

Capture positions are carried as *tags* on epsilon edges.  A layer of
the simulation holds, for every NFA state reached at the *same input
position*, the antichain of tag assignments that do not dominate one
another under the POSIX group ordering (restricted to groups already
finalized at that state -- see :func:`nfa._compute_active_groups`).
While a group is still open, a short and a long prefix are both kept;
as soon as the group closes, the longer match dominates and the front
collapses.  Fronts never mix assignments that arrived at different
input positions: a consuming edge moves to the next layer.  The front
size is bounded by the number of capturing groups, not by the number
of parse paths.

Acceptance selection uses the full ordering, giving POSIX
**leftmost-longest** semantics:

1. smallest starting offset;
2. then the largest ending offset;
3. then, for groups in opening-parenthesis order, a group matching
   beats one that does not, and a longer match beats a shorter one
   (earliest start breaking ties).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .nfa import Machine, State

# Assignment tuple layout:
#   index 0       -> start of the whole match (always set on a thread)
#   index 2g      -> position recorded on entry to capturing group g
#   index 2g + 1  -> position recorded on exit from capturing group g
# -1 means "not recorded yet" / group did not participate.
# index 1 is unused, kept so tag ids map straight onto tuple indices.
UNSET = -1

Assign = Tuple[int, ...]


class _Result:
    __slots__ = ("end", "assignment")

    def __init__(self, end: int, assignment: Assign) -> None:
        self.end = end
        self.assignment = assignment


def run(
    machine: Machine,
    text: str,
    anchored: bool = False,
    pos: int = 0,
) -> Optional[_Result]:
    groups = machine.groups
    width = 2 * groups + 2
    assertion = machine.assertion

    def fresh(start: int) -> Assign:
        a = [UNSET] * width
        a[0] = start
        return tuple(a)

    def compare(st: State, x: Assign, y: Assign) -> int:
        """POSIX order on assignments meeting at *st* at one position.

        Groups structurally active at *st* are skipped (their tags are
        provisional).  Returns -1 when *x* is better, +1 for *y*, 0
        when they are incomparable/equal on every finalized group.
        """
        if x[0] != y[0]:
            return -1 if x[0] < y[0] else 1
        active = st.active_groups
        for g in range(1, groups + 1):
            xo, xc = x[2 * g], x[2 * g + 1]
            yo, yc = y[2 * g], y[2 * g + 1]
            if g in active:
                # Group structurally open at this state: provisional.
                continue
            x_status = _group_status(xo, xc)
            y_status = _group_status(yo, yc)
            # Outside the group's body a thread can only have the group
            # closed (2) or never entered (0); an open tag here means
            # the thread will re-enter through a quantifier loop, which
            # is structurally inside another iteration and is treated
            # as provisional only when the state is actually reachable
            # from the loop body -- active_groups captures that.
            if x_status == 1 or y_status == 1:
                continue
            if x_status != y_status:
                # Closed match beats a structurally absent group.
                return -1 if x_status > y_status else 1
            if x_status == 2:
                xlen, ylen = xc - xo, yc - yo
                if xlen != ylen:
                    return -1 if xlen > ylen else 1
                if xo != yo:
                    return -1 if xo < yo else 1
        return 0

    def insert_front(front: List[Assign], st: State, a: Assign) -> bool:
        """Insert *a* into antichain *front* in place.

        Returns True when *a* was added; members it dominates are
        removed.  Ties keep the first inserted assignment.
        """
        kept: List[Assign] = []
        dominated = False
        for b in front:
            c = compare(st, a, b)
            if c > 0:
                # b is POSIX-better at some finalized group and nowhere
                # worse: it dominates a.
                dominated = True
                kept.append(b)
            elif c == 0 and a != b:
                # Incomparable (e.g. one has the group closed, the
                # other a structurally different, still-relevant path).
                kept.append(b)
            elif c == 0:
                # Fully indistinguishable for our purposes.
                dominated = True
                kept.append(b)
            # c < 0: a dominates b -> drop b.
        if dominated:
            front[:] = kept
            return False
        kept.append(a)
        front[:] = kept
        return True

    def closure(
        seeds: List[Tuple[State, Assign]], p: int
    ) -> Dict[State, List[Assign]]:
        """Epsilon closure at input position *p*.

        All *seeds* must represent threads that are physically at
        position *p*.  Tag actions record *p*; zero-width assertions
        are evaluated against position *p*.
        """
        live: Dict[State, List[Assign]] = {}
        queue: List = []
        for st, a in seeds:
            front = live.get(st)
            if front is None:
                live[st] = [a]
                queue.append((st, a))
            else:
                if insert_front(front, st, a):
                    queue.append((st, a))
        qi = 0
        while qi < len(queue):
            st, a = queue[qi]
            qi += 1
            if a not in live.get(st, ()):
                continue  # this queue entry was superseded
            for edge in st.edges:
                kind = edge[0]
                if kind == "c":
                    continue
                if kind == "a":
                    _, target, assertion_kind = edge
                    if not assertion(text, p, assertion_kind):
                        continue
                    na = a
                else:
                    _, target, actions = edge
                    na = a
                    if actions:
                        vals = None
                        for action in actions:
                            tag = action[1]
                            if na[tag] != p:
                                if vals is None:
                                    vals = list(na)
                                vals[tag] = p
                        if vals is not None:
                            na = tuple(vals)
                front = live.get(target)
                if front is None:
                    live[target] = [na]
                    queue.append((target, na))
                elif insert_front(front, target, na):
                    queue.append((target, na))
        return live

    def better_result(
        best: Optional[_Result], end: int, a: Assign
    ) -> Optional[_Result]:
        if best is None:
            return _Result(end, a)
        b = best.assignment
        if a[0] != b[0]:
            return _Result(end, a) if a[0] < b[0] else best
        if end != best.end:
            return _Result(end, a) if end > best.end else best
        # At the accept state every group is finalized.
        for g in range(1, groups + 1):
            r = _rank_group(
                a[2 * g], a[2 * g + 1], b[2 * g], b[2 * g + 1]
            )
            if r != 0:
                return _Result(end, a) if r < 0 else best
        return best

    best: Optional[_Result] = None
    n = len(text)

    # 'carry' holds threads (state -> antichain) that consumed the last
    # character and are therefore physically at the current position.
    carry: Dict[State, List[Assign]] = {}
    p = pos
    while p <= n:
        seeds: List = [(st, a) for st, front in carry.items() for a in front]
        if p == pos or not anchored:
            seeds.append((machine.start, fresh(p)))
        live = closure(seeds, p)

        for a in live.get(machine.accept, ()):
            best = better_result(best, p, a)

        if p == n:
            break

        # Consume text[p]; destinations form the carry at position p+1.
        ch = text[p]
        carry = {}
        for st, front in live.items():
            for a in front:
                for edge in st.edges:
                    if edge[0] == "c" and edge[2].member(ch):
                        carry.setdefault(edge[1], []).append(a)
        p += 1

    return best


def _rank_group(xo: int, xc: int, yo: int, yc: int) -> int:
    """Full POSIX order on one finalized capturing group.

    -1 = *x* better, +1 = *y* better, 0 = equal.  A group that matched
    beats one that did not; among matches the longer span wins, and
    ties break to the earlier start.
    """
    xs = _group_status(xo, xc)
    ys = _group_status(yo, yc)
    if xs != ys:
        return -1 if xs > ys else 1
    if xs == 0:
        return 0
    if xs == 2:
        xlen, ylen = xc - xo, yc - yo
        if xlen != ylen:
            return -1 if xlen > ylen else 1
    if xo != yo:
        return -1 if xo < yo else 1
    return 0


def _group_status(open_tag: int, close_tag: int) -> int:
    # 0 = did not participate, 1 = open, 2 = closed
    if open_tag == UNSET:
        return 0
    if close_tag == UNSET:
        return 1
    return 2
