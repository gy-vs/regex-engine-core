"""POSIX 最左最长捕获语义测试。

参照 Russ Cox “Regular Expression Matching Can Be Simple And Fast” 一文中
的经典对照：Python/Perl 的最左优先在 (a|ab)(c|bcd)(d*) 配 abcd 时给出
a/c/d，而 POSIX 必须给出 ab/c/d（整串一样长时，靠左的组尽量长）。
"""

import unittest

import posixre


class PosixCaptureTests(unittest.TestCase):
    def test_cox_example(self):
        m = posixre.match(r"(a|ab)(c|bcd)(d*)", "abcd")
        self.assertEqual(m.span(0), (0, 4))
        self.assertEqual(m.span(1), (0, 2))  # ab，不是 a
        self.assertEqual(m.span(2), (2, 3))  # c
        self.assertEqual(m.span(3), (3, 4))  # d
        self.assertEqual(m.groups(), ("ab", "c", "d"))

    def test_overall_longest_dominates(self):
        # 无论选择怎么排，整体最长必须胜出。
        for p in (r"(a|ab)(c|bcd)(d*)", r"(ab|a)(bcd|c)(d*)"):
            m = posixre.match(p, "abcd")
            self.assertEqual(m.groups(), ("ab", "c", "d"))

    def test_longest_overall_match(self):
        # 第一个分支能配 2 个字符，但第二个分支能配 4 个。
        m = posixre.match(r"(ab|abcd)", "abcd")
        self.assertEqual(m.span(1), (0, 4))

    def test_leftmost_start(self):
        # 后面有更长的匹配也必须选起点最左的。
        m = posixre.match(r"a+", "x a aaa")
        self.assertEqual(m.span(), (2, 3))

    def test_leftmost_empty_match(self):
        m = posixre.match(r"a*", "bbb")
        self.assertEqual(m.span(), (0, 0))

    def test_left_group_longer_on_tie(self):
        # 两种切法整体等长：a/bc 与 ab/c，靠左组要长 -> ab/c。
        m = posixre.match(r"(a|ab)(c|bc)", "abc")
        self.assertEqual(m.groups(), ("ab", "c"))

    def test_right_group_grows_when_left_fixed(self):
        # 第一组两种选择等长时，第二组尽量长。
        m = posixre.match(r"(x|x)(ab|b)", "xab")
        self.assertEqual(m.groups(), ("x", "ab"))

    def test_nested_groups(self):
        m = posixre.match(r"(((a|ab)(c|bcd))d)", "abcd")
        # 外层整串定死为 abcd，内层 ((a|ab)(c|bcd)) 必须让出最后一个 d，
        # 在 "abc" 内做最长切分 -> ab / c。
        self.assertEqual(m.span(1), (0, 4))  # abcd
        self.assertEqual(m.span(2), (0, 3))  # abc
        self.assertEqual(m.span(3), (0, 2))  # ab
        self.assertEqual(m.span(4), (2, 3))  # c

    def test_noncapturing_does_not_number(self):
        p = posixre.compile(r"(a)(?:b|bc)(c)")
        self.assertEqual(p.groups, 2)
        m = p.match("abc")
        self.assertEqual(m.groups(), ("a", "c"))

    def test_optional_group_unmatched(self):
        m = posixre.match(r"(a)(b)?(c)", "ac")
        self.assertEqual(m.span(1), (0, 1))
        self.assertIsNone(m.span(2))
        self.assertIsNone(m.group(2))
        self.assertEqual(m.span(3), (1, 2))
        self.assertEqual(m.groups(), ("a", None, "c"))

    def test_empty_participation_beats_nonparticipation(self):
        # (b*) 参与（空串）优先于整串少一组参与的切法：
        # 本模式两种走法整体都是 "a"，参与组更多的切法应当胜出。
        m = posixre.match(r"(a)(b*)?c?", "a")
        self.assertEqual(m.span(1), (0, 1))
        self.assertEqual(m.span(2), (1, 1))  # 参与了，空匹配

    def test_star_capture_holds_last_iteration(self):
        m = posixre.match(r"(ab)*", "ababab")
        self.assertEqual(m.span(0), (0, 6))
        self.assertEqual(m.span(1), (4, 6))  # 最后一次参与

    def test_plus_capture_nested(self):
        m = posixre.match(r"(a+)+b", "aaab")
        self.assertEqual(m.span(0), (0, 4))
        self.assertEqual(m.span(1), (0, 3))

    def test_greedy_classic_split(self):
        # 经典回溯题：.* 最长，剩下的组取最短可行。
        m = posixre.match(r"(.*)(c)", "abcabc")
        self.assertEqual(m.span(1), (0, 5))
        self.assertEqual(m.span(2), (5, 6))

    def test_group_in_alternative_repeats(self):
        m = posixre.match(r"(ab|a)*", "abaab")
        self.assertEqual(m.span(0), (0, 5))
        self.assertEqual(m.span(1), (3, 5))  # 最后一轮 'ab'

    def test_anchored_posix(self):
        m = posixre.match(r"^(a|ab).*d$", "abcd")
        self.assertEqual(m.span(1), (0, 2))

    def test_posix_classic_word_pairs(self):
        m = posixre.match(r"(.*)( .*)", "one two three")
        # 第一组最长，第二组只剩最后一个带空格的词。
        self.assertEqual(m.group(1), "one two")
        self.assertEqual(m.group(2), " three")

    def test_repeated_group_match_value(self):
        m = posixre.match(r"(\d)+", "123")
        self.assertEqual(m.span(1), (2, 3))
        self.assertEqual(m.group(1), "3")


if __name__ == "__main__":
    unittest.main()
