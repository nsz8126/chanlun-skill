#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论综合分析工具（直接基于 chanlun 核心库）

本脚本是 chanlun-skill 的唯一分析入口，直接调用 chanlun 核心库的完整能力，
不再依赖任何中间封装包。核心库的 API 面（__init__.pyi / chan.py）：

  - 立体分析器：多周期合成。声明周期组（长度 ≥2），只投喂最小周期的 K 线，
    引擎自动合成更大周期。单周期会触发 Rust 侧 PanicException（继承 BaseException，
    普通 except Exception 抓不到）。
  - 观察者：22 个结构序列（普通K线/缠K/分型/笔/线段/扩展线段/扩展中枢/各级线段组…）。
  - 买卖点类型：18 种（一/二/三买卖 + T1/T1P/T2/T2S/T3A/T3B 买卖），
    附 `是买点` / `是卖点` 布尔属性。
  - 虚线.买卖意义(线, 观察者) -> (bool, str)：仅返回「此处是否具备买卖意义」与理由，
    不返回方向、不返回类型。方向由分型结构（顶/底）或 K 线 MACD 柱正负判定。
  - 背驰分析：MACD/斜率/测度/全量/任意/配置/任选 14 个方法，均为 classmethod，
    实例必须作为第一个参数传入（如 线段.判断线段内部是否背驰(段, 观察者)）。
  - 指标：MACD/RSI/KDJ/BOLL 挂载在每根 K 线上（K线.macd / .rsi / .kdj / .指标）。

用法：
    python chan_analyzer.py --source csv --input test_data.csv --symbol 000001 --freq day
    python chan_analyzer.py --source csv --input test_data.csv --symbol 000001 --freq day --json
    python chan_analyzer.py --source eltdx --code sh600519 --freq day

依赖：chanlun==2606.73（核心库）、eltdx==3.2.2（在线数据源，可选）。
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta

from chanlun import 缠论配置

try:
    from rust_adapter import (
        K线, 立体分析器, 观察者, 虚线, 笔, 线段, 中枢, 背驰分析, 买卖点,
        append_raw_kline, get_observer,
    )
    from data_quality import inspect_rows
    from semantic import build_period_summary
    from signal_contract import normalize_signals
    from signal_schema import validate_standard_signals
    from strategy_plan import build_strategy_plan
except ImportError:  # pragma: no cover - package-style import fallback
    from .rust_adapter import (
        K线, 立体分析器, 观察者, 虚线, 笔, 线段, 中枢, 背驰分析, 买卖点,
        append_raw_kline, get_observer,
    )
    from .data_quality import inspect_rows
    from .semantic import build_period_summary
    from .signal_contract import normalize_signals
    from .signal_schema import validate_standard_signals
    from .strategy_plan import build_strategy_plan

# ---------------------------------------------------------------------------
# 周期映射：中文/英文名 -> 秒
# ---------------------------------------------------------------------------
_PERIOD_SECONDS = {
    "1m": 60, "1分钟": 60, "60s": 60,
    "5m": 300, "5分钟": 300,
    "15m": 900, "15分钟": 900,
    "30m": 1800, "30分钟": 1800,
    "60m": 3600, "60分钟": 3600, "1h": 3600,
    "day": 86400, "日线": 86400, "日": 86400,
    "week": 604800, "周线": 604800, "周": 604800,
    "month": 2592000, "月线": 2592000, "月": 2592000,
}
# 由小到大排列，用于自动补上级周期
_PERIOD_ORDER = [60, 300, 900, 1800, 3600, 86400, 604800, 2592000]

_SECONDS_NAME = {
    60: "1m", 300: "5m", 900: "15m", 1800: "30m",
    3600: "60m", 86400: "day", 604800: "week", 2592000: "month",
}


def period_to_seconds(freq: str) -> int:
    """周期名 -> 秒，支持中文与英文别名。"""
    key = str(freq).strip().lower()
    if key in _PERIOD_SECONDS:
        return _PERIOD_SECONDS[key]
    # 兼容 "N分钟"/"Nm"/"Nmin" 数字前缀
    if key.endswith(("分钟", "m", "min")):
        digits = "".join(ch for ch in key if ch.isdigit())
        if digits:
            return int(digits) * 60
    raise ValueError(f"不支持的周期: {freq!r}，可选：1m/5m/15m/30m/60m/day/week/month 或中文（1分钟/日线/周线/月线）")


def seconds_to_name(seconds: int) -> str:
    return _SECONDS_NAME.get(seconds, f"{seconds}s")


def upper_period(seconds: int) -> int:
    """返回严格大于当前周期的最小标准周期，用于补足周期组（单周期会 panic）。"""
    for p in _PERIOD_ORDER:
        if p > seconds:
            return p
    return seconds  # 已是最大周期则回退


