"""NFA 构造与模拟。

匹配算法是带“捕获标签”的 Thompson NFA 集合模拟：

* 任意一步存活的线程数不超过 NFA 状态数，每个输入字符只做一次
  ε-闭包和一次按字符迁移，最坏耗时 O(n·|Q|)（|Q| 只由模式决定），
  不存在回溯法那种随嵌套量词指数增长的路径数。
* 每个 NFA 状态在任一时刻只保留一条 POSIX 最优的捕获记录。
  Thompson 构造保证同一个结构状态要么固定在某个捕获组内部、要么固定
  在外部（inside 集合是状态的静态属性），因此“参与优先 / 开放比起点 /
  闭合比长度”的逐项比较是共享后缀上的支配序：被淘汰的记录在任何后续
  输入上都不可能反超，单记录不丢 POSIX 最优解，也不需要回溯。
"""

from . import parser
from .parser import (
    Char as _Char, Dot as _Dot, Anchor as _Anchor, Class as _Class,
    Group as _Group, Concat as _Concat, Alt as _Alt, Repeat as _Repeat,
)

_MAX_STATES = 100_000


class _State:
    __slots__ = ("uid", "edges")

    def __init__(self, uid):
        self.uid = uid
        self.edges = []


# 边的两种形式：
#   ("C", pred, target)    消耗一个字符；pred 见 _pred_match
#   ("E", action, target)  ε 边；action 为 None，或
#       ("open", g) / ("close", g) / ("guard", "^") / ("guard", "$")


class _NFA:
    def __init__(self, root, ngroups):
        self.ngroups = ngroups
        self.states = []
        self.accept = self.new_state()
        self.start = self.emit(root, self.accept)
        if len(self.states) > _MAX_STATES:
            raise parser.PatternError(
                "模式展开后状态数超过上限 %d" % _MAX_STATES, 0)
        self.inside = self._compute_inside()
        self.has_dollar = self._has_edge_action("guard", "$")
        self._compile_edges()

    def _compile_edges(self):
        """把边预处理成模拟期的扁平形式：

        * cedges[uid] = (target_uid, pred_kind, a, b)
          pred_kind: 0=点号(恒真) 1=单字符(a=码点) 2=类(a=payload)
        * eedges[uid] = (target_uid, tag, g)
          tag: 0=纯ε 1=open 2=close 3=guard^ 4=guard$
        """
        self.cedges = []
        self.eedges = []
        for s in self.states:
            ce = []
            ee = []
            for kind, payload, dst in s.edges:
                if kind == "C":
                    if payload[0] == 2:
                        ce.append((dst.uid, 2, payload[1], None))
                    else:
                        ce.append((dst.uid, payload[0], payload[1], None))
                else:
                    if payload is None:
                        tag, g = 0, -1
                    else:
                        g = payload[1]
                        tag = {"open": 1, "close": 2}.get(payload[0])
                        if tag is None:
                            tag = 3 if payload[1] == "^" else 4
                            g = -1
                    ee.append((dst.uid, tag, g))
            self.cedges.append(ce)
            self.eedges.append(ee)

    def _has_edge_action(self, kind, value):
        for s in self.states:
            for ek, act, _ in s.edges:
                if ek == "E" and act is not None \
                        and act[0] == kind and act[1] == value:
                    return True
        return False

    def new_state(self):
        s = _State(len(self.states))
        self.states.append(s)
        return s

    def eps(self, src, dst, action=None):
        src.edges.append(("E", action, dst))

    def char(self, src, dst, pred):
        src.edges.append(("C", pred, dst))

    # emit(node, k) 新建子表达式的状态，返回入口；匹配完 node 后 ε 续接 k。
    def emit(self, node, k):
        t = type(node)
        if t is _Char:
            s = self.new_state()
            self.char(s, k, (1, node.cp))
            return s
        if t is _Dot:
            s = self.new_state()
            self.char(s, k, (0, None))
            return s
        if t is _Anchor:
            s = self.new_state()
            self.eps(s, k, ("guard", node.kind))
            return s
        if t is _Class:
            s = self.new_state()
            payload = (tuple(node.ranges), node.comp_letters, node.negated)
            self.char(s, k, (2, payload))
            return s
        if t is _Group:
            child_k = k
            if node.index is not None:
                exit_s = self.new_state()
                self.eps(exit_s, k, ("close", node.index))
                child_k = exit_s
            child = self.emit(node.child, child_k)
            if node.index is None:
                return child
            entry = self.new_state()
            self.eps(entry, child, ("open", node.index))
            return entry
        if t is _Concat:
            cont = k
            for sub in reversed(node.items):
                cont = self.emit(sub, cont)
            return cont
        if t is _Alt:
            split = self.new_state()
            self.eps(split, self.emit(node.left, k))
            self.eps(split, self.emit(node.right, k))
            return split
        if t is _Repeat:
            return self._emit_repeat(node, k)
        raise AssertionError("未处理的 AST 节点 %r" % (node,))

    def _emit_repeat(self, node, k):
        lo, hi = node.lo, node.hi
        if hi is None:
            # (body){lo,}：lo 份强制副本，之后 split -> body -> split 循环。
            split = self.new_state()
            body = self.emit(node.child, split)
            self.eps(split, body)          # 继续重复
            self.eps(split, k)             # 结束
            cont = split
            for _ in range(lo):
                cont = self.emit(node.child, cont)
            return cont
        # 有界：lo 份强制副本，再接 hi-lo 个“可选副本”。
        cont = k
        for _ in range(hi - lo):
            body = self.emit(node.child, cont)
            split = self.new_state()
            self.eps(split, body)
            self.eps(split, cont)
            cont = split
        for _ in range(lo):
            cont = self.emit(node.child, cont)
        return cont

    def _compute_inside(self):
        """静态求每个状态“身处哪些捕获组内部”的集合。

        沿 ε 边传播：经过 open g 加入 g，经过 close g 去掉 g。
        字符边是边界：字符状态没有 ε 出边，其目标状态的身份也不依赖来源，
        因此只沿 ε 边传播即可。Thompson 构造中每个新建状态只属于唯一一个
        结构性嵌套层级，故传播到同一状态的集合必然相同。
        """
        sets = [None] * len(self.states)
        sets[self.start.uid] = frozenset()
        stack = [self.start]
        while stack:
            s = stack.pop()
            cur = sets[s.uid]
            for kind, act, dst in s.edges:
                if kind != "E":
                    continue
                nxt = cur
                if act is not None and act[0] == "open":
                    nxt = cur | frozenset((act[1],))
                elif act is not None and act[0] == "close":
                    nxt = cur - frozenset((act[1],))
                if sets[dst.uid] is None:
                    sets[dst.uid] = nxt
                    stack.append(dst)
                # 若理论上不该出现的不一致发生，以先到的值为准
                # （构造不变式保证不会走到这里）。
        for i, v in enumerate(sets):
            if v is None:
                sets[i] = frozenset()
        return sets


