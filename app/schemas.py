"""请求/响应 Pydantic 模型。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ComparisonState = Literal["equal", "forward", "backward", "incomparable"]

# RFC 1035 标签：字母数字开头/结尾，中间可为连字符，长度 1-63；点分隔，总长 <=253。
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_ZONE_RE = re.compile(rf"{_LABEL}(?:\.{_LABEL})*\.?")


class AuditCreate(BaseModel):
    zone: str = Field(..., min_length=1, max_length=253, description="区域名，如 example.org")
    serials: list[int] = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="按观测时间先后排列的 32 位无符号 SOA serial",
    )

    @field_validator("zone")
    @classmethod
    def validate_zone(cls, value: str) -> str:
        candidate = value.strip().rstrip(".").lower()
        if not _ZONE_RE.fullmatch(candidate):
            raise ValueError("非法区域名：需为 RFC 1035 风格的点分标签")
        if any(len(label) > 63 for label in candidate.split(".")):
            raise ValueError("单个标签长度不得超过 63")
        return candidate

    @field_validator("serials")
    @classmethod
    def validate_serials(cls, value: list[int]) -> list[int]:
        for serial in value:
            if not 0 <= serial <= 0xFFFFFFFF:
                raise ValueError("serial 必须是 32 位无符号整数 [0, 4294967295]")
        return value


class SerialItem(BaseModel):
    index: int
    observed_serial: int
    previous_serial: int | None
    state: ComparisonState | None
    reject_risk: bool
    note: str | None = None


class AuditSummary(BaseModel):
    total: int
    equal: int
    forward: int
    backward: int
    incomparable: int
    reject_risk_count: int


class SuggestionError(BaseModel):
    code: Literal[
        "DAILY_SEQUENCE_EXHAUSTED",
        "HALF_RANGE_AMBIGUITY",
        "SERIAL_SPACE_OVERFLOW",
    ]
    message: str


class NextSerialSuggestion(BaseModel):
    next_serial: int | None
    date_prefix: int | None
    valid_forward: bool
    error: SuggestionError | None = None


class AuditOut(BaseModel):
    id: int
    zone: str
    created_at: str
    serials: list[SerialItem]
    summary: AuditSummary
    suggestion: NextSerialSuggestion
    reference: str = "RFC 1982"
