import unittest

from posixre import compile, match


def found(pattern, text, anchored=False):
    m = compile(pattern).match(text, anchored=anchored)
    return None if m is None else (m.start(), m.end())


class LiteralTests(unittest.TestCase):
    def test_plain_literal(self):
        self.assertEqual(found("abc", "xabcx"), (1, 4))
        self.assertIsNone(match("abc", "axc"))

    def test_unicode(self):
        self.assertEqual(found("é", "café"), (3, 4))

    def test_empty_pattern_matches_everywhere(self):
        self.assertEqual(found("", "abc"), (0, 0))

    def test_dot(self):
        self.assertEqual(found("a.c", "xabcx"), (1, 4))
        self.assertIsNone(match("a.c", "ac"))

    def test_dot_does_not_match_past_end(self):
        self.assertIsNone(match("a.", "a"))


class ClassTests(unittest.TestCase):
    def test_basic_class(self):
        self.assertEqual(found("[abc]+", "xabc"), (1, 4))

    def test_range(self):
        self.assertEqual(found("[0-9]+", "ab123z"), (2, 5))

    def test_negated_class(self):
        self.assertEqual(found("[^0-9]+", "ab12"), (0, 2))

    def test_class_with_shorthands(self):
        self.assertEqual(found(r"[\w]+", "a_b-9"), (0, 3))
        self.assertEqual(found(r"[\d\s]+", "x1 2z"), (1, 4))

    def test_negated_shorthand_inside_class(self):
        self.assertEqual(found(r"[\D]+", "1ab2"), (1, 3))

    def test_class_metachars_literal(self):
        self.assertEqual(found("[.*+?()|]", "a|b"), (1, 2))

    def test_closing_bracket_as_first_char(self):
        self.assertEqual(found("[]a]", "]"), (0, 1))
        # [^]a]+ : negated set containing ']' and 'a'
        self.assertEqual(found("[^]a]+", "ba]"), (0, 1))

    def test_escaped_bracket(self):
        self.assertEqual(found(r"\[a\]", "[a]"), (0, 3))

    def test_hyphen_at_edges_is_literal(self):
        # Greedy '+' runs through the included '-' as well.
        self.assertEqual(found("[-a]+", "-a-"), (0, 3))
        self.assertEqual(found("[a-]+", "a-b"), (0, 2))

    def test_bad_range_rejected(self):
        from posixre.errors import error

        with self.assertRaises(error):
            compile("[z-a]")


class QuantifierTests(unittest.TestCase):
    def test_star(self):
        self.assertEqual(found("a*", "baaa"), (0, 0))
        self.assertEqual(found("ba*", "baaac"), (0, 4))

    def test_plus(self):
        self.assertEqual(found("a+", "baaa"), (1, 4))
        self.assertIsNone(match("a+", "bbb"))

    def test_question(self):
        self.assertEqual(found("ab?c", "ac"), (0, 2))
        self.assertEqual(found("ab?c", "abc"), (0, 3))

    def test_counts(self):
        self.assertEqual(found("a{3}", "baaa"), (1, 4))
        self.assertIsNone(match("a{3}", "baa"))
        self.assertEqual(found("a{2,}", "baaaa"), (1, 5))
        self.assertEqual(found("a{2,3}", "baaaa"), (1, 4))
        # a{0,1} against "ba": at position 0 the empty match is the
        # leftmost; longest does not apply since both are zero-length.
        self.assertEqual(found("a{0,1}", "ba"), (0, 0))
        self.assertEqual(found("ba{0,1}", "ba"), (0, 2))
        self.assertEqual(found("ba{0,1}", "b"), (0, 1))

    def test_count_with_adjacent_quantifier_syntax(self):
        from posixre.errors import error

        with self.assertRaises(error):
            compile("a{2}{3}")

    def test_bare_braces_are_literal(self):
        self.assertEqual(found("a{b}", "a{b}"), (0, 4))

    def test_nested_quantifier(self):
        # (a*)* must behave, not loop exponentially.
        self.assertEqual(found("(a*)*b", "aaab"), (0, 4))
        self.assertIsNone(match("(a*)*b", "aaa"))


class GroupTests(unittest.TestCase):
    def test_non_capturing_group(self):
        self.assertEqual(found("(?:ab)+c", "ababc"), (0, 5))
        p = compile("(?:ab)+c")
        self.assertEqual(p.groups, 0)

    def test_alternation_empty_branch(self):
        self.assertEqual(found("a|", "b"), (0, 0))
        self.assertEqual(found("(|a)b", "b"), (0, 1))

    def test_anchors(self):
        self.assertEqual(found("^abc", "abc"), (0, 3))
        self.assertIsNone(match("^abc", "xabc"))
        self.assertEqual(found("abc$", "xabc"), (1, 4))
        self.assertIsNone(match("abc$", "abcd"))
        self.assertEqual(found("^$", ""), (0, 0))
        self.assertIsNone(match("^$", "x"))

    def test_word_boundary(self):
        self.assertEqual(found(r"\bword\b", "a word!"), (2, 6))
        self.assertIsNone(match(r"\bword\b", "password"))
        # \B requires a non-boundary on both sides, i.e. the word is
        # embedded in word characters.
        self.assertIsNone(match(r"\Bword\B", "password"))
        m = compile(r"\Bword\B").match("passwords")
        self.assertIsNotNone(m)
        self.assertEqual((m.start(), m.end()), (4, 8))

    def test_escapes(self):
        self.assertEqual(found(r"\t", "a\tb"), (1, 2))
        self.assertEqual(found(r"\n", "\n"), (0, 1))
        self.assertEqual(found(r"\\", "\\"), (0, 1))
        self.assertEqual(found(r"\.", "."), (0, 1))
        self.assertEqual(found(r"\x41", "A"), (0, 1))
        self.assertEqual(found(r"\d", "x9y"), (1, 2))
        self.assertEqual(found(r"\D", "9a"), (1, 2))
        self.assertEqual(found(r"\s", "a b"), (1, 2))
        self.assertEqual(found(r"\S", " a"), (1, 2))
        self.assertEqual(found(r"\w+", "a_b-"), (0, 3))


class AnchorQuantifierTests(unittest.TestCase):
    def test_quantifier_on_anchor_rejected(self):
        from posixre.errors import error

        with self.assertRaises(error):
            compile("^*")
        with self.assertRaises(error):
            compile("a$*")


if __name__ == "__main__":
    unittest.main()
