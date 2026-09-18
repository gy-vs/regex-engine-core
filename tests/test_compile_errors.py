"""编译期拒绝反向引用与环视的测试，错误位置必须精确到字符下标。"""

import unittest

import posixre
from posixre import PatternError


class CompileErrorTests(unittest.TestCase):
    def assert_bad(self, pattern, expected_pos):
        with self.assertRaises(PatternError) as cm:
            posixre.compile(pattern)
        self.assertEqual(cm.exception.pos, expected_pos,
                         "模式 %r 报错位置应为 %d，实际 %d"
                         % (pattern, expected_pos, cm.exception.pos))

    def test_backreference_digit(self):
        self.assert_bad(r"a\1", 1)
        self.assert_bad(r"(x)\1", 3)

    def test_named_backreference(self):
        self.assert_bad(r"(?P=n)", 0)
        self.assert_bad(r"(?<n>a)", 0)  # 尖括号命名也不支持

    def test_lookahead(self):
        self.assert_bad(r"a(?=b)", 1)
        self.assert_bad(r"a(?!b)", 1)

    def test_lookbehind(self):
        self.assert_bad(r"(?<=a)b", 0)
        self.assert_bad(r"(?<!a)b", 0)

    def test_unclosed_paren(self):
        self.assert_bad(r"(abc", 0)
        # 多个未闭合时指出最外层（最先打开）的那个。
        self.assert_bad(r"a(b(c)", 1)

    def test_unmatched_close_paren(self):
        self.assert_bad(r"abc)", 3)

    def test_unclosed_class(self):
        self.assert_bad(r"[ab", 0)

    def test_dangling_backslash(self):
        self.assert_bad("\\", 0)

    def test_bad_repeat_bounds(self):
        self.assert_bad(r"a{2,1}", 1)

    def test_leading_quantifier(self):
        self.assert_bad(r"*abc", 0)
        self.assert_bad(r"+a", 0)
        self.assert_bad(r"?a", 0)

    def test_double_quantifier(self):
        self.assert_bad(r"a**", 2)
        self.assert_bad(r"a?*", 2)

    def test_lazy_and_possessive_rejected(self):
        with self.assertRaises(PatternError) as cm:
            posixre.compile(r"a+?")
        self.assertEqual(cm.exception.pos, 2)
        with self.assertRaises(PatternError) as cm:
            posixre.compile(r"a*+")
        self.assertEqual(cm.exception.pos, 2)

    def test_quantifier_on_anchor(self):
        self.assert_bad(r"^*", 1)
        self.assert_bad(r"a$+", 2)

    def test_word_boundary_rejected_outside_class(self):
        self.assert_bad(r"\b", 0)
        self.assert_bad(r"a\Bb", 1)

    def test_named_group_rejected(self):
        self.assert_bad(r"(?P<n>a)", 0)

    def test_comment_and_atomic_rejected(self):
        self.assert_bad(r"(?#x)", 0)
        self.assert_bad(r"(?>a)", 0)

    def test_backreference_inside_class_rejected(self):
        self.assert_bad(r"[\1]", 1)

    def test_error_is_valueerror_compatible(self):
        # 便于调用方按 ValueError 兜底。
        self.assertTrue(issubclass(PatternError, ValueError))

    def test_legal_things_compile(self):
        for p in (r"a{3}", r"a{b", r"{}", r"\d\D\w\W\s\S", r"[\b]",
                  r"\x41", r"(?:a|b)?", r"[A-Za-z0-9_]+",
                  r"a{0,4096}", r"[\d.]+", r"[\^\]]", r"\{\}"):
            posixre.compile(p)  # 不抛异常即可


if __name__ == "__main__":
    unittest.main()
