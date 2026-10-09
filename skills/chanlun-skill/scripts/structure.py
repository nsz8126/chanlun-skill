"""缠论结构上下文、走势判定与中枢序列化辅助函数。"""

from datetime import datetime, timedelta, timezone

try:
    from rust_adapter import 观察者
except ImportError:  # pragma: no cover - package-style import fallback
    from .rust_adapter import 观察者


_CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def _fmt_ts(ts) -> str:
    """时间戳 -> 中国标准时间（Asia/Shanghai）可读日期。"""
    if ts is None:
        return "-"
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=_CHINA_TZ).strftime("%Y-%m-%d %H:%M")
        return datetime.fromtimestamp(int(ts), tz=_CHINA_TZ).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return str(ts)


def _dir_name(d) -> str:
    """相对方向对象 -> 简洁中文（向上/向下/缺口/衔接/包含）。"""
    for attr in ("是否向上", "是否向下", "是否缺口", "是否衔接", "是否包含"):
        method = getattr(d, attr, None)
        if callable(method):
            try:
                if method():
                    return {
                        "是否向上": "向上", "是否向下": "向下", "是否缺口": "缺口",
                        "是否衔接": "衔接", "是否包含": "包含",
                    }[attr]
            except BaseException:
                pass
    text = str(d)
    for keyword in ("向上", "向下", "缺口", "衔接", "包含", "顺", "逆", "同"):
        if keyword in text:
            return keyword
    return text


def _ts_val(ts) -> int:
    """时间戳统一为可比较的秒级数值。"""
    if ts is None:
        return 0
    try:
        if isinstance(ts, (int, float)):
            return int(ts)
        return int(ts.timestamp())
    except (ValueError, OSError, OverflowError, AttributeError):
        return 0


def _segment_internal_pen_hub_items(obs: 观察者) -> list[tuple[object, object]]:
    """Return ``(segment, hub)`` pairs for segment-internal pen hubs only."""
    items = []
    seen = set()
    for segment_index, segment in enumerate(getattr(obs, "线段序列", [])):
        for hub_index, hub in enumerate(getattr(segment, "合_中枢序列", [])):
            key = (
                getattr(segment, "序号", segment_index),
                getattr(hub, "序号", hub_index),
                _ts_val(getattr(getattr(hub, "文", None), "时间戳", None)),
                _ts_val(getattr(getattr(hub, "武", None), "时间戳", None)),
                getattr(hub, "高", None),
                getattr(hub, "低", None),
            )
            if key not in seen:
                seen.add(key)
                items.append((segment, hub))
    return items


def _segment_internal_pen_hubs(obs: 观察者) -> list:
    """Return only segment-internal combined pen hubs, in segment/time order."""
    return [hub for _, hub in _segment_internal_pen_hub_items(obs)]


def _segment_structure_context(obs: 观察者, segment) -> dict:
    """Describe the latest segment's local hub movement separately from global trend."""
    hubs = list(getattr(segment, "合_中枢序列", []) or []) if segment else []
    relations = []
    for index in range(max(0, len(hubs) - 1)):
        previous, current = hubs[index], hubs[index + 1]
        if current.低 > previous.高:
            relation = "上移"
        elif current.高 < previous.低:
            relation = "下移"
        else:
            relation = "接触/重叠"
        relations.append({
            "前中枢": getattr(previous, "序号", index),
            "后中枢": getattr(current, "序号", index + 1),
            "关系": relation,
            "前区间": {"ZD": previous.低, "ZG": previous.高},
            "后区间": {"ZD": current.低, "ZG": current.高},
        })
    return {
        "线段方向": _dir_name(getattr(segment, "方向", None)) if segment else None,
        "中枢数量": len(hubs),
        "相邻中枢关系": relations,
        "局部方向": relations[-1]["关系"] if relations else "中枢关系不足",
    }


def _trend_analysis(obs: 观察者) -> dict:
    """Analyze trend type using segment-internal pen hubs."""
    source = "线段内部笔中枢"
    hubs = _segment_internal_pen_hubs(obs)
    transitions = []
    up = down = overlap = 0
    for index in range(max(0, len(hubs) - 1)):
        previous, current = hubs[index], hubs[index + 1]
        if current.低 > previous.高:
            relation = "上移"
            up += 1
        elif current.高 < previous.低:
            relation = "下移"
            down += 1
        else:
            relation = "重叠/扩展"
            overlap += 1
        transitions.append({
            "前中枢": getattr(previous, "序号", index),
            "后中枢": getattr(current, "序号", index + 1),
            "关系": relation,
        })
    if up and not down and not overlap:
        kind, direction = "趋势", "上涨"
    elif down and not up and not overlap:
        kind, direction = "趋势", "下跌"
    else:
        kind, direction = "盘整", "震荡/未定"
    return {
        "类型": kind,
        "方向": direction,
        "判据来源": source,
        "中枢数量": len(hubs),
        "上移次数": up,
        "下移次数": down,
        "重叠次数": overlap,
        "相邻关系": transitions,
    }


