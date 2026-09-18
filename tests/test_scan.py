"""finditer 全局扫描与空匹配推进规则测试。"""

import unittest

import posixre


def scan(pattern, text):
    return [(m.span(), m.group()) for m in posixre.finditer(pattern, text)]


class FinditerTests(unittest.TestCase):
    def test_nonoverlapping(self):
        self.assertEqual(
            [(s, e) for (s, e), _ in scan(r"\d+", "a12b34c56")],
            [(1, 3), (4, 6), (7, 9)])

    def test_alternatives_longest_each_position(self):
        # 每个起点仍然遵守最左最长，且匹配之间不重叠。
        self.assertEqual(
            [g for _, g in scan(r"ab|a", "aabab")],
            ["a", "ab", "ab"])

    def test_empty_match_advances_one_char(self):
        # 核心规则：空匹配后强制跨过一个字符，同位置不重复产出空串。
        self.assertEqual([s for (s, e), _ in scan(r"a*", "aba")],
                         [0, 1, 2, 3])
        # (1,1) 之后跨过 'b'，再在 2 配到 "a"，最后 3 是末尾空匹配。
        self.assertEqual(scan(r"a*", "aba"),
                         [((0, 1), "a"), ((1, 1), ""),
                          ((2, 3), "a"), ((3, 3), "")])

    def test_all_empty_pattern(self):
        # 空模式：每个位置一个空匹配，位置严格递增，没有重复。
        spans = [s for (s, e), _ in scan("", "abc")]
        self.assertEqual(spans, [0, 1, 2, 3])

    def test_optional_everywhere(self):
        self.assertEqual([s for (s, e), _ in scan(r"x?", "abc")],
                         [0, 1, 2, 3])

    def test_empty_after_nonempty(self):
        # 非空匹配后若下一轮只能配空，空匹配允许出现（位置不同即可）。
        self.assertEqual(scan(r"a|", "ba"),
                         [((0, 0), ""), ((1, 2), "a"), ((2, 2), "")])

    def test_no_match(self):
        self.assertEqual(scan(r"z+", "abc"), [])

    def test_match_then_no_more(self):
        self.assertEqual([g for _, g in scan(r"ab", "abxab")],
                         ["ab", "ab"])

    def test_scan_is_iterator(self):
        it = posixre.finditer("a", "aaa")
        self.assertEqual(next(it).span(), (0, 1))
        self.assertEqual(next(it).span(), (1, 2))
        self.assertEqual(next(it).span(), (2, 3))
        with self.assertRaises(StopIteration):
            next(it)

    def test_groups_in_scan(self):
        result = [(m.group(1), m.group(2))
                  for m in posixre.finditer(r"(\w+)=(\d+)", "a=1 b=22")]
        self.assertEqual(result, [("a", "1"), ("b", "22")])

    def test_empty_text(self):
        self.assertEqual(scan(r"a*", ""), [((0, 0), "")])
        self.assertEqual(scan(r"a+", ""), [])

    def test_empty_match_consumes_separator_character(self):
        # 空匹配跨过的字符不属于任何匹配："." 永远不会被产出。
        ms = scan(r"", ".")
        self.assertEqual(ms, [((0, 0), ""), ((1, 1), "")])


if __name__ == "__main__":
    unittest.main()
