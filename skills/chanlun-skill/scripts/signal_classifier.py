"""基于 Rust 结构事实分类一、二、三类及 T 系列信号。"""

try:
    from rust_adapter import 观察者
    from structure import (
        _dir_name, _fmt_ts, _formed_valid_hub, _hub_core_completeness,
        _hub_end_ts, _segment_internal_pen_hubs, _source_hubs,
        _trend_analysis, _ts_val,
    )
except ImportError:  # pragma: no cover - package-style import fallback
    from .rust_adapter import 观察者
    from .structure import (
        _dir_name, _fmt_ts, _formed_valid_hub, _hub_core_completeness,
        _hub_end_ts, _segment_internal_pen_hubs, _source_hubs,
        _trend_analysis, _ts_val,
    )


def _first_class_context(
    stroke, obs: 观察者, trend_info: dict, is_buy: bool, has_divergence: bool
) -> tuple[bool, dict]:
    """Validate the structural template for a Chan-theory first-class point."""
    trend_info = trend_info or {}
    trend_type = trend_info.get("类型")
    trend_direction = trend_info.get("方向")
    expected_direction = "下跌" if is_buy else "上涨"
    stroke_ts = _ts_val(stroke.武.时间戳)
    preceding_hubs = [
        hub for hub in _source_hubs(obs, trend_info)
        if _formed_valid_hub(hub) and _hub_end_ts(hub) < stroke_ts
    ]
    hub_count = len(preceding_hubs)
    last_hub_ts = _hub_end_ts(preceding_hubs[-1]) if preceding_hubs else 0
    if trend_type == "趋势" and hub_count >= 2:
        template, structure_gate = "a+A+b+B+c", True
    elif trend_type == "盘整" and hub_count >= 1:
        template, structure_gate = "a+A+b", True
    else:
        template, structure_gate = "未形成一类结构模板", False
    checks = {
        "背驰辅助证据": has_divergence,
        "结构模板": template,
        "结构门槛": structure_gate,
        "前置已形成有效中枢数量": hub_count,
        "前置中枢序号": [
            getattr(hub, "序号", index) for index, hub in enumerate(preceding_hubs)
        ],
        "前置中枢核心完整性": [
            {"序号": getattr(hub, "序号", index),
             "完整性_实": _hub_core_completeness(hub)}
            for index, hub in enumerate(preceding_hubs)
        ],
        "走势类型": trend_type,
        "走势方向": trend_direction,
        "要求走势方向": expected_direction,
        "方向匹配": trend_type == "盘整" or trend_direction == expected_direction,
        "最后中枢后": bool(last_hub_ts and stroke_ts > last_hub_ts),
        "笔端时间": _fmt_ts(stroke.武.时间戳),
        "最后中枢结束时间": _fmt_ts(last_hub_ts) if last_hub_ts else None,
    }
    valid = (
        structure_gate
        and (trend_type == "盘整" or trend_direction == expected_direction)
        and checks["最后中枢后"]
    )
    return valid, checks


def _first_type_ts(obs: 观察者, trend_info: dict = None):
    """Return the first strict first-class point timestamp for T3A/T3B order."""
    trend_info = trend_info or _trend_analysis(obs)
    for stroke in obs.笔序列:
        is_buy = _dir_name(stroke.方向) == "向下"
        is_first, _ = _first_class_context(stroke, obs, trend_info, is_buy, False)
        if is_first:
            return _ts_val(stroke.武.时间戳)
    return None


def _following_strokes(obs: 观察者, stroke) -> list:
    """Return later strokes in core sequence order."""
    index = getattr(stroke, "序号", -1)
    return [item for item in obs.笔序列 if getattr(item, "序号", -1) > index]


def _structure_preserved(
    obs: 观察者, stroke, is_buy: bool, boundary: float, reenter: bool = False
) -> tuple[bool, object]:
    """Check whether a later stroke has broken a structural boundary."""
    for later in _following_strokes(obs, stroke):
        broken = later.低 <= boundary if is_buy and reenter else (
            later.低 < boundary if is_buy else
            later.高 >= boundary if reenter else later.高 > boundary
        )
        if broken:
            return False, later
    return True, None


