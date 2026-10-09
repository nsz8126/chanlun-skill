"""周期规范化与 CSV/eltdx 行情加载。"""

import csv


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
    if key.endswith(("分钟", "m", "min")):
        digits = "".join(ch for ch in key if ch.isdigit())
        if digits:
            return int(digits) * 60
    raise ValueError(
        f"不支持的周期: {freq!r}，可选：1m/5m/15m/30m/60m/day/week/month "
        "或中文（1分钟/日线/周线/月线）"
    )


def seconds_to_name(seconds: int) -> str:
    return _SECONDS_NAME.get(seconds, f"{seconds}s")


def upper_period(seconds: int) -> int:
    """返回严格大于当前周期的最小标准周期，用于补足周期组。"""
    for period in _PERIOD_ORDER:
        if period > seconds:
            return period
    return seconds


def lower_period(seconds: int) -> int:
    """返回严格小于当前周期的最大标准周期。"""
    previous = None
    for period in _PERIOD_ORDER:
        if period >= seconds:
            break
        previous = period
    return previous


def load_csv_data(file_path: str) -> list:
    data = []
    try:
        file = open(file_path, "r", encoding="utf-8-sig")
    except FileNotFoundError:
        raise SystemExit(f"错误：找不到文件 {file_path!r}")
    except OSError as exc:
        raise SystemExit(f"错误：无法读取文件 {file_path!r}：{exc}")

    required = {"date", "open", "high", "low", "close", "volume"}
    with file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise SystemExit(f"错误：{file_path!r} 无表头")
        missing = required - set(reader.fieldnames)
        if missing:
            raise SystemExit(
                f"错误：{file_path!r} 缺少必需列 {sorted(missing)}，"
                f"需要 {sorted(required)}"
            )
        for index, row in enumerate(reader, start=2):
            try:
                data.append({
                    "date": row["date"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                })
            except (KeyError, ValueError, TypeError) as exc:
                raise SystemExit(
                    f"错误：{file_path!r} 第 {index} 行数据非法（{exc}）：{row!r}"
                )
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
        raise SystemExit("错误：--adjust 只支持 none/qfq/hfq/fixed_qfq/fixed_hfq")
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

    ``count`` 表示本次最多请求的原始 K 线总数；超过接口单页上限时按游标
    分页。所有页面先合并、去重并按时间排序，再裁剪日期范围后交给分析器，
    避免分页边界切断笔、线段或中枢。

    复权默认 ``qfq``；``page_size`` 必须在 1~800 之间，``max_pages`` 用于
    防止服务端游标异常导致无限请求。
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
    period = period_map.get(period_to_seconds(freq), "day")
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
                # 显式传 start/count，兼容不支持 all_pages 的旧客户端。
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
                        # 保留分钟级时间；核心内部再按周期边界对齐。
                        "date": date_text,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume_lots,
                    }
                requested += len(page_bars)
                if len(rows_by_time) == before:
                    raise RuntimeError("分页未返回新的时间序列，已停止以避免死循环")
                # 短页不代表历史结束；只有空页才结束，兼容服务端临时短页。
    except Exception as exc:
        raise SystemExit(f"错误：从 eltdx 获取数据失败：{exc}")

    data = [rows_by_time[key] for key in sorted(rows_by_time)]
    start_bound = str(start_date).strip() if start_date else None
    end_bound = str(end_date).strip() if end_date else None
    if end_bound and len(end_bound) == 10 and end_bound[4] == "-" and end_bound[7] == "-":
        end_bound += " 23:59:59.999999"
    if start_date:
        data = [row for row in data if row["date"] >= start_bound]
    if end_date:
        data = [row for row in data if row["date"] <= end_bound]
    return data


__all__ = [
    "period_to_seconds",
    "seconds_to_name",
    "upper_period",
    "lower_period",
    "load_csv_data",
    "load_csv_periods",
    "load_eltdx_data",
    "_ELTDX_KLINE_PAGE_SIZE",
    "_ELTDX_DEFAULT_MAX_PAGES",
    "_ELTDX_ADJUST_CHOICES",
    "_ELTDX_DEFAULT_ADJUST",
]
