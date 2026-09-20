"""Input validation and provenance checks for Skill analysis."""

from datetime import datetime, timezone
import math
from typing import Optional


def _timestamp(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S",
                    "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def inspect_rows(rows: list, period_seconds: Optional[int] = None) -> dict:
    """Return compact, machine-readable quality metadata.

    The validator is intentionally conservative: market holidays and ordinary
    overnight gaps are reported as metadata, not treated as invalid candles.
    """

    required = ("date", "open", "high", "low", "close", "volume")
    issues = []
    timestamps = []
    invalid_rows = []
    invalid_time_rows = []
    duplicate_count = 0
    out_of_order = 0
    previous = None

    for index, row in enumerate(rows):
        missing = [key for key in required if key not in row or row[key] in (None, "")]
        if missing:
            invalid_rows.append(index)
            issues.append({"类型": "缺失字段", "行": index + 1, "字段": missing})
            continue

        numeric_bad = []
        for key in ("open", "high", "low", "close", "volume"):
            try:
                if not math.isfinite(float(row[key])):
                    numeric_bad.append(key)
            except (TypeError, ValueError):
                numeric_bad.append(key)
        if numeric_bad:
            invalid_rows.append(index)
            issues.append({"类型": "数值非法", "行": index + 1, "字段": numeric_bad})
        else:
            o, h, l, c = (float(row[key]) for key in ("open", "high", "low", "close"))
            if h < l or o > h or o < l or c > h or c < l:
                invalid_rows.append(index)
                issues.append({
                    "类型": "OHLC区间非法",
                    "行": index + 1,
                    "值": {"open": o, "high": h, "low": l, "close": c},
                })

        ts = _timestamp(row.get("date"))
        timestamps.append(ts)
        if ts is None:
            invalid_time_rows.append(index)
            issues.append({"类型": "时间无法解析", "行": index + 1,
                           "值": str(row.get("date"))})
        elif previous is not None:
            if ts == previous:
                duplicate_count += 1
            elif ts < previous:
                out_of_order += 1
        if ts is not None:
            previous = ts

    valid_timestamps = [ts for ts in timestamps if ts is not None]
    if duplicate_count:
        issues.append({"类型": "重复时间", "数量": duplicate_count})
    if out_of_order:
        issues.append({"类型": "时间乱序", "数量": out_of_order})

    gaps = []
    if period_seconds and len(valid_timestamps) > 1:
        for left, right in zip(valid_timestamps, valid_timestamps[1:]):
            delta = right - left
            if delta > period_seconds * 3:
                gaps.append(round(delta / period_seconds, 2))
    if gaps:
        issues.append({"类型": "时间间隔较大", "数量": len(gaps),
                       "最大周期倍数": max(gaps)})

    return {
        "K线数量": len(rows),
        "有效行": len(rows) - len(set(invalid_rows)),
        "时间可解析": len(valid_timestamps),
        "重复时间": duplicate_count,
        "乱序数量": out_of_order,
        "大间隔数量": len(gaps),
        "首个时间": min(valid_timestamps) if valid_timestamps else None,
        "末个时间": max(valid_timestamps) if valid_timestamps else None,
        "可用于分析": (
            len(rows) >= 2
            and not invalid_rows
            and not invalid_time_rows
            and not duplicate_count
            and not out_of_order
        ),
        "问题": issues,
    }


__all__ = ["inspect_rows"]
