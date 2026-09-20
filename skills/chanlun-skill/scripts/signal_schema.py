"""Independent validator for the canonical standard-signal contract."""

from __future__ import annotations

from typing import Any, Iterable, Optional

try:
    from signal_contract import VALID_CONFIRMATION_STATES
except ImportError:  # pragma: no cover - package-style import fallback
    from .signal_contract import VALID_CONFIRMATION_STATES


VALID_DIRECTIONS = frozenset({"买", "卖", "未知"})
VALID_TYPES = frozenset(
    f"{base}{side}"
    for base in ("T1", "T1P", "T2", "T2S", "T3A", "T3B")
    for side in ("买", "卖")
)
REQUIRED_FIELDS = (
    "schema_version",
    "周期",
    "类型",
    "方向",
    "确认状态",
    "结构来源",
    "分类来源",
    "止损来源",
    "证据",
    "可执行",
    "走势上下文",
)


def _error(message: str, index: Optional[int] = None) -> str:
    return f"标准信号[{index}] {message}" if index is not None else message


def validate_signal(signal: Any, index: Optional[int] = None) -> list[str]:
    """Return contract violations for one normalized signal."""
    errors: list[str] = []
    if not isinstance(signal, dict):
        return [_error("必须是对象", index)]
    for field in REQUIRED_FIELDS:
        if field not in signal:
            errors.append(_error(f"缺少必需字段 {field!r}", index))

    if signal.get("schema_version") != "signal-1.0":
        errors.append(_error("schema_version 必须为 'signal-1.0'", index))
    if not isinstance(signal.get("周期"), str) or not signal.get("周期"):
        errors.append(_error("周期必须是非空字符串", index))
    if signal.get("类型") not in VALID_TYPES:
        errors.append(_error(f"类型非法: {signal.get('类型')!r}", index))
    if signal.get("方向") not in VALID_DIRECTIONS:
        errors.append(_error(f"方向非法: {signal.get('方向')!r}", index))
    if signal.get("类型") in VALID_TYPES:
        expected_direction = "买" if signal["类型"].endswith("买") else "卖"
        if signal.get("方向") not in (expected_direction, "未知"):
            errors.append(
                _error(
                    f"方向与类型不一致（{signal.get('类型')} 应为 {expected_direction}）",
                    index,
                )
            )
    if signal.get("确认状态") not in VALID_CONFIRMATION_STATES:
        errors.append(_error(f"确认状态非法: {signal.get('确认状态')!r}", index))
    if "确认级别" in signal and signal.get("确认级别") != signal.get("确认状态"):
        errors.append(_error("确认级别必须与确认状态一致", index))
    for field in ("结构来源", "分类来源", "止损来源"):
        if not isinstance(signal.get(field), str) or not signal.get(field):
            errors.append(_error(f"{field}必须是非空字符串", index))
    if not isinstance(signal.get("证据"), dict):
        errors.append(_error("证据必须是对象", index))
    else:
        stop = signal["证据"].get("止损")
        if not isinstance(stop, dict):
            errors.append(_error("证据.止损必须是对象", index))
    if not isinstance(signal.get("走势上下文"), dict):
        errors.append(_error("走势上下文必须是对象", index))
    if not isinstance(signal.get("可执行"), bool):
        errors.append(_error("可执行必须是布尔值", index))
    else:
        stop_valid = (signal.get("证据") or {}).get("止损", {}).get("有效性", True)
        expected = signal.get("确认状态") == "已确认" and stop_valid is not False
        if signal["可执行"] is not expected:
            errors.append(
                _error(
                    "可执行与确认状态/止损有效性不一致"
                    f"（期望 {expected}）",
                    index,
                )
            )
    trail = signal.get("状态轨迹")
    if trail is not None:
        if not isinstance(trail, list) or not trail:
            errors.append(_error("状态轨迹必须是非空数组", index))
        elif any(
            not isinstance(item, dict)
            or item.get("状态") not in VALID_CONFIRMATION_STATES
            for item in trail
        ):
            errors.append(_error("状态轨迹包含非法状态记录", index))
        elif trail[-1].get("状态") != signal.get("确认状态"):
            errors.append(_error("状态轨迹末状态必须等于确认状态", index))
    return errors


def validate_standard_signals(
    signals: Iterable[Any], period: Optional[str] = None
) -> dict:
    """Validate a period's standard-signal list.

    The result is JSON-ready and intentionally independent of signal
    generation, making it suitable for CI, downstream services, and tests.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(signals, list):
        errors.append("标准信号必须是数组")
        return {"有效": False, "错误": errors, "警告": warnings}
    for index, signal in enumerate(signals):
        errors.extend(validate_signal(signal, index))
        if period is not None and isinstance(signal, dict):
            if signal.get("周期") != period:
                errors.append(
                    _error(
                        f"周期不一致（期望 {period!r}，实际 {signal.get('周期')!r}）",
                        index,
                    )
                )
    if not signals:
        warnings.append("当前周期没有标准信号")
    return {"有效": not errors, "错误": errors, "警告": warnings}


__all__ = [
    "VALID_DIRECTIONS",
    "VALID_TYPES",
    "REQUIRED_FIELDS",
    "validate_signal",
    "validate_standard_signals",
]
