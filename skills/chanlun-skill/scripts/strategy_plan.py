"""No-lookahead, conditional strategy plan built from canonical signals."""


def build_strategy_plan(detail: dict) -> dict:
    """Create a decision plan, never treating a candidate as confirmed."""

    trend = detail.get("走势判据") or {}
    signals = detail.get("标准信号") or []
    latest = signals[-1] if signals else None
    quality = detail.get("数据质量") or {}
    contract = detail.get("标准信号校验") or {}
    if contract and contract.get("有效") is False:
        return {
            "状态": "不可执行",
            "主方向": "未知",
            "最新信号": latest,
            "入场条件": "标准信号契约校验失败，先修复输出结构",
            "确认条件": "重新生成并通过标准信号 schema 校验",
            "仓位建议": "不建立新仓位",
            "止损": None,
            "失效条件": "当前信号契约无效",
            "未来数据使用": False,
        }
    if not quality.get("可用于分析", True):
        return {
            "状态": "不可分析",
            "主方向": "未知",
            "最新信号": None,
            "入场条件": "先修复数据质量问题",
            "确认条件": "数据质量通过后重新分析",
            "仓位建议": "不建立新仓位",
            "止损": None,
            "失效条件": "当前分析结果无效",
            "未来数据使用": False,
        }

    if latest is None:
        return {
            "状态": "观望",
            "主方向": trend.get("方向", "未知"),
            "最新信号": None,
            "入场条件": "等待新的核心结构信号",
            "确认条件": "等待线段完成、背驰或买卖意义成立",
            "仓位建议": "不基于当前数据强行入场",
            "止损": None,
            "失效条件": "出现新的结构事实后重新评估",
            "未来数据使用": False,
        }

    if latest.get("确认状态") == "已失效":
        return {
            "状态": "观望",
            "主方向": trend.get("方向", "未知"),
            "最新信号": latest,
            "入场条件": "等待新的核心结构信号，不使用已失效信号入场",
            "确认条件": "新的候选信号需经过后续K线确认",
            "仓位建议": "不建立新仓位",
            "止损": latest.get("证据", {}).get("止损"),
            "失效条件": "该信号已失效",
            "未来数据使用": False,
        }

    confirmed = latest.get("确认状态") == "已确认"
    return {
        "状态": "条件执行" if confirmed else "等待确认",
        "主方向": latest.get("方向", trend.get("方向", "未知")),
        "最新信号": latest,
        "入场条件": (
            f"确认{latest.get('类型')}并满足后续K线确认"
            if not confirmed else f"按{latest.get('类型')}方向执行"
        ),
        "确认条件": "不使用当前信号之后的数据回填历史结论",
        "仓位建议": "候选信号仅允许观察/试仓；已确认信号再按账户风险预算决定",
        "止损": latest.get("证据", {}).get("止损"),
        "失效条件": f"价格突破破位值 {latest.get('破位值')}",
        "未来数据使用": False,
    }


__all__ = ["build_strategy_plan"]
