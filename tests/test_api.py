"""对外接口（compile / Pattern.match / Match / 窗口与锚点）测试。"""

import unittest

import posixre
from posixre import Pattern, Match, PatternError


class ApiTests(unittest.TestCase):
    def test_compile_returns_pattern(self):
        p = posixre.compile(r"(\d)(\d)")
        self.assertIsInstance(p, Pattern)
        self.assertEqual(p.groups, 2)
        self.assertEqual(p.pattern, r"(\d)(\d)")

    def test_compile_cache_same_object(self):
        self.assertIs(posixre.compile(r"abc"), posixre.compile(r"abc"))

    def test_module_level_match(self):
        m = posixre.match(r"b", "abc")
        self.assertIsInstance(m, Match)
        self.assertEqual(m.span(), (1, 2))

    def test_module_level_no_match(self):
        self.assertIsNone(posixre.match(r"z", "abc"))

    def test_match_is_method(self):
        p = posixre.compile(r"\d+")
        self.assertEqual(p.match("a12").span(), (1, 3))

    def test_group_accessors(self):
        m = posixre.match(r"(\w+)=(\d+)", "x=42")
        self.assertEqual(m.span(0), (0, 4))
        self.assertEqual(m.start(1), 0)
        self.assertEqual(m.end(1), 1)
        self.assertEqual(m.start(2), 2)
        self.assertEqual(m.end(2), 4)
        self.assertEqual(m[1], "x")
        self.assertEqual(m.groups(), ("x", "42"))
        self.assertEqual(m.string, "x=42")
        self.assertIs(m.re, posixre.compile(r"(\w+)=(\d+)"))

    def test_invalid_group_index(self):
        m = posixre.match(r"(a)", "a")
        with self.assertRaises(IndexError):
            m.span(2)
        with self.assertRaises(IndexError):
            m.span(-1)

    def test_pos_endpos_window(self):
        p = posixre.compile(r"\d+")
        m = p.match("xx123xx", pos=2, endpos=5)
        self.assertEqual(m.span(), (2, 5))
        self.assertEqual(m.group(), "123")

    def test_empty_window(self):
        p = posixre.compile(r"")
        self.assertEqual(p.match("abc", pos=2, endpos=2).span(), (2, 2))

    def test_window_bounds_validation(self):
        p = posixre.compile(r"a")
        with self.assertRaises(ValueError):
            p.match("abc", pos=2, endpos=1)
        with self.assertRaises(ValueError):
            p.match("abc", pos=4)
        with self.assertRaises(ValueError):
            p.match("abc", pos=-1)

    def test_caret_relative_to_whole_text(self):
        p = posixre.compile(r"^\d+")
        self.assertIsNone(p.match("a123", pos=1))
        self.assertEqual(p.match("123x", endpos=3).span(), (0, 3))

    def test_dollar_relative_to_endpos(self):
        p = posixre.compile(r"\d+$")
        self.assertEqual(p.match("12x", endpos=2).span(), (0, 2))
        self.assertIsNone(p.match("12x3", endpos=3))

    def test_non_str_inputs(self):
        with self.assertRaises(TypeError):
            posixre.compile(123)
        p = posixre.compile(r"a")
        with self.assertRaises(TypeError):
            p.match(b"abc")

    def test_repr_does_not_crash(self):
        self.assertIn("Pattern", repr(posixre.compile(r"a")))
        self.assertIn("Match", repr(posixre.match(r"a", "a")))

    def test_finditer_is_generator(self):
        p = posixre.compile(r"a")
        it = p.finditer("aaa")
        self.assertEqual(next(it).span(), (0, 1))


if __name__ == "__main__":
    unittest.main()
