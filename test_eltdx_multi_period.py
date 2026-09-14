"""eltdx多周期集成测试。"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from eltdx import TdxClient
from eltdx.hosts import DEFAULT_HOSTS
from chanlun_skill.core.analyzer import ChanlunAnalyzer
from chanlun_skill.core.adapter import feed_klines_to_observer

def test_eltdx_multi_period():
    """测试eltdx多周期分析。"""
    print("=" * 60)
    print("eltdx多周期分析测试")
    print("=" * 60)
    
    try:
        # 连接eltdx
        client = TdxClient(hosts=DEFAULT_HOSTS[:3], timeout=15)
        client.connect()
        print("eltdx连接成功")
        
        # 创建分析器（多个周期）
        analyzer = ChanlunAnalyzer("sz000001", periods=["5m", "30m", "day"])
        print("分析器创建成功")
        
        # 立体分析器只接受最小周期数据，其他周期自动合成
        # 获取5分钟数据（最小周期）
        series = client.bars.get(
            code='000001',
            period='5m',
            count=800
        )
        count = feed_klines_to_observer(analyzer.engine, series)
        print(f"5分钟投喂: {count}根K线")
        
        # 获取各周期分析结果
        print("\n--- 各周期分析结果 ---")
        periods = [
            ("5m", 300),
            ("30m", 1800),
            ("day", 86400)
        ]
        for period_name, period_sec in periods:
            structure = analyzer.get_structure(period_sec)
            print(f"\n{period_name}:")
            print(f"  缠论K线: {structure['chan_kline_count']}")
            print(f"  分型: {structure['fractal_count']}")
            print(f"  笔: {structure['stroke_count']}")
            print(f"  中枢: {structure['hub_count']}")
        
        # 获取日线详细数据
        print("\n--- 日线详细分析 ---")
        
        # 笔序列
        strokes = analyzer.get_strokes(86400)
        print(f"笔数量: {len(strokes)}")
        for s in strokes[:5]:
            print(f"  {s['direction']}: {s['start_price']:.2f} -> {s['end_price']:.2f}")
        
        # 线段
        segments = analyzer.get_segments(86400, level=0)
        print(f"\n线段数量: {len(segments)}")
        for seg in segments[:3]:
            print(f"  {seg['direction']}: 级别={seg['level']}")
        
        # 中枢
        hubs = analyzer.get_hubs(86400)
        print(f"\n中枢数量: {len(hubs)}")
        for h in hubs[:3]:
            print(f"  低={h['low']:.2f}, 高={h['high']:.2f}")
        
        # 信号
        signals = analyzer.get_signals(86400)
        print(f"\n信号数量: {len(signals)}")
        for s in signals[:5]:
            print(f"  {s['type']}: {s['reason']}")
        
        # 多级别摘要
        summary = analyzer.get_multi_level_summary(86400)
        print("\n--- 多级别摘要 ---")
        for level_name, data in summary["levels"].items():
            if data["count"] > 0:
                print(f"  {level_name}: {data['count']}个, 信号{data['signal_count']}个")
        
        client.close()
        print("\n" + "=" * 60)
        print("eltdx多周期分析测试完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_eltdx_multi_period()