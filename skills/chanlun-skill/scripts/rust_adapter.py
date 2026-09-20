"""Rust-first adapter for the chanlun Python binding.

The installed ``chanlun`` package exposes the Rust engine through PyO3 while
keeping a Python compatibility module in ``chanlun.chan``.  This module is the
single import/access point used by the Skill so the rest of the code does not
depend on private Rust binding details.
"""

from chanlun import (
    K线,
    立体分析器,
    缠论配置,
    观察者,
    虚线,
    笔,
    线段,
    中枢,
    背驰分析,
    买卖点,
)


def get_observer(engine: 立体分析器, period_seconds: int) -> 观察者:
    """Return a period observer from the Rust multi-period engine.

    ``_单体分析器`` is currently the only way to access observers from the
    binding.  Keeping that access here makes a future public API migration
    local instead of spreading private-field usage through the analyzer.
    """

    observers = getattr(engine, "_单体分析器", None)
    if observers is None:
        raise RuntimeError("chanlun Rust binding 未暴露周期观察者容器")
    try:
        return observers[period_seconds]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"Rust 核心未找到周期 {period_seconds}s 的观察者"
        ) from exc


def append_raw_kline(
    observer: 观察者,
    symbol: str,
    timestamp: int,
    row: dict,
    index: int,
    period_seconds: int,
) -> None:
    """Create and append one raw K-line through the Rust binding."""

    kline = K线.创建普K(
        symbol,
        timestamp,
        row["open"],
        row["high"],
        row["low"],
        row["close"],
        row["volume"],
        index,
        period_seconds,
    )
    observer.增加原始K线(kline)


__all__ = [
    "K线",
    "立体分析器",
    "缠论配置",
    "观察者",
    "虚线",
    "笔",
    "线段",
    "中枢",
    "背驰分析",
    "买卖点",
    "get_observer",
    "append_raw_kline",
]
