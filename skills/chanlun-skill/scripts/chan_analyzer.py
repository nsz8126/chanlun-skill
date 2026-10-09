#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论综合分析工具（直接基于 chanlun 核心库）

本脚本是 chanlun-skill 的 CLI 与分析编排入口，通过 rust_adapter 访问 chanlun
核心库；周期规范化和 CSV/eltdx 数据加载由 data_source 模块负责。核心库的 API 面
（__init__.pyi / chan.py）：

    - 周期分析：每个输入周期创建独立观察者；上级周期由数据源或调用方另行提供。
  - 观察者：22 个结构序列（普通K线/缠K/分型/笔/线段/扩展线段/扩展中枢/各级线段组…）。
  - 背驰分析：MACD/斜率/测度/全量/任意/配置/任选 14 个方法，均为 classmethod，
    实例必须作为第一个参数传入（如 线段.判断线段内部是否背驰(段, 观察者)）。
  - 指标：MACD/RSI/KDJ/BOLL 挂载在每根 K 线上（K线.macd / .rsi / .kdj / .指标）。

用法：
    python chan_analyzer.py --source csv --input test_data.csv --symbol 000001 --freq day
    python chan_analyzer.py --source csv --input test_data.csv --symbol 000001 --freq day --json
    python chan_analyzer.py --source eltdx --code sh600519 --freq day

