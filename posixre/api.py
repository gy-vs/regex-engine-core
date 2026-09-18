"""对外接口：编译模式、单次匹配、全局扫描。

三个公开入口：

* :func:`compile` —— 把模式字符串编译成 :class:`Pattern`
* :func:`match`   —— 在文本中找最左最长匹配，返回 :class:`Match` 或 None
* :func:`finditer` —— 从头到尾扫描，按不重叠方式逐个产出 :class:`Match`
"""

from .errors import PatternError
from . import parser
from .engine import _NFA, run as _nfa_run


class Match:
    """一次匹配的结果。"""

    __slots__ = ("re", "string", "_sp", "_ep")

    def __init__(self, pattern, string, sp, ep):
        self.re = pattern
        self.string = string
        self._sp = sp
        self._ep = ep

    def span(self, group=0):
        """返回组 group 的 (起, 止) 位置；未参与的组为 None。

        组 0 表示整条匹配。
        """
        self._check_group(group)
        s = self._sp[group]
        if s is None:
            return None
        return (s, self._ep[group])

    def start(self, group=0):
        sp = self._sp[group]
        return None if sp is None else sp

    def end(self, group=0):
        sp = self._sp[group]
        return None if sp is None else self._ep[group]

    def group(self, group=0):
        """返回组 group 匹配到的子串；未参与返回 None，空匹配返回 ''。"""
        sp = self.span(group)
        if sp is None:
            return None
        return self.string[sp[0]:sp[1]]

    def groups(self):
        """按编号返回所有捕获组（不含组 0）。"""
        return tuple(self.group(g)
                     for g in range(1, self.re.groups + 1))

    def _check_group(self, group):
        if not isinstance(group, int) or group < 0 or group > self.re.groups:
            raise IndexError("没有编号为 %r 的捕获组" % (group,))

    def __getitem__(self, group):
        return self.group(group)

    def __repr__(self):
        return "<Match span=%r %r>" % (self.span(), self.group())


class Pattern:
    """编译后的模式。

    ``pattern.match(text)`` 等价于模块级 :func:`match`；
    ``pattern.finditer(text)`` 等价于模块级 :func:`finditer`。
    """

    __slots__ = ("pattern", "groups", "_nfa")

    def __init__(self, pattern):
        if not isinstance(pattern, str):
            raise TypeError("模式必须是 str")
        node, ngroups = parser.parse(pattern)
        self.pattern = pattern
        self.groups = ngroups
        self._nfa = _NFA(node, ngroups)

    def match(self, text, pos=0, endpos=None):
        """在 text[pos:endpos] 中做一次最左最长搜索。

        返回的 Match 位置基于整个 text（绝对位置），不复制字符串。
        """
        if not isinstance(text, str):
            raise TypeError("待匹配文本必须是 str")
        if endpos is None:
            endpos = len(text)
        if pos < 0 or endpos < pos or endpos > len(text):
            raise ValueError("pos/endpos 越界")
        result = _nfa_run(self._nfa, text, pos, endpos)
        if result is None:
            return None
        start, end, sp, ep = result
        # 引擎返回的是窗口内相对位置，转成整个 text 的绝对位置。
        sp = tuple(None if x is None else x + pos for x in sp)
        ep = tuple(None if x is None else x + pos for x in ep)
        return Match(self, text, sp, ep)

    def finditer(self, text):
        """从头到尾扫描 text，产出全部不重叠匹配（见模块文档的推进规则）。"""
        return _scan(self, text)

    def __repr__(self):
        return "<Pattern %r groups=%d>" % (self.pattern, self.groups)


def _scan(pattern, text):
    """全局扫描，底层为引擎的单遍连续模拟（见 posixre.engine.scan）。

    推进规则：

    1. 在当前游标 pos 处找下一个匹配 [s, e)，s >= pos；
    2. 下一轮从 e 开始；
    3. 若该匹配是空匹配（s == e），则先把位置推进到 e+1 再继续搜索，
       即跳过 text[e] 这一个字符（该字符不出现在任何匹配中，也不会被
       再当作匹配起点），避免在同一位置反复产出空串；
    4. 已经越过文本末尾时停止。

    因此在末尾位置允许产出一个空匹配，例如 ``a*`` 扫描 ``"ab"`` 依次
    得到 ``"a"``(0,1)、``""``(1,1)、``""``(2,2)——中间的 'b' 按规则 3
    被跨过；两个空匹配不会落在同一位置。
    """
    n = len(text)
    pos = 0
    while pos <= n:
        result = _nfa_run(pattern._nfa, text, pos, n)
        if result is None:
            return
        start, end, sp, ep = result
        s = pos + start
        e = pos + end
        yield Match(pattern, text,
                    tuple(None if x is None else x + pos for x in sp),
                    tuple(None if x is None else x + pos for x in ep))
        if s == e:
            pos = e + 1  # 空匹配：强制跨过一个字符
        else:
            pos = e


_cache = {}


def compile(pattern):
    """编译模式（带一个按模式字符串的小型缓存），返回 Pattern。"""
    cached = _cache.get(pattern)
    if cached is None:
        cached = Pattern(pattern)
        _cache[pattern] = cached
        if len(_cache) > 512:
            _cache.clear()
    return cached


def match(pattern, text):
    """编译（或取缓存）pattern 并在 text 中找一次最左最长匹配。"""
    return compile(pattern).match(text)


def finditer(pattern, text):
    """编译（或取缓存）pattern 并扫描 text 的全部不重叠匹配。"""
    return compile(pattern).finditer(text)