def _first_class_validity(
    obs: 观察者, stroke, is_buy: bool, checks: dict, has_divergence: bool
) -> tuple[str, str, object]:
    """Evaluate first-class validity from divergence, reversal and structure."""
    boundary = stroke.低 if is_buy else stroke.高
    preserved, breaker = _structure_preserved(obs, stroke, is_buy, boundary)
    if not preserved:
        return "已失效", "后续结构突破一类端点", breaker
    reverse_direction = "向上" if is_buy else "向下"
    reverse_strokes = [
        item for item in _following_strokes(obs, stroke)
        if _dir_name(item.方向) == reverse_direction
    ]
    if not reverse_strokes:
        return "候选", "等待离开段后的反向笔", None
    if has_divergence:
        return "已确认", "反向笔已出现，且离开段背驰", reverse_strokes[0]
    hub_ids = checks.get("前置中枢序号", [])
    hubs = [
        hub for hub in _segment_internal_pen_hubs(obs)
        if getattr(hub, "序号", None) in hub_ids
    ]
    if hubs:
        previous_hub = hubs[-1]
        for reverse in reverse_strokes:
            reenters = (
                reverse.高 >= previous_hub.低 if is_buy
                else reverse.低 <= previous_hub.高
            )
            if reenters:
                return "已确认", "无背驰，反向笔重新进入前中枢（小转大）", reverse
    return "候选", "反向笔已出现但未重新进入前中枢", reverse_strokes[0]


