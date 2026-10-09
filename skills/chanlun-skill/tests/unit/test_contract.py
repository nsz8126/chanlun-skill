#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lightweight contract tests that do not require the Rust extension."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

SKILL_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(RUNTIME_DIR))

from data_quality import inspect_rows
from semantic import build_period_summary
from signal_contract import normalize_signal, transition_signal_state
from signal_schema import (
    REQUIRED_FIELDS,
    VALID_DIRECTIONS,
    VALID_TYPES,
    validate_signal,
    validate_standard_signals,
)
from check_dependencies import read_requirements


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


def test_dependency_checker_reads_direct_wheel_url_version():
    requirements = read_requirements()
    assert requirements["chanlun"] == "2606.73"
    assert requirements["eltdx"] == "3.2.2"
    assert requirements["PyYAML"] == "6.0.3"


def test_data_quality_counts_nonadjacent_duplicate_timestamps():
    rows = [
        {"date": "2026-01-01", "open": 1, "high": 2, "low": 0, "close": 1, "volume": 1},
        {"date": "2026-01-02", "open": 1, "high": 2, "low": 0, "close": 1, "volume": 1},
        {"date": "2026-01-01", "open": 1, "high": 2, "low": 0, "close": 1, "volume": 1},
    ]
    quality = inspect_rows(rows, 86400)
    assert quality["重复时间"] == 1
    assert quality["乱序数量"] == 1
    assert not quality["可用于分析"]


def test_data_quality_normalizes_explicit_timezone_and_midnight_boundary():
    rows = [
        {"date": "2026-01-02T23:59:00+08:00", "open": 1, "high": 2, "low": 0, "close": 1, "volume": 1},
        {"date": "2026-01-03T00:00:00+08:00", "open": 1, "high": 2, "low": 0, "close": 1, "volume": 1},
    ]
    quality = inspect_rows(rows, 60)
    expected_first = datetime.fromisoformat(rows[0]["date"]).timestamp()
    expected_last = datetime.fromisoformat(rows[1]["date"]).timestamp()
    assert quality["可用于分析"]
    assert quality["首个时间"] == expected_first
    assert quality["末个时间"] == expected_last
    assert quality["大间隔数量"] == 0


def test_data_quality_assumes_utc_for_naive_timestamps():
    rows = [
        {"date": "2026-01-02", "open": 1, "high": 2, "low": 0, "close": 1, "volume": 1},
        {"date": "2026-01-02T00:00:00Z", "open": 1, "high": 2, "low": 0, "close": 1, "volume": 1},
    ]
    quality = inspect_rows(rows)
    expected = datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp()
    assert quality["首个时间"] == expected
    assert quality["末个时间"] == expected
    assert quality["重复时间"] == 1


def test_semantic_summary_contains_facts_and_interpretations():
    detail = {
        "走势类型": "趋势",
        "线段": 3,
        "中枢": 1,
        "当前线段": {"方向": "向上", "高": 12.8, "低": 11.2},
        "当前中枢": {"高": 12.0, "低": 11.4, "状态": "延伸"},
        "买卖点": [{
            "kind": "T3A买",
            "time": "2026-01-01 09:35",
            "结构失效边界": 11.4,
            "结构失效条件": "回调重新进入已突破中枢",
            "来源": "rust_structure+skill_classifier",
        }],
        "背驰": [],
    }
    summary = build_period_summary(detail, {"可用于分析": True})
    assert summary["事实"]
    assert summary["解释"][0]["结论"] == "最近出现T3A买候选信号"
    assert "情景" not in summary


def _sample_signal():
    return normalize_signal(
        {
            "kind": "T1买",
            "base": "一买",
            "确认级别": "候选",
            "结构来源": "rust_core",
            "类型来源": "skill_classifier",
            "核心判据": {"结构模板": "a+A+b+B+c"},
            "index": 1,
            "time": "2026-01-01 09:35",
            "high": 12.0,
            "low": 10.5,
            "结构失效边界": 10.0,
            "结构失效条件": "后续回调跌破一买端点",
        },
        "day",
        {"类型": "趋势", "方向": "向上"},
    )


def test_signal_schema_accepts_candidate_without_execution_flag():
    signal = _sample_signal()
    assert not validate_signal(signal)
    assert validate_standard_signals([signal], "day")["有效"]


def test_json_schema_matches_python_signal_contract():
    schema_path = SKILL_ROOT / "references" / "standard-signal.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert set(schema["required"]) == set(REQUIRED_FIELDS)
    assert set(schema["properties"]["类型"]["enum"]) == VALID_TYPES
    assert set(schema["properties"]["方向"]["enum"]) == VALID_DIRECTIONS
    assert schema["properties"]["确认状态"] == {"$ref": "#/$defs/state"}
    assert schema["$defs"]["state"]["enum"] == ["候选", "已确认", "已失效"]
    sample = _sample_signal()
    assert not validate_signal(sample)
    validator = Draft202012Validator(schema)
    assert validator.is_valid(sample)
    invalid = {**sample, "方向": "卖"}
    assert not validator.is_valid(invalid)


def test_external_trading_metadata_does_not_change_structure_candidate():
    raw = {
        "kind": "T1买",
        "base": "一买",
        "确认级别": "候选",
        "结构来源": "rust_core",
        "类型来源": "skill_classifier",
        "止损": {"破位值": 10.0, "有效性": False},
        "index": 1,
        "time": "2026-01-01 09:35",
        "high": 12.0,
        "low": 10.5,
        "结构失效边界": 10.0,
        "结构失效条件": "后续回调跌破一买端点",
    }
    signal = normalize_signal(raw, "day")
    assert signal["确认状态"] == "候选"
    assert signal["状态轨迹"][-1]["原因"] == "核心结构命中，等待后续K线确认"
    assert signal["结构失效边界"] == 10.0


def test_signal_state_machine_is_strict():
    signal = _sample_signal()
    assert signal["确认状态"] == "候选"
    transition_signal_state(signal, "已确认", "后续K线确认")
    assert signal["确认状态"] == "已确认"
    transition_signal_state(signal, "已失效", "跌破止损")
    assert signal["确认状态"] == "已失效"
    try:
        transition_signal_state(signal, "已确认", "不得复活")
    except ValueError as exc:
        assert "非法状态流转" in str(exc)
    else:
        raise AssertionError("已失效信号不应允许回到已确认")

if __name__ == "__main__":
    test_data_quality_rejects_bad_time_and_ohlc()
    test_dependency_checker_reads_direct_wheel_url_version()
    test_data_quality_counts_nonadjacent_duplicate_timestamps()
    test_data_quality_normalizes_explicit_timezone_and_midnight_boundary()
    test_data_quality_assumes_utc_for_naive_timestamps()
    test_semantic_summary_contains_facts_and_interpretations()
    test_signal_schema_accepts_candidate_without_execution_flag()
    test_json_schema_matches_python_signal_contract()
    test_external_trading_metadata_does_not_change_structure_candidate()
    test_signal_state_machine_is_strict()
    print("contract tests passed")
