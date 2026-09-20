#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lightweight contract tests that do not require the Rust extension."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from data_quality import inspect_rows
from semantic import build_period_summary
from signal_contract import normalize_signal, transition_signal_state
from signal_schema import validate_signal, validate_standard_signals
from strategy_plan import build_strategy_plan


def test_data_quality_rejects_bad_time_and_ohlc():
    rows = [
        {"date": "bad", "open": 1, "high": 0, "low": 2, "close": 1, "volume": 1},
        {"date": "2026-01-01 09:35", "open": 1, "high": 2, "low": 0, "close": 1, "volume": 1},
    ]
    quality = inspect_rows(rows, 300)
    assert not quality["可用于分析"]
    issue_types = {item["类型"] for item in quality["问题"]}
    assert "时间无法解析" in issue_types
    assert "OHLC区间非法" in issue_types


def test_semantic_summary_keeps_strategy_conditional():
    detail = {
        "走势类型": "趋势",
        "线段": 3,
        "中枢": 1,
        "当前线段": {"方向": "向上", "高": 12.8, "低": 11.2},
        "当前中枢": {"高": 12.0, "低": 11.4, "状态": "延伸"},
        "买卖点": [{
            "kind": "T3A买",
            "time": "2026-01-01 09:35",
            "break": 11.4,
            "来源": "rust_core+skill_classifier",
            "止损": {"破位值": 11.4, "有效性": True},
        }],
        "背驰": [],
    }
    summary = build_period_summary(detail, {"可用于分析": True})
    assert summary["情景"][0]["名称"] == "主情景"
    assert "入场条件" in summary["情景"][0]
    assert summary["情景"][0]["来源"] == "rust_core+skill_classifier"


def _sample_signal():
    return normalize_signal(
        {
            "kind": "T1买",
            "base": "一买",
            "确认级别": "候选",
            "结构来源": "rust_core",
            "类型来源": "skill_classifier",
            "止损来源": "rust_factory",
            "止损": {"破位值": 10.0, "有效性": True},
            "核心判据": {"买卖意义": True},
            "核心匹配": {"任意": True},
            "index": 1,
            "time": "2026-01-01 09:35",
            "high": 12.0,
            "low": 10.5,
            "break": 10.0,
        },
        "day",
        {"类型": "趋势", "方向": "向上"},
    )


def test_signal_schema_rejects_executable_candidate():
    signal = _sample_signal()
    signal["可执行"] = True
    errors = validate_signal(signal)
    assert any("可执行与确认状态" in error for error in errors)
    assert not validate_standard_signals([signal], "day")["有效"]


def test_signal_state_machine_is_strict():
    signal = _sample_signal()
    assert signal["确认状态"] == "候选"
    transition_signal_state(signal, "已确认", "后续K线确认")
    assert signal["可执行"] is True
    transition_signal_state(signal, "已失效", "跌破止损")
    assert signal["可执行"] is False
    try:
        transition_signal_state(signal, "已确认", "不得复活")
    except ValueError as exc:
        assert "非法状态流转" in str(exc)
    else:
        raise AssertionError("已失效信号不应允许回到已确认")


def test_strategy_plan_does_not_wait_on_invalid_signal():
    signal = _sample_signal()
    transition_signal_state(signal, "已失效", "跌破止损")
    plan = build_strategy_plan(
        {
            "走势判据": {"方向": "向上"},
            "标准信号": [signal],
            "标准信号校验": {"有效": True},
            "数据质量": {"可用于分析": True},
        }
    )
    assert plan["状态"] == "观望"
    assert "已失效" in plan["失效条件"]


if __name__ == "__main__":
    test_data_quality_rejects_bad_time_and_ohlc()
    test_semantic_summary_keeps_strategy_conditional()
    test_signal_schema_rejects_executable_candidate()
    test_signal_state_machine_is_strict()
    test_strategy_plan_does_not_wait_on_invalid_signal()
    print("contract tests passed")
