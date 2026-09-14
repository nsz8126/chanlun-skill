"""创建更长的测试数据并测试分析。"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, timedelta
from chanlun import K线
from chanlun_skill.core.analyzer import ChanlunAnalyzer
from chanlun_skill.core.config import default_config

def create_mock_klines(count: int = 500, start_price: float = 10.0):
    """创建模拟K线数据，包含足够的波动以形成笔。"""
    klines = []
    current_price = start_price
    base_time = datetime(2024, 1, 1)
    
    for i in range(count):
        # 生成随机波动
        import random
        random.seed(i)  # 固定种子确保可重复
        
        # 价格波动
        change = random.uniform(-0.05, 0.05)
        current_price = max(current_price * (1 + change), 1.0)
        
        # K线数据
        open_price = current_price
        high_price = open_price * (1 + random.uniform(0, 0.03))
        low_price = open_price * (1 - random.uniform(0, 0.03))
        close_price = open_price * (1 + random.uniform(-0.02, 0.02))
        volume = random.randint(1000000, 5000000)
        
        # 时间戳
        timestamp = int((base_time + timedelta(hours=i)).timestamp())
        
        kline = K线.创建普K(
            标识="sz000001",
            时间戳=timestamp,
            开盘价=open_price,
            最高价=high_price,
            最低价=low_price,
            收盘价=close_price,
            成交量=volume,
            序号=i,
            周期=86400
        )
        klines.append(kline)
    
    return klines

def test_with_mock_data():
    """使用模拟数据测试分析功能。"""
    print("=" * 60)
    print("模拟数据分析测试")
    print("=" * 60)
    
    # 创建分析器
    cfg = default_config()
    analyzer = ChanlunAnalyzer("sz000001", periods=["5m", "day"], config=cfg)
    
    # 创建模拟K线
    klines = create_mock_klines(count=500, start_price=10.0)
    print(f"创建K线数量: {len(klines)}")
    
    # 投喂到日线周期
    obs = analyzer.get_observer(86400)
    for kline in klines:
        obs.增加原始K线(kline)
    
    # 获取结构数据
    print("\n--- 日线结构 ---")
    structure = analyzer.get_structure(86400)
    print(f"原始K线: {structure['kline_count']}")
    print(f"缠论K线: {structure['chan_kline_count']}")
    print(f"分型: {structure['fractal_count']}")
    print(f"笔: {structure['stroke_count']}")
    print(f"中枢: {structure['hub_count']}")
    
    # 获取笔序列
    print("\n--- 笔序列 (前10个) ---")
    strokes = analyzer.get_strokes(86400)
    for s in strokes[:10]:
        print(f"笔{s['index']}: {s['direction']}, 开始={s['start_price']:.2f}, 结束={s['end_price']:.2f}")
    
    # 获取线段
    print("\n--- 线段序列 ---")
    segments = analyzer.get_segments(86400, level=0)
    print(f"线段数量: {len(segments)}")
    for seg in segments[:5]:
        print(f"线段{seg['index']}: {seg['direction']}, 级别={seg['level']}")
    
    # 获取中枢
    print("\n--- 中枢序列 ---")
    hubs = analyzer.get_hubs(86400)
    print(f"中枢数量: {len(hubs)}")
    for h in hubs[:3]:
        print(f"中枢{h['index']}: 低={h['low']:.2f}, 高={h['high']:.2f}")
    
    # 获取信号
    print("\n--- 买卖点信号 ---")
    signals = analyzer.get_signals(86400)
    print(f"信号数量: {len(signals)}")
    for s in signals[:5]:
        print(f"{s['type']}: {s['reason']}")
    
    # 获取多级别摘要
    print("\n--- 多级别摘要 ---")
    summary = analyzer.get_multi_level_summary(86400)
    for level_name, data in summary["levels"].items():
        print(f"{level_name}: {data['count']}个, 信号{data['signal_count']}个")
    
    print("\n" + "=" * 60)
    print("模拟数据分析测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_with_mock_data()