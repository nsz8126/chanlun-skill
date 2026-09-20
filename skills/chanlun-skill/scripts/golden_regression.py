#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Golden fixture regression for the Rust-first signal contract."""

import json
import os
import subprocess
import sys

import chan_analyzer as analyzer

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "chan_analyzer.py")


def run_fixture(name: str) -> dict:
    path = os.path.join(HERE, name)
    result = subprocess.run(
        [sys.executable, "-X", "utf8", SCRIPT,
         "--source", "csv", "--input", path, "--symbol", "000001",
         "--freq", "day", "--json"],
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout.decode("utf-8"))


class _Point:
    def __init__(self, timestamp: int):
        self.时间戳 = timestamp


class _Hub:
    def __init__(
        self,
        index: int,
        start: int,
        end: int,
        low: float,
        high: float,
        complete: bool = True,
        formed: bool = True,
    ):
        self.序号 = index
        self.文 = _Point(start)
        self.武 = _Point(end)
        self.低 = low
        self.高 = high
        self.低低 = low
        self.高高 = high
        self.基础序列 = [object(), object(), object()] if formed else [object()]
        self._complete = complete

    def 完整性(self, mode: str) -> bool:
        return self._complete if mode == "实" else False


class _Stroke:
    def __init__(self, timestamp: int):
        self.武 = _Point(timestamp)


class _Segment:
    def __init__(self, index: int, hubs):
        self.序号 = index
        self.合_中枢序列 = hubs


class _Observer:
    def __init__(self, internal_hubs, global_hubs=None):
        self.线段序列 = [_Segment(0, internal_hubs)]
        self.笔_中枢序列 = global_hubs if global_hubs is not None else []


def main() -> int:
    base = run_fixture("test_data.csv")
    assert base["schema_version"] == "2.0"
    detail = base["periods_detail"]["day"]
    assert "走势判据" in detail
    assert "全局走势" in detail
    assert "当前线段结构" in detail
    assert all(
        "完整性" in hub
        for hub in detail.get("线段内部笔中枢", [])
    )
    assert "核心买卖点信息" in detail
    assert detail["核心买卖点信息"]["匹配API"]
    assert all("标准信号" in d for d in base["periods_detail"].values())

    trend = run_fixture("test_data_trend.csv")
    trend_detail = trend["periods_detail"]["day"]
    assert trend_detail["笔中枢口径"] == "线段内部合中枢"
    assert "线段内部笔中枢" in trend_detail
    assert not any(
        s["类型"].startswith(("T1", "T1P"))
        for s in trend_detail["标准信号"]
    )

    # Structural template is authoritative; divergence alone is insufficient.
    complete_obs = _Observer([
        _Hub(0, 100, 200, 20, 30),
        _Hub(1, 300, 400, 10, 15),
    ])
    ok, evidence = analyzer._first_class_context(
        _Stroke(500),
        complete_obs,
        {"类型": "趋势", "方向": "下跌", "判据来源": "线段内部笔中枢"},
        True,
        False,
    )
    assert ok and evidence["结构模板"] == "a+A+b+B+c"
    # Raw global pen hubs are audit-only and must not supply A/B structure.
    global_only_obs = _Observer([], [_Hub(9, 100, 200, 20, 30)])
    ok, evidence = analyzer._first_class_context(
        _Stroke(500),
        global_only_obs,
        {"类型": "盘整", "方向": "震荡/未定", "判据来源": "线段内部笔中枢"},
        True,
        True,
    )
    assert not ok and evidence["前置已形成有效中枢数量"] == 0
    # A formed but core-incomplete hub is still a valid A/B.  Completeness
    # remains exposed as evidence rather than being used as a hard gate.
    incomplete_obs = _Observer([
        _Hub(0, 100, 200, 20, 30, complete=False),
        _Hub(1, 300, 400, 10, 15, complete=True),
    ])
    ok, _ = analyzer._first_class_context(
        _Stroke(500),
        incomplete_obs,
        {"类型": "趋势", "方向": "下跌", "判据来源": "线段内部笔中枢"},
        True,
        True,
    )
    assert ok
    unformed_obs = _Observer([
        _Hub(0, 100, 200, 20, 30, complete=False, formed=False),
        _Hub(1, 300, 400, 10, 15, complete=True),
    ])
    ok, _ = analyzer._first_class_context(
        _Stroke(500),
        unformed_obs,
        {"类型": "趋势", "方向": "下跌", "判据来源": "线段内部笔中枢"},
        True,
        True,
    )
    assert not ok

    t3b = run_fixture("test_data_t3b.csv")
    assert any(
        s["类型"].startswith("T3A")
        for s in t3b["periods_detail"]["day"]["标准信号"]
    )
    t3a = run_fixture("test_data_t3a.csv")
    assert any(
        s["类型"].startswith("T3A")
        for s in t3a["periods_detail"]["day"]["标准信号"]
    )
    print("golden regression passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
