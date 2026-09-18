import unittest

from posixre import compile, scan


def spans(pattern, text):
    return [m.span() for m in compile(pattern).scan(text)]


class ScanTests(unittest.TestCase):
    def test_non_overlapping(self):
        self.assertEqual(spans(r"a+", "banana"), [(1, 2), (3, 4), (5, 6)])
        self.assertEqual(spans(r"\w+", "ab cd ef"), [(0, 2), (3, 5), (6, 8)])

    def test_no_match(self):
        self.assertEqual(spans(r"z+", "abc"), [])

    def test_empty_pattern_progresses(self):
        # Empty pattern matches between every pair and at both ends.
        self.assertEqual(spans("", "abc"), [(0, 0), (1, 1), (2, 2), (3, 3)])

    def test_empty_matches_interleaved(self):
        # After the non-empty match (1,2), the empty match that would
        # sit at its end position 2 is suppressed; search resumes at 3
        # and the empty match at the end of text is the last result.
        self.assertEqual(spans(r"a*", "bab"), [(0, 0), (1, 2), (3, 3)])

    def test_empty_then_real_match(self):
        # Empty at 0 advances to 1; the real match 'bc' at 1 is found;
        # the empty match at its end (3) is suppressed.
        p = compile("|bc")
        self.assertEqual([m.span() for m in p.scan("abc")], [(0, 0), (1, 3)])

    def test_empty_match_at_end_is_yielded_once(self):
        # a* at 0 is non-empty (0-2); the empty match at 2 would share
        # position 2 with that end, so it is suppressed and the scan
        # stops.  (Contrast x* where the match at 0 is itself empty.)
        self.assertEqual(spans(r"a*", "aa"), [(0, 2)])

    def test_nonempty_reaching_end_stops_scan(self):
        # Empty at 0 (advance), non-empty at 1 reaching the end: the
        # trailing empty at that same end position is suppressed.
        self.assertEqual(spans(r"a*", "baa"), [(0, 0), (1, 3)])

    def test_consecutive_empty_advances_one_each_time(self):
        # An empty-only pattern: every empty match moves the cursor one
        # character, with one final empty match at the end.
        self.assertEqual(spans(r"x*", "ab"), [(0, 0), (1, 1), (2, 2)])

    def test_scan_groups_consistent(self):
        results = list(scan(r"(a)(b)?", "aab"))
        # (a) at 0-1 with no b; (a) at 1-2 with group2 b at 2-3.
        self.assertEqual(results[0].groups(), ("a", None))
        self.assertEqual(results[1].groups(), ("a", "b"))

    def test_posix_longest_in_scan(self):
        # At 0 the longest alternative wins (3 chars), not the first
        # listed 2-char one.
        self.assertEqual(spans(r"aa|aaa", "aaaaa"), [(0, 3), (3, 5)])

    def test_unicode_text(self):
        self.assertEqual(spans(r"\w+", "caf na"), [(0, 3), (4, 6)])
        self.assertEqual(spans(r"\w+", "café naïve"), [(0, 4), (5, 10)])


if __name__ == "__main__":
    unittest.main()
