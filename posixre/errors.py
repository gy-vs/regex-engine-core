"""编译期错误类型。"""


class PatternError(ValueError):
    """模式本身非法或使用了本子集之外的写法。

    所有报错都通过 :attr:`pos` 指出问题在模式中的 0 基下标；
    用户可见的消息里会同时给出 1 基的“第几个字符”。
    """

    def __init__(self, message: str, pos: int):
        self.message = message
        self.pos = pos
        super().__init__(f"{message}（第 {pos + 1} 个字符，0 基下标 {pos}）")
