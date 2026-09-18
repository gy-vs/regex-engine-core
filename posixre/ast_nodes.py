"""AST node types for the supported regular-expression grammar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .charsets import CharSet


class Node:
    pass


@dataclass
class Empty(Node):
    pass


@dataclass
class Char(Node):
    set: CharSet


@dataclass
class Concat(Node):
    nodes: List[Node]


@dataclass
class Alt(Node):
    branches: List[Node]


@dataclass
class Repeat(Node):
    node: Node
    lo: int
    hi: Optional[int]  # None means unbounded


@dataclass
class Group(Node):
    node: Node
    index: int  # >=1 for capturing, 0 for non-capturing


@dataclass
class Assertion(Node):
    kind: str  # "bol", "eol", "wb", "nwb"
