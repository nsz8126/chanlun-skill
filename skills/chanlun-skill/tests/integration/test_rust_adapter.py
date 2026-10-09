#!/usr/bin/env python3
"""Pinned Rust/PyO3 binding smoke test for the observer adapter."""

from pathlib import Path
import sys

SKILL_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(RUNTIME_DIR))

import chan_analyzer as analyzer
from chanlun import 缠论配置, 观察者
from rust_adapter import append_raw_kline, create_observer


def main() -> int:
    rows = analyzer.load_csv_data(
        str(SKILL_ROOT / "tests" / "fixtures" / "test_data.csv")
    )[:3]
    assert len(rows) == 3

    observer = create_observer(
        "adapter-smoke", 86400, 缠论配置.不推送()
    )
    second_observer = create_observer(
        "adapter-smoke", 604800, 缠论配置.不推送()
    )
    assert isinstance(observer, 观察者)
    assert isinstance(second_observer, 观察者)
    assert observer is not second_observer
    assert observer.周期 == 86400
    assert second_observer.周期 == 604800
    assert observer.配置 is not second_observer.配置

    for index, row in enumerate(rows):
        append_raw_kline(
            observer,
            "adapter-smoke",
            analyzer._parse_date(row["date"], index),
            row,
            index,
            86400,
        )

    assert len(observer.普通K线序列) == len(rows)
    assert len(observer.普通K线序列) >= 2
    print("Rust adapter smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
