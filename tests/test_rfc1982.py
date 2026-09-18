"""RFC 1982 领域逻辑单元测试。"""

from datetime import date

import pytest

from app.rfc1982 import (
    BACKWARD,
    EQUAL,
    FORWARD,
    INCOMPARABLE,
    HALF_SPAN,
    MAX_SERIAL,
    SuggestionConflict,
    compare_serials,
    signed_distance,
    suggest_next_serial,
)
from app.service import build_audit

TODAY = date(2026, 9, 18)
BASE = 2026091800


def test_signed_distance_basic():
    assert signed_distance(10, 15) == 5
    assert signed_distance(15, 10) == -5
    assert signed_distance(10, 10) == 0


def test_compare_equal_forward_backward():
    assert compare_serials(100, 100) == EQUAL
    assert compare_serials(100, 101) == FORWARD
    assert compare_serials(101, 100) == BACKWARD


def test_compare_wraparound_near_max():
    # 4294967295 -> 0 是有效前进（回绕 1 步）
    assert compare_serials(MAX_SERIAL, 0) == FORWARD
    assert compare_serials(0, MAX_SERIAL) == BACKWARD


def test_compare_half_span_is_incomparable():
    assert compare_serials(100, 100 + HALF_SPAN) == INCOMPARABLE
    # 反方向同样不可比较
    assert compare_serials(100 + HALF_SPAN, 100) == INCOMPARABLE


def test_compare_just_inside_half_span():
    assert compare_serials(0, HALF_SPAN - 1) == FORWARD
    assert compare_serials(0, HALF_SPAN + 1) == BACKWARD


def test_suggest_normal_day_increments_nn():
    result = suggest_next_serial(BASE + 5, TODAY)
    assert result.next_serial == BASE + 6
    assert result.date_prefix == BASE


def test_suggest_start_of_day_from_zero():
    result = suggest_next_serial(0, TODAY)
    assert result.next_serial == BASE
    # 相对 0 严格前进且不足半圈
    assert 0 < signed_distance(0, BASE) < HALF_SPAN


def test_suggest_from_previous_day_serial():
    # 前一天 23:59 的日期编码，今天 nn=00 即前进
    result = suggest_next_serial(2026091799, TODAY)
    assert result.next_serial == BASE


def test_suggest_wraparound_forward():
    # 当前值接近 2^32 上界，今日日期编码在环上为有效前进
    result = suggest_next_serial(MAX_SERIAL, TODAY)
    assert result.next_serial == BASE
    assert 0 < signed_distance(MAX_SERIAL, BASE) < HALF_SPAN


def test_suggest_daily_sequence_exhausted():
    with pytest.raises(SuggestionConflict) as exc:
        suggest_next_serial(BASE + 99, TODAY)
    assert exc.value.code == "DAILY_SEQUENCE_EXHAUSTED"


def test_suggest_future_date_prefix_is_exhausted():
    with pytest.raises(SuggestionConflict) as exc:
        suggest_next_serial(2099010100, TODAY)
    assert exc.value.code == "DAILY_SEQUENCE_EXHAUSTED"


def test_suggest_half_range_ambiguity():
    # 让当日首个候选 BASE 恰好与 current 差 2^31，其后候选全部倒退
    current = (BASE - HALF_SPAN) % (1 << 32)
    assert signed_distance(current, BASE) == HALF_SPAN
    with pytest.raises(SuggestionConflict) as exc:
        suggest_next_serial(current, TODAY)
    assert exc.value.code == "HALF_RANGE_AMBIGUITY"


def test_build_audit_marks_reject_nodes():
    serials = [
        BASE,
        BASE + 2,  # 前进
        BASE + 2,  # 相等
        BASE + 1,  # 倒退
        BASE + 1 + HALF_SPAN,  # 相对前驱恰差半圈，不可比较
        BASE + 2,  # 从歧义点（2^31+1 处）看为倒退
    ]
    status_code, doc = build_audit("example.org", serials, TODAY)
    states = [item["state"] for item in doc["serials"]]
    assert states == [None, FORWARD, EQUAL, BACKWARD, INCOMPARABLE, BACKWARD]

    reject = [item["index"] for item in doc["serials"] if item["reject_risk"]]
    assert reject == [3, 4, 5]

    summary = doc["summary"]
    assert summary == {
        "total": 6,
        "equal": 1,
        "forward": 1,
        "backward": 2,
        "incomparable": 1,
        "reject_risk_count": 3,
    }
    assert status_code == 201
    assert doc["suggestion"]["next_serial"] == BASE + 3
    assert doc["suggestion"]["valid_forward"] is True


def test_build_audit_conflict_status():
    status_code, doc = build_audit("example.org", [BASE + 99], TODAY)
    assert status_code == 409
    assert doc["suggestion"]["valid_forward"] is False
    assert doc["suggestion"]["error"]["code"] == "DAILY_SEQUENCE_EXHAUSTED"
