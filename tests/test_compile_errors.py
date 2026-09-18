import unittest

from posixre import compile
from posixre.errors import error


def expect_error_pos(pattern):
    try:
        compile(pattern)
    except error as exc:
        return exc.pos
    raise AssertionError(f"pattern {pattern!r} should have failed to compile")


class CompileErrorTests(unittest.TestCase):
    def test_backreference_digit(self):
        # \1 at characters 2..
        pos = expect_error_pos(r"(a)\1")
        self.assertEqual(pos, 3)  # 0-based; message reports character 4

    def test_backreference_early(self):
        pos = expect_error_pos(r"\2")
        self.assertEqual(pos, 0)

    def test_named_backreference(self):
        # (?P<... and (?<... syntax is rejected at the '?' (0-based).
        self.assertEqual(expect_error_pos(r"(?P<x>a)y"), 1)
        self.assertEqual(expect_error_pos(r"(?<x>a)"), 1)

    def test_lookahead(self):
        # Error points at the '?' marker of the unsupported group.
        self.assertEqual(expect_error_pos(r"a(?=b)"), 2)
        self.assertEqual(expect_error_pos(r"a(?!b)"), 2)

    def test_lookbehind(self):
        self.assertEqual(expect_error_pos(r"(?<=a)b"), 1)
        self.assertEqual(expect_error_pos(r"(?<!a)b"), 1)

    def test_error_message_uses_1_based_position(self):
        try:
            compile(r"x\1")
        except error as exc:
            self.assertEqual(exc.pos, 1)
            self.assertIn("character 2", str(exc))
        else:
            self.fail("expected compile error")

    def test_unbalanced_paren(self):
        with self.assertRaises(error):
            compile("(a")
        with self.assertRaises(error):
            compile("a)")

    def test_unterminated_class(self):
        with self.assertRaises(error):
            compile("[abc")

    def test_dangling_backslash(self):
        with self.assertRaises(error):
            compile("abc\\")

    def test_nothing_to_repeat(self):
        with self.assertRaises(error):
            compile("*")
        with self.assertRaises(error):
            compile("a**")

    def test_reversed_count(self):
        with self.assertRaises(error):
            compile("a{5,2}")

    def test_lazy_quantifier_rejected(self):
        with self.assertRaises(error):
            compile("a*?")

    def test_octal_backreference_rejected(self):
        # Outside a class, \1 ... \9 are backreferences and rejected.
        with self.assertRaises(error):
            compile(r"(a)\1")
        with self.assertRaises(error):
            compile(r"\1")

    def test_huge_count_rejected(self):
        with self.assertRaises(error):
            compile("a{100000}")

    def test_digit_backreference_inside_class_is_literal_escape(self):
        # Inside a class there are no backreferences: \1 is literal.
        p = compile(r"[\1]")
        self.assertIsNotNone(p.match("\x01"))


if __name__ == "__main__":
    unittest.main()
