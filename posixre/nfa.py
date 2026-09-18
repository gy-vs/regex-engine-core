"""Thompson NFA construction.

The compiled program is an epsilon-NFA.  Every edge is one of:

* a consuming edge carrying a :class:`~posixre.charsets.CharSet`;
* an epsilon edge carrying a *tag action* (set one of the 2*G capture
  tags to the current input position);
* an epsilon edge carrying a zero-width assertion (``^``, ``$``,
  ``\\b``, ``\\B``).

Each capturing group *g* owns two tags: tag ``2g`` is set on entry to
the group and tag ``2g+1`` on exit.  Quantifiers that repeat a group
simply set the same tags again on every iteration, so the final value
left in a tag is the position recorded by the *last* iteration -- the
POSIX-required semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from . import ast_nodes as ast

# Edge kinds:
#   ("c", target, charset)                consuming
#   ("e", target, [(tag, value-or-None)])  epsilon with tag assignments
#   ("a", target, assertion_kind)          epsilon with assertion
Edge = Tuple


@dataclass(eq=False)
class State:
    edges: List[Edge] = field(default_factory=list)
    # Set of capturing-group indices whose body contains this state,
    # i.e. groups that are structurally "open" at this state.  Filled
    # in once after construction.
    active_groups: frozenset = field(default_factory=frozenset)


@dataclass
class Machine:
    start: State
    accept: State
    states: List[State]
    groups: int
    # Called by the simulator with (text, position, kind); True if the
    # zero-width assertion holds at that position.
    assertion: Callable[[str, int, str], bool]


def compile_machine(tree: ast.Node, groups: int) -> Machine:
    builder = _Builder()
    start, end = builder.emit(tree)
    states = builder.states
    _compute_active_groups(states, start)
    return Machine(start, end, states, groups, _assertion_holds)


def _compute_active_groups(states: List[State], start: State) -> None:
    """Fill ``State.active_groups`` for every state reachable from
    *start*.

    A capturing group is *active* at a state when threads reaching that
    state are structurally inside the group's body, meaning its close
    tag cannot have been recorded yet.  The information is structural
    (independent of the input): the graph around an enter/exit pair is
    a reducible region, so a state either is or is not inside it.
    """
    # First, identify each group's body states by forward expansion
    # starting at the target of its open-tag edge, stopping at the
    # source of its close-tag edge.  Edges in the Thompson NFA can
    # leave the body only through that close edge, so this is exact.
    for g in range(1, _max_group(states) + 1):
        open_target = None
        close_source = None
        for s in states:
            for edge in s.edges:
                if edge[0] != "e":
                    continue
                for action in edge[2]:
                    if action == ("set", 2 * g):
                        open_target = edge[1]
                    elif action == ("set", 2 * g + 1):
                        close_source = s
        if open_target is None or close_source is None:
            continue
        inside = set()
        stack = [open_target]
        while stack:
            s = stack.pop()
            if s in inside or s is close_source:
                continue
            inside.add(s)
            for edge in s.edges:
                # All edges from an interior state stay in the region,
                # except the close-tag epsilon edge itself (which is a
                # property of the single close_source state).
                stack.append(edge[1])
        for s in inside:
            s.active_groups = s.active_groups | frozenset((g,))


def _max_group(states: List[State]) -> int:
    max_g = 0
    for s in states:
        for edge in s.edges:
            if edge[0] == "e":
                for action in edge[2]:
                    tag = action[1]
                    if tag % 2 == 0:
                        max_g = max(max_g, tag // 2)
    return max_g


class _Builder:
    def __init__(self) -> None:
        self.states: List[State] = []

    def state(self) -> State:
        s = State()
        self.states.append(s)
        return s

    def emit(self, node: ast.Node) -> Tuple[State, State]:
        if isinstance(node, ast.Empty):
            a, b = self.state(), self.state()
            a.edges.append(("e", b, ()))
            return a, b
        if isinstance(node, ast.Char):
            a, b = self.state(), self.state()
            a.edges.append(("c", b, node.set))
            return a, b
        if isinstance(node, ast.Assertion):
            a, b = self.state(), self.state()
            a.edges.append(("a", b, node.kind))
            return a, b
        if isinstance(node, ast.Concat):
            return self._concat(node.nodes)
        if isinstance(node, ast.Alt):
            return self._alt(node.branches)
        if isinstance(node, ast.Group):
            return self._group(node)
        if isinstance(node, ast.Repeat):
            return self._repeat(node)
        raise AssertionError(type(node))

    def _concat(self, nodes: List[ast.Node]) -> Tuple[State, State]:
        first = self.state()
        prev_out = first
        last_end: Optional[State] = None
        for child in nodes:
            cs, ce = self.emit(child)
            prev_out.edges.append(("e", cs, ()))
            prev_out = ce
        end = self.state()
        prev_out.edges.append(("e", end, ()))
        return first, end

    def _alt(self, branches: List[ast.Node]) -> Tuple[State, State]:
        split = self.state()
        end = self.state()
        for child in branches:
            cs, ce = self.emit(child)
            split.edges.append(("e", cs, ()))
            ce.edges.append(("e", end, ()))
        return split, end

    def _group(self, node: ast.Group) -> Tuple[State, State]:
        gs, ge = self.emit(node.node)
        if node.index == 0:
            return gs, ge
        enter, exit_ = self.state(), self.state()
        enter.edges.append(("e", gs, (("set", 2 * node.index),)))
        ge.edges.append(("e", exit_, (("set", 2 * node.index + 1),)))
        return enter, exit_

    def _repeat(self, node: ast.Repeat) -> Tuple[State, State]:
        lo = node.lo
        hi = node.hi

        # Emit *copies* independent body fragments connected by epsilon.
        def body() -> Tuple[State, State]:
            return self.emit(node.node)

        first = self.state()
        tail = first

        for _ in range(lo):
            bs, be = body()
            tail.edges.append(("e", bs, ()))
            tail = be

        if hi is None:
            # tail -> split -> bs; be -> split; split -> end
            split = self.state()
            bs, be = body()
            end = self.state()
            tail.edges.append(("e", split, ()))
            split.edges.append(("e", bs, ()))
            split.edges.append(("e", end, ()))
            be.edges.append(("e", split, ()))
            return first, end

        extra = hi - lo
        ends: List[State] = [tail]
        for _ in range(extra):
            split = self.state()
            bs, be = body()
            end = self.state()
            tail.edges.append(("e", split, ()))
            split.edges.append(("e", bs, ()))
            split.edges.append(("e", end, ()))
            be.edges.append(("e", end, ()))
            tail = end
            ends.append(tail)
        final = self.state()
        for e in ends:
            e.edges.append(("e", final, ()))
        return first, final


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

def _is_word(ch: str) -> bool:
    # Same definition as the \w shorthand in charsets.py.
    return ch == "_" or ch.isalnum()


def _assertion_holds(text: str, pos: int, kind: str) -> bool:
    if kind == "bol":
        return pos == 0
    if kind == "eol":
        return pos == len(text)
    before = _is_word(text[pos - 1]) if pos > 0 else False
    after = _is_word(text[pos]) if pos < len(text) else False
    at_boundary = before != after
    if kind == "wb":
        return at_boundary
    if kind == "nwb":
        return not at_boundary
    raise AssertionError(kind)
