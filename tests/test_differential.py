"""Differential testing against the brute-force POSIX oracle.

Hundreds of small random patterns over a small alphabet are compiled
and run over small random texts; both the single-match result and the
full scan sequence (spans and every capture group) are compared with
the oracle.  The oracle does not use re and simply enumerates AST
parses.
"""

import random
import unittest

from posixre import compile
from posixre.parser import Parser

from tests.oracle import search as oracle_search


ALPHABET = ["a", "b", "c"]


def gen_pattern(rng: random.Random, depth: int) -> str:
    depth -= 1
    if depth <= 0 or rng.random() < 0.35:
        return gen_atom(rng)
    choice = rng.random()
    if choice < 0.4:
        parts = [gen_pattern(rng, depth - 1) for _ in range(rng.randint(1, 3))]
        return "".join(parts)
    if choice < 0.7:
        parts = [gen_pattern(rng, depth - 1) for _ in range(rng.randint(2, 3))]
        return "|".join(parts)
    atom = gen_atom(rng)
    q = rng.choice(["*", "+", "?"])
    if rng.random() < 0.3:
        lo = rng.randint(0, 2)
        hi = lo + rng.randint(0, 2)
        q = "{%d,%d}" % (lo, hi)
    if rng.random() < 0.5:
        atom = "(" + atom + ")"
    return atom + q


def gen_atom(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.45:
        return rng.choice(ALPHABET)
    if r < 0.6:
        return "."
    if r < 0.72:
        lo = rng.choice(ALPHABET)
        hi = rng.choice(ALPHABET)
        if lo > hi:
            lo, hi = hi, lo
        return "[" + lo + "-" + hi + "]"
    if r < 0.82:
        body = rng.sample(ALPHABET, rng.randint(1, 2))
        neg = "^" if rng.random() < 0.3 else ""
        return "[" + neg + "".join(body) + "]"
    if r < 0.9:
        return "(?:" + rng.choice(ALPHABET) + "|" + rng.choice(ALPHABET) + ")"
    return rng.choice(ALPHABET)


def gen_text(rng: random.Random) -> str:
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 8)))


def oracle_scan(source, text):
    """Reference implementation of the documented scan advancement."""
    tree, groups = Parser(source).parse()
    out = []
    p = 0
    n = len(text)
    last_end = -1
    while p <= n:
        found = oracle_search(tree, groups, text, from_pos=p)
        if found is None:
            break
        start, end, spans = found
        if end == start and start == last_end:
            if p == n:
                break
            p += 1
            continue
        out.append((start, end, tuple(spans)))
        last_end = end
        if end > start:
            p = end
        else:
            if p == n:
                break
            p += 1
    return out


class DifferentialTests(unittest.TestCase):
    def test_random_single_matches(self):
        rng = random.Random(20260918)
        checked = 0
        for _ in range(900):
            source = gen_pattern(rng, depth=rng.randint(2, 4))
            try:
                tree, groups = Parser(source).parse()
                pat = compile(source)
            except Exception:
                continue
            text = gen_text(rng)
            try:
                expected = oracle_search(tree, groups, text)
            except RuntimeError:
                continue
            actual = pat.match(text)
            if expected is None:
                self.assertIsNone(
                    actual, f"{source!r} on {text!r}: unexpected match"
                )
                continue
            estart, eend, espans = expected
            self.assertIsNotNone(
                actual, f"{source!r} on {text!r}: missed match"
            )
            self.assertEqual(
                actual.span(),
                (estart, eend),
                f"{source!r} on {text!r}: span mismatch",
            )
            self.assertEqual(
                actual.groupspans(),
                tuple(espans),
                f"{source!r} on {text!r}: groups mismatch",
            )
            checked += 1
        self.assertGreater(checked, 200)

    def test_random_scans(self):
        rng = random.Random(424242)
        checked = 0
        for _ in range(300):
            source = gen_pattern(rng, depth=rng.randint(2, 3))
            try:
                pat = compile(source)
                Parser(source).parse()  # validates for the oracle
            except Exception:
                continue
            text = gen_text(rng)
            try:
                expected = oracle_scan(source, text)
            except RuntimeError:
                continue
            actual = [
                (m.start(), m.end(), m.groupspans()) for m in pat.scan(text)
            ]
            self.assertEqual(
                [(s, e) for s, e, _ in actual],
                [(s, e) for s, e, _ in expected],
                f"scan spans {source!r} on {text!r}",
            )
            self.assertEqual(
                [sp for _, _, sp in actual],
                [sp for _, _, sp in expected],
                f"scan groups {source!r} on {text!r}",
            )
            checked += 1
        self.assertGreater(checked, 100)

    def test_targeted_overlap_patterns(self):
        patterns = [
            r"(a|ab)(c|bcd)(d*)",
            r"(a|aa)*b",
            r"(a|a)*",
            r"((ab|a)(bc|c))*",
            r"(x|xy|xyz)*z?",
            r"(a*)(a*)",
            r"(ab?)(b?c)?",
            r"(a|ab|abc)(d|bcd|cd)?",
            r"((a|b)+)(c|cc)*",
            r"(.?)(a?)(b*)",
        ]
        texts = [
            "", "a", "ab", "abc", "abcd", "aa", "aaa", "aab", "b", "bb",
            "c", "ac", "abb", "xabc", "bcd", "acd", "abaab", "ababc",
            "cc", "aaab",
        ]
        for source in patterns:
            tree, groups = Parser(source).parse()
            pat = compile(source)
            for text in texts:
                try:
                    expected = oracle_search(tree, groups, text)
                except RuntimeError:
                    continue
                actual = pat.match(text)
                if expected is None:
                    self.assertIsNone(actual, f"{source!r} {text!r}")
                    continue
                estart, eend, espans = expected
                self.assertIsNotNone(actual, f"{source!r} {text!r}")
                self.assertEqual(
                    actual.span(), (estart, eend), f"{source!r} {text!r}"
                )
                self.assertEqual(
                    actual.groupspans(),
                    tuple(espans),
                    f"{source!r} on {text!r}",
                )


if __name__ == "__main__":
    unittest.main()
