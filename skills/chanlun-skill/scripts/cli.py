"""Command-line interface for Chan analysis."""

import argparse
import json
import sys

from chanlun import 缠论配置

try:
    from data_source import (
        _ELTDX_ADJUST_CHOICES,
        _ELTDX_DEFAULT_ADJUST,
        _ELTDX_DEFAULT_MAX_PAGES,
        _ELTDX_KLINE_PAGE_SIZE,
        load_csv_data,
        load_csv_periods,
        load_eltdx_data,
        period_to_seconds,
        seconds_to_name,
        upper_period,
    )
    from report import render_text
except ImportError:  # pragma: no cover - package-style import fallback
    from .data_source import (
        _ELTDX_ADJUST_CHOICES,
        _ELTDX_DEFAULT_ADJUST,
        _ELTDX_DEFAULT_MAX_PAGES,
        _ELTDX_KLINE_PAGE_SIZE,
        load_csv_data,
        load_csv_periods,
        load_eltdx_data,
        period_to_seconds,
        seconds_to_name,
        upper_period,
    )
    from .report import render_text


def main(analyze):
    parser = argparse.ArgumentParser(description="缠论综合分析工具（chanlun 核心库）")
    parser.add_argument("--source", choices=["csv", "eltdx"], default="csv", help="数据源")
    parser.add_argument("--input", type=str, help="CSV 文件路径（csv 模式）")
    parser.add_argument(
        "--input_periods", type=str,
        help="多周期 CSV 映射，如 day=day.csv,week=week.csv；提供后覆盖 --input",
    )
    parser.add_argument("--code", type=str, help="股票代码（eltdx 模式，如 sh600519）")
    parser.add_argument("--symbol", type=str, default=None,
                        help="标的标识（默认：csv 模式为 000001，eltdx 模式为 code）")
    parser.add_argument("--start_date", type=str, help="开始日期 YYYY-MM-DD（eltdx）")
    parser.add_argument("--end_date", type=str, help="结束日期 YYYY-MM-DD（eltdx）")
    parser.add_argument("--freq", type=str, default="day",
                        help="分析周期（1m/5m/.../day/week/month 或中文）")
    parser.add_argument("--count", type=int, default=800,
                        help="eltdx 拉取 K 线总数（超过 800 自动分页）")
    parser.add_argument("--page-size", type=int, default=_ELTDX_KLINE_PAGE_SIZE,
                        help="eltdx 单页数量（1~800，默认 800）")
    parser.add_argument("--max-pages", type=int, default=_ELTDX_DEFAULT_MAX_PAGES,
                        help="eltdx 最大分页次数（默认 200）")
    parser.add_argument("--adjust", type=str, default=_ELTDX_DEFAULT_ADJUST,
                        choices=list(_ELTDX_ADJUST_CHOICES),
                        help="eltdx 复权模式（默认 qfq 前复权；可选 none/hfq/fixed_qfq/fixed_hfq）")
    parser.add_argument("--anchor-date", "--anchor_date", dest="anchor_date", type=str,
                        help="定点复权锚定日期 YYYY-MM-DD（fixed_qfq/fixed_hfq 必填）")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    parser.add_argument("--output", type=str, help="输出文件路径")
    parser.add_argument("--cal_indicators", action="store_true", default=True,
                        help="计算技术指标（默认开）")
    parser.add_argument("--笔内元素数量", type=int, default=None,
                        help="成笔最低 K 线数（默认 5，改 3 笔数可增加约 2.9 倍）")
    parser.add_argument("--boll", action="store_true", help="计算 BOLL 布林带")
    parser.add_argument("--均线", type=str, default=None,
                        help="计算均线，逗号分隔周期（如 5,20,60）")
    parser.add_argument("--均线类型", type=str, default="SMA",
                        help="均线类型（SMA/EMA，逗号分隔，如 SMA,EMA）")
    parser.add_argument("--指标计算方式", type=str, default=None,
                        choices=["收", "高", "低"],
                        help="指标计算基准（默认 收）")
    args = parser.parse_args()

    try:
        freq_seconds = period_to_seconds(args.freq)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)

    if args.source == "csv":
        if args.input_periods:
            data_by_period = load_csv_periods(args.input_periods)
        elif args.input:
            data_by_period = {freq_seconds: load_csv_data(args.input)}
        else:
            print("错误：csv 模式需要 --input 或 --input_periods", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.code:
            print("错误：eltdx 模式需要 --code", file=sys.stderr)
            sys.exit(1)
        data_by_period = {}
        up = upper_period(freq_seconds)
        for period in sorted({freq_seconds, up}):
            period_name = seconds_to_name(period)
            rows = load_eltdx_data(
                args.code,
                period_name,
                args.start_date,
                args.end_date,
                args.count,
                args.page_size,
                args.max_pages,
                args.adjust,
                args.anchor_date,
            )
            if len(rows) >= 2:
                data_by_period[period] = rows

    if not data_by_period:
        print("错误：数据不足（<2 根 K 线），无法分析", file=sys.stderr)
        sys.exit(1)

    config = 缠论配置.不推送()
    config.计算指标 = args.cal_indicators
    if args.笔内元素数量 is not None:
        config.笔内元素数量 = args.笔内元素数量
    if args.boll:
        config.计算BOLL = True
    if args.均线:
        periods = [int(value) for value in args.均线.split(",") if value.strip()]
        types = [value.strip().upper() for value in args.均线类型.split(",") if value.strip()]
        config.均线_类型列表 = [value for value in types if value in ("SMA", "EMA")] or ["SMA"]
        config.均线_周期列表 = periods
    if args.指标计算方式 is not None:
        config.指标计算方式 = args.指标计算方式

    symbol = args.symbol or (args.code if args.source == "eltdx" else "000001")
    try:
        result = analyze(symbol, data_by_period, config)
        result["data_source"] = {
            "source": args.source,
            "复权模式": args.adjust if args.source == "eltdx" else "csv原样",
            "anchor_date": args.anchor_date if args.source == "eltdx" else None,
        }
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except BaseException as exc:
        print(f"错误：分析失败（{type(exc).__name__}）：{exc}", file=sys.stderr)
        sys.exit(1)

    output = (
        json.dumps(result, ensure_ascii=False, indent=2, default=str)
        if args.json else render_text(result)
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(output)
        print(f"报告已保存到 {args.output}")
    else:
        print(output)


__all__ = ["main"]
