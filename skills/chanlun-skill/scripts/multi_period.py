"""跨周期信号共振。"""

from datetime import datetime, timezone


def _resonance(periods_detail: dict) -> list:
    """跨周期共振：主周期（小周期）的同向买卖点在大周期也有命中。

    输出每个共振事件包含主周期信号时间、方向、同向周期数量及匹配信号。
    同向信号的时间距离必须小于 30 天。
    """
    events = []
    period_names = list(periods_detail.keys())
    if len(period_names) < 2:
        return events

    def timestamp(signal):
        try:
            text = signal.get("time", "")
            return int(datetime.strptime(text, "%Y-%m-%d %H:%M")
                       .replace(tzinfo=timezone.utc).timestamp())
        except (ValueError, TypeError, OSError):
            return 0

    primary = period_names[0]
    primary_signals = []
    for signal in periods_detail[primary].get("买卖点", []):
        ts = timestamp(signal)
        if ts:
            primary_signals.append({**signal, "_ts": ts})

    other_signals = {}
    for period in period_names[1:]:
        other_signals[period] = []
        for signal in periods_detail[period].get("买卖点", []):
            ts = timestamp(signal)
            if ts:
                other_signals[period].append({**signal, "_ts": ts})

    window_seconds = 30 * 86400
    for primary_signal in primary_signals:
        is_buy = "买" in primary_signal["kind"]
        matches = [{
            "period": primary,
            "kind": primary_signal["kind"],
            "time": primary_signal["time"],
            "index": primary_signal["index"],
        }]
        for period, signals in other_signals.items():
            closest = None
            min_distance = window_seconds
            for signal in signals:
                if ("买" in signal["kind"]) != is_buy:
                    continue
                distance = abs(signal["_ts"] - primary_signal["_ts"])
                if distance < min_distance:
                    closest = signal
                    min_distance = distance
            if closest is not None:
                matches.append({
                    "period": period,
                    "kind": closest["kind"],
                    "time": closest["time"],
                    "index": closest["index"],
                    "距离天数": min_distance // 86400,
                })
        if len(matches) >= 2:
            events.append({
                "primary_time": primary_signal["time"],
                "direction": "买" if is_buy else "卖",
                "strength": len(matches),
                "matches": matches,
            })
    return events


__all__ = ["_resonance"]
