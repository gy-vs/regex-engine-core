import time
import unittest

from posixre import compile


class PerformanceTests(unittest.TestCase):
    """The whole point of replacing the old engine: matching time must
    stay linear in the text length instead of exploding when nested
    quantifiers admit exponentially many parse paths."""

    PATTERN = r"(a|aa)*b"

    def _measure(self, length):
        text = "a" * length
        p = compile(self.PATTERN)
        # Warm up so import/jit-ish noise does not skew the first point.
        p.match(text)
        t0 = time.perf_counter()
        m = p.match(text)
        elapsed = time.perf_counter() - t0
        self.assertIsNone(m, "no 'b' => no match")
        return elapsed

    def test_catastrophic_pattern_milliseconds_linear(self):
        lengths = [20, 40, 60, 80]
        times = []
        for length in lengths:
            elapsed = self._measure(length)
            times.append(elapsed)
            self.assertLess(
                elapsed,
                2.0,
                f"{self.PATTERN} on {length} chars took {elapsed:.3f}s",
            )
        # Visibly linear (or near linear): the longest input must not
        # cost anywhere near an exponential factor of the shortest.
        slope = (times[-1] - times[0]) / (lengths[-1] - lengths[0])
        self.assertGreaterEqual(slope, 0.0)
        ratio = times[-1] / max(times[0], 1e-9)
        # Doubling 20->80; exponential blow-up is a factor in the
        # thousands.  A well-bounded linear implementation stays under
        # an order of magnitude even with interpreter noise.
        self.assertLess(
            ratio,
            25.0,
            f"timings {times} do not look linear (ratio {ratio:.1f})",
        )

    def test_other_nested_quantifier_patterns(self):
        cases = [
            (r"(a*)*", "a" * 100),
            (r"(a+)+b", "a" * 100),
            (r"(a|a)*b", "a" * 100),
            (r"(a?){0,100}b", "a" * 100),
            (r"((a|aa)*b)*c", "a" * 80),
        ]
        for pat, text in cases:
            with self.subTest(pattern=pat):
                t0 = time.perf_counter()
                compile(pat).match(text)
                self.assertLess(time.perf_counter() - t0, 2.0)

    def test_match_and_captures_both_fast(self):
        # Extraction of group positions must stay inside the same bound.
        p = compile(r"(a|aa)*b")
        text = "aa" * 40 + "b"
        t0 = time.perf_counter()
        m = p.match(text)
        self.assertLess(time.perf_counter() - t0, 2.0)
        self.assertIsNotNone(m)
        # Last iteration consumes the final 'aa'.
        self.assertEqual(m.span(1), (len(text) - 3, len(text) - 1))


if __name__ == "__main__":
    unittest.main()
