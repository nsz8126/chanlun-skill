"""使用CSV数据进行分析测试。"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import csv
from datetime import datetime
from chanlun import K线
from chanlun_skill.core.analyzer import ChanlunAnalyzer

def load_csv_to_analyzer(csv_path: str, analyzer: ChanlunAnalyzer, period_seconds: int = 86400):
    """将CSV数据加载到分析器。"""
    klines = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 解析日期并转换为int时间戳
            date_str = row['date']
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            timestamp = int(dt.timestamp())
            
            # 创建K线
            kline = K线.创建普K(
                标识="sz000001",
                时间戳=timestamp,
                开盘价=float(row['open']),
                最高价=float(row['high']),
                最低价=float(row['low']),
                收盘价=float(row['close']),
                成交量=float(row['volume']),
                序号=len(klines),
                周期=period_seconds
            )
            klines.append(kline)
    
    # 投喂到分析器
    obs = analyzer.get_observer(period_seconds)
    for kline in klines:
        obs.增加原始K线(kline)
    
    return len(klines)


def test_with_csv():
    """使用CSV数据测试分析功能。"""
    print("=" * 60)
    print("CSV数据分析测试")
    print("=" * 60)
    
    # 创建分析器（至少需要2个周期）
    analyzer = ChanlunAnalyzer("sz000001", periods=["5m", "day"])
    
    # 加载CSV数据到日线周期
    csv_path = Path(__file__).parent / "skills" / "chanlun-skill" / "scripts" / "test_data.csv"
    kline_count = load_csv_to_analyzer(str(csv_path), analyzer, period_seconds=86400)
    print(f"加载K线数量: {kline_count}")
    
    # 获取结构数据
    print("\n--- 日线结构 ---")
    structure = analyzer.get_structure(86400)
    print(f"原始K线: {structure['kline_count']}")
    print(f"缠论K线: {structure['chan_kline_count']}")
    print(f"分型: {structure['fractal_count']}")
    print(f"笔: {structure['stroke_count']}")
    print(f"中枢: {structure['hub_count']}")
    
    # 获取笔序列
    print("\n--- 笔序列 ---")
    strokes = analyzer.get_strokes(86400)
    for s in strokes[:5]:
        print(f"笔{s['index']}: {s['direction']}, 开始={s['start_time']}, 结束={s['end_time']}")
    
    # 获取线段
    print("\n--- 线段序列 ---")
    segments = analyzer.get_segments(86400, level=0)
    for seg in segments[:5]:
        print(f"线段{seg['index']}: {seg['direction']}, 级别={seg['level']}")
    
    # 获取中枢
    print("\n--- 中枢序列 ---")
    hubs = analyzer.get_hubs(86400)
    for h in hubs[:3]:
        print(f"中枢{h['index']}: 低={h['low']}, 高={h['high']}")
    
    # 获取信号
    print("\n--- 买卖点信号 ---")
    signals = analyzer.get_signals(86400)
    for s in signals[:5]:
        print(f"{s['type']}: {s['reason']}")
    
    # 获取多级别摘要
    print("\n--- 多级别摘要 ---")
    summary = analyzer.get_multi_level_summary(86400)
    for level_name, data in summary["levels"].items():
        print(f"{level_name}: {data['count']}个, 信号{data['signal_count']}个")
    
    print("\n" + "=" * 60)
    print("CSV数据分析测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_with_csv()