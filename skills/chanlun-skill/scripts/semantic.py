"""Convert Rust-derived structure facts into an AI-friendly semantic layer."""

from typing import Optional


def _latest(items):
    return items[-1] if items else None


def _signal(signal: dict, canonical: str, legacy: str, default=None):
    return signal.get(canonical, signal.get(legacy, default))


def _signal_stop(signal: dict) -> dict:
    return signal.get("证据", {}).get("止损") or signal.get("止损") or {}


def build_period_summary(detail: dict, quality: Optional[dict] = None) -> dict:
    """Build facts, interpretations and conditional scenarios.

    This layer does not recalculate Chan theory structures.  It only explains
    the already extracted Rust facts and labels heuristic classifications as
    such, so the model can distinguish evidence from interpretation.
    """

    signals = detail.get("标准信号") or detail.get("买卖点", [])
    divergences = detail.get("背驰", [])
    latest_signal = _latest(signals)
    latest_divergence = _latest(divergences)
    current_line = detail.get("当前线段")
    current_hub = detail.get("当前中枢")
    trend = detail.get("走势类型", "未知")
    trend_direction = detail.get("走势方向", "未知")
    trend_evidence = detail.get("走势判据", {})

    facts = [
        f"走势类型={trend}，方向={trend_direction}",
        f"线段数量={detail.get('线段', 0)}",
        f"中枢数量={detail.get('中枢', 0)}",
    ]
    if current_line:
        facts.append(
            f"当前线段={current_line.get('方向', '未知')} "
            f"[{current_line.get('低')}~{current_line.get('高')}]"
        )
    if current_hub:
        facts.append(
            f"当前中枢=[{current_hub.get('低')}~{current_hub.get('高')}] "
            f"状态={current_hub.get('状态', '未知')}"
        )
    if trend_evidence:
        facts.append(
            f"走势判据来源={trend_evidence.get('判据来源', '未知')}，"
            f"上移={trend_evidence.get('上移次数', 0)}，"
            f"下移={trend_evidence.get('下移次数', 0)}，"
            f"重叠={trend_evidence.get('重叠次数', 0)}"
        )
    if latest_divergence:
        facts.append(
            f"最近背驰={_signal(latest_divergence, '类型', 'kind')} "
            f"方向={_signal(latest_divergence, '方向', 'direction')}"
        )
    if latest_signal:
        facts.append(
            f"最近信号={_signal(latest_signal, '类型', 'kind')} "
            f"时间={_signal(latest_signal, '时间', 'time')}"
        )

    interpretations = []
    if latest_signal:
        signal_type = _signal(latest_signal, "类型", "kind")
        interpretations.append({
            "结论": f"最近出现{signal_type}候选信号",
            "依据": ["Rust结构事实", "Skill买卖点分类"],
            "确定性": "需结合后续K线确认",
        })
    if latest_divergence:
        interpretations.append({
            "结论": f"检测到{latest_divergence.get('kind')}",
            "依据": ["Rust核心背驰检测"],
            "确定性": "已检测",
        })
    if not interpretations:
        interpretations.append({
            "结论": "当前没有可供策略触发的明确买卖点",
            "依据": ["当前结构序列和信号列表为空"],
            "确定性": "当前数据范围内",
        })

    scenarios = []
    if latest_signal:
        signal_type = _signal(latest_signal, "类型", "kind")
        break_value = _signal(latest_signal, "破位值", "break")
        scenarios.append({
            "名称": "主情景",
            "触发": f"价格按{signal_type}方向继续并满足后续确认",
            "动作": "等待确认后再考虑入场或持有",
            "入场条件": f"确认{signal_type}方向，并出现后续K线确认",
            "确认条件": "不以单根K线或未完成结构作为确认",
            "止损": _signal_stop(latest_signal),
            "失效": f"触发价/破位值={break_value}",
            "来源": latest_signal.get(
                "结构来源", latest_signal.get("来源", "rust_core+skill_classifier")
            ),
        })
        scenarios.append({
            "名称": "备选情景",
            "触发": "价格反向突破信号失效位",
            "动作": "取消该信号，重新按当前中枢和线段分析",
            "入场条件": "无",
            "确认条件": "等待新的核心结构信号",
            "止损": None,
            "失效": "不把未确认信号当作确定趋势",
            "来源": "skill_strategy_template",
        })
    else:
        scenarios.append({
            "名称": "观望情景",
            "触发": "等待新的线段完成、背驰确认或买卖点出现",
            "动作": "不基于当前数据强行预测",
            "失效": "出现新的核心结构事实后重新分析",
        })

    return {
        "走势类型": trend,
        "走势方向": trend_direction,
        "走势判据": trend_evidence,
        "当前线段": current_line,
        "当前中枢": current_hub,
        "事实": facts,
        "解释": interpretations,
        "情景": scenarios,
        "数据质量": quality or {},
    }


__all__ = ["build_period_summary"]
