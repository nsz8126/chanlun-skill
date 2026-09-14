# chanlun.rs

基于chanlun库和eltdx库的A股缠论分析技能

## 功能特性

- **多周期分析**：支持1分钟、5分钟、15分钟、30分钟、60分钟、日线等周期
- **标准买卖点识别**：一买/二买/三买、一卖/二卖/三卖
- **混合架构**：Python快速识别 + AI智能验证
- **背驰检测**：MACD背驰、斜率背驰、测度背驰
- **技术指标**：MACD、RSI、KDJ、布林带等

## 安装

```bash
pip install chanlun eltdx
```

## 快速开始

### Python API

```python
from chanlun_skill.core.analyzer import ChanlunAnalyzer

# 创建分析器
analyzer = ChanlunAnalyzer("sz000001", periods=["5m", "30m", "day"])

# 获取eltdx数据
from eltdx import TdxClient
from eltdx.hosts import DEFAULT_HOSTS
from chanlun_skill.core.adapter import feed_klines_to_observer

client = TdxClient(hosts=DEFAULT_HOSTS[:3], timeout=15)
client.connect()

series = client.bars.get(code='000001', period='5m', count=800)
feed_klines_to_observer(analyzer.engine, series)

# 识别标准买卖点
signals = analyzer.identify_standard_signals(300)  # 5分钟
for sig in signals:
    print(f"{sig['signal_type']}: {sig['reason']}")
```

### 命令行

```bash
# 基础分析
python scripts/chan_analyzer.py \
    --source csv \
    --input scripts/test_data.csv \
    --symbol 000001 \
    --freq 日线

# 在线获取
python scripts/chan_analyzer.py \
    --source eltdx \
    --code sh600519 \
    --start_date 20240101 \
    --end_date 20240614 \
    --freq 日线
```

## 混合架构

```
第一层：Python快速识别（确定性逻辑）
├── 获取笔、中枢数据
├── 应用缠论规则
├── 输出候选买卖点
↓
第二层：AI分析验证（智能分析）
├── 验证信号合理性
├── 结合多周期分析
├── 评估风险收益
├── 生成详细报告
```

## 标准买卖点

| 买卖点 | 条件 |
|--------|------|
| 一买 | 下跌趋势背驰 |
| 一卖 | 上涨趋势背驰 |
| 二买 | 回调不破一买低点 |
| 二卖 | 反弹不破一卖高点 |
| 三买 | 中枢突破后回踩 |
| 三卖 | 中枢跌破后反弹 |

## 项目结构

```
chanlun.rs/
├── chanlun_skill/           # 核心包
│   ├── core/
│   │   ├── adapter.py      # eltdx适配器
│   │   ├── analyzer.py     # 分析引擎
│   │   └── config.py       # 配置管理
│   └── signals/
│       └── text.py         # 文本输出
├── skills/chanlun-skill/    # SKILL文件
│   ├── SKILL.md            # 主文档
│   ├── agents/             # AI配置
│   ├── examples/           # 实战案例
│   ├── references/         # 理论参考
│   └── scripts/            # 工具脚本
└── tests/                  # 测试文件
```

## 文档

- [SKILL.md](skills/chanlun-skill/SKILL.md) - 完整的使用文档
- [缠论核心理论](skills/chanlun-skill/references/chan-theory-core.md) - 理论基础
- [使用场景示例](skills/chanlun-skill/examples/usage-scenarios.md) - 实战案例

## 许可证

MIT License