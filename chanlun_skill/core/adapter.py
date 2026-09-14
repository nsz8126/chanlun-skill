"""eltdx → chanlun 数据格式转换适配器。"""

from __future__ import annotations

from chanlun import K线

# eltdx period 字符串 → chanlun 周期（秒）
PERIOD_MAP: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "60m": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
    "quarter": 7776000,
    "year": 31536000,
}


def period_to_seconds(period: str) -> int:
    """将 eltdx period 字符串转换为秒数。"""
    if period in PERIOD_MAP:
        return PERIOD_MAP[period]
    raise ValueError(f"不支持的周期: {period!r}，可选: {list(PERIOD_MAP.keys())}")


def eltdx_to_chanlun(
    bar,
    symbol: str,
    period_seconds: int,
    index: int,
) -> K线:
    """将 eltdx KlineBar 转换为 chanlun K线。

    :param bar: eltdx KlineBar 实例
    :param symbol: 股票代码 (如 "sz000001")
    :param period_seconds: 周期秒数
    :param index: K线序号
    :return: chanlun K线 实例
    """
    timestamp = bar.time
    if hasattr(timestamp, "timestamp"):
        ts = int(timestamp.timestamp())
    else:
        ts = int(timestamp)

    return K线.创建普K(
        symbol,
        ts,
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        bar.volume_lots,
        index,
        period_seconds,
    )


def fetch_klines(client, symbol: str, period: str, count: int = 800, adjust: str | None = None):
    """从 eltdx 获取 K 线数据。

    :param client: eltdx TdxClient 实例
    :param symbol: 股票代码 (如 "sz000001")
    :param period: 周期字符串 (如 "day", "5m")
    :param count: K线数量
    :param adjust: 复权模式 (None/qfq/hfq)
    :return: KlineSeries
    """
    kwargs = {"period": period, "count": count}
    if adjust is not None:
        kwargs["adjust"] = adjust
    return client.bars.get(symbol, **kwargs)


def feed_klines_to_observer(observer, kline_series):
    """将 eltdx KlineSeries 批量投喂给 chanlun 观察者。

    :param observer: chanlun 观察者 或 立体分析器
    :param kline_series: eltdx KlineSeries
    :return: 投喂的 K线 数量
    """
    period_seconds = period_to_seconds(kline_series.period_name)
    symbol = f"{kline_series.exchange}{kline_series.code}"
    count = 0
    for i, bar in enumerate(kline_series.bars):
        k = eltdx_to_chanlun(bar, symbol, period_seconds, i)
        observer.投喂K线(k)
        count += 1
    return count
