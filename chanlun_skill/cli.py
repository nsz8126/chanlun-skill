"""命令行入口。"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        prog="chanlun-skill",
        description="A股缠论分析 — 基于 chanlun + eltdx",
    )
    parser.add_argument("symbol", help="股票代码 (如 sz000001, sh600000)")
    parser.add_argument(
        "--periods",
        default="1m,5m,30m,day",
        help="分析周期，逗号分隔 (默认: 1m,5m,30m,day)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=800,
        help="每个周期获取的K线数量 (默认: 800)",
    )
    parser.add_argument(
        "--adjust",
        choices=["qfq", "hfq"],
        default=None,
        help="复权模式: qfq=前复权, hfq=后复权 (默认: 不复权)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="仅输出简要摘要",
    )

    args = parser.parse_args(argv)
    periods = [p.strip() for p in args.periods.split(",") if p.strip()]

    try:
        from eltdx import TdxClient
    except ImportError:
        print("错误: 请先安装 eltdx: pip install eltdx", file=sys.stderr)
        sys.exit(1)

    from chanlun_skill.core.analyzer import ChanlunAnalyzer
    from chanlun_skill.signals.text import format_signals, format_summary

    print(f"正在连接行情服务器并获取 {args.symbol} 数据...")

    try:
        with TdxClient(timeout=10) as client:
            analyzer = ChanlunAnalyzer(args.symbol, periods=periods)
            counts = analyzer.feed_batch(client, counts={p: args.count for p in periods}, adjust=args.adjust)

            for period, count in counts.items():
                print(f"  {period}: 投喂 {count} 根K线")

            # 识别买卖点
            analyzer.identify_signals()

            if args.summary:
                print(format_summary(analyzer))
            else:
                print(format_signals(analyzer))

    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
