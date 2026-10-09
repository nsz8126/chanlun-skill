"""结构序列与指标事实的 JSON 序列化辅助函数。"""

try:
    from rust_adapter import K线, 观察者, 线段
    from structure import _dir_name, _fmt_ts, _hub_detail
except ImportError:  # pragma: no cover - package-style import fallback
    from .rust_adapter import K线, 观察者, 线段
    from .structure import _dir_name, _fmt_ts, _hub_detail


def _segment_detail(segment) -> dict:
    """Serialize a segment plus Rust fine-grained structural evidence."""
    row = {
        "序号": getattr(segment, "序号", None),
        "方向": _dir_name(getattr(segment, "方向", None)),
        "高": getattr(segment, "高", None),
        "低": getattr(segment, "低", None),
        "起点": _fmt_ts(getattr(getattr(segment, "文", None), "时间戳", None)),
        "终点": _fmt_ts(getattr(getattr(segment, "武", None), "时间戳", None)),
    }
    for label, method_name in (
        ("四象", "四象"),
        ("特征分型终结", "特征分型终结"),
        ("特征序列状态", "特征序列状态"),
        ("缺口", "获取缺口"),
    ):
        method = getattr(线段, method_name, None)
        if method is None:
            row[label] = None
            continue
        try:
            value = method(segment)
            if label == "缺口" and value is not None:
                row[label] = str(value)
            elif isinstance(value, tuple):
                row[label] = list(value)
            else:
                row[label] = value
        except BaseException:
            row[label] = None
    return row


def _multi_level_detail(obs: 观察者) -> dict:
    """展开扩展线段、中枢和混合扩展级别序列。"""
    seg_levels = []
    for level_index, group in enumerate(obs.扩展线段序列组):
        seg_levels.append({
            "层级": level_index + 1,
            "数量": len(group),
            "线段": [_segment_detail(segment) for segment in group],
        })
    hub_levels = []
    for level_index, group in enumerate(obs.扩展中枢序列组):
        hub_levels.append({
            "层级": level_index + 1,
            "数量": len(group),
            "中枢": [
                {
                    "序号": hub.序号, "高": hub.高, "低": hub.低,
                    "高高": hub.高高, "低低": hub.低低,
                    "状态": hub.当前状态() if hasattr(hub, "当前状态") else "",
                }
                for hub in group
            ],
        })
    mixed_seg_levels = []
    for level_index, group in enumerate(getattr(obs, "混合扩展线段序列组", [])):
        mixed_seg_levels.append({
            "层级": level_index + 1,
            "数量": len(group),
            "线段": [_segment_detail(segment) for segment in group],
        })
    mixed_hub_levels = []
    for level_index, group in enumerate(getattr(obs, "混合扩展中枢序列组", [])):
        mixed_hub_levels.append({
            "层级": level_index + 1,
            "数量": len(group),
            "中枢": [_hub_detail(hub) for hub in group],
        })
    return {
        "扩展线段层": seg_levels,
        "扩展中枢层": hub_levels,
        "混合扩展线段层": mixed_seg_levels,
        "混合扩展中枢层": mixed_hub_levels,
    }


def _get_container(kline, name):
    """Read indicator child from either a mapping or a binding object."""
    indicators = getattr(kline, "指标", None)
    if indicators is None:
        return None
    if isinstance(indicators, dict):
        return indicators.get(name)
    return getattr(indicators, name, None)


def _indicator_tail(obs: 观察者, n: int = 3) -> list:
    """提取最近 N 根 K 线上的技术指标值。"""
    rows = []
    for kline in obs.普通K线序列[-n:]:
        macd = getattr(kline, "macd", None)
        rsi = getattr(kline, "rsi", None)
        kdj = getattr(kline, "kdj", None)
        boll = _get_container(kline, "boll")
        moving_averages = _get_container(kline, "均线")
        rows.append({
            "time": _fmt_ts(kline.时间戳),
            "close": kline.收盘价,
            "macd_dif": getattr(macd, "DIF", None),
            "macd_dea": getattr(macd, "DEA", None),
            "macd_bar": getattr(macd, "MACD柱", None),
            "rsi": getattr(rsi, "RSI", None),
            "kdj_k": getattr(kdj, "K", None),
            "kdj_d": getattr(kdj, "D", None),
            "kdj_j": getattr(kdj, "J", None),
            "boll_up": getattr(boll, "上轨", None),
            "boll_mid": getattr(boll, "中轨", None),
            "boll_low": getattr(boll, "下轨", None),
            "均线": dict(moving_averages) if isinstance(moving_averages, dict) else None,
        })
    return rows


def _macd_area(obs: 观察者) -> dict:
    """计算全序列 MACD 柱面积统计。"""
    klines = obs.普通K线序列
    if len(klines) < 2:
        return {}
    try:
        return K线.获取MACD(klines, klines[0], klines[-1])
    except BaseException:
        return {}


__all__ = [
    "_segment_detail", "_multi_level_detail", "_get_container",
    "_indicator_tail", "_macd_area",
]
