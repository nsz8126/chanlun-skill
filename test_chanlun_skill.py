"""chanlun_skill 灰度测试。"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from chanlun_skill.core.analyzer import ChanlunAnalyzer
from chanlun_skill.core.config import default_config, minimal_config, quiet_config

def test_config():
    """测试配置功能。"""
    print("=" * 50)
    print("测试1: 配置功能")
    print("=" * 50)
    
    cfg = default_config()
    print(f"默认配置 MACD: {cfg.平滑异同移动平均线_快线周期}, {cfg.平滑异同移动平均线_慢线周期}, {cfg.平滑异同移动平均线_信号周期}")
    print(f"默认配置 RSI周期: {cfg.相对强弱指数_周期}")
    print(f"默认配置 KDJ周期: {cfg.随机指标_RSV周期}")
    
    cfg_min = minimal_config()
    print(f"\n轻量配置: 计算指标={cfg_min.计算指标}, 分析笔={cfg_min.分析笔}")
    
    cfg_quiet = quiet_config()
    print(f"静默配置 MACD: {cfg_quiet.平滑异同移动平均线_快线周期}, {cfg_quiet.平滑异同移动平均线_慢线周期}, {cfg_quiet.平滑异同移动平均线_信号周期}")
    
    print("[PASS] 配置测试通过\n")
    return True


def test_analyzer_creation():
    """测试分析器创建。"""
    print("=" * 50)
    print("测试2: 分析器创建")
    print("=" * 50)
    
    analyzer = ChanlunAnalyzer("sz000001", periods=["1m", "5m", "30m", "day"])
    print(f"股票代码: {analyzer.symbol}")
    print(f"分析周期: {analyzer.periods}")
    print(f"周期秒数: {analyzer._period_seconds}")
    
    observers = analyzer.get_observers()
    print(f"观察者数量: {len(observers)}")
    
    print("[PASS] 分析器创建测试通过\n")
    return True


def test_structure_data():
    """测试结构数据获取。"""
    print("=" * 50)
    print("测试3: 结构数据获取")
    print("=" * 50)
    
    analyzer = ChanlunAnalyzer("sz000001", periods=["1m", "5m", "30m", "day"])
    
    for period_name, period_sec in [("1m", 60), ("5m", 300), ("30m", 1800), ("day", 86400)]:
        structure = analyzer.get_structure(period_sec)
        print(f"\n{period_name}结构:")
        print(f"  原始K线: {structure['kline_count']}")
        print(f"  缠论K线: {structure['chan_kline_count']}")
        print(f"  分型: {structure['fractal_count']}")
        print(f"  笔: {structure['stroke_count']}")
        print(f"  中枢: {structure['hub_count']}")
    
    print("\n[PASS] 结构数据获取测试通过\n")
    return True


def test_signals():
    """测试信号获取。"""
    print("=" * 50)
    print("测试4: 信号获取")
    print("=" * 50)
    
    analyzer = ChanlunAnalyzer("sz000001", periods=["1m", "5m", "30m", "day"])
    
    for period_name, period_sec in [("5m", 300), ("30m", 1800), ("day", 86400)]:
        signals = analyzer.get_signals(period_sec)
        print(f"\n{period_name}笔级别信号: {len(signals)}个")
        for s in signals[:3]:
            print(f"  {s['type']}: {s['reason']}")
    
    print("\n[PASS] 信号获取测试通过\n")
    return True


def test_level_structure():
    """测试级别结构获取。"""
    print("=" * 50)
    print("测试5: 级别结构获取")
    print("=" * 50)
    
    analyzer = ChanlunAnalyzer("sz000001", periods=["5m", "30m", "day"])
    
    for period_name, period_sec in [("5m", 300), ("30m", 1800), ("day", 86400)]:
        summary = analyzer.get_multi_level_summary(period_sec)
        print(f"\n{period_name}多级别摘要:")
        for level_name, data in summary["levels"].items():
            if data["count"] > 0:
                print(f"  {level_name}: {data['count']}个, 信号{data['signal_count']}个")
    
    print("\n[PASS] 级别结构获取测试通过\n")
    return True


def test_line_level():
    """测试线段级别获取。"""
    print("=" * 50)
    print("测试6: 线段级别获取")
    print("=" * 50)
    
    analyzer = ChanlunAnalyzer("sz000001", periods=["5m", "30m", "day"])
    
    for period_name, period_sec in [("5m", 300), ("30m", 1800), ("day", 86400)]:
        print(f"\n{period_name}线段级别:")
        for level in range(3):
            segments = analyzer.get_segments(period_sec, level)
            level_name = f"级别{level + 2}"
            print(f"  {level_name}: {len(segments)}个")
    
    print("\n[PASS] 线段级别获取测试通过\n")
    return True


def test_divergence():
    """测试背驰获取。"""
    print("=" * 50)
    print("测试7: 背驰获取")
    print("=" * 50)
    
    analyzer = ChanlunAnalyzer("sz000001", periods=["5m", "30m", "day"])
    
    for period_name, period_sec in [("5m", 300), ("30m", 1800), ("day", 86400)]:
        divergence = analyzer.get_divergence(period_sec)
        print(f"\n{period_name}背驰: {len(divergence)}个")
        for d in divergence[:3]:
            print(f"  线段{d['segment_index']}: MACD={d['macd_divergence']}, 斜率={d['slope_divergence']}")
    
    print("\n[PASS] 背驰获取测试通过\n")
    return True


def main():
    """主测试函数。"""
    print("=" * 50)
    print("chanlun_skill 灰度测试")
    print("=" * 50)
    
    tests = [
        test_config,
        test_analyzer_creation,
        test_structure_data,
        test_signals,
        test_level_structure,
        test_line_level,
        test_divergence,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__} 失败: {e}")
            failed += 1
    
    print("=" * 50)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 50)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)