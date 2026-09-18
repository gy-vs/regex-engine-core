import unittest

from posixre import match


def groups_of(pattern, text):
    m = match(pattern, text)
    return None if m is None else [m.span(g) for g in range(1, m._spans.__len__() + 1)]


class POSIXLongestTests(unittest.TestCase):
    def test_required_example(self):
        # (a|ab)(c|bcd)(d*) against "abcd":
        # Python/Perl (leftmost-first) give ('a', 'bc'? ...) -- actually
        # groups a / bcd / ""  or a / c / d depending on path; POSIX
        # longest requires groups ab / c / d with whole match "abcd".
        m = match(r"(a|ab)(c|bcd)(d*)", "abcd")
        self.assertIsNotNone(m)
        self.assertEqual(m.span(), (0, 4))
        self.assertEqual(m.group(1), "ab")
        self.assertEqual(m.group(2), "c")
        self.assertEqual(m.group(3), "d")
        self.assertEqual(m.groups(), ("ab", "c", "d"))

    def test_alternation_prefers_long_over_order(self):
        # Alternation order must not decide; the longest alternative
        # that participates in the longest whole match wins.
        m = match(r"(abc|ab)", "abc")
        self.assertEqual(m.group(1), "abc")
        m = match(r"(ab|abc)", "abc")
        self.assertEqual(m.group(1), "abc")

    def test_star_keeps_last_iteration_group(self):
        m = match(r"(a)(b)*", "abbb")
        self.assertEqual(m.span(), (0, 4))
        self.assertEqual(m.span(1), (0, 1))
        # The repeated group retains its LAST iteration's positions.
        self.assertEqual(m.span(2), (3, 4))

    def test_nested_group_retains_last_outer_iteration(self):
        # 'aba' = iteration 'ab' then iteration 'a'.  Group1 keeps the
        # last iteration ('a'); group2 was captured in the earlier
        # iteration at (1,2) and is not reset by an iteration that
        # simply does not exercise its optional body -- the tags hold
        # the most recently recorded positions.
        m = match(r"(a(b)?)+", "aba")
        self.assertEqual(m.span(1), (2, 3))
        self.assertEqual(m.span(2), (1, 2))
        # Compare with 'ab': single iteration, inner group captured.
        m = match(r"(a(b)?)+", "ab")
        self.assertEqual(m.span(1), (0, 2))
        self.assertEqual(m.span(2), (1, 2))
        # And 'aa': second iteration never enters b, so group2 does not
        # participate at all.
        m = match(r"(a(b)?)+", "aa")
        self.assertEqual(m.span(1), (1, 2))
        self.assertIsNone(m.group(2))

    def test_optional_unmatched_group_is_none(self):
        m = match(r"a(b)?c", "ac")
        self.assertEqual(m.group(1), None)
        self.assertIsNone(m.span(1))

    def test_empty_participating_group_is_empty_span(self):
        m = match(r"(a*)b", "b")
        self.assertEqual(m.span(1), (0, 0))
        self.assertEqual(m.group(1), "")

    def test_leftmost_start_then_longest_end(self):
        m = match(r"a+", "baaa")
        self.assertEqual(m.span(), (1, 4))
        m = match(r"aa|aaa", "baaa")
        self.assertEqual(m.span(), (1, 4))

    def test_outer_group_wins_over_inner(self):
        # The trailing (d*) lets both g2 choices reach the same overall
        # length 4; then outer-group order (g2 before g3 before g4)
        # makes g2=ab win.
        m = match(r"((a|ab)(c|bcd)(d*))", "abcd")
        self.assertEqual(m.group(1), "abcd")
        self.assertEqual(m.group(2), "ab")
        self.assertEqual(m.group(3), "c")
        self.assertEqual(m.group(4), "d")

    def test_overall_longest_beats_left_group_length(self):
        # Without (d*), g2=ab can only finish at length 3 while g2=a
        # reaches length 4; POSIX keeps the overall longest match.
        m = match(r"((a|ab)(c|bcd))", "abcd")
        self.assertEqual(m.group(1), "abcd")
        self.assertEqual(m.group(2), "a")
        self.assertEqual(m.group(3), "bcd")

    def test_counted_quantifier_capture(self):
        m = match(r"(ab){2}", "xababx")
        self.assertEqual(m.span(1), (3, 5))
        m = match(r"(x|ab){2,3}", "xabab")
        self.assertEqual(m.span(1), (3, 5))

    def test_longest_match_across_pipes(self):
        m = match(r"a(ab|b)c|aabc", "aabc")
        self.assertEqual(m.span(), (0, 4))

    def test_zero_iteration_vs_more(self):
        m = match(r"(a*)", "bbb")
        self.assertEqual(m.span(), (0, 0))
        self.assertEqual(m.span(1), (0, 0))

    def test_group_inside_alternation_other_branch(self):
        m = match(r"(x)|(y)", "y")
        self.assertIsNone(m.group(1))
        self.assertEqual(m.group(2), "y")


if __name__ == "__main__":
    unittest.main()
