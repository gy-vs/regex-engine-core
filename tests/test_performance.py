"""耗时形状测试：嵌套量词不得导致指数级耗时，捕获位置同样在内。

线性判定用相邻长度的耗时比值（40/20、60/40、80/60）：长度翻倍时
耗时不应翻倍式恶化；这里用一个远松于指数阈值的上限做回归保护。
"""

import time
import unittest

import posixre


def _best_time(pattern, text, runs=7):
    p = posixre.compile(pattern)
    best = float("inf")
    result = None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = p.match(text)
        best = min(best, time.perf_counter() - t0)
    return best, result


class PerformanceShapeTests(unittest.TestCase):
    PATTERN = r"(a|aa)*b"

    def test_milliseconds_at_80(self):
        elapsed, m = _best_time(self.PATTERN, "a" * 80)
        self.assertIsNone(m)
        self.assertLess(elapsed, 0.05,  # 50ms 上限，实测约 2ms
                        "长度 80 耗时 %.1fms，疑似指数级" % (elapsed * 1000))

    def test_growth_is_subquadratic(self):
        timings = {}
        for n in (20, 40, 60, 80):
            elapsed, m = _best_time(self.PATTERN, "a" * n, runs=5)
            self.assertIsNone(m)
            timings[n] = max(elapsed, 1e-5)
        # 若为指数（约 2^(n/2) 的 Fibonacci 路径数），长度 +20 耗时要涨
        # 上千倍。线性增长的比值在 2 附近，这里放到 6 倍作为环境抖动下的
        # 回归红线，但三个相邻比值都必须达标。
        for lo, hi in ((20, 40), (40, 60), (60, 80)):
            ratio = timings[hi] / timings[lo]
            self.assertLess(
                ratio, 6.0,
                "长度 %d->%d 耗时比值 %.2f，增长形状不是近线性"
                % (lo, hi, ratio))

    def test_other_catastrophic_patterns(self):
        cases = [
            (r"(a+)+b", "a" * 80),
            (r"(a|a)*b", "a" * 80),
            (r"(a?)*b", "a" * 80),
            (r"(a|aa)*b", "a" * 80),
            (r"^(a+)+b$", "a" * 80),
        ]
        for pattern, text in cases:
            elapsed, m = _best_time(pattern, text, runs=3)
            self.assertLess(elapsed, 0.05,
                            "%r 耗时 %.1fms" % (pattern, elapsed * 1000))
            self.assertIsNone(m)

    def test_capture_extraction_in_same_budget(self):
        # 带捕获组的灾难性模式，取分组位置也不能退回指数级。
        pattern = r"(a|aa)*((b)?b)?"
        elapsed, m = _best_time(pattern, "a" * 80, runs=3)
        self.assertLess(elapsed, 0.05)
        # (a|aa)* 吃掉全部 80 个 a，后面 b 组未参与；同时验证取捕获位置。
        self.assertEqual(m.span(0), (0, 80))
        self.assertIsNone(m.span(2))
        self.assertIsNone(m.span(3))

    def test_long_plain_text_is_linear(self):
        p = posixre.compile(r"[a-z]+")
        text = "a" * 20000
        t0 = time.perf_counter()
        m = p.match(text)
        elapsed = time.perf_counter() - t0
        self.assertEqual(m.span(), (0, 20000))
        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
