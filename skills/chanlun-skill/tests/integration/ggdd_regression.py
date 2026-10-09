#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression contract for hub ZD/ZG/GG/DD values on live historical data.

The cases fixture records the expected structural result for stable historical
windows. The test uses the same eltdx loader and Rust-first observer path as
chan_analyzer.py, covering both segment-internal and pen-hub fallback scopes.
"""

import json
from pathlib import Path
import sys

SKILL_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = SKILL_ROOT / "scripts"
FIXTURES_DIR = SKILL_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(RUNTIME_DIR))

import chan_analyzer as analyzer
from chanlun import 缠论配置
from rust_adapter import create_observer


CASES = FIXTURES_DIR / "ggdd_regression_cases.json"
SECONDS = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "60m": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
}
TOLERANCE = 1e-6


def _observer(code: str, freq: str, count: int):
    seconds = SECONDS[freq]
    rows = analyzer.load_eltdx_data(
        code, freq, count=count, page_size=800, max_pages=10, adjust="qfq"
    )
    observer = create_observer(code, seconds, 缠论配置.不推送())
    for index, row in enumerate(rows):
        analyzer.append_raw_kline(
            observer, code, analyzer._parse_date(row["date"], index), row, index, seconds
        )
    return observer


def _latest_hub(observer: object):
    hubs = []
    for segment in observer.线段序列:
        hubs.extend(getattr(segment, "合_中枢序列", []))
    if hubs:
        return "segment", hubs[-1]
    hubs = list(getattr(observer, "笔_中枢序列", []))
    if hubs:
        return "pen", hubs[-1]
    raise AssertionError("没有可用中枢")


def _assert_close(actual: float, expected: float, label: str) -> None:
    if abs(actual - expected) > TOLERANCE:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def main() -> int:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    for case in cases:
        observer = _observer(case["code"], case["freq"], case["count"])
        source, hub = _latest_hub(observer)
        assert source == case["expected_source"], (
            f"{case['code']} {case['freq']}: expected {case['expected_source']}, got {source}"
        )
        _assert_close(hub.低, case["zd"], "ZD")
        _assert_close(hub.高, case["zg"], "ZG")
        _assert_close(hub.低低, case["dd"], "DD")
        _assert_close(hub.高高, case["gg"], "GG")
    print(f"GG/DD regression passed ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