# 谓词 ---------------------------------------------------------------------

_DIGIT_TAB = frozenset(range(ord("0"), ord("9") + 1))
_WORD_TAB = (_DIGIT_TAB
             | frozenset(range(ord("A"), ord("Z") + 1))
             | frozenset(range(ord("a"), ord("z") + 1))
             | frozenset((ord("_"),)))
_SPACE_TAB = frozenset([ord("\t"), ord("\n"), ord("\v"), ord("\f"),
                        ord("\r"), ord(" ")])
# \D \W \S 共享一张“正向对应类”的表，键用小写字母。
_POS_TAB = {"d": _DIGIT_TAB, "w": _WORD_TAB, "s": _SPACE_TAB}


def _pred_match_payload(payload, cp):
    """字符类判定；payload 为 (ranges, comp_letters, negated)。"""
    ranges, comp_letters, negated = payload
    member = False
    for lo, hi in ranges:
        if lo <= cp <= hi:
            member = True
            break
    if not member:
        for letter in comp_letters:
            if cp not in _POS_TAB[letter]:
                member = True
                break
    return (not member) if negated else member


def _pred_match(pred, cp):
    kind = pred[0]
    if kind == 0:  # . 匹配任意字符（含换行）
        return True
    if kind == 1:
        return cp == pred[1]
    return _pred_match_payload(pred[1], cp)



# 带标签的集合模拟 ---------------------------------------------------------
#
# 每个存活线程的“记录”是 (start, sp, ep)：
#   start  线程起点（决定最左）
#   sp/ep  长度为组数+1 的元组，记录每个捕获组的起点/终点，None=未参与
# 跨越 open/close 边时只复制这两个元组，其大小只由模式的捕获组数决定，
# 与输入长度无关，因此每个字符、每条边的处理都是常数（相对组数量级），
# 总耗时严格 O(n·|Q|·G)，不随输入长度退化成平方。
#
# 每个 NFA 状态同一时刻只保留 POSIX 支配序下最优的一条记录（见
# _record_better）。


def _fresh_record(start, ng):
    sp = [None] * (ng + 1)
    ep = [None] * (ng + 1)
    sp[0] = start
    return (start, tuple(sp), tuple(ep))


def _apply(rec, tag, g, p):
    """在记录上施加 open(tag=1)/close(tag=2) 动作，返回新记录。"""
    start, sp, ep = rec
    sp = list(sp)
    ep = list(ep)
    if tag == 1:  # open
        sp[g] = p
        ep[g] = None
    else:  # close
        ep[g] = p
    return (start, tuple(sp), tuple(ep))


