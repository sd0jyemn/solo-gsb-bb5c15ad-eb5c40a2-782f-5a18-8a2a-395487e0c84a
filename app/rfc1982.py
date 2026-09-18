"""RFC 1982 (Serial Number Arithmetic) 领域逻辑。

32 位无符号序列号在模 2^32 的环形空间中比较：
  * 相等（equal）：两值完全相同；
  * 前进（forward）：后继值位于环形正方向且严格小于半圈；
  * 倒退（backward）：后继值位于环形负方向且严格小于半圈；
  * 不可比较（incomparable）：差值恰为 2^31（半区间，RFC 1982 未定义结果）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

BITS = 32
MODULUS = 1 << BITS  # 2^32
HALF_SPAN = 1 << (BITS - 1)  # 2^31
MAX_SERIAL = MODULUS - 1

EQUAL = "equal"
FORWARD = "forward"
BACKWARD = "backward"
INCOMPARABLE = "incomparable"

# 会使从服务器拒绝加载该区域的状态：倒退或落在半区间歧义点。
REJECT_STATES = frozenset({BACKWARD, INCOMPARABLE})


class SuggestionConflict(Exception):
    """无法给出 YYYYMMDDnn 风格的有效前进建议（映射为 HTTP 409）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def signed_distance(current: int, candidate: int) -> int:
    """从 current 到 candidate 的有符号环形距离，范围 [-2^31, 2^31]。

    正且严格小于 2^31 为前进；负为倒退；恰为 2^31 不可比较。
    """
    delta = (candidate - current) % MODULUS
    if delta > HALF_SPAN:
        delta -= MODULUS
    return delta


def compare_serials(previous: int, current: int) -> str:
    """按 RFC 1982 判定 current 相对 previous 的关系。"""
    distance = signed_distance(previous, current)
    if distance == 0:
        return EQUAL
    if distance == HALF_SPAN:
        return INCOMPARABLE
    return FORWARD if distance > 0 else BACKWARD


@dataclass(frozen=True)
class Suggestion:
    next_serial: int
    date_prefix: int  # 建议序列号基准（YYYYMMDD * 100）


def suggest_next_serial(current: int, today: date) -> Suggestion:
    """给出相对 current 为 RFC 1982 有效前进的最小 YYYYMMDDnn。

    依次尝试当日 nn=00..99，取第一个与 current 的环形距离落在
    (0, 2^31) 区间内的候选。全部不构成有效前进时抛出
    SuggestionConflict（HTTP 409）：
      * DAILY_SEQUENCE_EXHAUSTED：当日编号全部为相等/倒退（含当日编号
        已用完、current 的日期前缀已在今天之后等情形）；
      * HALF_RANGE_AMBIGUITY：阻断候选与 current 恰差 2^31，RFC 1982
        比较结果未定义；
      * SERIAL_SPACE_OVERFLOW：当日前缀超出 32 位无符号范围。
    """
    base = int(today.strftime("%Y%m%d")) * 100  # YYYYMMDD00
    if base > MAX_SERIAL:
        raise SuggestionConflict(
            "SERIAL_SPACE_OVERFLOW",
            f"今日前缀 {base} 超出 32 位无符号序列号范围",
        )

    for nn in range(100):
        candidate = base + nn
        distance = signed_distance(current, candidate)
        if 0 < distance < HALF_SPAN:
            return Suggestion(next_serial=candidate, date_prefix=base)

    # 没有有效前进候选：定位阻断原因。100 个候选连续递增，歧义点之后的
    # 候选在环上均变为倒退，因此真正阻断建议的歧义点只能是当日首个候选。
    ambiguous = [
        base + nn
        for nn in range(100)
        if signed_distance(current, base + nn) == HALF_SPAN
    ]
    if ambiguous:
        candidate = ambiguous[0]
        raise SuggestionConflict(
            "HALF_RANGE_AMBIGUITY",
            f"候选 {candidate} 与当前序列号 {current} 恰差 2^31，"
            "RFC 1982 比较结果未定义",
        )

    raise SuggestionConflict(
        "DAILY_SEQUENCE_EXHAUSTED",
        f"当前序列号 {current}：{today.isoformat()} 的 YYYYMMDDnn "
        "编号均不构成有效前进（当日编号耗尽或当前值已在今日之后）",
    )
