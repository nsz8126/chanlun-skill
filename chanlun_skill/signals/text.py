"""文本信号输出。"""

from __future__ import annotations

from datetime import datetime

from chanlun_skill.core.analyzer import ChanlunAnalyzer


def _format_time(ts) -> str:
    """格式化时间戳。"""
    if ts is None:
        return "?"
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    return str(ts)


def format_signals(analyzer: ChanlunAnalyzer) -> str:
    """将分析结果格式化为可读文本（含买卖点和背驰）。"""
    lines = []
    lines.append(f"{'=' * 56}")
    lines.append(f"  {analyzer.symbol} 缠论分析")
    lines.append(f"{'=' * 56}")

    for period_sec, obs in sorted(analyzer.get_observers().items()):
        period_name = analyzer._seconds_to_name(period_sec)
        lines.append("")
        lines.append(f"--- {period_name} ---")
        lines.append(
            f"  K线: {len(obs.普通K线序列)}"
            f" | 缠K: {len(obs.缠论K线序列)}"
            f" | 分型: {len(obs.分型序列)}"
        )

        # === 笔 ===
        strokes = obs.笔序列
        lines.append(f"  笔: {len(strokes)}")
        if strokes:
            for s in strokes[-5:]:
                try:
                    direction = "↑" if str(s.方向).endswith("向上") else "↓"
                    start_t = _format_time(s.文.中.标的K线.时间戳) if s.文 else "?"
                    end_t = _format_time(s.武.中.标的K线.时间戳) if s.武 else "?"
                    start_p = s.文.中.标的K线.收盘价 if s.文 else 0
                    end_p = s.武.中.标的K线.收盘价 if s.武 else 0
                    lines.append(f"    {direction} {start_t}({start_p:.2f}) -> {end_t}({end_p:.2f})")
                except Exception:
                    lines.append(f"    (解析异常)")

        # === 笔中枢 ===
        hubs = obs.笔_中枢序列
        lines.append(f"  笔中枢: {len(hubs)}")
        if hubs:
            for hub in hubs[-3:]:
                try:
                    low = hub.基础序列[0].武.中.标的K线.收盘价 if hub.基础序列 else 0
                    high = hub.基础序列[0].文.中.标的K线.收盘价 if hub.基础序列 else 0
                    lines.append(f"    [{low:.2f} ~ {high:.2f}]")
                except Exception:
                    lines.append(f"    (解析异常)")

        # === 线段 ===
        if hasattr(obs, "线段序列组") and obs.线段序列组:
            for level, segs in enumerate(obs.线段序列组):
                if segs:
                    lines.append(f"  线段(L{level}): {len(segs)}")
                    for seg in segs[-3:]:
                        try:
                            direction = "↑" if str(seg.方向).endswith("向上") else "↓"
                            start_t = _format_time(seg.文.中.标的K线.时间戳) if seg.文 else "?"
                            end_t = _format_time(seg.武.中.标的K线.时间戳) if seg.武 else "?"
                            lines.append(f"    {direction} {start_t} -> {end_t}")
                        except Exception:
                            lines.append(f"    (解析异常)")

        # === 买卖点信号 ===
        try:
            stroke_signals = analyzer.get_stroke_signals(period_sec)
            if stroke_signals:
                lines.append(f"  [买卖点] 笔信号: {len(stroke_signals)}")
                for sig in stroke_signals[-5:]:
                    icon = "B" if sig["type"] == "buy" else "S"
                    t = _format_time(sig["end_time"])
                    p = sig["end_price"]
                    reason = sig["reason"]
                    lines.append(f"    [{icon}] {t} {p:.2f} ({reason})")
        except Exception:
            pass

        # === 线段买卖点 ===
        try:
            seg_signals = analyzer.get_segment_signals(period_sec, level=0)
            if seg_signals:
                lines.append(f"  [线段信号] {len(seg_signals)}")
                for sig in seg_signals[-3:]:
                    icon = "B" if sig["type"] == "buy" else "S"
                    t = _format_time(sig["end_time"])
                    p = sig["end_price"]
                    reason = sig["reason"]
                    lines.append(f"    [{icon}] {t} {p:.2f} ({reason})")
        except Exception:
            pass

        # === 背驰 ===
        try:
            divergences = analyzer.check_divergence(period_sec)
            if divergences:
                lines.append(f"  [背驰] {len(divergences)} 处")
                for div in divergences[-3:]:
                    direction = "↑" if "向上" in div["direction"] else "↓"
                    types = []
                    if div["macd_divergence"]:
                        types.append("MACD")
                    if div["slope_divergence"]:
                        types.append("斜率")
                    if div["measure_divergence"]:
                        types.append("测度")
                    lines.append(f"    {direction} 线段#{div['segment_index']} [{'+'.join(types)}]")
        except Exception:
            pass

    lines.append("")
    lines.append(f"{'=' * 56}")
    return "\n".join(lines)


def format_summary(analyzer: ChanlunAnalyzer) -> str:
    """输出简要摘要。"""
    summary = analyzer.summary()
    lines = [f"{summary['symbol']} 分析摘要:"]
    for period, data in summary["periods"].items():
        buys = data.get("stroke_buys", 0)
        sells = data.get("stroke_sells", 0)
        divs = data.get("divergence_count", 0)
        lines.append(
            f"  {period}: K线={data['kline_count']}"
            f" 分型={data['fractal_count']}"
            f" 笔={data['stroke_count']}"
            f" 中枢={data['hub_count']}"
            f" 买{buys}/卖{sells}"
            f" 背驰={divs}"
        )
    return "\n".join(lines)