def _classify_signals(
    obs: 观察者, trend_info: dict = None, divergence_results: list = None
) -> list:
    """Classify T-series signals from Rust structure facts; divergence is auxiliary."""
    signals = []
    trend_info = trend_info or _trend_analysis(obs)
    trend = trend_info["类型"]
    first_ts = _first_type_ts(obs, trend_info)
    divergence_by_stroke = {
        (row.get("index"), row.get("direction")): row
        for row in (divergence_results or [])
        if row.get("kind") == "笔内背驰"
    }

    for hub in _segment_internal_pen_hubs(obs):
        line = hub.第三买卖线
        if line is None:
            continue
        is_buy = line.低 >= hub.高
        hub_start_ts = _ts_val(hub.文.时间戳)
        base = "T3B" if first_ts is not None and hub_start_ts < first_ts else "T3A"
        reason = f"中枢#{hub.序号} 第三买卖线（走势={trend}"
        if base == "T3B":
            reason += "，二三类重合"
        reason += "）"
        signal = {
            "kind": base + ("买" if is_buy else "卖"),
            "base": "三买" if is_buy else "三卖",
            "来源": "rust_structure+skill_classifier",
            "结构来源": "rust_core",
            "类型来源": "skill_classifier",
            "确认级别": "候选",
            "核心判据": {
                "第三买卖线": True,
                "中枢序号": hub.序号,
                "中枢位置": "上方" if is_buy else "下方",
                "结构中枢来源": "线段内部笔中枢",
            },
            "index": line.序号,
            "direction": "向上" if is_buy else "向下",
            "high": line.高,
            "low": line.低,
            "结构失效边界": hub.高 if is_buy else hub.低,
            "结构失效条件": "回调重新进入已突破中枢",
            "reason": reason,
            "time": _fmt_ts(line.武.时间戳),
        }
        preserved, breaker = _structure_preserved(
            obs, line, is_buy, signal["结构失效边界"], reenter=True
        )
        signal["结构有效性"] = "已确认" if preserved else "已失效"
        signal["确认级别"] = signal["结构有效性"]
        signal["结构有效性依据"] = (
            "后续未重新进入已突破中枢"
            if preserved else f"后续笔#{getattr(breaker, '序号', '-')}重新进入中枢"
        )
        signals.append(signal)

    buy_stage = sell_stage = 0
    first_seen = {"买": False, "卖": False}
    first_boundary = {"买": None, "卖": None}
    post_hub_structure_seen = {"买": False, "卖": False}
    for stroke in obs.笔序列:
        direction = _dir_name(stroke.方向)
        is_buy = direction == "向下"
        side = "买" if is_buy else "卖"
        divergence = divergence_by_stroke.get((stroke.序号, direction), {})
        has_divergence = bool(divergence)
        structural_first, first_checks = _first_class_context(
            stroke, obs, trend_info, is_buy, has_divergence
        )
        after_last_hub = bool(first_checks.get("最后中枢后"))
        is_first = (
            structural_first
            and not first_seen[side]
            and not post_hub_structure_seen[side]
        )
        if after_last_hub:
            post_hub_structure_seen[side] = True
        if is_first:
            base = "T1" if trend == "趋势" else "T1P"
            base_label = "一买" if is_buy else "一卖"
            if is_buy:
                buy_stage = 0
            else:
                sell_stage = 0
            first_seen[side] = True
        else:
            if not first_seen[side]:
                continue
            boundary = first_boundary[side]
            not_break = (
                boundary is not None
                and (stroke.低 >= boundary if is_buy else stroke.高 <= boundary)
            )
            if not not_break:
                continue
            if is_buy:
                buy_stage += 1
                base = "T2" if buy_stage == 1 else "T2S"
            else:
                sell_stage += 1
                base = "T2" if sell_stage == 1 else "T2S"
            base_label = "二买" if is_buy else "二卖"

        reason = ""
        if is_first:
            template = first_checks.get("结构模板", "一类结构")
            divergence_state = "命中" if has_divergence else "未命中/待确认"
            reason = (
                f"{template}结构一类候选；背驰辅助证据={divergence_state}；"
                "背驰仅作为辅助证据"
            )
        signal = {
            "kind": base + ("买" if is_buy else "卖"),
            "base": base_label,
            "来源": "rust_structure+skill_classifier",
            "结构来源": "rust_core",
            "类型来源": "skill_classifier",
            "确认级别": "候选",
            "核心判据": {
                "结构中枢来源": "线段内部笔中枢",
                "背驰辅助证据": has_divergence,
                "背驰证据": divergence,
                "一类结构": first_checks if is_first else None,
                "二类不破": None if is_first else {
                    "一类端点": first_boundary[side],
                    "当前端点": stroke.低 if is_buy else stroke.高,
                    "不破": True,
                },
            },
            "index": stroke.序号,
            "direction": direction,
            "high": stroke.高,
            "low": stroke.低,
            "结构失效边界": stroke.低 if is_buy else stroke.高,
            "结构失效条件": (
                "后续回调跌破一买端点" if is_buy else "后续反弹突破一卖端点"
            ),
            "reason": reason,
            "time": _fmt_ts(stroke.武.时间戳),
        }
        if is_first:
            validity, validity_reason, _ = _first_class_validity(
                obs, stroke, is_buy, first_checks, has_divergence
            )
        else:
            preserved, breaker = _structure_preserved(
                obs, stroke, is_buy, signal["结构失效边界"]
            )
            validity = "已确认" if preserved else "已失效"
            validity_reason = (
                "后续未破坏二类结构端点"
                if preserved else f"后续笔#{getattr(breaker, '序号', '-')}破坏二类结构端点"
            )
        signal["结构有效性"] = validity
        signal["确认级别"] = validity
        signal["结构有效性依据"] = validity_reason
        signals.append(signal)
        if is_first:
            first_boundary[side] = stroke.低 if is_buy else stroke.高

    signals.sort(key=lambda signal: signal["index"])
    return signals


__all__ = [
    "_first_class_context", "_first_type_ts", "_following_strokes",
    "_structure_preserved", "_first_class_validity", "_classify_signals",
]
