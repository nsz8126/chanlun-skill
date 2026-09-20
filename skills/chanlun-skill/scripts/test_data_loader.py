#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eltdx 分页取数层的离线契约测试。

测试通过注入一个最小的假 TdxClient，不访问网络，验证：
  - 超过 800 根时按 start 游标分页；
  - 多页结果合并、去重并按时间升序；
  - 短页继续请求，空页才结束；
  - 日期范围在合并后裁剪；
  - 默认使用前复权 qfq，并允许显式切换复权模式；
  - 分页参数错误给出明确失败。
"""

from datetime import datetime, timedelta
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import chan_analyzer


class _Bar:
    def __init__(self, timestamp, value):
        self.time = timestamp
        self.open = value
        self.high = value + 1
        self.low = value - 1
        self.close = value + 0.5
        self.volume_lots = value * 10


class _Series:
    def __init__(self, bars):
        self.bars = tuple(bars)
        self.count = len(self.bars)


class _FakeClient:
    source_bars = []
    calls = []

    def __init__(self, timeout=15):
        self.timeout = timeout
        self.bars = self

    def __enter__(self):
        type(self).calls = []
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, code, *, period, start=0, count=800, **kwargs):
        call = {
            "code": code,
            "period": period,
            "start": start,
            "count": count,
        }
        call.update(kwargs)
        type(self).calls.append(call)
        return _Series(type(self).source_bars[start:start + count])


def _install_fake_eltdx():
    original = sys.modules.get("eltdx")
    fake = types.ModuleType("eltdx")
    fake.TdxClient = _FakeClient
    sys.modules["eltdx"] = fake
    return original


def _restore_eltdx(original):
    if original is None:
        sys.modules.pop("eltdx", None)
    else:
        sys.modules["eltdx"] = original


def test_pagination_merge_and_sort():
    base = datetime(2026, 1, 1)
    # 模拟服务端按最新到最旧返回；取数层最终必须恢复时间升序。
    _FakeClient.source_bars = [
        _Bar(base + timedelta(days=i), float(i))
        for i in reversed(range(1600))
    ]
    original = _install_fake_eltdx()
    try:
        rows = chan_analyzer.load_eltdx_data(
            "sz000001", "day", count=1600, page_size=800
        )
    finally:
        _restore_eltdx(original)

    assert len(rows) == 1600
    assert rows[0]["date"] < rows[-1]["date"]
    assert len(_FakeClient.calls) == 2
    assert [c["start"] for c in _FakeClient.calls] == [0, 800]
    assert all(c["count"] == 800 for c in _FakeClient.calls)
    assert all(c["adjust"] == "qfq" for c in _FakeClient.calls)


def test_short_page_and_date_filter():
    base = datetime(2026, 2, 1)
    _FakeClient.source_bars = [
        _Bar(base + timedelta(days=i), float(i))
        for i in reversed(range(500))
    ]
    original = _install_fake_eltdx()
    try:
        rows = chan_analyzer.load_eltdx_data(
            "sh600519",
            "day",
            start_date="2026-02-11",
            end_date="2026-02-20",
            count=1000,
        )
    finally:
        _restore_eltdx(original)

    assert len(rows) == 10
    assert rows[0]["date"].startswith("2026-02-11")
    assert rows[-1]["date"].startswith("2026-02-20")
    # 短页不提前结束；下一页返回空页后才停止。
    assert len(_FakeClient.calls) == 2


def test_adjust_mode_can_be_overridden_and_anchored():
    base = datetime(2026, 3, 1)
    _FakeClient.source_bars = [
        _Bar(base + timedelta(days=i), float(i))
        for i in reversed(range(10))
    ]
    original = _install_fake_eltdx()
    try:
        rows = chan_analyzer.load_eltdx_data(
            "sz000001",
            "day",
            count=5,
            adjust="fixed_qfq",
            anchor_date="2026-03-05",
        )
    finally:
        _restore_eltdx(original)

    assert len(rows) == 5
    assert _FakeClient.calls[0]["adjust"] == "fixed_qfq"
    assert _FakeClient.calls[0]["anchor_date"] == "2026-03-05"


def test_invalid_pagination_arguments():
    for kwargs in (
        {"count": 0},
        {"count": 10, "page_size": 801},
        {"count": 10, "page_size": 0},
        {"count": 10, "max_pages": 0},
        {"count": 10, "adjust": "bad"},
        {"count": 10, "adjust": "fixed_qfq"},
    ):
        try:
            chan_analyzer.load_eltdx_data("sz000001", "day", **kwargs)
        except SystemExit:
            continue
        raise AssertionError(f"参数应拒绝：{kwargs}")


if __name__ == "__main__":
    test_pagination_merge_and_sort()
    test_short_page_and_date_filter()
    test_adjust_mode_can_be_overridden_and_anchored()
    test_invalid_pagination_arguments()
    print("data loader tests passed")
