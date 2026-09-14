"""分析002812恩捷股份。"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from eltdx import TdxClient
from eltdx.hosts import DEFAULT_HOSTS
from chanlun_skill.core.analyzer import ChanlunAnalyzer
from chanlun_skill.core.adapter import feed_klines_to_observer

def analyze_002812():
    """分析002812恩捷股份。"""
    print("=" * 60)
    print("002812 恩捷股份 缠论分析")
    print("=" * 60)
    
    try:
        # 连接eltdx
        client = TdxClient(hosts=DEFAULT_HOSTS[:3], timeout=15)
        client.connect()
        print("eltdx连接成功")
        
        # 创建分析器
        analyzer = ChanlunAnalyzer("sz002812", periods=["5m", "30m", "day"])
        print("分析器创建成功")
        
        # 获取5分钟数据（最小周期）
        series = client.bars.get(
            code='002812',
            period='5m',
            count=800
        )
        count = feed_klines_to_observer(analyzer.engine, series)
        print(f"5分钟投喂: {count}根K线")
        
        # 获取各周期结构
        print("\n--- 各周期结构 ---")
        periods = [
            ("5分钟", 300),
            ("30分钟", 1800),
            ("日线", 86400)
        ]
        
        for name, sec in periods:
            structure = analyzer.get_structure(sec)
            print(f"\n{name}:")
            print(f"  缠论K线: {structure['chan_kline_count']}")
            print(f"  分型: {structure['fractal_count']}")
            print(f"  笔: {structure['stroke_count']}")
            print(f"  中枢: {structure['hub_count']}")
        
        # 日线详细分析
        print("\n--- 日线详细分析 ---")
        
        # 笔序列
        strokes = analyzer.get_strokes(86400)
        print(f"笔数量: {len(strokes)}")
        if strokes:
            print("\n最近5笔:")
            for s in strokes[-5:]:
                print(f"  {s['direction']}: {s['start_price']:.2f} -> {s['end_price']:.2f}")
        
        # 线段
        segments = analyzer.get_segments(86400, level=0)
        print(f"\n线段数量: {len(segments)}")
        if segments:
            print("\n最近3段:")
            for seg in segments[-3:]:
                print(f"  {seg['direction']}: 级别={seg['level']}")
        
        # 中枢
        hubs = analyzer.get_hubs(86400)
        print(f"\n中枢数量: {len(hubs)}")
        if hubs:
            print("\n最近3个中枢:")
            for h in hubs[-3:]:
                print(f"  低={h['low']:.2f}, 高={h['high']:.2f}")
        
        # 信号
        signals = analyzer.get_signals(86400)
        print(f"\n信号数量: {len(signals)}")
        if signals:
            print("\n最近5个信号:")
            for s in signals[-5:]:
                print(f"  {s['type']}: {s['reason']}")
        
        # 多级别摘要
        summary = analyzer.get_multi_level_summary(86400)
        print("\n--- 多级别摘要 ---")
        for level_name, data in summary["levels"].items():
            if data["count"] > 0:
                print(f"  {level_name}: {data['count']}个, 信号{data['signal_count']}个")
        
        # 30分钟分析
        print("\n--- 30分钟分析 ---")
        strokes_30m = analyzer.get_strokes(1800)
        print(f"笔数量: {len(strokes_30m)}")
        if strokes_30m:
            print("\n最近5笔:")
            for s in strokes_30m[-5:]:
                print(f"  {s['direction']}: {s['start_price']:.2f} -> {s['end_price']:.2f}")
        
        signals_30m = analyzer.get_signals(1800)
        print(f"\n信号数量: {len(signals_30m)}")
        if signals_30m:
            print("\n最近3个信号:")
            for s in signals_30m[-3:]:
                print(f"  {s['type']}: {s['reason']}")
        
        # 5分钟分析
        print("\n--- 5分钟分析 ---")
        strokes_5m = analyzer.get_strokes(300)
        print(f"笔数量: {len(strokes_5m)}")
        signals_5m = analyzer.get_signals(300)
        print(f"信号数量: {len(signals_5m)}")
        
        client.close()
        print("\n" + "=" * 60)
        print("002812分析完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    analyze_002812()