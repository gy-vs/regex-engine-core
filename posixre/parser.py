"""模式解析器：把正则子集编译成 AST。

支持的语法见包文档。遇到反向引用、环视等不支持的写法时，
在解析阶段直接抛出 :class:`posixre.errors.PatternError`，错误位置为
模式中的 0 基字符下标（对中文等非 ASCII 字符按码点计数）。
"""

from .errors import PatternError

# 计数量词的上限，防止 a{999999999} 之类的模式耗尽内存。
MAX_REPEAT = 4096


# AST 节点 -----------------------------------------------------------------

class Char:
    __slots__ = ("cp", "quoted")

    def __init__(self, cp, quoted=False):
        self.cp = cp
        self.quoted = quoted  # 由反斜杠转义而来，后面的 '{' 不能当量词


class Dot:
    __slots__ = ()


class Anchor:
    __slots__ = ("kind",)  # '^' 或 '$'

    def __init__(self, kind):
        self.kind = kind


class Class:
    """字符类。

    ranges     正向码点闭区间（含 \\d\\w\\s 展开结果）
    comp_ranges 需要取补集参与的字母集合，元素取自 'dws'，
                 对应 \\D \\W \\S 这些“反向简写”
    negated    整个类是否被 [^ ...] 取反
    最终成员判定：先按 ranges ∪ (⋃ 反向简写的补集) 求成员，
    再按 negated 整体取反——两层否定互不混淆。
    """

    __slots__ = ("ranges", "comp_letters", "negated")

    def __init__(self, ranges, comp_letters, negated):
        self.ranges = ranges
        self.comp_letters = comp_letters
        self.negated = negated


class Group:
    __slots__ = ("index", "child")

    def __init__(self, index, child):
        self.index = index      # None 表示不捕获
        self.child = child


class Concat:
    __slots__ = ("items",)

    def __init__(self, items):
        self.items = items


class Alt:
    __slots__ = ("left", "right")

    def __init__(self, left, right):
        self.left = left
        self.right = right


class Repeat:
    __slots__ = ("child", "lo", "hi")  # hi 为 None 表示无穷

    def __init__(self, child, lo, hi):
        self.child = child
        self.lo = lo
        self.hi = hi


_EMPTY = Concat([])


# 字符类辅助 ---------------------------------------------------------------

_DIGIT = [(ord("0"), ord("9"))]
_WORD = [(ord("0"), ord("9")), (ord("A"), ord("Z")),
         (ord("a"), ord("z")), (ord("_"), ord("_"))]
_SPACE = [(0x09, 0x0D), (ord(" "), ord(" "))]  # \t\n\v\f\r 和空格


_SHORTHAND_RANGES = {"d": _DIGIT, "w": _WORD, "s": _SPACE}


