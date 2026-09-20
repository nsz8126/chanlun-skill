"""Canonical signal contract for Rust-derived Chan analysis results.

This module owns normalization and the small, explicit confirmation state
machine used by the Skill.  It deliberately does not infer confirmation from
the mere fact that a Rust factory currently reports a signal as valid.
"""

from typing import Optional


VALID_CONFIRMATION_STATES = frozenset({"候选", "已确认", "已失效"})
TERMINAL_CONFIRMATION_STATES = frozenset({"已失效"})


def _requested_state(raw: dict) -> str:
    """Read the state without upgrading an ordinary live signal."""
    state = raw.get("确认状态", raw.get("确认级别", "候选"))
    return state if state in VALID_CONFIRMATION_STATES else "候选"


def derive_signal_state(raw: dict) -> tuple[str, str]:
    """Derive a canonical state and a deterministic reason.

    A signal remains ``候选`` unless its producer explicitly marks it
    ``已确认``.  A false stop-loss validity always dominates and invalidates
    the signal.  This is intentionally conservative for batch historical
    analysis, where future candles are not available for confirmation.
    """
    stop = raw.get("止损") or {}
    if stop.get("有效性") is False:
        return "已失效", "核心止损工厂判定失效"
    requested = _requested_state(raw)
    if requested == "已确认":
        return "已确认", "上游明确提供确认状态"
    if requested == "已失效":
        return "已失效", "上游明确提供失效状态"
    return "候选", "核心结构命中，等待后续K线确认"


def transition_signal_state(
    signal: dict, new_state: str, reason: str = ""
) -> dict:
    """Apply one legal state transition and append an audit trail.

    Legal transitions are ``候选→已确认`` / ``候选→已失效`` and
    ``已确认→已失效``.  Idempotent transitions are allowed so a caller can
    re-emit the same event without duplicating state changes.
    """
    if new_state not in VALID_CONFIRMATION_STATES:
        raise ValueError(f"非法确认状态: {new_state!r}")
    current = signal.get("确认状态", signal.get("确认级别", "候选"))
    if current not in VALID_CONFIRMATION_STATES:
        raise ValueError(f"信号当前状态非法: {current!r}")
    legal = {
        "候选": {"候选", "已确认", "已失效"},
        "已确认": {"已确认", "已失效"},
        "已失效": {"已失效"},
    }
    if new_state not in legal[current]:
        raise ValueError(f"非法状态流转: {current} → {new_state}")
    signal["确认状态"] = new_state
    signal["确认级别"] = new_state
    trail = signal.setdefault("状态轨迹", [])
    if not trail or trail[-1].get("状态") != new_state:
        trail.append({"状态": new_state, "原因": reason or "状态更新"})
    signal["可执行"] = (
        new_state == "已确认"
        and (signal.get("证据") or {}).get("止损", {}).get("有效性", True) is not False
    )
    return signal


def normalize_signal(raw: dict, period: str, trend: Optional[dict] = None) -> dict:
    """Normalize legacy signal fields without changing their original values."""

    kind = raw.get("kind", "")
    direction = raw.get("direction")
    if direction not in ("买", "卖"):
        direction = "买" if "买" in kind else "卖" if "卖" in kind else "未知"
    stop = raw.get("止损") or {}
    core_match = raw.get("核心匹配") or {}
    evidence = {
        "核心判据": raw.get("核心判据") or {},
        "核心匹配": core_match,
        "背驰": raw.get("背驰证据") or {},
        "止损": stop,
    }
    state, state_reason = derive_signal_state(raw)
    normalized = {
        "schema_version": "signal-1.0",
        "周期": period,
        "类型": kind,
        "基础类型": raw.get("base"),
        "方向": direction,
        "确认状态": state,
        "状态轨迹": [{"状态": state, "原因": state_reason}],
        "结构来源": raw.get("结构来源", "rust_core"),
        "分类来源": raw.get("类型来源", "skill_classifier"),
        "止损来源": raw.get("止损来源", "rust_factory"),
        "置信度": raw.get("置信度", "未知"),
        "时间": raw.get("time"),
        "序号": raw.get("index"),
        "高": raw.get("high"),
        "低": raw.get("low"),
        "破位值": raw.get("break"),
        "证据": evidence,
        "理由": raw.get("reason", ""),
        "可执行": state == "已确认" and stop.get("有效性", True) is not False,
        "走势上下文": {
            "类型": (trend or {}).get("类型"),
            "方向": (trend or {}).get("方向"),
        },
    }
    # Keep the legacy alias for consumers that have not migrated yet.
    normalized["确认级别"] = state
    return normalized


def normalize_signals(signals: list, period: str, trend: Optional[dict] = None) -> list:
    return [normalize_signal(signal, period, trend) for signal in signals]


__all__ = [
    "VALID_CONFIRMATION_STATES",
    "derive_signal_state",
    "transition_signal_state",
    "normalize_signal",
    "normalize_signals",
]