依赖：chanlun==2606.73（核心库）、eltdx==3.2.2（在线数据源，可选）。
"""

from datetime import datetime, timezone, timedelta

from chanlun import 缠论配置

try:
    from rust_adapter import (
        K线, 观察者, 笔, 线段, 中枢, 背驰分析,
        append_raw_kline, create_observer,
    )
    from data_quality import inspect_rows
    from semantic import build_period_summary
    from signal_contract import normalize_signals
    from signal_schema import validate_standard_signals
    from multi_period import _resonance
    from report import render_text
    from analysis_output import (
        _indicator_tail,
        _macd_area,
        _multi_level_detail,
        _segment_detail,
    )
    from divergence import _divergences
    from structure import (
        _dir_name,
        _fmt_ts,
        _formed_valid_hub,
        _hub_base_stroke_ids,
        _hub_completeness,
        _hub_core_completeness,
        _hub_detail,
        _hub_end_ts,
        _hub_status,
        _segment_internal_pen_hub_items,
        _segment_internal_pen_hubs,
        _segment_structure_context,
        _source_hubs,
        _third_line_detail,
        _trend_analysis,
        _trend_type,
        _ts_val,
    )
    from data_source import (
        _ELTDX_ADJUST_CHOICES,
        _ELTDX_DEFAULT_ADJUST,
        _ELTDX_DEFAULT_MAX_PAGES,
        _ELTDX_KLINE_PAGE_SIZE,
        load_csv_data,
        load_csv_periods,
        load_eltdx_data,
        period_to_seconds,
        seconds_to_name,
    )
    from signal_classifier import (
        _classify_signals,
        _first_class_context,
        _first_class_validity,
        _following_strokes,
        _structure_preserved,
    )
except ImportError:  # pragma: no cover - package-style import fallback
    from .rust_adapter import (
        K线, 观察者, 笔, 线段, 中枢, 背驰分析,
        append_raw_kline, create_observer,
    )
    from .data_quality import inspect_rows
    from .semantic import build_period_summary
    from .signal_contract import normalize_signals
    from .signal_schema import validate_standard_signals
    from .multi_period import _resonance
    from .report import render_text
    from .analysis_output import (
        _indicator_tail,
        _macd_area,
        _multi_level_detail,
        _segment_detail,
    )
    from .divergence import _divergences
    from .structure import (
        _dir_name,
        _fmt_ts,
        _formed_valid_hub,
        _hub_base_stroke_ids,
        _hub_completeness,
        _hub_core_completeness,
        _hub_detail,
        _hub_end_ts,
        _hub_status,
        _segment_internal_pen_hub_items,
        _segment_internal_pen_hubs,
        _segment_structure_context,
        _source_hubs,
        _third_line_detail,
        _trend_analysis,
        _trend_type,
        _ts_val,
    )
    from .data_source import (
        _ELTDX_ADJUST_CHOICES,
        _ELTDX_DEFAULT_ADJUST,
        _ELTDX_DEFAULT_MAX_PAGES,
        _ELTDX_KLINE_PAGE_SIZE,
        load_csv_data,
        load_csv_periods,
        load_eltdx_data,
        period_to_seconds,
        seconds_to_name,
    )
    from .signal_classifier import (
        _classify_signals,
        _first_class_context,
        _first_class_validity,
        _following_strokes,
        _structure_preserved,
    )


# ---------------------------------------------------------------------------
# 结构化结果
# ---------------------------------------------------------------------------
def analyze(symbol: str, data_by_period: dict, config: 缠论配置 = None) -> dict:
    """分别对各周期直接投喂并产出结构化结果。

    data_by_period: {周期秒数: [K线行]}。每个周期用各自真实数据独立分析，
    直接对每个周期的独立观察者调用 `增加原始K线`。不同周期数据由调用方分别提供；
    本函数不负责把小周期 K 线聚合成更大周期。
    """
    seconds_list = sorted(data_by_period.keys())
    if not seconds_list:
        raise ValueError("无数据")

    cfg = config if config is not None else 缠论配置.不推送()
    quality_by_period = {
        p: inspect_rows(data_by_period[p], p) for p in seconds_list
    }
    unusable = [
        (p, quality_by_period[p])
        for p in seconds_list
        if not quality_by_period[p]["可用于分析"]
    ]
    if unusable:
        p, quality = unusable[0]
        issue_types = [item.get("类型", "未知") for item in quality.get("问题", [])]
        raise ValueError(
            f"{seconds_to_name(p)} 数据质量不满足分析要求："
            f"{', '.join(issue_types) or '有效K线不足'}"
        )

    # 每个周期使用独立观察者和该周期的输入数据，不进行跨周期 K 线合成。
    observers = {
        period: create_observer(symbol, period, cfg)
        for period in seconds_list
    }

    # 批量历史数据直接增加原始K线，无增量合成器 pending 状态。
    for p in seconds_list:
        obs = observers[p]
        for i, row in enumerate(data_by_period[p]):
            ts = _parse_date(row["date"], i)
            append_raw_kline(obs, symbol, ts, row, i, p)

    primary = min(seconds_list)
    result = {
        "schema_version": "2.0",
        "engine": {
            "name": "chanlun",
            "implementation": "rust-pyo3",
            "python_compat_layer": True,
        },
        "symbol": symbol,
        "freq": seconds_to_name(primary),
        "periods": [seconds_to_name(p) for p in seconds_list],
        "kline_count": len(data_by_period[primary]),
        "periods_detail": {},
    }

    for p in seconds_list:
        obs = observers[p]
        name = seconds_to_name(p)
        latest_line = obs.线段序列[-1] if obs.线段序列 else None
        internal_hub_items = _segment_internal_pen_hub_items(obs)
        internal_hubs = [z for _, z in internal_hub_items]
        latest_hub = internal_hubs[-1] if internal_hubs else None
        trend_info = _trend_analysis(obs)
        local_structure = _segment_structure_context(obs, latest_line)
        detail = {
            "普通K线": len(obs.普通K线序列),
            "缠论K线": len(obs.缠论K线序列),
            "分型": len(obs.分型序列),
            "笔": len(obs.笔序列),
            "笔中枢": len(internal_hubs),
            "笔中枢口径": "线段内部合中枢",
            "原始全局笔中枢": len(getattr(obs, "笔_中枢序列", [])),
            "线段": len(obs.线段序列),
            "中枢": len(obs.中枢序列),
            "扩展线段": len(obs.扩展线段序列),
            "扩展中枢": len(obs.扩展中枢序列),
            "线段_线段": len(obs.线段_线段序列),
            "线段_中枢": len(obs.线段_中枢序列),
            "扩展线段_扩展线段": len(obs.扩展线段序列_扩展线段),
            "扩展中枢_扩展线段": len(obs.扩展中枢序列_扩展线段),
        }
        detail["走势类型"] = trend_info["类型"]
        detail["走势方向"] = trend_info["方向"]
        detail["走势判据"] = trend_info
        detail["全局走势"] = {
            "类型": trend_info["类型"],
            "方向": trend_info["方向"],
            "判据": trend_info,
        }
        detail["当前线段结构"] = local_structure
        detail["当前线段"] = (
            _segment_detail(latest_line) if latest_line else None
        )
        detail["当前中枢"] = (
            _hub_detail(latest_hub)
            if latest_hub else None
        )
        detail["笔序列"] = [
            {"序号": s.序号, "方向": _dir_name(s.方向), "高": s.高, "低": s.低,
             "文": _fmt_ts(s.文.时间戳), "武": _fmt_ts(s.武.时间戳)}
            for s in obs.笔序列[-10:]
        ]
        detail["中枢序列"] = [
            _hub_detail(z)
            for z in obs.中枢序列[-5:]
        ]
        detail["线段内部笔中枢"] = [
            _hub_detail(z, seg)
            for seg, z in internal_hub_items[-10:]
        ]
        # 级别递归序列组（多级别结构，逐层展开计数）
        detail["线段序列组"] = [len(g) for g in obs.线段序列组]
        detail["中枢序列组"] = [len(g) for g in obs.中枢序列组]
        detail["扩展线段序列组"] = [len(g) for g in obs.扩展线段序列组]
        detail["扩展中枢序列组"] = [len(g) for g in obs.扩展中枢序列组]
        detail["混合扩展线段序列组"] = [len(g) for g in obs.混合扩展线段序列组]
        detail["混合扩展中枢序列组"] = [len(g) for g in obs.混合扩展中枢序列组]
        detail["背驰"] = _divergences(obs, cfg)[-10:]
        detail["买卖点"] = _classify_signals(
            obs, trend_info, detail["背驰"]
        )[-10:]
        detail["标准信号"] = normalize_signals(
            detail["买卖点"], name, trend_info
        )
        detail["标准信号校验"] = validate_standard_signals(
            detail["标准信号"], name
        )
        if not detail["标准信号校验"]["有效"]:
            errors = "；".join(detail["标准信号校验"]["错误"])
            raise ValueError(f"{name} 标准信号契约校验失败：{errors}")
        detail["MACD面积"] = _macd_area(obs)
        detail["指标_最近"] = _indicator_tail(obs, 3)
        # 多级别展开（审计 Stage 3-13）
        detail["多级别展开"] = _multi_level_detail(obs)
        detail["数据质量"] = quality_by_period[p]
        detail["语义摘要"] = build_period_summary(
            detail, quality_by_period[p]
        )
        result["periods_detail"][name] = detail

    # 跨周期共振（审计 Stage 3-15）
    result["跨周期共振"] = _resonance(result["periods_detail"])
    return result


def _parse_date(date_str: str, fallback: int) -> int:
    """日期字符串 -> 秒级时间戳。

    关键：核心库（Rust 绑定）把时间戳按 UTC 对齐到周期边界。若用本地时区
    （北京时间）的 00:00 生成时间戳，会被向下对齐到「前一个 UTC 日」，导致
    日期整体偏移 -1 天。因此这里用 UTC 00:00 生成时间戳（等价于本地时间戳 +8h）。
    """
    if isinstance(date_str, datetime):
        parsed = date_str
    else:
        text = str(date_str).strip()
        parsed = None
        for fmt in (
            "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                pass
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


# ---------------------------------------------------------------------------
# CLI compatibility entry point
# ---------------------------------------------------------------------------
def main():
    try:
        from cli import main as run_cli
    except ImportError:  # pragma: no cover - package-style import fallback
        from .cli import main as run_cli
    return run_cli(analyze)


if __name__ == "__main__":
    main()