def lower_period(seconds: int) -> int:
    """返回严格小于当前周期的最大标准周期。

    当目标周期已是最大周期（month）时，无法向上补足，需向下补一个「占位周期」
    使周期组长度 ≥2 以满足 `立体分析器` 的硬约束；此时该占位周期不会被投喂数据。
    """
    prev = None
    for p in _PERIOD_ORDER:
        if p >= seconds:
            break
        prev = p
    return prev


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_csv_data(file_path: str) -> list:
    data = []
    try:
        f = open(file_path, "r", encoding="utf-8-sig")
    except FileNotFoundError:
        raise SystemExit(f"错误：找不到文件 {file_path!r}")
    except OSError as e:
        raise SystemExit(f"错误：无法读取文件 {file_path!r}：{e}")

    required = {"date", "open", "high", "low", "close", "volume"}
    with f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SystemExit(f"错误：{file_path!r} 无表头")
        missing = required - set(reader.fieldnames)
        if missing:
            raise SystemExit(
                f"错误：{file_path!r} 缺少必需列 {sorted(missing)}，"
                f"需要 {sorted(required)}")
        for i, row in enumerate(reader, start=2):
            try:
                data.append({
                    "date": row["date"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                })
            except (KeyError, ValueError, TypeError) as e:
                raise SystemExit(
                    f"错误：{file_path!r} 第 {i} 行数据非法（{e}）：{row!r}")
    return data


def load_csv_periods(spec: str) -> dict:
    """Load multiple CSV files from ``period=path,period=path`` syntax."""

    if not spec:
        return {}
    result = {}
    for item in spec.split(","):
        item = item.strip()
        if not item or "=" not in item:
            raise SystemExit(
                "错误：--input_periods 格式应为 day=day.csv,week=week.csv"
            )
        freq, path = item.split("=", 1)
        seconds = period_to_seconds(freq.strip())
        if seconds in result:
            raise SystemExit(f"错误：--input_periods 重复声明周期 {freq!r}")
        if not path.strip():
            raise SystemExit(f"错误：周期 {freq!r} 未提供 CSV 路径")
        result[seconds] = load_csv_data(path.strip())
    return result


_ELTDX_KLINE_PAGE_SIZE = 800
_ELTDX_DEFAULT_MAX_PAGES = 200
_ELTDX_ADJUST_CHOICES = ("none", "qfq", "hfq", "fixed_qfq", "fixed_hfq")
_ELTDX_DEFAULT_ADJUST = "qfq"


def _normalize_eltdx_adjust(adjust: str = None) -> str:
    """规范化 eltdx 复权模式；默认前复权。"""

    mode = _ELTDX_DEFAULT_ADJUST if adjust in (None, "") else str(adjust).strip().lower()
    if mode not in _ELTDX_ADJUST_CHOICES:
        raise SystemExit(
            "错误：--adjust 只支持 none/qfq/hfq/fixed_qfq/fixed_hfq"
        )
    return mode


def load_eltdx_data(
    code: str,
    freq: str,
    start_date: str = None,
    end_date: str = None,
    count: int = 800,
    page_size: int = _ELTDX_KLINE_PAGE_SIZE,
    max_pages: int = _ELTDX_DEFAULT_MAX_PAGES,
    adjust: str = _ELTDX_DEFAULT_ADJUST,
    anchor_date: str = None,
) -> list:
    """从 eltdx 分页获取 K 线并合并为一条有序序列。

    通达信 7709 的单页 K 线请求最多 800 根。``count`` 表示本次分析最多
    请求的原始 K 线总数，超过 800 时按 ``start`` 游标分页；分页结果随后
    去重、按时间升序排列，再执行日期范围裁剪。所有页面在进入 Rust 核心
    前会合并，避免在页面边界切断笔、线段或中枢。

    ``adjust`` 默认 ``qfq``（前复权），用于保持历史走势连续；需要与真实
    未复权价格对齐时可显式传 ``none``。``page_size`` 用于调试或降低单页
    负载，必须在 1~800 之间；``max_pages`` 是防止服务端游标异常导致无限
    请求的保护阈值。
    """
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise SystemExit("错误：--count 必须是大于 0 的整数")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= _ELTDX_KLINE_PAGE_SIZE
    ):
        raise SystemExit(
            f"错误：--page-size 必须是 1~{_ELTDX_KLINE_PAGE_SIZE} 的整数"
        )
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages <= 0:
        raise SystemExit("错误：--max-pages 必须是大于 0 的整数")
    adjust_mode = _normalize_eltdx_adjust(adjust)
    if adjust_mode.startswith("fixed_") and not anchor_date:
        raise SystemExit("错误：fixed_qfq/fixed_hfq 需要同时提供 --anchor-date")

    try:
        from eltdx import TdxClient
    except ImportError:
        raise SystemExit("错误：需要安装 eltdx 库：pip install eltdx==3.2.2")

    period_map = {
        60: "1m", 300: "5m", 900: "15m", 1800: "30m",
        3600: "60m", 86400: "day", 604800: "week", 2592000: "month",
    }
    seconds = period_to_seconds(freq)
    period = period_map.get(seconds, "day")

    # 以时间字符串为键去重。服务端偶发重叠页时，保留最后一次返回的记录，
    # 最终仍按时间升序喂给 Rust；这比按页直接拼接更安全。
    rows_by_time = {}
    requested = 0
    pages = 0
    try:
        with TdxClient(timeout=15) as client:
            while requested < count:
                if pages >= max_pages:
                    raise RuntimeError(
                        f"分页超过 --max-pages={max_pages}，已获取 {requested} 根"
                    )
                batch_count = min(page_size, count - requested)
                # 7709 单页上限为 800；显式传 start/count，兼容不支持
                # all_pages 的旧客户端，同时让每个分页请求可审计。
                series = client.bars.get(
                    code,
                    period=period,
                    start=requested,
                    count=batch_count,
                    adjust=adjust_mode,
                    anchor_date=anchor_date,
                )
                page_bars = list(getattr(series, "bars", ()) or ())
                if not page_bars:
                    break

                pages += 1
                before = len(rows_by_time)
                for bar in page_bars:
                    timestamp = getattr(bar, "time", None)
                    if timestamp is None:
                        continue
                    date_text = timestamp.isoformat(sep=" ")
                    rows_by_time[date_text] = {
                        # 保留分钟级原始时间，Rust 核心内部仍会按周期边界对齐。
                        "date": date_text,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume_lots,
                    }

                # 正常情况下每页都应推进游标。若服务端重复返回同一页，
                # 继续请求只会形成死循环，直接报出可定位错误。
                requested += len(page_bars)
                if len(rows_by_time) == before:
                    raise RuntimeError("分页未返回新的时间序列，已停止以避免死循环")
                # 与 eltdx 的 all_pages 语义保持一致：短页不代表历史结束，
                # 只有空页才结束；这样可兼容服务端临时返回短页的情况。
    except Exception as e:
        raise SystemExit(f"错误：从 eltdx 获取数据失败：{e}")

    data = [
        rows_by_time[key]
        for key in sorted(rows_by_time)
    ]

    # 按日期范围裁剪。CLI 允许只传 YYYY-MM-DD；结束日期应包含该交易日
    # 的全部分钟/日线记录，不能直接与带时分的 ISO 字符串比较。
    start_bound = str(start_date).strip() if start_date else None
    end_bound = str(end_date).strip() if end_date else None
    if end_bound and len(end_bound) == 10 and end_bound[4] == "-" and end_bound[7] == "-":
        end_bound = end_bound + " 23:59:59.999999"
    if start_date:
        data = [d for d in data if d["date"] >= start_bound]
    if end_date:
        data = [d for d in data if d["date"] <= end_bound]
    return data


# ---------------------------------------------------------------------------
# 取数：全部走核心库原生字段，不做二次推断
# ---------------------------------------------------------------------------
_CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def _fmt_ts(ts) -> str:
    """时间戳 -> 中国标准时间（Asia/Shanghai）可读日期。

    Rust 核心内部使用 Unix 秒级时间戳；交易数据和用户报告均采用北京时间。
    这里统一按北京时间展示，避免把 11:05/14:15 等交易时段错误显示为 UTC 的
    03:05/06:15。内部时间戳仍保持原值，不影响排序、周期计算或共振匹配。
    """
    if ts is None:
        return "-"
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=_CHINA_TZ).strftime("%Y-%m-%d %H:%M")
        return datetime.fromtimestamp(int(ts), tz=_CHINA_TZ).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return str(ts)


def _dir_name(d) -> str:
    """相对方向对象 -> 简洁中文（向上/向下/缺口/衔接/包含）。

    运行时该对象是 Rust 绑定类型（chanlun._chanlun.相对方向），
    其 name/value 均为 None，str() 返回形如 "相对方向.向下"。
    因此这里优先调用布尔方法（返回 builtin method 对象时再退回字符串解析）。
    """
    # 优先尝试布尔方法（部分版本返回 method 对象，需调用）
    for attr in ("是否向上", "是否向下", "是否缺口", "是否衔接", "是否包含"):
        m = getattr(d, attr, None)
        if callable(m):
            try:
                if m():
                    return {"是否向上": "向上", "是否向下": "向下",
                            "是否缺口": "缺口", "是否衔接": "衔接", "是否包含": "包含"}[attr]
            except BaseException:
                pass
    s = str(d)
    for kw in ("向上", "向下", "缺口", "衔接", "包含", "顺", "逆", "同"):
        if kw in s:
            return kw
    return s


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
    """Return ``(segment, hub)`` pairs for segment-internal pen hubs only.

    Rust exposes two different pen-hub views:
    - ``obs.笔_中枢序列``: a raw global pen-hub sequence across all pens;
    - ``seg.合_中枢序列``: pen hubs calculated inside each segment.

    The skill uses the second view for trend context and buy/sell-point
    classification.  The global sequence is intentionally excluded from this
    helper so it cannot silently participate in signal judgment.
    """

    items = []
    seen = set()
    for seg_i, seg in enumerate(getattr(obs, "线段序列", [])):
        for z_i, z in enumerate(getattr(seg, "合_中枢序列", [])):
            key = (
                getattr(seg, "序号", seg_i),
                getattr(z, "序号", z_i),
                _ts_val(getattr(getattr(z, "文", None), "时间戳", None)),
                _ts_val(getattr(getattr(z, "武", None), "时间戳", None)),
                getattr(z, "高", None),
                getattr(z, "低", None),
            )
            if key in seen:
                continue
            seen.add(key)
            items.append((seg, z))
    return items


def _segment_internal_pen_hubs(obs: 观察者) -> list:
    """Return only segment-internal combined pen hubs, in segment/time order."""

    return [z for _, z in _segment_internal_pen_hub_items(obs)]


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
        "局部方向": (
            relations[-1]["关系"] if relations else "中枢关系不足"
        ),
    }