class _Parser:
    def __init__(self, pattern):
        self.p = pattern
        self.n = len(pattern)
        self.i = 0
        self.groups = 0

    def error(self, msg, pos=None):
        raise PatternError(msg, self.i if pos is None else pos)

    def peek(self):
        return self.p[self.i] if self.i < self.n else ""

    def parse(self):
        node = self.parse_alt()
        if self.i != self.n:
            self.error("未闭合的圆括号 ')' 没有匹配的 '('")
        return node, self.groups

    # 递归下降 -------------------------------------------------------------

    def parse_alt(self):
        left = self.parse_concat()
        while self.peek() == "|":
            self.i += 1
            right = self.parse_concat()
            left = Alt(left, right)
        return left

    def parse_concat(self):
        items = []
        while True:
            c = self.peek()
            if c == "" or c == "|" or c == ")":
                break
            items.append(self.parse_quantified())
        if not items:
            return _EMPTY
        return items[0] if len(items) == 1 else Concat(items)

    def parse_quantified(self):
        atom = self.parse_atom()
        c = self.peek()
        if c in ("*", "+", "?"):
            if isinstance(atom, Anchor):
                self.error("量词不能修饰锚点 %r" % atom.kind)
            if c == "*":
                lo, hi = 0, None
            elif c == "+":
                lo, hi = 1, None
            else:
                lo, hi = 0, 1
            self.i += 1
            self.check_quantifier_suffix()
            atom = Repeat(atom, lo, hi)
        elif c == "{":
            if not (isinstance(atom, Char) and atom.quoted):
                parsed = self.try_parse_brace()
                if parsed is not None:
                    if isinstance(atom, Anchor):
                        self.error("量词不能修饰锚点 '{'")
                    lo, hi = parsed
                    self.check_quantifier_suffix()
                    atom = Repeat(atom, lo, hi)
        return atom

    def check_quantifier_suffix(self):
        c = self.peek()
        if c == "?":
            self.error("本子集不支持非贪婪（惰性）量词")
        if c == "+":
            self.error("本子集不支持占有量词")

    def try_parse_brace(self):
        """形如 {n} {n,} {n,m} 才当量词；其余把 '{' 当普通字符（位置还原）。"""
        saved = self.i
        j = self.i + 1
        start = j
        while j < self.n and self.p[j].isdigit():
            j += 1
        if j == start:
            self.i = saved
            return None
        lo = int(self.p[start:j])
        hi = lo
        if j < self.n and self.p[j] == ",":
            j += 1
            k = j
            while j < self.n and self.p[j].isdigit():
                j += 1
            if j == k:
                hi = None
            else:
                hi = int(self.p[k:j])
        if j >= self.n or self.p[j] != "}":
            self.i = saved
            return None
        if hi is not None and lo > hi:
            self.error("计数量词的下界大于上界", self.i)
        if lo > MAX_REPEAT or (hi is not None and hi > MAX_REPEAT):
            self.error("计数量词重复次数超过上限 %d" % MAX_REPEAT, self.i)
        self.i = j + 1
        return lo, hi

    def parse_atom(self):
        c = self.peek()
        if c == "":
            self.error("意外的模式结尾")
        if c in ("*", "+", "?"):
            self.error("量词 %r 前面没有可重复的单元" % c)
        if c == ")":
            self.error("圆括号 ')' 没有匹配的 '('")
        if c == "(":
            return self.parse_group()
        if c == "[":
            return self.parse_class()
        if c == ".":
            self.i += 1
            return Dot()
        if c in ("^", "$"):
            self.i += 1
            return Anchor(c)
        if c == "\\":
            return self.parse_escape(in_class=False)
        if c == "{":
            # 不是合法计数量词，按字面花括号处理。
            self.i += 1
            return Char(ord(c))
        self.i += 1
        return Char(ord(c))

    def parse_group(self):
        open_pos = self.i
        assert self.peek() == "("
        self.i += 1
        if self.peek() == "?":
            self.i += 1
            c = self.peek()
            if c == ":":
                self.i += 1
                child = self.parse_alt()
                self.expect_close(open_pos)
                return Group(None, child)
            if c in ("=", "!"):
                self.error("本子集不支持环视（顺序环视）", open_pos)
            if c == "<" and self.i + 1 < self.n and self.p[self.i + 1] in ("=", "!"):
                self.error("本子集不支持环视（逆序环视）", open_pos)
            if c == "<":
                self.error("本子集不支持命名分组", open_pos)
            if c == "#":
                self.error("本子集不支持注释分组", open_pos)
            if c == "P":
                self.error("本子集不支持命名分组或命名反向引用", open_pos)
            if c == ">":
                self.error("本子集不支持原子分组", open_pos)
            self.error("不识别的分组写法 (?%s" % c, open_pos)
        self.groups += 1
        index = self.groups
        child = self.parse_alt()
        self.expect_close(open_pos)
        return Group(index, child)

    def expect_close(self, open_pos):
        if self.peek() != ")":
            self.error("圆括号未闭合（缺少 ')'）", open_pos)
        self.i += 1

    # 转义与字符类 ----------------------------------------------------------

    def parse_escape(self, in_class):
        """入口时 self.p[self.i] == '\\\\'。"""
        slash = self.i
        self.i += 1
        if self.i >= self.n:
            self.error("反斜杠后面缺少被转义字符", slash)
        c = self.p[self.i]
        self.i += 1

        if c.isdigit():
            if in_class:
                # 字符类内不允许 \1 这类写法（POSIX 语义未定义）。
                self.error("字符类内不支持数字转义", slash)
            if c != "0":
                self.error("本子集不支持反向引用 (\\%s)" % c, slash)
            return Char(0)
        if not in_class and c in ("g", "k"):
            self.error("本子集不支持命名反向引用", slash)
        if not in_class and c == "b":
            self.error("本子集不支持单词边界 \\b（字符类内的 \\b 退格除外）", slash)
        if not in_class and c in ("B",):
            self.error("本子集不支持单词边界 \\B", slash)

        simple = {
            "n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v",
            "a": "\a", "0": "\0",
            "\\": "\\", ".": ".", "|": "|", "*": "*", "+": "+",
            "?": "?", "(": "(", ")": ")", "[": "[", "]": "]",
            "{": "{", "}": "}", "^": "^", "$": "$", "-": "-",
            "/": "/", "'": "'", '"': '"',
        }
        if c in simple:
            ch = simple[c]
            if in_class and c == "b":
                return Char(0x08)
            return Char(ord(ch))
        if in_class and c == "b":
            return Char(0x08)
        if c in ("d", "w", "s", "D", "W", "S"):
            letter = c.lower()
            if c.islower():
                ranges = list(_SHORTHAND_RANGES[letter])
                if in_class:
                    return ("SH", ranges, "")
                return Class(ranges, "", False)
            if in_class:
                return ("SH", [], letter)
            # 类外的 \D \W \S 本身就是“正向类的补集”。
            return Class([], letter, False)
        if c == "x":
            return Char(self.parse_hex(slash, 2))
        if c == "u":
            return Char(self.parse_hex(slash, 4))
        self.error("无法识别的转义序列 \\%s" % c, slash)

    def parse_hex(self, slash, count):
        start = self.i
        for _ in range(count):
            if self.i >= self.n or not _is_hex(self.p[self.i]):
                self.error("十六进制转义位数不足", slash)
            self.i += 1
        return int(self.p[start:self.i], 16)

    def parse_class(self):
        open_pos = self.i
        self.i += 1  # 吃掉 '['
        negated = False
        if self.peek() == "^":
            negated = True
            self.i += 1
        ranges = []
        comp_letters = []
        # 开头的 ] 是字面量。
        first = True
        while first or self.peek() != "]":
            first = False
            if self.peek() == "":
                self.error("字符类未闭合（缺少 ']'）", open_pos)
            item = self.parse_class_item(open_pos)
            kind = item[0]
            if kind == "RANGE":
                ranges.append((item[1], item[2]))
            elif kind == "SH":
                ranges.extend(item[1])
                if item[2]:
                    comp_letters.append(item[2])
        self.i += 1  # 吃掉 ']'
        return Class(ranges, "".join(comp_letters), negated)

    def parse_class_item(self, open_pos):
        c = self.peek()
        if c == "\\":
            item = self.parse_escape(in_class=True)
            if isinstance(item, tuple):
                if self.peek() == "-" and self._next_is_range_end():
                    self.error("简写字符类不能作为字符区间的端点", open_pos)
                return item
            cp = item.cp
            if self.peek() == "-" and self._next_is_range_end():
                self.i += 1  # 吃掉 '-'
                end = self.parse_class_endpoint(open_pos)
                if cp > end:
                    self.error("字符类区间上下界颠倒", open_pos)
                return ("RANGE", cp, end)
            return ("RANGE", cp, cp)
        # 字面字符（含开头位置的 ']'、'-' 等）。
        if c == "-":
            self.i += 1
            cp = ord("-")
        else:
            self.i += 1
            cp = ord(c)
        if self.peek() == "-" and self._next_is_range_end():
            self.i += 1
            end = self.parse_class_endpoint(open_pos)
            if cp > end:
                self.error("字符类区间上下界颠倒", open_pos)
            return ("RANGE", cp, end)
        return ("RANGE", cp, cp)

    def _next_is_range_end(self):
        """当前在 '-' 上，判断后面是否真跟着区间右端。"]' 和结尾不算。"""
        if self.i + 1 >= self.n:
            return False
        return self.p[self.i + 1] != "]"

    def parse_class_endpoint(self, open_pos):
        c = self.peek()
        if c == "":
            self.error("字符类区间缺少右端", open_pos)
        if c == "\\":
            item = self.parse_escape(in_class=True)
            if isinstance(item, tuple):
                self.error("简写字符类不能作为字符区间的端点", open_pos)
            return item.cp
        if c == "]":
            self.error("字符类区间缺少右端", open_pos)
        self.i += 1
        return ord(c)


def _is_hex(c):
    return c in "0123456789abcdefABCDEF"


def parse(pattern):
    if not isinstance(pattern, str):
        raise TypeError("模式必须是 str")
    return _Parser(pattern).parse()
