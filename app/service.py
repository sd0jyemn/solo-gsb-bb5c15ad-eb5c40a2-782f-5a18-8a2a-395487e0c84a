"""审计结果组装：RFC 1982 逐项判定 + 下一序列号建议。"""

from __future__ import annotations

from datetime import datetime, timezone

from .rfc1982 import (
    EQUAL,
    FORWARD,
    BACKWARD,
    INCOMPARABLE,
    REJECT_STATES,
    SuggestionConflict,
    compare_serials,
    suggest_next_serial,
)

_STATE_NOTES = {
    BACKWARD: "序列号倒退，从服务器将拒绝加载该区域（SOA serial 未更新）",
    INCOMPARABLE: "差值恰为 2^31，RFC 1982 未定义比较结果，从服务器拒绝更新",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_audit(zone: str, serials: list[int], today_utc) -> tuple[int, dict]:
    """对一组按观测时间排列的 serial 逐项判定并生成建议。

    返回 (HTTP 状态码, 尚未分配 id 的可持久化文档字典)。
    即使建议阶段产生 409，审计记录仍会持久化，便于按 ID 回查。
    """
    items: list[dict] = []
    counts = {EQUAL: 0, FORWARD: 0, BACKWARD: 0, INCOMPARABLE: 0}
    reject_risk_count = 0

    for index, serial in enumerate(serials):
        if index == 0:
            # 首项没有前驱，不参与比较。
            items.append(
                {
                    "index": 0,
                    "observed_serial": serial,
                    "previous_serial": None,
                    "state": None,
                    "reject_risk": False,
                    "note": "首个观测值，无可比较的前驱",
                }
            )
            continue

        previous = serials[index - 1]
        state = compare_serials(previous, serial)
        counts[state] += 1
        reject = state in REJECT_STATES
        reject_risk_count += int(reject)
        items.append(
            {
                "index": index,
                "observed_serial": serial,
                "previous_serial": previous,
                "state": state,
                "reject_risk": reject,
                "note": _STATE_NOTES.get(state),
            }
        )

    current = serials[-1]
    try:
        proposed = suggest_next_serial(current, today_utc)
        suggestion = {
            "next_serial": proposed.next_serial,
            "date_prefix": proposed.date_prefix,
            "valid_forward": True,
            "error": None,
        }
        status_code = 201
    except SuggestionConflict as exc:
        suggestion = {
            "next_serial": None,
            "date_prefix": None,
            "valid_forward": False,
            "error": {"code": exc.code, "message": exc.message},
        }
        status_code = 409

    document = {
        "zone": zone,
        "created_at": _utc_now_iso(),
        "serials": items,
        "summary": {
            "total": len(serials),
            EQUAL: counts[EQUAL],
            FORWARD: counts[FORWARD],
            BACKWARD: counts[BACKWARD],
            INCOMPARABLE: counts[INCOMPARABLE],
            "reject_risk_count": reject_risk_count,
        },
        "suggestion": suggestion,
        "reference": "RFC 1982",
    }
    return status_code, document
