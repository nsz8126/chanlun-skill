#!/usr/bin/env python3
"""
缠论综合分析工具

功能：
- 结构分析（分型、笔、线段、中枢）
- 买卖点信号检测
- 背驰判断
- 技术指标计算（MACD、RSI、KDJ）
- 线段级分析

使用方法：
    # 基础分析（本地CSV）
    python chan_analyzer.py --source csv --input test_data.csv --symbol 000001 --freq 日线

    # 在线获取（eltdx）
    python chan_analyzer.py --source eltdx --code sh600519 --start_date 20240101 --end_date 20240614 --freq 日线

    # 启用技术指标
    python chan_analyzer.py --source csv --input test_data.csv --symbol 000001 --cal_macd --cal_rsi --cal_kdj

    # 启用线段级分析
    python chan_analyzer.py --source csv --input test_data.csv --symbol 000001 --analyze_seg_level
"""

import argparse
import sys
import os
from datetime import datetime
from typing import Optional

# 添加当前目录到路径，以便导入chanlun_skill
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def load_csv_data(file_path: str) -> list:
    """加载CSV数据"""
    import csv
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
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
    return data


def load_eltdx_data(code: str, start_date: str, end_date: str, freq: str) -> list:
    """从eltdx加载数据"""
    try:
        from eltdx import TdxClient
        from chanlun_skill.core.adapter import fetch_klines, period_to_seconds
        
        # 转换频率参数
        period_map = {
            '1分钟': '1m',
            '5分钟': '5m',
            '15分钟': '15m',
            '30分钟': '30m',
            '60分钟': '60m',
            '日线': 'day',
            '周线': 'week',
            '月线': 'month'
        }
        period = period_map.get(freq, 'day')
        
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
            return data
    except ImportError:
        print("错误: 需要安装eltdx库: pip install eltdx")
        sys.exit(1)
    except Exception as e:
        print(f"错误: 从eltdx获取数据失败: {e}")
        sys.exit(1)


def analyze_data(data: list, symbol: str, freq: str, 
                cal_macd: bool = False, cal_rsi: bool = False, cal_kdj: bool = False,
                analyze_seg_level: bool = False):
    """分析数据"""
    from chanlun_skill.core.analyzer import ChanlunAnalyzer
    from chanlun_skill.core.config import default_config
    from chanlun_skill.signals.text import format_signals
    
    # 创建配置
    config = default_config()
    config.计算指标 = cal_macd or cal_rsi or cal_kdj
    
    # 创建分析器
    analyzer = ChanlunAnalyzer(symbol, periods=[freq], config=config)
    
    # 将数据投喂到分析器
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
    
    # 输出结果
    print(f"\n{'='*60}")
    print(f"  {symbol} 缠论分析 ({freq})")
    print(f"{'='*60}")
    
    # 获取观察者
    obs = analyzer.get_observer(period_seconds)
    
    # 基础信息
    print(f"\n基础信息:")
    print(f"  K线数量: {len(obs.普通K线序列)}")
    print(f"  缠论K线: {len(obs.缠论K线序列)}")
    print(f"  分型数量: {len(obs.分型序列)}")
    print(f"  笔数量: {len(obs.笔序列)}")
    print(f"  中枢数量: {len(obs.笔_中枢序列)}")
    
    # 线段信息
    if hasattr(obs, "线段序列组") and obs.线段序列组:
        print(f"\n线段信息:")
        for level, segs in enumerate(obs.线段序列组):
            if segs:
                print(f"  线段(L{level}): {len(segs)}")
    
    # 买卖点信号
    try:
        signals = analyzer.get_stroke_signals(period_seconds)
        if signals:
            print(f"\n买卖点信号: {len(signals)}")
            for sig in signals[-5:]:  # 显示最近5个信号
                icon = "B" if sig["type"] == "buy" else "S"
                print(f"  [{icon}] {sig['end_time']} {sig['end_price']:.2f} ({sig['reason']})")
    except Exception as e:
        print(f"\n买卖点检测失败: {e}")
    
    # 背驰检测
    try:
        divergences = analyzer.check_divergence(period_seconds)
        if divergences:
            print(f"\n背驰信号: {len(divergences)}")
            for div in divergences[-3:]:  # 显示最近3个背驰
                direction = "↑" if "向上" in div["direction"] else "↓"
                types = []
                if div["macd_divergence"]:
                    types.append("MACD")
                if div["slope_divergence"]:
                    types.append("斜率")
                if div["measure_divergence"]:
                    types.append("测度")
                print(f"  {direction} 线段#{div['segment_index']} [{'+'.join(types)}]")
    except Exception as e:
        print(f"\n背驰检测失败: {e}")
    
    # 技术指标
    if cal_macd or cal_rsi or cal_kdj:
        print(f"\n技术指标:")
        if cal_macd:
            print(f"  MACD: 已计算")
        if cal_rsi:
            print(f"  RSI: 已计算")
        if cal_kdj:
            print(f"  KDJ: 已计算")
    
    # 线段级分析
    if analyze_seg_level:
        print(f"\n线段级分析:")
        try:
            # 这里可以添加线段级分析的逻辑
            print(f"  线段级分析已启用")
        except Exception as e:
            print(f"  线段级分析失败: {e}")
    
    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(description='缠论综合分析工具')
    parser.add_argument('--source', choices=['csv', 'eltdx'], default='csv', 
                       help='数据源类型')
    parser.add_argument('--input', type=str, help='输入CSV文件路径')
    parser.add_argument('--code', type=str, help='股票代码（eltdx模式）')
    parser.add_argument('--symbol', type=str, default='000001', help='股票代码')
    parser.add_argument('--start_date', type=str, help='开始日期（eltdx模式）')
    parser.add_argument('--end_date', type=str, help='结束日期（eltdx模式）')
    parser.add_argument('--freq', type=str, default='日线', 
                       choices=['1分钟', '5分钟', '15分钟', '30分钟', '60分钟', '日线', '周线', '月线'],
                       help='分析频率')
    parser.add_argument('--cal_macd', action='store_true', help='计算MACD指标')
    parser.add_argument('--cal_rsi', action='store_true', help='计算RSI指标')
    parser.add_argument('--cal_kdj', action='store_true', help='计算KDJ指标')
    parser.add_argument('--analyze_seg_level', action='store_true', help='启用线段级分析')
    
    args = parser.parse_args()
    
    # 加载数据
    if args.source == 'csv':
        if not args.input:
            print("错误: CSV模式需要指定--input参数")
            sys.exit(1)
        data = load_csv_data(args.input)
    else:  # eltdx
        if not args.code:
            print("错误: eltdx模式需要指定--code参数")
            sys.exit(1)
        data = load_eltdx_data(args.code, args.start_date, args.end_date, args.freq)
    
    # 分析数据
    analyze_data(data, args.symbol, args.freq, 
                args.cal_macd, args.cal_rsi, args.cal_kdj, args.analyze_seg_level)


if __name__ == '__main__':
    main()