def _trend_analysis(obs: 观察者) -> dict:
    """Analyze trend type using segment-internal pen hubs.

    The binding does not expose a single canonical ``走势类型`` property.  For
    buy/sell-point semantics this skill deliberately uses only pen hubs inside
    segments (``seg.合_中枢序列``).  The raw global ``obs.笔_中枢序列`` is not a
    signal source.
    """

    source = "线段内部笔中枢"
    hubs = _segment_internal_pen_hubs(obs)
    transitions = []
    up = down = overlap = 0
    for i in range(max(0, len(hubs) - 1)):
        z0, z1 = hubs[i], hubs[i + 1]
        if z1.低 > z0.高:
            relation = "上移"
            up += 1
        elif z1.高 < z0.低:
            relation = "下移"
            down += 1
        else:
            relation = "重叠/扩展"
            overlap += 1
        transitions.append({
            "前中枢": getattr(z0, "序号", i),
            "后中枢": getattr(z1, "序号", i + 1),
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


def _hub_end_ts(z) -> int:
    """Return the latest available timestamp for a hub boundary."""

    return max(
        _ts_val(getattr(getattr(z, "文", None), "时间戳", None)),
        _ts_val(getattr(getattr(z, "武", None), "时间戳", None)),
    )


def _source_hubs(obs: 观察者, trend_info: dict) -> list:
    source = (trend_info or {}).get("判据来源", "线段内部笔中枢")
    if source in ("线段内部笔中枢", "笔中枢"):
        return _segment_internal_pen_hubs(obs)
    return []


def _hub_core_completeness(z):
    """Return Rust's special ``完整性("实")`` evidence when available.

    ``中枢.完整性("实")`` is not the same as "has a valid three-element
    overlap".  For a 笔中枢 it normally means that a third buy/sell line has
    appeared; for a 线段中枢 it checks an internal departure.  It is useful
    evidence for interpretation, but it is deliberately *not* the A/B
    formation gate.
    """

    method = getattr(z, "完整性", None)
    if not callable(method):
        return None
    try:
        return bool(method("实"))
    except BaseException:
        return None


def _formed_valid_hub(z) -> bool:
    """Whether a hub is formed and still valid for an A/B structure.

    The core puts invalidated hubs out of its public hub sequences.  The
    explicit checks below make that contract auditable and also protect the
    classifier when a compatible binding exposes a partially built object.
    Importantly, ``完整性("实")`` is *not* checked here: a formed but
    incomplete hub is still a legitimate A/B in ``a+A+b`` or
    ``a+A+b+B+c``.
    """

    base = getattr(z, "基础序列", None)
    if base is not None:
        try:
            if len(base) < 3:
                return False
        except BaseException:
            return False

    # Some compatible bindings may expose an explicit validity flag.  Treat
    # an explicit False as invalid; absence of the flag means the object is
    # already filtered by the core hub sequence.
    validity = getattr(z, "有效性", None)
    if validity is not None:
        try:
            value = validity() if callable(validity) else validity
        except BaseException:
            return False
        if value is False:
            return False
        if value is not None and not bool(value):
            return False
    return True


def _hub_status(z) -> str:
    try:
        return z.当前状态() if hasattr(z, "当前状态") else ""
    except BaseException:
        return ""


def _hub_completeness(z) -> dict:
    """Expose Rust hub completeness separately for real/virtual/combined views."""

    method = getattr(z, "完整性", None)
    if not callable(method):
        return {mode: None for mode in ("实", "虚", "合")}
    result = {}
    for mode in ("实", "虚", "合"):
        try:
            result[mode] = bool(method(mode))
        except BaseException:
            result[mode] = None
    return result


def _hub_base_stroke_ids(z) -> list:
    base = getattr(z, "基础序列", None)
    if base is None:
        return []
    ids = []
    try:
        iterator = list(base)
    except BaseException:
        return ids
    for item in iterator:
        ids.append(getattr(item, "序号", None))
    return ids


def _third_line_detail(z):
    line = getattr(z, "第三买卖线", None)
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


def _hub_detail(z, seg=None) -> dict:
    row = {
        "序号": getattr(z, "序号", None),
        "高": getattr(z, "高", None),
        "低": getattr(z, "低", None),
        "高高": getattr(z, "高高", None),
        "低低": getattr(z, "低低", None),
        "状态": _hub_status(z),
        "已形成有效": _formed_valid_hub(z),
        "核心完整性_实": _hub_core_completeness(z),
        "完整性": _hub_completeness(z),
    }
    if seg is not None:
        row["所属线段"] = getattr(seg, "序号", None)
        row["所属线段方向"] = _dir_name(getattr(seg, "方向", None))
    base_ids = _hub_base_stroke_ids(z)
    if base_ids:
        row["基础笔序号"] = base_ids
    third = _third_line_detail(z)
    if third is not None:
        row["第三买卖线"] = third
    return row


def _first_class_context(
    stroke, obs: 观察者, trend_info: dict, is_buy: bool, has_divergence: bool
) -> tuple[bool, dict]:
    """Validate the structural template for a Chan-theory first-class point.

    A divergence result is only auxiliary evidence.  The structural gate is:
    trend ``a+A+b+B+c`` (two sequential non-overlapping hubs) or consolidation
    ``a+A+b`` (one hub), with the terminal stroke after the last hub.
    """

    trend_info = trend_info or {}
    trend_type = trend_info.get("类型")
    trend_direction = trend_info.get("方向")
    expected_direction = "下跌" if is_buy else "上涨"
    stroke_ts = _ts_val(stroke.武.时间戳)
    preceding_hubs = [
        z for z in _source_hubs(obs, trend_info)
        if _formed_valid_hub(z) and _hub_end_ts(z) < stroke_ts
    ]
    hub_count = len(preceding_hubs)
    last_hub_ts = _hub_end_ts(preceding_hubs[-1]) if preceding_hubs else 0
    if trend_type == "趋势" and hub_count >= 2:
        structure_template = "a+A+b+B+c"
        structure_gate = True
    elif trend_type == "盘整" and hub_count >= 1:
        structure_template = "a+A+b"
        structure_gate = True
    else:
        structure_template = "未形成一类结构模板"
        structure_gate = False
    checks = {
        "背驰辅助证据": has_divergence,
        "结构模板": structure_template,
        "结构门槛": structure_gate,
        "前置已形成有效中枢数量": hub_count,
        "前置中枢序号": [
            getattr(z, "序号", i) for i, z in enumerate(preceding_hubs)
        ],
        "前置中枢核心完整性": [
            {
                "序号": getattr(z, "序号", i),
                "完整性_实": _hub_core_completeness(z),
            }
            for i, z in enumerate(preceding_hubs)
        ],
        "走势类型": trend_type,
        "走势方向": trend_direction,
        "要求走势方向": expected_direction,
        "方向匹配": (
            trend_type == "盘整"
            or trend_direction == expected_direction
        ),
        "最后中枢后": bool(last_hub_ts and stroke_ts > last_hub_ts),
        "笔端时间": _fmt_ts(stroke.武.时间戳),
        "最后中枢结束时间": _fmt_ts(last_hub_ts) if last_hub_ts else None,
    }
    ok = (
        structure_gate
        and (
            trend_type == "盘整"
            or trend_direction == expected_direction
        )
        and checks["最后中枢后"]
    )
    return ok, checks


def _first_type_ts(obs: 观察者, trend_info: dict = None):
    """找第一个严格一类买卖点的时间戳，用于 T3A/T3B 时序判定。"""
    trend_info = trend_info or _trend_analysis(obs)
    for s in obs.笔序列:
        try:
            meaningful, reason = 虚线.买卖意义(s, obs)
        except BaseException:
            meaningful, reason = False, ""
        if not meaningful:
            continue
        d = _dir_name(s.方向)
        is_buy = d == "向下"
        is_first, _ = _first_class_context(
            s, obs, trend_info, is_buy, "背驰" in reason
        )
        if is_first:
            return _ts_val(s.武.时间戳)
    return None


def _core_buy_sell_evidence(obs: 观察者) -> dict:
    """Probe the binding's native per-Chan-K buy/sell information.

    Some chanlun builds expose ``买卖点信息`` but leave it empty because the
    observer configuration does not attach generated objects to each candle.
    We report that fact explicitly instead of silently treating the heuristic
    classifier as an official signal sequence.
    """

    rows = []
    for ck in getattr(obs, "缠论K线序列", []):
        try:
            info = getattr(ck, "买卖点信息", None)
            if callable(info):
                info = info()
            if info:
                rows.append({
                    "时间": _fmt_ts(getattr(ck, "时间戳", None)),
                    "信息": str(info),
                })
        except BaseException:
            continue
    method_status = {}
    sample_stroke = next(iter(getattr(obs, "笔序列", [])), None)
    for name in ("买卖点配置匹配", "买卖点任意匹配",
                 "买卖点全量匹配", "买卖点相对匹配",
                 "缠K买卖点模式"):
        method_status[name] = bool(hasattr(虚线, name))
    return {
        "可用": bool(rows),
        "数量": len(rows),
        "样例": rows[:10],
        "匹配API": method_status,
        "生成工厂": bool(hasattr(买卖点, "生成买卖点")),
        "匹配样例": (
            _core_signal_matching(sample_stroke, obs) if sample_stroke else {}
        ),
        "说明": (
            "Rust 绑定在当前配置下直接挂载了买卖点信息"
            if rows else
            "当前配置/绑定未在缠论K线上挂载买卖点信息；买卖点由核心判据与 Skill 分类整理"
        ),
    }


def _core_signal_matching(stroke_or_line, obs: 观察者) -> dict:
    """Return official indicator-matching predicates for a signal endpoint."""

    if stroke_or_line is None:
        return {}
    try:
        ck = stroke_or_line.武.中
    except BaseException:
        return {}
    if ck is None:
        return {}
    config = getattr(obs, "配置", None)
    result = {}
    for label, method_name, args in (
        ("配置", "买卖点配置匹配", (ck, config)),
        ("任意", "买卖点任意匹配", (ck,)),
        ("全量", "买卖点全量匹配", (ck,)),
        ("相对", "买卖点相对匹配", (ck,)),
    ):
        method = getattr(虚线, method_name, None)
        if method is None:
            result[label] = None
            continue
        try:
            result[label] = bool(method(*args))
        except BaseException:
            result[label] = None
    try:
        info = getattr(ck, "买卖点信息", None)
        if callable(info):
            info = info()
        result["原生买卖点信息"] = list(info) if info else []
    except BaseException:
        result["原生买卖点信息"] = []
    return result


def _classify_signals(
    obs: 观察者, trend_info: dict = None, divergence_results: list = None
) -> list:
    """识别 T 系列买卖点（结构类型优先，背驰仅作辅助证据）。

    在 6 类基础买卖点（一/二/三 × 买/卖）之上，按走势类型与回踩次序二次细分：
    - 一类买卖点（缠论结构末端 + 背驰辅助确认）：
        T1  = ``a+A+b+B+c``，趋势至少含两个依次同向且不重叠的中枢；
        T1P = ``a+A+b``，盘整含一个有效中枢。
    - 二类买卖点（有买卖意义、非背驰）：
        T2  = 标准二类（一类之后的第一次回踩不破）
        T2S = 类二类（一类之后的后续回踩不破）
    - 三类买卖点（中枢第三买卖线非空）：
        T3A = 中枢在一类之后形成（反转后新建中枢再突破）
        T3B = 中枢在一类之前形成（突破老中枢 = 二三类重合）

    方向口径：向下笔终点（底分型）= 买；向上笔终点（顶分型）= 卖。
    第三买卖线：按相对中枢的位置（缺口方向）判买/卖——在中枢上方 = 三买，
    在中枢下方 = 三卖（注意不是第三买卖线自身的笔方向）。

    每个信号附带：
    - `time` —— 笔终点分型时间戳（用于跨周期共振匹配）
    - `止损` —— 由 `买卖点` factory 构造的官方止损信息（失效K线/有效性/与MACD柱子分型匹配）
    """
    signals = []
    trend_info = trend_info or _trend_analysis(obs)
    trend = trend_info["类型"]
    first_ts = _first_type_ts(obs, trend_info)
    divergence_by_stroke = {
        (row.get("index"), row.get("direction")): row
        for row in (divergence_results or [])
        if row.get("kind") == "笔内背驰"
    }

    # 三类买卖点：来自线段内部笔中枢的第三买卖线。
    # 原始全局 obs.笔_中枢序列 只作底层审计，不参与买卖点判断。
    for z in _segment_internal_pen_hubs(obs):
        line = z.第三买卖线
        if line is None:
            continue
        # 第三买卖线相对中枢的位置（缺口方向），不是它自身的笔方向：
        # 在中枢上方（向上缺口）= 三买；在中枢下方（向下缺口）= 三卖
        is_buy = line.低 >= z.高
        hub_start_ts = _ts_val(z.文.时间戳)  # 中枢起点分型时间戳（形成时序）
        if first_ts is not None and hub_start_ts < first_ts:
            base = "T3B"  # 中枢起点在一类之前 = 老中枢
        else:
            base = "T3A"  # 中枢起点在一类之后 = 新中枢（或无一类参考）
        reason_text = f"中枢#{z.序号} 第三买卖线（走势={trend}"
        if base == "T3B":
            reason_text += "，二三类重合"
        reason_text += "）"
        kind = base + ("买" if is_buy else "卖")
        sig = {
            "kind": kind,
            "base": "三买" if is_buy else "三卖",
            "来源": "rust_core+skill_classifier",
            "置信度": "高",
            "结构来源": "rust_core",
            "类型来源": "skill_classifier",
            "确认级别": "候选",
            "核心判据": {
                "第三买卖线": True,
                "中枢序号": z.序号,
                "中枢位置": "上方" if is_buy else "下方",
                "结构中枢来源": "线段内部笔中枢",
            },
            "核心匹配": _core_signal_matching(line, obs),
            "index": line.序号,
            "direction": "向上" if is_buy else "向下",
            "high": line.高, "low": line.低,
            "break": z.高 if is_buy else z.低,  # 中枢上沿/下沿，回踩跌破即失效
            "reason": reason_text,
            "time": _fmt_ts(line.武.时间戳),
            "止损": _stop_loss_info(line, obs, kind),
            "止损来源": "rust_factory",
        }
        signals.append(sig)

    # 一/二类：来自具备买卖意义的笔；背驰只作为一类的辅助证据。
    # 二类按「一类之后的回踩次序」区分：第一次回踩 = T2，后续回踩 = T2S
    buy_stage = 0   # 一买之后出现过的非背驰买点计数
    sell_stage = 0  # 一卖之后出现过的非背驰卖点计数
    first_seen = {"买": False, "卖": False}
    first_boundary = {"买": None, "卖": None}
    post_hub_meaningful = {"买": False, "卖": False}
    for s in obs.笔序列:
        try:
            meaningful, reason = 虚线.买卖意义(s, obs)
        except BaseException:
            meaningful, reason = False, ""
        if not meaningful:
            continue
        d = _dir_name(s.方向)
        is_buy = d == "向下"  # 向下笔终点是底分型 → 买点语境
        side = "买" if is_buy else "卖"
        divergence = divergence_by_stroke.get((s.序号, d), {})
        divergence_strength = divergence.get("强度", "无")
        has_divergence = "背驰" in reason or bool(divergence)
        structural_first, first_checks = _first_class_context(
            s, obs, trend_info, is_buy, has_divergence
        )
        # A first-class point must be the first meaningful terminal leg after
        # the final hub in that direction; later divergence remains evidence,
        # not another first-class point.
        after_last_hub = bool(first_checks.get("最后中枢后"))
        is_first = (
            structural_first
            and not first_seen[side]
            and not post_hub_meaningful[side]
        )
        if after_last_hub:
            post_hub_meaningful[side] = True
        if is_first:
            base = "T1" if trend == "趋势" else "T1P"
            base_label = "一买" if is_buy else "一卖"
            # 一类点出现后，重置对应方向的二类回踩计数
            if is_buy:
                buy_stage = 0
            else:
                sell_stage = 0
            first_seen[side] = True
        else:
            # A second-class point is defined relative to an existing first
            # class.  Pre-first meaningful strokes are not classified as T2.
            if not first_seen[side]:
                continue
            boundary = first_boundary[side]
            not_break = (
                boundary is not None
                and (s.低 >= boundary if is_buy else s.高 <= boundary)
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
        signal_reason = reason
        if is_first:
            template = first_checks.get("结构模板", "一类结构")
            divergence_state = "命中" if has_divergence else "未命中/待确认"
            signal_reason = (
                f"{template}结构一类候选；"
                f"背驰辅助证据={divergence_state}；"
                f"核心买卖意义={reason or '未提供'}"
            )
        kind = base + ("买" if is_buy else "卖")
        sig = {
            "kind": kind,
            "base": base_label,
            "来源": "rust_core+skill_classifier",
            "置信度": (
                "高" if is_first and divergence_strength in ("强", "内部")
                else "中" if is_first and has_divergence
                else "中" if is_first
                else "中"
            ),
            "结构来源": "rust_core",
            "类型来源": "skill_classifier",
            "确认级别": "候选",
            "核心判据": {
                "买卖意义": True,
                "理由": reason,
                "买卖意义用途": "辅助筛选，不定义买卖点类型",
                "结构中枢来源": "线段内部笔中枢",
                "背驰辅助证据": has_divergence,
                "背驰证据": divergence,
                "一类结构": first_checks if is_first else None,
                "二类不破": (
                    None if is_first
                    else {
                        "一类端点": first_boundary[side],
                        "当前端点": s.低 if is_buy else s.高,
                        "不破": True,
                    }
                ),
            },
            "核心匹配": _core_signal_matching(s, obs),
            "index": s.序号,
            "direction": d,
            "high": s.高, "low": s.低,
            "break": s.低 if is_buy else s.高,  # 跌破/涨破端点即失效
            "reason": signal_reason,
            "time": _fmt_ts(s.武.时间戳),
            "止损": _stop_loss_info(s, obs, kind),
            "止损来源": "rust_factory",
        }
        signals.append(sig)
        if is_first:
            first_boundary[side] = s.低 if is_buy else s.高

    signals.sort(key=lambda x: x["index"])
    return signals


def _stop_loss_info(stroke_or_line, obs: 观察者, kind: str) -> dict:
    """基于 `买卖点` factory 提取官方止损信息（失效K线/有效性/与MACD柱子分型匹配）。

    实现要点（审计 Stage 2-9）：
    - `缠论K线.买卖点信息` 在所有配置下实测都返回空 set()，不可作为载体。
    - 必须用 factory：把 `kind` 中的「买/卖」改成「买点/卖点」即可命中 18 个 classmethod。
    - 输入：笔（针对一/二类）或中枢第三买卖线（针对三类）+ 观察者。
    - 输出字段含：破位值/失效K线/有效性/与MACD柱子分型匹配/与MACD柱子匹配/偏移/失效偏移。
    """
    info = {
        "类型": None,
        "备注": None,
        "结构": None,
        "偏移": None,
        "破位值": None,
        "失效K线": None,
        "终结K线": None,
        "有效性": True,
        "失效偏移": None,
        "与MACD柱子匹配": None,
        "与RSI匹配": None,
        "与KDJ匹配": None,
        "与MACD柱子分型匹配": None,
    }
    # factory 方法命名：kind 末尾追加「点」即可 → e.g. "T1买"→"T1买点"
    method_name = kind + "点"
    factory = getattr(买卖点, method_name, None)
    if factory is None:
        return info

    # 取分型 + 当前 K 线
    fenxing = getattr(stroke_or_line, "武", None)
    if fenxing is None:
        return info
    try:
        current_k = fenxing.中.标的K线
    except BaseException:
        return info
    if current_k is None:
        return info

    # 初始破位值（来自 signal 的 break 字段），factory 会基于此判定有效性
    initial_break = getattr(stroke_or_line, "低", None) or getattr(stroke_or_line, "高", None)

    try:
        bp = factory(fenxing, current_k, "auto", "", initial_break)
    except BaseException:
        return info

    # 安全取值（factory 输出的部分字段可能抛错）
    def _safe_value(value, attr=None):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if attr in ("失效K线", "终结K线"):
            return {
                "时间": _fmt_ts(getattr(value, "时间戳", None)),
                "开": getattr(value, "开盘价", None),
                "高": getattr(value, "最高价", None),
                "低": getattr(value, "最低价", None),
                "收": getattr(value, "收盘价", None),
            }
        return str(value)

    def _safe(attr, default=None):
        try:
            v = getattr(bp, attr, default)
            return _safe_value(v, attr)
        except BaseException:
            return default

    info["破位值"] = _safe("破位值")
    info["类型"] = _safe("类型")
    info["备注"] = _safe("备注")
    info["结构"] = _safe("结构")
    info["偏移"] = _safe("偏移")
    info["失效K线"] = _safe("失效K线")
    info["终结K线"] = _safe("终结K线")
    info["有效性"] = _safe("有效性", True)
    info["失效偏移"] = _safe("失效偏移")
    info["与MACD柱子匹配"] = _safe("与MACD柱子匹配")
    info["与RSI匹配"] = _safe("与RSI匹配")
    info["与KDJ匹配"] = _safe("与KDJ匹配")
    info["与MACD柱子分型匹配"] = _safe("与MACD柱子分型匹配")
    return info


def _safe_bool(fn):
    """Run a Rust/PyO3 predicate and normalize failures to None."""

    try:
        return bool(fn())
    except BaseException:
        return None


def _kline_position_rows(positions, limit: int = 5) -> list:
    """Compact K-line/Chan K-line positions returned by Rust helpers."""

    rows = []
    for k in list(positions or [])[:limit]:
        base = getattr(k, "标的K线", k)
        rows.append({
            "time": _fmt_ts(getattr(base, "时间戳", getattr(k, "时间戳", None))),
            "high": getattr(k, "高", getattr(base, "最高价", None)),
            "low": getattr(k, "低", getattr(base, "最低价", None)),
            "close": getattr(base, "收盘价", None),
        })
    return rows


def _divergence_evidence_matrix(a, b, obs: 观察者, config: 缠论配置) -> dict:
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
        "命中": {
            "原子": atomic_hits,
            "组合": composite_hits,
            "模式": mode_hits,
        },
    }


def _divergences(obs: 观察者, config: 缠论配置) -> list:
    """基于核心库 `背驰分析` 与 `线段.判断线段内部是否背驰` 检测背驰。

    线段/笔对象的方法为 classmethod，实例必须作第一个参数传入。
    """
    results = []
    # 线段级内部背驰（最贴近原文的「线段内部背驰」）
    for seg in obs.线段序列:
        try:
            inner = 线段.判断线段内部是否背驰(seg, obs)
        except BaseException:
            inner = None
        if inner:
            try:
                positions = 线段.是否背驰过(seg, obs)
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
                "index": seg.序号,
                "direction": _dir_name(seg.方向),
                "high": seg.高, "low": seg.低,
            })
    # 笔内 MACD 趋向背驰（笔.是否背驰过）
    for s in obs.笔序列:
        try:
            positions = 笔.是否背驰过(s, obs)
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
                "index": s.序号,
                "direction": _dir_name(s.方向),
                "high": s.高, "low": s.低,
            })
    # 相邻线段对之间的 MACD/斜率/测度/组合/模式背驰证据矩阵
    segs = obs.线段序列
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        if a.方向 != b.方向:
            continue
        matrix = _divergence_evidence_matrix(a, b, obs, config)
        if matrix["成立"]:
            kinds = matrix["命中"]["原子"] or matrix["命中"]["组合"] or matrix["命中"]["模式"]
            results.append({
                "kind": "+".join(kinds),
                "来源": "rust_core",
                "确认": True,
                "强度": matrix["强度"],
                "证据矩阵": matrix,
                "index": b.序号,
                "direction": _dir_name(b.方向),
                "high": b.高, "low": b.低,
            })
    return results