def _trend_type(obs: 观察者) -> str:
    """Backward-compatible trend label."""
    return _trend_analysis(obs)["类型"]


def _hub_end_ts(hub) -> int:
    """Return the latest available timestamp for a hub boundary."""
    return max(
        _ts_val(getattr(getattr(hub, "文", None), "时间戳", None)),
        _ts_val(getattr(getattr(hub, "武", None), "时间戳", None)),
    )


def _source_hubs(obs: 观察者, trend_info: dict) -> list:
    source = (trend_info or {}).get("判据来源", "线段内部笔中枢")
    if source in ("线段内部笔中枢", "笔中枢"):
        return _segment_internal_pen_hubs(obs)
    return []


def _hub_core_completeness(hub):
    """Return Rust's special real-completeness evidence when available."""
    method = getattr(hub, "完整性", None)
    if not callable(method):
        return None
    try:
        return bool(method("实"))
    except BaseException:
        return None


def _formed_valid_hub(hub) -> bool:
    """Whether a hub is formed and still valid for an A/B structure."""
    base = getattr(hub, "基础序列", None)
    if base is not None:
        try:
            if len(base) < 3:
                return False
        except BaseException:
            return False
    validity = getattr(hub, "有效性", None)
    if validity is not None:
        try:
            value = validity() if callable(validity) else validity
        except BaseException:
            return False
        if value is False or (value is not None and not bool(value)):
            return False
    return True


def _hub_status(hub) -> str:
    try:
        return hub.当前状态() if hasattr(hub, "当前状态") else ""
    except BaseException:
        return ""


def _hub_completeness(hub) -> dict:
    """Expose Rust hub completeness separately for real/virtual/combined views."""
    method = getattr(hub, "完整性", None)
    if not callable(method):
        return {mode: None for mode in ("实", "虚", "合")}
    result = {}
    for mode in ("实", "虚", "合"):
        try:
            result[mode] = bool(method(mode))
        except BaseException:
            result[mode] = None
    return result


def _hub_base_stroke_ids(hub) -> list:
    base = getattr(hub, "基础序列", None)
    if base is None:
        return []
    try:
        return [getattr(item, "序号", None) for item in list(base)]
    except BaseException:
        return []


def _third_line_detail(hub):
    line = getattr(hub, "第三买卖线", None)
    if line is None:
        return None
    try:
        return {
            "序号": getattr(line, "序号", None),
            "方向": _dir_name(getattr(line, "方向", None)),
            "高": getattr(line, "高", None),
            "低": getattr(line, "低", None),
            "文": _fmt_ts(getattr(getattr(line, "文", None), "时间戳", None)),
            "武": _fmt_ts(getattr(getattr(line, "武", None), "时间戳", None)),
        }
    except BaseException:
        return {"可用": True}


def _hub_detail(hub, segment=None) -> dict:
    row = {
        "序号": getattr(hub, "序号", None),
        "高": getattr(hub, "高", None),
        "低": getattr(hub, "低", None),
        "高高": getattr(hub, "高高", None),
        "低低": getattr(hub, "低低", None),
        "状态": _hub_status(hub),
        "已形成有效": _formed_valid_hub(hub),
        "核心完整性_实": _hub_core_completeness(hub),
        "完整性": _hub_completeness(hub),
    }
    if segment is not None:
        row["所属线段"] = getattr(segment, "序号", None)
        row["所属线段方向"] = _dir_name(getattr(segment, "方向", None))
    base_ids = _hub_base_stroke_ids(hub)
    if base_ids:
        row["基础笔序号"] = base_ids
    third = _third_line_detail(hub)
    if third is not None:
        row["第三买卖线"] = third
    return row


__all__ = [
    "_fmt_ts", "_dir_name", "_ts_val", "_segment_internal_pen_hub_items",
    "_segment_internal_pen_hubs", "_segment_structure_context", "_trend_analysis",
    "_trend_type", "_hub_end_ts", "_source_hubs", "_hub_core_completeness",
    "_formed_valid_hub", "_hub_status", "_hub_completeness", "_hub_base_stroke_ids",
    "_third_line_detail", "_hub_detail",
]
