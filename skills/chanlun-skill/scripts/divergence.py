"""Rust core divergence checks and auditable evidence matrices."""

try:
    from rust_adapter import 观察者, 笔, 线段, 背驰分析
    from structure import _dir_name, _fmt_ts
except ImportError:  # pragma: no cover - package-style import fallback
    from .rust_adapter import 观察者, 笔, 线段, 背驰分析
    from .structure import _dir_name, _fmt_ts


def _safe_bool(fn):
    """Run a Rust/PyO3 predicate and normalize failures to None."""
    try:
        return bool(fn())
    except BaseException:
        return None


def _kline_position_rows(positions, limit: int = 5) -> list:
    """Compact K-line/Chan K-line positions returned by Rust helpers."""
    rows = []
    for kline in list(positions or [])[:limit]:
        base = getattr(kline, "标的K线", kline)
        rows.append({
            "time": _fmt_ts(getattr(base, "时间戳", getattr(kline, "时间戳", None))),
            "high": getattr(kline, "高", getattr(base, "最高价", None)),
            "low": getattr(kline, "低", getattr(base, "最低价", None)),
            "close": getattr(base, "收盘价", None),
        })
    return rows


def _divergence_evidence_matrix(a, b, obs: 观察者, config) -> dict:
    """Build a detailed divergence evidence matrix for two same-direction lines."""
    macd = {
        mode: _safe_bool(lambda mode=mode: 背驰分析.MACD背驰_OBS(a, b, obs, mode))
        for mode in ("总", "阳", "阴", "合")
    }
    atomic = {
        "MACD": macd.get("总"),
        "斜率": _safe_bool(lambda: 背驰分析.斜率背驰(a, b)),
        "测度": _safe_bool(lambda: 背驰分析.测度背驰(a, b)),
    }
    composite = {
        "全量": _safe_bool(lambda: 背驰分析.全量背驰_OBS(a, b, obs)),
        "任意": _safe_bool(lambda: 背驰分析.任意背驰_OBS(a, b, obs)),
        "任选": _safe_bool(lambda: 背驰分析.任选背驰_OBS(a, b, obs)),
        "配置": _safe_bool(lambda: 背驰分析.配置背驰_OBS(a, b, obs, config)),
    }
    modes = {
        mode: _safe_bool(
            lambda mode=mode: 背驰分析.背驰模式_OBS(a, b, obs, config, mode)
        )
        for mode in ("全量", "任意", "配置", "相对")
    }
    atomic_hits = [name for name, value in atomic.items() if value is True]
    composite_hits = [name for name, value in composite.items() if value is True]
    mode_hits = [name for name, value in modes.items() if value is True]
    independent_count = len(atomic_hits)
    aggregate_count = len(composite_hits) + len(mode_hits)
    if independent_count >= 2:
        strength = "强"
    elif independent_count == 1:
        strength = "中"
    elif aggregate_count:
        strength = "弱"
    else:
        strength = "无"
    return {
        "成立": bool(atomic_hits or composite_hits or mode_hits),
        "强度": strength,
        "证据等级": strength,
        "独立证据数": independent_count,
        "聚合确认数": aggregate_count,
        "成立条件数": independent_count,
        "方法来源": {
            "MACD": "背驰分析.MACD背驰_OBS",
            "斜率": "背驰分析.斜率背驰",
            "测度": "背驰分析.测度背驰",
            "组合": "背驰分析.*_OBS",
            "模式": "背驰分析.背驰模式_OBS",
        },
        "静态判据": ["斜率", "测度"],
        "OBS判据": ["MACD", "全量", "任意", "任选", "配置", "模式"],
        "原子判据": atomic,
        "MACD面积方式": macd,
        "组合判据": composite,
        "模式判据": modes,
        "命中": {"原子": atomic_hits, "组合": composite_hits, "模式": mode_hits},
    }


def _divergences(obs: 观察者, config) -> list:
    """基于 Rust 背驰分析及线段内部判定收集可审计背驰事实。"""
    results = []
    for segment in obs.线段序列:
        try:
            inner = 线段.判断线段内部是否背驰(segment, obs)
        except BaseException:
            inner = None
        if inner:
            try:
                positions = 线段.是否背驰过(segment, obs)
            except BaseException:
                positions = []
            results.append({
                "kind": "线段内部背驰",
                "来源": "rust_core",
                "确认": True,
                "强度": "内部",
                "证据矩阵": {
                    "线段内部背驰": True,
                    "背驰K线数量": len(positions),
                    "背驰位置": _kline_position_rows(positions),
                },
                "index": segment.序号,
                "direction": _dir_name(segment.方向),
                "high": segment.高,
                "low": segment.低,
            })
    for stroke in obs.笔序列:
        try:
            positions = 笔.是否背驰过(stroke, obs)
        except BaseException:
            positions = []
        if positions:
            results.append({
                "kind": "笔内背驰",
                "来源": "rust_core",
                "确认": True,
                "强度": "内部",
                "证据矩阵": {
                    "笔内背驰": True,
                    "背驰K线数量": len(positions),
                    "背驰位置": _kline_position_rows(positions),
                },
                "index": stroke.序号,
                "direction": _dir_name(stroke.方向),
                "high": stroke.高,
                "low": stroke.低,
            })
    segments = obs.线段序列
    for index in range(len(segments) - 1):
        previous, current = segments[index], segments[index + 1]
        if previous.方向 != current.方向:
            continue
        matrix = _divergence_evidence_matrix(previous, current, obs, config)
        if matrix["成立"]:
            kinds = (
                matrix["命中"]["原子"]
                or matrix["命中"]["组合"]
                or matrix["命中"]["模式"]
            )
            results.append({
                "kind": "+".join(kinds),
                "来源": "rust_core",
                "确认": True,
                "强度": matrix["强度"],
                "证据矩阵": matrix,
                "index": current.序号,
                "direction": _dir_name(current.方向),
                "high": current.高,
                "low": current.低,
            })
    return results


__all__ = ["_safe_bool", "_kline_position_rows", "_divergence_evidence_matrix", "_divergences"]
