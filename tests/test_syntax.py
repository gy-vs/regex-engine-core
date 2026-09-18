"""语法子集的功能测试（不使用 re，预期结果按 POSIX 语义手工给出）。"""

import unittest

import posixre
from posixre import PatternError


def spans(pattern, text):
    m = posixre.match(pattern, text)
    if m is None:
        return None
    return [m.span(g) for g in range(0, m.re.groups + 1)]


class LiteralsAndConcatTests(unittest.TestCase):
    def test_plain_literal(self):
        self.assertEqual(spans("abc", "xabcy"), [(1, 4)])

    def test_literal_no_match(self):
        self.assertIsNone(posixre.match("abc", "abx"))

    def test_escaped_metachars(self):
        self.assertEqual(posixre.match(r"a\.b", "x a.b y").span(), (2, 5))
        target = "()[]{}|*+?$^\\"
        self.assertEqual(posixre.match(r"\(\)\[\]\{\}\|\*\+\?\$\^\\",
                                       target).span(), (0, len(target)))

    def test_dot_matches_newline(self):
        self.assertEqual(posixre.match("a.b", "a\nb").span(), (0, 3))

    def test_dot_is_one_char(self):
        self.assertIsNone(posixre.match("a.b", "ab"))

    def test_empty_pattern(self):
        m = posixre.match("", "abc")
        self.assertEqual(m.span(), (0, 0))

    def test_leftmost_position(self):
        self.assertEqual(posixre.match("ab", "ab ab").span(), (0, 2))
        self.assertEqual(posixre.match("ab", "x ab").span(), (2, 4))

    def test_unicode(self):
        m = posixre.match("汉字", "说汉字吧")
        self.assertEqual(m.span(), (1, 3))


class CharacterClassTests(unittest.TestCase):
    def test_basic_class(self):
        self.assertEqual(posixre.match("[abc]+", "xbabay").span(), (1, 5))

    def test_range(self):
        m = posixre.match("[0-9]+", "ab1234c")
        self.assertEqual(m.span(), (2, 6))

    def test_negated(self):
        self.assertEqual(posixre.match("[^0-9]+", "ab1234c").span(), (0, 2))

    def test_negated_consumes_newline(self):
        self.assertEqual(posixre.match("[^a]+", "x\nz").span(), (0, 3))

    def test_close_bracket_first_is_literal(self):
        self.assertEqual(posixre.match("[]]+", "]x").span(), (0, 1))
        self.assertEqual(posixre.match("[]a]", "a").span(), (0, 1))

    def test_negate_then_close_bracket(self):
        self.assertEqual(posixre.match("[^]]+", "abc]").span(), (0, 3))

    def test_dash_literal_at_edges(self):
        self.assertEqual(posixre.match("[-a]+", "a-a").span(), (0, 3))
        self.assertEqual(posixre.match("[a-]+", "a-a").span(), (0, 3))
        self.assertEqual(posixre.match("[-]+", "-").span(), (0, 1))

    def test_caret_literal_inside(self):
        self.assertEqual(posixre.match("[a^]+", "^").span(), (0, 1))

    def test_shorthands_in_class(self):
        self.assertEqual(posixre.match(r"[\d.]+", "v1.2.3x").span(), (1, 6))
        self.assertEqual(posixre.match(r"[\w]+", "a_b-9").span(), (0, 3))
        self.assertEqual(posixre.match(r"a[\s]b", "a b").span(), (0, 3))
        self.assertEqual(posixre.match(r"a[\s]b", "a\nb").span(), (0, 3))

    def test_negated_shorthand_in_class(self):
        self.assertEqual(posixre.match(r"[\D]+", "ab1").span(), (0, 2))
        # 类体是并集：\D 与 \d 合起来覆盖全部字符，取反后为空。
        self.assertIsNone(posixre.match(r"[^\D\d]", "x"))
        self.assertIsNone(posixre.match(r"[^\D\d]", "1"))
        # [^\W_] 等价于字母数字：\W 补集再与 _ 取并，整体取反。
        self.assertIsNone(posixre.match(r"[^\W_]", "_"))
        self.assertEqual(posixre.match(r"[^\W_]+", "ab9_").span(), (0, 3))
        self.assertEqual(posixre.match(r"[\w\s]+", "a b\t").span(), (0, 4))
        # \S 是空白的补集。
        self.assertEqual(posixre.match(r"[\S]+", " a ").span(), (1, 2))

    def test_shorthand_outside_class(self):
        self.assertEqual(posixre.match(r"\d+", "ab99x").span(), (2, 4))
        self.assertEqual(posixre.match(r"\s", "a b").span(), (1, 2))
        self.assertEqual(posixre.match(r"\W", "a!b").span(), (1, 2))
        self.assertEqual(posixre.match(r"\S+", " a ").span(), (1, 2))

    def test_backspace_in_class(self):
        self.assertEqual(posixre.match(r"[\b]", "\b").span(), (0, 1))

    def test_hex_escapes(self):
        self.assertEqual(posixre.match(r"\x41", "A").span(), (0, 1))
        self.assertEqual(posixre.match(r"é", "é").span(), (0, 1))

    def test_class_range_order_error(self):
        with self.assertRaises(PatternError) as cm:
            posixre.compile("[z-a]")
        self.assertEqual(cm.exception.pos, 0)