def _record_better(a, b, ng, inside):
    """POSIX 支配序：返回不劣者（完全相同返回 a）。"""
    if a is None:
        return b
    if b is None:
        return a
    if a[0] != b[0]:
        return a if a[0] < b[0] else b
    spa, epa = a[1], a[2]
    spb, epb = b[1], b[2]
    for g in range(1, ng + 1):
        sa, sb = spa[g], spb[g]
        pa = sa is not None
        pb = sb is not None
        if pa != pb:
            return a if pa else b
        if not pa:
            continue
        if g in inside:
            if sa != sb:  # 开放组：起点越小越长
                return a if sa < sb else b
        else:
            ea, eb = epa[g], epb[g]
            if ea is not None and eb is not None:
                la, lb = ea - sa, eb - sb
                if la != lb:
                    return a if la > lb else b
                if sa != sb:
                    return a if sa < sb else b
    return a


def run(nfa, text, pos=0, endpos=None):
    """在 text[pos:endpos] 中做一次最左最长匹配（不复制字符串）。

    返回 (start, end, sp, ep)（窗口相对坐标）或 None。

    双缓冲数组 + 各自的稀疏活跃状态列表：每步字符迁移只遍历当前活跃状态，
    ε 闭包在目标缓冲上原地做不动点，从不对状态数组做整表清零。
    """
    if endpos is None:
        endpos = len(text)
    ng = nfa.ngroups
    Q = len(nfa.states)
    inside = nfa.inside
    accept_uid = nfa.accept.uid
    has_dollar = nfa.has_dollar
    win_len = endpos - pos
    cedges = nfa.cedges
    eedges = nfa.eedges

    bufs = [[None] * Q, [None] * Q]
    lives = [[], []]
    cur_i = 0
    work = []

    def add_in(buf_i, uid, rec):
        buf = bufs[buf_i]
        old = buf[uid]
        if old is None:
            buf[uid] = rec
            lives[buf_i].append(uid)
            work.append(uid)
            return
        best = _record_better(old, rec, ng, inside[uid])
        if best is not old:
            buf[uid] = best
            work.append(uid)

    def closure(buf_i, abs_p, rel_p, end_abs):
        buf = bufs[buf_i]
        while work:
            uid = work.pop()
            rec = buf[uid]
            for d, tag, g in eedges[uid]:
                if tag == 3:  # guard ^
                    if abs_p == 0:
                        add_in(buf_i, d, rec)
                elif tag == 4:  # guard $
                    if abs_p == end_abs:
                        add_in(buf_i, d, rec)
                elif tag == 0:
                    add_in(buf_i, d, rec)
                else:
                    add_in(buf_i, d, _apply(rec, tag, g, rel_p))

    def accept_into(buf_i, end_p, best):
        rec = bufs[buf_i][accept_uid]
        if rec is None:
            return best
        if best is None:
            return (end_p, rec)
        bend, brec = best
        if rec[0] < brec[0]:
            return (end_p, rec)
        if rec[0] == brec[0]:
            if end_p > bend:
                return (end_p, rec)
            if end_p == bend:
                winner = _record_better(brec, rec, ng,
                                        inside[accept_uid])
                if winner is not brec:
                    return (end_p, rec)
        return best

    # best: (end, rec)。起点更靠左的线程可能接受得早，起点更靠右的线程
    # 可能接受得晚且更长——POSIX 仍取前者。只有当“起点不大于 best 起点
    # 的线程全部死亡”后，best 的起点才最终锁定（committed）。
    add_in(cur_i, nfa.start.uid, _fresh_record(0, ng))
    closure(cur_i, pos, 0, endpos)
    best = accept_into(cur_i, 0, None)
    committed = False

    for p in range(win_len):
        # 起点锁定判定：存活线程里已没有起点 <= best 起点的。
        if best is not None and not committed:
            bs0 = best[1][0]
            committed = not any(
                bufs[cur_i][u] is not None
                and bufs[cur_i][u][0] <= bs0
                for u in lives[cur_i])
        if committed and not has_dollar:
            break

        nxt_i = cur_i ^ 1
        old_life = lives[nxt_i]
        for u in old_life:
            bufs[nxt_i][u] = None
        del old_life[:]
        del work[:]

        cp = ord(text[pos + p])
        bs0 = best[1][0] if best is not None else None
        for uid in lives[cur_i]:
            rec = bufs[cur_i][uid]
            if committed and rec[0] != bs0:
                continue
            for d, pk, a, _b in cedges[uid]:
                if pk == 0:
                    add_in(nxt_i, d, rec)
                elif pk == 1:
                    if a == cp:
                        add_in(nxt_i, d, rec)
                elif _pred_match_payload(a, cp):
                    add_in(nxt_i, d, rec)

        new_abs = pos + p + 1
        # 补种入口线程与字符迁移结果合并到同一次闭包完成。
        if not committed:
            add_in(nxt_i, nfa.start.uid, _fresh_record(p + 1, ng))
        closure(nxt_i, new_abs, p + 1, endpos)

        cur_i = nxt_i
        best = accept_into(cur_i, p + 1, best)

    if best is None:
        return None
    end, rec = best
    start, sp, ep = rec
    sp = list(sp)
    ep = list(ep)
    sp[0] = start
    ep[0] = end
    return start, end, tuple(sp), tuple(ep)
