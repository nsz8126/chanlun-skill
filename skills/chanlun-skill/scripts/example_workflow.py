#!/usr/bin/env python3
"""
缠论分析示例工作流

功能：
- 自动化执行完整分析流程
- 支持本地CSV和在线eltdx数据源
- 生成分析报告

使用方法：
    # 使用本地样例数据
    python example_workflow.py

    # 切换到在线数据源
    python example_workflow.py --source eltdx --code sh600519 --days 180

    # 指定输出文件
    python example_workflow.py --output report.txt
"""

import argparse
import sys
import os
from datetime import datetime, timedelta

# 添加当前目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def run_workflow(source: str = 'csv', code: str = None, days: int = 180, output: str = None):
    """运行分析工作流"""
    from chanlun_skill.core.analyzer import ChanlunAnalyzer
    from chanlun_skill.core.config import default_config
    from chanlun_skill.signals.text import format_signals, format_summary
    
    print("=" * 60)
    print("  缠论分析工作流")
    print("=" * 60)
    
    # 确定数据源
    if source == 'csv':
        # 使用本地CSV数据
        data_file = os.path.join(os.path.dirname(__file__), 'test_data.csv')
        if not os.path.exists(data_file):
            print(f"错误: 找不到数据文件 {data_file}")
            sys.exit(1)
        
        print(f"\n数据源: 本地CSV")
        print(f"数据文件: {data_file}")
        
        # 加载数据
        import csv
        data = []
        with open(data_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append({
                    'date': row['date'],
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                })
        
        symbol = "000001"
        freq = "日线"
        
    else:  # eltdx
        if not code:
            print("错误: eltdx模式需要指定--code参数")
            sys.exit(1)
        
        print(f"\n数据源: eltdx在线")
        print(f"股票代码: {code}")
        print(f"时间范围: 最近{days}天")
        
        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 加载数据
        try:
            from eltdx import TdxClient
            from chanlun_skill.core.adapter import fetch_klines, period_to_seconds
            
            # 转换频率参数
            period = 'day'
            
            # 连接服务器
            with TdxClient() as client:
                # 获取数据
                series = fetch_klines(client, code, period, count=800)
                
                # 转换格式
                data = []
                for bar in series.bars:
                    data.append({
                        'date': bar.time.strftime('%Y-%m-%d'),
                        'open': bar.open,
                        'high': bar.high,
                        'low': bar.low,
                        'close': bar.close,
                        'volume': bar.volume_lots
                    })
            
            symbol = code
            freq = "日线"
            
        except ImportError:
            print("错误: 需要安装eltdx库: pip install eltdx")
            sys.exit(1)
        except Exception as e:
            print(f"错误: 从eltdx获取数据失败: {e}")
            sys.exit(1)
    
    # 创建分析器
    print(f"\n创建分析器...")
    config = default_config()
    analyzer = ChanlunAnalyzer(symbol, periods=[freq], config=config)
    
    # 将数据投喂到分析器
    print(f"投喂数据 ({len(data)}根K线)...")
    from chanlun import K线
    from chanlun_skill.core.adapter import period_to_seconds
    
    period_seconds = period_to_seconds(freq)
    
    for i, row in enumerate(data):
        # 转换日期字符串为时间戳
        date_str = row['date']
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            ts = int(dt.timestamp())
        except:
            ts = i  # 使用索引作为时间戳
        
        # 创建K线
        k = K线.创建普K(
            symbol,
            ts,
            row['open'],
            row['high'],
            row['low'],
            row['close'],
            row['volume'],
            i,
            period_seconds
        )
        
        # 投喂K线
        analyzer.engine.投喂K线(k)
    
    # 执行分析
    print(f"执行缠论分析...")
    
    # 获取分析结果
    obs = analyzer.get_observer(period_seconds)
    
    # 生成报告
    report_lines = []
    report_lines.append("=" * 60)
    report_lines.append(f"  {symbol} 缠论分析报告")
    report_lines.append("=" * 60)
    report_lines.append(f"")
    report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"数据源: {source}")
    report_lines.append(f"分析周期: {freq}")
    report_lines.append(f"K线数量: {len(data)}")
    report_lines.append(f"")
    
    # 基础信息
    report_lines.append(f"基础信息:")
    report_lines.append(f"  K线数量: {len(obs.普通K线序列)}")
    report_lines.append(f"  缠论K线: {len(obs.缠论K线序列)}")
    report_lines.append(f"  分型数量: {len(obs.分型序列)}")
    report_lines.append(f"  笔数量: {len(obs.笔序列)}")
    report_lines.append(f"  中枢数量: {len(obs.笔_中枢序列)}")
    report_lines.append(f"")
    
    # 线段信息
    if hasattr(obs, "线段序列组") and obs.线段序列组:
        report_lines.append(f"线段信息:")
        for level, segs in enumerate(obs.线段序列组):
            if segs:
                report_lines.append(f"  线段(L{level}): {len(segs)}")
        report_lines.append(f"")
    
    # 买卖点信号
    try:
        signals = analyzer.get_stroke_signals(period_seconds)
        if signals:
            report_lines.append(f"买卖点信号: {len(signals)}")
            for sig in signals[-5:]:  # 显示最近5个信号
                icon = "B" if sig["type"] == "buy" else "S"
                report_lines.append(f"  [{icon}] {sig['end_time']} {sig['end_price']:.2f} ({sig['reason']})")
            report_lines.append(f"")
    except Exception as e:
        report_lines.append(f"买卖点检测失败: {e}")
        report_lines.append(f"")
    
    # 背驰检测
    try:
        divergences = analyzer.check_divergence(period_seconds)
        if divergences:
            report_lines.append(f"背驰信号: {len(divergences)}")
            for div in divergences[-3:]:  # 显示最近3个背驰
                direction = "↑" if "向上" in div["direction"] else "↓"
                types = []
                if div["macd_divergence"]:
                    types.append("MACD")
                if div["slope_divergence"]:
                    types.append("斜率")
                if div["measure_divergence"]:
                    types.append("测度")
                report_lines.append(f"  {direction} 线段#{div['segment_index']} [{'+'.join(types)}]")
            report_lines.append(f"")
    except Exception as e:
        report_lines.append(f"背驰检测失败: {e}")
        report_lines.append(f"")
    
    # 完整信号输出
    report_lines.append(f"完整信号输出:")
    report_lines.append(format_signals(analyzer))
    report_lines.append(f"")
    
    # 摘要输出
    report_lines.append(f"分析摘要:")
    report_lines.append(format_summary(analyzer))
    report_lines.append(f"")
    report_lines.append("=" * 60)
    
    # 生成报告
    report = "\n".join(report_lines)
    
    # 输出到控制台
    print(report)
    
    # 输出到文件
    if output:
        with open(output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\n报告已保存到: {output}")
    else:
        # 默认输出到控制台
        pass
    
    print(f"\n分析完成!")


def main():
    parser = argparse.ArgumentParser(description='缠论分析示例工作流')
    parser.add_argument('--source', choices=['csv', 'eltdx'], default='csv', 
                       help='数据源类型')
    parser.add_argument('--code', type=str, help='股票代码（eltdx模式）')
    parser.add_argument('--days', type=int, default=180, 
                       help='时间范围天数（eltdx模式）')
    parser.add_argument('--output', type=str, help='输出文件路径')
    
    args = parser.parse_args()
    
    run_workflow(args.source, args.code, args.days, args.output)


if __name__ == '__main__':
    main()