class QuantifierTests(unittest.TestCase):
    def test_star(self):
        self.assertEqual(posixre.match("a*", "aaab").span(), (0, 3))
        self.assertEqual(posixre.match("a*", "bbb").span(), (0, 0))

    def test_plus(self):
        self.assertEqual(posixre.match("a+", "aaab").span(), (0, 3))
        self.assertIsNone(posixre.match("a+", "bbb"))

    def test_question(self):
        self.assertEqual(posixre.match("ab?c", "ac").span(), (0, 2))
        self.assertEqual(posixre.match("ab?c", "abc").span(), (0, 3))
        self.assertIsNone(posixre.match("ab?c", "abbc"))

    def test_exact_count(self):
        self.assertEqual(posixre.match("a{3}", "aaaa").span(), (0, 3))
        self.assertIsNone(posixre.match("a{3}", "aa"))

    def test_range_count(self):
        self.assertEqual(posixre.match("a{2,4}", "aaaaa").span(), (0, 4))
        self.assertEqual(posixre.match("a{2,4}", "aaa").span(), (0, 3))
        self.assertIsNone(posixre.match("a{2,4}", "a"))

    def test_open_ended_count(self):
        self.assertEqual(posixre.match("a{2,}", "aaaaa").span(), (0, 5))

    def test_literal_brace_when_not_quantifier(self):
        self.assertEqual(posixre.match("a{b", "a{b").span(), (0, 3))
        self.assertEqual(posixre.match("{}", "{}").span(), (0, 2))
        self.assertEqual(posixre.match("a{x}", "a{x}").span(), (0, 4))

    def test_greedy_then_backtrack_free_longest(self):
        # .* 必须吃掉到最后一个 " 之前不能回退多个位置——这里验证最长：
        self.assertEqual(posixre.match('".*"', '"a"b"').span(), (0, 5))

    def test_nested_quantifiers(self):
        self.assertEqual(posixre.match("(a*)*", "aaa").span(), (0, 3))
        self.assertEqual(posixre.match("(a?)*", "aaa").span(), (0, 3))
        self.assertEqual(posixre.match("(a+)+", "aaa").span(), (0, 3))


class AnchorTests(unittest.TestCase):
    def test_start_anchor(self):
        self.assertEqual(posixre.match("^abc", "abc").span(), (0, 3))
        self.assertIsNone(posixre.match("^abc", "xabc"))

    def test_end_anchor(self):
        self.assertEqual(posixre.match("abc$", "abc").span(), (0, 3))
        self.assertIsNone(posixre.match("abc$", "abcd"))

    def test_both_anchors(self):
        self.assertEqual(posixre.match("^abc$", "abc").span(), (0, 3))
        self.assertIsNone(posixre.match("^abc$", "xabc"))
        self.assertIsNone(posixre.match("^abc$", "abcd"))

    def test_anchor_not_line_oriented(self):
        self.assertIsNone(posixre.match("^b", "a\nb"))
        self.assertIsNone(posixre.match("a$", "a\nb"))

    def test_empty_anchored(self):
        self.assertEqual(posixre.match("^$", "").span(), (0, 0))
        self.assertIsNone(posixre.match("^$", "a"))


if __name__ == "__main__":
    unittest.main()
