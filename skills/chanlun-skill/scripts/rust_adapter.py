"""Rust-first adapter for the chanlun Python binding.

The installed ``chanlun`` package exposes the Rust engine through PyO3 while
keeping a Python compatibility module in ``chanlun.chan``.  This module is the
single import/access point used by the Skill so the rest of the code does not
depend on private Rust binding details.
"""

from chanlun import (
    K线,
    缠论配置,
    观察者,
    笔,
    线段,
    中枢,
    背驰分析,
)


def create_observer(
    symbol: str, period_seconds: int, config: 缠论配置 = None
) -> 观察者:
    """Create an independent observer for one real input period.

    The analyzer receives each period's own bars, so it does not need the
    multi-period engine to synthesize bars or act as an observer container.
    Copy the config to isolate per-period observer state.
    """
    source_config = config if config is not None else 缠论配置.不推送()
    observer_config = source_config.model_copy(update={
        "推送K线": False,
        "推送笔": False,
        "推送线段": False,
        "图表展示": False,
    })
    return 观察者(symbol, period_seconds, observer_config)


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
    "缠论配置",
    "观察者",
    "笔",
    "线段",
    "中枢",
    "背驰分析",
    "create_observer",
    "append_raw_kline",
]
