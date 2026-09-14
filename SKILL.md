# Chanlun Skill - 缠论分析技能

## 功能描述
基于chanlun库和eltdx库实现的A股缠论分析技能，支持多周期分析、买卖点识别和背驰检测。

## 核心组件

### 1. ChanlunAnalyzer - 多周期缠论分析器
```python
from chanlun_skill.core.analyzer import ChanlunAnalyzer

# 创建分析器
analyzer = ChanlunAnalyzer(
    symbol="sz000001",  # 股票代码
    periods=["1m", "5m", "30m", "day"],  # 分析周期
    config=None  # 缠论配置，None时使用默认配置
)

# 从eltdx获取数据并分析
with TdxClient() as client:
    # 批量投喂所有周期数据
    counts = analyzer.feed_batch(client, counts={"day": 500, "5m": 500})
    
    # 获取分析结果
    signals = analyzer.get_stroke_signals(period_seconds=300)  # 获取5分钟笔买卖信号
    divergences = analyzer.check_divergence(period_seconds=300)  # 检查5分钟背驰
    summary = analyzer.summary()  # 获取摘要
```

### 2. 配置管理
```python
from chanlun_skill.core.config import default_config, minimal_config, quiet_config

# 默认配置（全量分析）
cfg = default_config()

# 轻量配置（仅笔和中枢）
cfg = minimal_config()

# 静默配置（关闭推送和图表）
cfg = quiet_config()
```

### 3. 数据转换适配器
```python
from chanlun_skill.core.adapter import (
    period_to_seconds,      # 周期字符串转秒数
    eltdx_to_chanlun,       # eltdx K线转chanlun K线
    fetch_klines,           # 从eltdx获取K线
    feed_klines_to_observer # 批量投喂K线到观察者
)
```

### 4. 文本输出
```python
from chanlun_skill.signals.text import format_signals, format_summary

# 详细信号输出
text = format_signals(analyzer)

# 摘要输出
text = format_summary(analyzer)
```

## 支持的周期
- "1m" → 60秒
- "5m" → 300秒
- "15m" → 900秒
- "30m" → 1800秒
- "60m" → 3600秒
- "day" → 86400秒

## 买卖点类型
- 一买/一卖：趋势背驰点
- 二买/二卖：回调不破位点
- 三买/三卖：中枢突破点
- T1/T1P/T2/T2S/T3A/T3B：扩展买卖点类型

## 背驰检测
- MACD背驰：价格创新高/低但MACD未同步
- 斜率背驰：价格变化率背离
- 测度背驰：价格幅度背离

## 使用示例

### 完整分析流程
```python
from eltdx import TdxClient
from chanlun_skill.core.analyzer import ChanlunAnalyzer
from chanlun_skill.signals.text import format_signals

# 1. 创建分析器
analyzer = ChanlunAnalyzer("sz000001", periods=["5m", "30m", "day"])

# 2. 连接行情服务器获取数据
with TdxClient() as client:
    # 3. 批量投喂数据
    analyzer.feed_batch(client)
    
    # 4. 获取并输出分析结果
    print(format_signals(analyzer))
    
    # 5. 获取特定周期的信号
    signals_5m = analyzer.get_stroke_signals(300)  # 5分钟
    signals_30m = analyzer.get_stroke_signals(1800)  # 30分钟
    
    # 6. 检查背驰
    divergences = analyzer.check_divergence(300)
```

### 自定义配置
```python
from chanlun import 缠论配置
from chanlun_skill.core.analyzer import ChanlunAnalyzer

# 创建自定义配置
cfg = 缠论配置()
cfg.平滑异同移动平均线_快线周期 = 12
cfg.平滑异同移动平均线_慢线周期 = 26
cfg.平滑异同移动平均线_信号周期 = 9
cfg.分析笔 = True
cfg.分析线段 = True
cfg.计算指标 = True

# 使用自定义配置
analyzer = ChanlunAnalyzer("sz000001", config=cfg)
```

## 注意事项
1. 需要先安装依赖：`pip install chanlun eltdx`
2. eltdx需要连接通达信行情服务器才能获取实时数据
3. 买卖点识别需要足够的K线数据（建议至少500根）
4. 背驰检测需要MACD等指标数据