def _resonance(periods_detail: dict) -> list:
    """跨周期共振：主周期（小周期）的同向买卖点在大周期也有命中。

    缠论「级别联立」思想：周线买点 + 日线买点同时出现 = 强信号。
    输出每个共振事件：
      - primary_time：主周期信号时间
      - direction：买/卖
      - strength：同向周期数（≥2 才算共振）
      - matches：参与共振的各周期信号列表（含时间距离）

    时间窗口：30 天（30*86400 秒）。同向信号落入窗口内即算共振。
    """
    events = []
    period_names = list(periods_detail.keys())
    if len(period_names) < 2:
        return events

    def _ts(sig):
        try:
            ts_str = sig.get("time", "")
            return int(datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
                       .replace(tzinfo=timezone.utc).timestamp())
        except (ValueError, TypeError, OSError):
            return 0

    primary = period_names[0]
    primary_sigs = []
    for sig in periods_detail[primary].get("买卖点", []):
        ts = _ts(sig)
        if ts:
            primary_sigs.append({**sig, "_ts": ts})

    other_sigs = {}
    for pn in period_names[1:]:
        other_sigs[pn] = []
        for sig in periods_detail[pn].get("买卖点", []):
            ts = _ts(sig)
            if ts:
                other_sigs[pn].append({**sig, "_ts": ts})

    WINDOW = 30 * 86400
    for ps in primary_sigs:
        is_buy = "买" in ps["kind"]
        matches = [{"period": primary, "kind": ps["kind"], "time": ps["time"],
                    "index": ps["index"]}]
        for pn, sigs in other_sigs.items():
            closest = None
            min_dist = WINDOW
            for s in sigs:
                if ("买" in s["kind"]) != is_buy:
                    continue
                d = abs(s["_ts"] - ps["_ts"])
                if d < min_dist:
                    closest = s
                    min_dist = d
            if closest is not None:
                matches.append({"period": pn, "kind": closest["kind"],
                                "time": closest["time"], "index": closest["index"],
                                "距离天数": min_dist // 86400})
        if len(matches) >= 2:
            events.append({
                "primary_time": ps["time"],
                "direction": "买" if is_buy else "卖",
                "strength": len(matches),
                "matches": matches,
            })
    return events


def _structure_alignment(periods_detail: dict) -> list:
    """Map adjacent-period current segments by time range and direction only.

    This is a Skill-layer audit mapping; the Rust core computes each observer
    independently and does not assert cross-period segment identity.
    """

    names = list(periods_detail.keys())
    alignments = []

    def _ts(value):
        try:
            return int(datetime.strptime(value, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc
            ).timestamp())
        except (ValueError, TypeError, OSError):
            return 0

    for index in range(len(names) - 1):
        lower_name, upper_name = names[index], names[index + 1]
        lower = periods_detail[lower_name].get("当前线段")
        upper = periods_detail[upper_name].get("当前线段")
        if not lower or not upper:
            continue
        lower_start, lower_end = _ts(lower.get("起点")), _ts(lower.get("终点"))
        upper_start, upper_end = _ts(upper.get("起点")), _ts(upper.get("终点"))
        overlap_start = max(lower_start, upper_start)
        overlap_end = min(lower_end, upper_end)
        if not overlap_start or overlap_end < overlap_start:
            relation = "无时间重叠"
        elif lower_start >= upper_start and lower_end <= upper_end:
            relation = "低周期时间覆盖"
        else:
            relation = "时间交叠"
        if lower.get("方向") == upper.get("方向"):
            relation += "/同向"
        else:
            relation += "/方向不同"
        alignments.append({
            "低周期": lower_name,
            "高周期": upper_name,
            "关系": relation,
            "低周期线段": lower,
            "高周期线段": upper,
            "端点对应": {
                "低周期起点": lower.get("起点"),
                "低周期终点": lower.get("终点"),
                "高周期起点": upper.get("起点"),
                "高周期终点": upper.get("终点"),
                "起点在高周期内": upper_start <= lower_start <= upper_end,
                "终点在高周期内": upper_start <= lower_end <= upper_end,
            },
            "价格包含": {
                "低周期高点": lower.get("高"),
                "低周期低点": lower.get("低"),
                "高周期高点": upper.get("高"),
                "高周期低点": upper.get("低"),
                "低周期价格被包含": (
                    upper.get("低") <= lower.get("低")
                    and lower.get("高") <= upper.get("高")
                ),
            },
            "说明": "时间与方向映射，不代表 Rust 核心建立了线段身份对应",
        })
    return alignments


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
    """扩展级别深度展开：把 `扩展线段序列组` / `扩展中枢序列组` 逐层结构展开。

    例：`扩展线段序列组 = [10, 3, 1]` 表示：
      - 第 1 层（基础扩展线段）：10 条
      - 第 2 层（扩展线段之扩展线段）：3 条
      - 第 3 层（再上一层）：1 条

    对每层：列出序号、方向、起讫时间、端点价。这是缠论「级别递归」的载体，
    多级别联立分析的基础。审计 Stage 3-13。
    """
    seg_levels = []
    for li, group in enumerate(obs.扩展线段序列组):
        seg_levels.append({
            "层级": li + 1,
            "数量": len(group),
            "线段": [
                _segment_detail(s)
                for s in group
            ],
        })
    hub_levels = []
    for li, group in enumerate(obs.扩展中枢序列组):
        hub_levels.append({
            "层级": li + 1,
            "数量": len(group),
            "中枢": [
                {"序号": z.序号, "高": z.高, "低": z.低, "高高": z.高高, "低低": z.低低,
                 "状态": z.当前状态() if hasattr(z, "当前状态") else ""}
                for z in group
            ],
        })
    mixed_seg_levels = []
    for li, group in enumerate(getattr(obs, "混合扩展线段序列组", [])):
        mixed_seg_levels.append({
            "层级": li + 1,
            "数量": len(group),
            "线段": [_segment_detail(s) for s in group],
        })
    mixed_hub_levels = []
    for li, group in enumerate(getattr(obs, "混合扩展中枢序列组", [])):
        mixed_hub_levels.append({
            "层级": li + 1,
            "数量": len(group),
            "中枢": [_hub_detail(z) for z in group],
        })
    return {
        "扩展线段层": seg_levels,
        "扩展中枢层": hub_levels,
        "混合扩展线段层": mixed_seg_levels,
        "混合扩展中枢层": mixed_hub_levels,
    }


def _get_container(k, name):
    """从 K 线指标容器取子指标，兼容 Rust 绑定（dict）与属性访问。"""
    指标 = getattr(k, "指标", None)
    if 指标 is None:
        return None
    if isinstance(指标, dict):
        return 指标.get(name)
    return getattr(指标, name, None)


def _indicator_tail(obs: 观察者, n: int = 3) -> list:
    """提取最近 N 根 K 线的技术指标值（挂在 K 线上）。"""
    rows = []
    for k in obs.普通K线序列[-n:]:
        macd = getattr(k, "macd", None)
        rsi = getattr(k, "rsi", None)
        kdj = getattr(k, "kdj", None)
        boll = _get_container(k, "boll")
        均线 = _get_container(k, "均线")
        rows.append({
            "time": _fmt_ts(k.时间戳),
            "close": k.收盘价,
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
            "均线": dict(均线) if isinstance(均线, dict) else None,
        })
    return rows


def _macd_area(obs: 观察者) -> dict:
    """用 `K线.获取MACD` 计算全序列 MACD 柱面积分向统计（量化背驰的原料）。

    注意：该方法要求普 `K线` 序列（非缠论K线），且 `始`/`终` 是 K 线对象而非索引。
    """
    ks = obs.普通K线序列
    if len(ks) < 2:
        return {}
    try:
        return K线.获取MACD(ks, ks[0], ks[-1])
    except BaseException:
        return {}


# ---------------------------------------------------------------------------
# 结构化结果
# ---------------------------------------------------------------------------
def analyze(symbol: str, data_by_period: dict, config: 缠论配置 = None) -> dict:
    """分别对各周期直接投喂并产出结构化结果。

    data_by_period: {周期秒数: [K线行]}。每个周期用各自真实数据独立分析，
    直接对观察者 `增加原始K线`（绕开 `立体分析器.投喂K线` 的增量式合成器）。

    为什么绕开合成器：`投喂K线` 是增量式设计（逐根投喂、维护「当前K线」状态，
    适合实时行情流式更新），会把最后一根 K 线留在 pending 状态不进序列。而本
    工具是一次性批量分析历史数据，直接 `增加原始K线` 即可——无 pending、无需
    flush、语义更清晰。
    """
    seconds_list = sorted(data_by_period.keys())
    if not seconds_list:
        raise ValueError("无数据")

    # 立体分析器仅作观察者容器，其周期组长度必须 ≥2（Rust 侧硬约束，单周期 panic）
    periods = list(seconds_list)
    if len(periods) < 2:
        p0 = periods[0]
        up = upper_period(p0)
        if up != p0:
            periods.append(up)
        else:
            periods.insert(0, lower_period(p0))

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

    engine = 立体分析器(symbol, periods, cfg)

    # 分别投喂各周期（直接增加原始K线，无 pending）
    for p in seconds_list:
        obs = get_observer(engine, p)
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
        obs = get_observer(engine, p)
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
        detail["核心买卖点信息"] = _core_buy_sell_evidence(obs)
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
        detail["策略计划"] = build_strategy_plan(detail)
        result["periods_detail"][name] = detail

    # 跨周期共振（审计 Stage 3-15）
    result["跨周期共振"] = _resonance(result["periods_detail"])
    result["周期结构对齐"] = _structure_alignment(result["periods_detail"])
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
# 文本报告
# ---------------------------------------------------------------------------
def render_text(result: dict) -> str:
    lines = []
    lines.append("=" * 64)
    lines.append(f"  {result['symbol']} 缠论分析（{result['freq']}，周期组 {result['periods']}）")
    source_meta = result.get("data_source", {})
    if source_meta:
        lines.append(
            f"  数据源={source_meta.get('source', '-')}"
            f"  复权={source_meta.get('复权模式', '-')}"
            + (
                f"  锚定日期={source_meta['anchor_date']}"
                if source_meta.get("anchor_date") else ""
            )
        )
    lines.append("=" * 64)

    for name, d in result["periods_detail"].items():
        lines.append("")
        lines.append(f"--- {name} ---")
        lines.append(f"  K线 {d['普通K线']}  缠K {d['缠论K线']}  分型 {d['分型']}  "
                     f"笔 {d['笔']}  笔中枢 {d['笔中枢']}")
        lines.append(
            f"  笔中枢口径：{d.get('笔中枢口径', '未知')}"
            f"（原始全局笔中枢 {d.get('原始全局笔中枢', 0)}，仅审计）"
        )
        lines.append(f"  线段 {d['线段']}  中枢 {d['中枢']}  扩展线段 {d['扩展线段']}  "
                     f"扩展中枢 {d['扩展中枢']}")
        lines.append(f"  走势类型：{d.get('走势类型', '未知')} "
                     f"方向={d.get('走势方向', '未知')}")
        trend_evidence = d.get("走势判据", {})
        if trend_evidence:
            lines.append(
                f"  走势判据：{trend_evidence.get('判据来源', '未知')} "
                f"上移={trend_evidence.get('上移次数', 0)} "
                f"下移={trend_evidence.get('下移次数', 0)} "
                f"重叠={trend_evidence.get('重叠次数', 0)}"
            )
        core_signal = d.get("核心买卖点信息", {})
        if core_signal:
            lines.append(
                f"  核心买卖点挂载：{'是' if core_signal.get('可用') else '否'}"
            )
        quality = d.get("数据质量", {})
        if quality.get("问题"):
            lines.append(f"  数据质量警告：{len(quality['问题'])} 项")
        contract = d.get("标准信号校验", {})
        if contract:
            lines.append(
                f"  标准信号校验：{'通过' if contract.get('有效') else '失败'}"
                f"（错误 {len(contract.get('错误', []))} 项）"
            )
        semantic = d.get("语义摘要", {})
        for interpretation in semantic.get("解释", [])[:2]:
            lines.append(f"  语义判断：{interpretation.get('结论', '-')}"
                         f"（{interpretation.get('确定性', '未知')}）")

        if d["笔序列"]:
            lines.append("  最近笔：")
            for s in d["笔序列"]:
                lines.append(f"    笔#{s['序号']} {s['方向']} {s['文']}→{s['武']} "
                             f"[{s['低']:.2f} ~ {s['高']:.2f}]")
        if d["中枢序列"]:
            lines.append("  中枢：")
            for z in d["中枢序列"]:
                lines.append(f"    中枢#{z['序号']} 区间 [{z['低']:.2f} ~ {z['高']:.2f}] "
                             f"极值 [{z['低低']:.2f} ~ {z['高高']:.2f}] {z['状态']}")
        if d.get("线段内部笔中枢"):
            lines.append("  线段内部笔中枢：")
            for z in d["线段内部笔中枢"]:
                seg = z.get("所属线段", "-")
                lines.append(
                    f"    线段#{seg} 笔中枢#{z['序号']} "
                    f"区间 [{z['低']:.2f} ~ {z['高']:.2f}] "
                    f"极值 [{z['低低']:.2f} ~ {z['高高']:.2f}] {z['状态']}"
                )
        if d["买卖点"]:
            lines.append("  买卖点（T 系列）：")
            for s in d["买卖点"]:
                line = (f"    {s['kind']}（{s['base']}） 笔#{s['index']} {s['direction']} "
                        f"[{s['low']:.2f} ~ {s['high']:.2f}] "
                        f"破位 {s['break']:.2f} 时间={s.get('time', '-')}")
                line += (
                    f" [结构={s.get('结构来源', '-')}|类型={s.get('类型来源', '-')}"
                    f"|确认={s.get('确认级别', '-')}|止损={s.get('止损来源', '-')}]"
                )
                # 止损信息（审计 Stage 2-9）
                stop = s.get("止损", {})
                if stop:
                    validity = "有效" if stop.get("有效性", True) else "失效"
                    match_macd = "MACD匹配" if stop.get("与MACD柱子分型匹配") else "MACD不匹配"
                    line += f" [{validity}|{match_macd}|破位值={stop.get('破位值')}]"
                line += f" 理由={s['reason'] or '-'}"
                lines.append(line)
        if d["背驰"]:
            lines.append("  背驰：")
            for v in d["背驰"]:
                matrix = v.get("证据矩阵", {})
                strength = v.get("强度")
                extra = f" 强度={strength}" if strength else ""
                if isinstance(matrix, dict) and matrix.get("命中"):
                    hits = matrix["命中"]
                    hit_text = ",".join(hits.get("原子", []) + hits.get("组合", []))
                    if hit_text:
                        extra += f" 命中={hit_text}"
                lines.append(f"    {v['kind']} #{v['index']} {v['direction']}{extra}")
        if d.get("MACD面积"):
            lines.append(f"  MACD面积（全序列）: {d['MACD面积']}")
        # 多级别展开（审计 Stage 3-13）
        ml = d.get("多级别展开", {})
        if ml.get("扩展线段层"):
            lines.append("  扩展级别（多级别递归）：")
            for lvl in ml["扩展线段层"]:
                lines.append(f"    L{lvl['层级']}（{lvl['数量']} 条）：")
                for s in lvl["线段"]:
                    lines.append(f"      线段#{s['序号']} {s['方向']} [{s['低']:.2f}~{s['高']:.2f}] "
                                 f"{s['起点']}→{s['终点']}")
        if d.get("指标_最近"):
            lines.append("  最近指标：")
            for r in d["指标_最近"]:
                line = (f"    {r['time']} 收 {r['close']:.2f} "
                        f"MACD(DIF {r['macd_dif']}, BAR {r['macd_bar']}) "
                        f"RSI {r['rsi']} KDJ(K {r['kdj_k']}, D {r['kdj_d']}, J {r['kdj_j']})")
                if r.get("boll_mid") is not None:
                    line += f" BOLL({r['boll_low']:.2f}/{r['boll_mid']:.2f}/{r['boll_up']:.2f})"
                if r.get("均线"):
                    line += f" 均线{r['均线']}"
                lines.append(line)

    # 跨周期共振（审计 Stage 3-15）
    if result.get("跨周期共振"):
        lines.append("")
        lines.append("  跨周期共振（多级别同向买卖点）：")
        for ev in result["跨周期共振"]:
            lines.append(f"    [{ev['direction']}] 强度={ev['strength']} @ {ev['primary_time']}")
            for m in ev["matches"]:
                extra = f"（距{m['距离天数']}天）" if "距离天数" in m else ""
                lines.append(f"      - {m['period']} {m['kind']} {m['time']}{extra}")

    lines.append("")
    lines.append("=" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="缠论综合分析工具（chanlun 核心库）")
    parser.add_argument("--source", choices=["csv", "eltdx"], default="csv", help="数据源")
    parser.add_argument("--input", type=str, help="CSV 文件路径（csv 模式）")
    parser.add_argument(
        "--input_periods", type=str,
        help="多周期 CSV 映射，如 day=day.csv,week=week.csv；提供后覆盖 --input",
    )
    parser.add_argument("--code", type=str, help="股票代码（eltdx 模式，如 sh600519）")
    parser.add_argument("--symbol", type=str, default=None,
                        help="标的标识（默认：csv 模式为 000001，eltdx 模式为 code）")
    parser.add_argument("--start_date", type=str, help="开始日期 YYYY-MM-DD（eltdx）")
    parser.add_argument("--end_date", type=str, help="结束日期 YYYY-MM-DD（eltdx）")
    parser.add_argument("--freq", type=str, default="day", help="分析周期（1m/5m/.../day/week/month 或中文）")
    parser.add_argument("--count", type=int, default=800,
                        help="eltdx 拉取 K 线总数（超过 800 自动分页）")
    parser.add_argument("--page-size", type=int, default=_ELTDX_KLINE_PAGE_SIZE,
                        help="eltdx 单页数量（1~800，默认 800）")
    parser.add_argument("--max-pages", type=int, default=_ELTDX_DEFAULT_MAX_PAGES,
                        help="eltdx 最大分页次数（默认 200）")
    parser.add_argument("--adjust", type=str, default=_ELTDX_DEFAULT_ADJUST,
                        choices=list(_ELTDX_ADJUST_CHOICES),
                        help="eltdx 复权模式（默认 qfq 前复权；可选 none/hfq/fixed_qfq/fixed_hfq）")
    parser.add_argument("--anchor-date", "--anchor_date", dest="anchor_date", type=str,
                        help="定点复权锚定日期 YYYY-MM-DD（fixed_qfq/fixed_hfq 必填）")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    parser.add_argument("--output", type=str, help="输出文件路径")
    parser.add_argument("--cal_indicators", action="store_true", default=True,
                        help="计算技术指标（默认开）")
    parser.add_argument("--笔内元素数量", type=int, default=None,
                        help="成笔最低 K 线数（默认 5，改 3 笔数可增加约 2.9 倍）")
    parser.add_argument("--买卖点激进识别", action="store_true", default=None,
                        help="买卖点激进识别（不考虑分型完整性）")
    parser.add_argument("--boll", action="store_true", help="计算 BOLL 布林带")
    parser.add_argument("--均线", type=str, default=None,
                        help="计算均线，逗号分隔周期（如 5,20,60）")
    parser.add_argument("--均线类型", type=str, default="SMA",
                        help="均线类型（SMA/EMA，逗号分隔，如 SMA,EMA）")
    # ---- Stage 3-12 参数杠杆 ----
    parser.add_argument("--指标计算方式", type=str, default=None,
                        choices=["收", "高", "低"],
                        help="指标计算基准（默认 收；选 高/低 会同时改变 MACD 数值与买卖意义命中数）")
    parser.add_argument("--买卖点_指标模式", type=str, default=None,
                        choices=["全量", "任意", "配置"],
                        help="买卖点指标匹配模式（默认 配置）")
    parser.add_argument("--买卖点_指标匹配_MACD", type=str, default=None,
                        choices=["True", "False"],
                        help="是否要求买卖点与 MACD 柱分型匹配（True=严格；官方约定：买在负、卖在正）")

    args = parser.parse_args()

    # 解析目标周期
    try:
        freq_seconds = period_to_seconds(args.freq)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    # 加载数据（多周期：目标周期 + 上一级周期，用于跨级别共振判断）
    if args.source == "csv":
        if args.input_periods:
            data_by_period = load_csv_periods(args.input_periods)
        elif args.input:
            data_by_period = {freq_seconds: load_csv_data(args.input)}
        else:
            print("错误：csv 模式需要 --input 或 --input_periods", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.code:
            print("错误：eltdx 模式需要 --code", file=sys.stderr)
            sys.exit(1)
        data_by_period = {}
        up = upper_period(freq_seconds)
        for p in sorted({freq_seconds, up}):
            pname = seconds_to_name(p)
            rows = load_eltdx_data(
                args.code,
                pname,
                args.start_date,
                args.end_date,
                args.count,
                args.page_size,
                args.max_pages,
                args.adjust,
                args.anchor_date,
            )
            if len(rows) >= 2:
                data_by_period[p] = rows

    if not data_by_period:
        print("错误：数据不足（<2 根 K 线），无法分析", file=sys.stderr)
        sys.exit(1)

    # 配置：默认开启指标，关闭推送
    config = 缠论配置.不推送()
    config.计算指标 = args.cal_indicators
    if args.笔内元素数量 is not None:
        config.笔内元素数量 = args.笔内元素数量
    if args.买卖点激进识别 is not None:
        config.买卖点激进识别 = args.买卖点激进识别
    if args.boll:
        config.计算BOLL = True
    if args.均线:
        periods = [int(x) for x in args.均线.split(",") if x.strip()]
        types = [t.strip().upper() for t in args.均线类型.split(",") if t.strip()]
        types = [t for t in types if t in ("SMA", "EMA")] or ["SMA"]
        config.均线_类型列表 = types
        config.均线_周期列表 = periods
    # ---- Stage 3-12 参数杠杆 ----
    if args.指标计算方式 is not None:
        config.指标计算方式 = args.指标计算方式
    if args.买卖点_指标模式 is not None:
        config.买卖点_指标模式 = args.买卖点_指标模式
    if args.买卖点_指标匹配_MACD is not None:
        config.买卖点_指标匹配_MACD = (args.买卖点_指标匹配_MACD == "True")

    # 分析
    symbol = args.symbol or (args.code if args.source == "eltdx" else "000001")
    try:
        result = analyze(symbol, data_by_period, config)
        result["data_source"] = {
            "source": args.source,
            "复权模式": args.adjust if args.source == "eltdx" else "csv原样",
            "anchor_date": args.anchor_date if args.source == "eltdx" else None,
        }
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except BaseException as e:
        # 兜底：PanicException 继承 BaseException，这里让错误可见而非无声猝死
        print(f"错误：分析失败（{type(e).__name__}）：{e}", file=sys.stderr)
        sys.exit(1)

    # 输出
    if args.json:
        out = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    else:
        out = render_text(result)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"报告已保存到 {args.output}")
    else:
        print(out)


if __name__ == "__main__":
    main()
