# chanlun-skill: 基于 chanlun + eltdx 的缠论分析 Skills

## 项目概述

以 `chanlun` 库（Rust 高性能缠论引擎）为核心，`eltdx`（通达信 7709 协议）为 A 股数据源，构建一个 Python 包，实现多周期缠论实时分析和买卖点信号输出。

## 技术栈

| 组件 | 选型 | 用途 |
|------|------|------|
| 缠论引擎 | `chanlun 2606.73` | 分型/笔/线段/中枢/买卖点分析 |
| 数据源 | `eltdx 3.2.2` | A 股实时行情、K 线数据 |
| Python | 3.10+ | 运行环境 |

## 项目结构

```
chanlun.rs/
├── pyproject.toml
├── chanlun_skill/
│   ├── __init__.py          # 包导出
│   ├── cli.py               # CLI 入口
│   ├── core/
│   │   ├── __init__.py
│   │   ├── adapter.py       # eltdx → chanlun 数据格式转换
│   │   ├── analyzer.py      # 多周期缠论分析引擎
│   │   └── config.py        # 分析配置管理
│   └── signals/
│       ├── __init__.py
│       └── text.py          # 文本信号输出
└── tests/
    └── test_basic.py
```

## 核心模块设计

### 1. `core/adapter.py` — 数据适配器

eltdx 返回 `KlineBar`（含 time/open/high/low/close/volume_lots），chanlun 需要 `K线` 对象。

```python
# 核心转换函数
def kline_to_chanlun(bar: KlineBar, symbol: str, period_seconds: int, index: int) -> K线:
    """将 eltdx KlineBar 转换为 chanlun K线"""
    return K线.创建普K(
        标识=symbol,
        时间戳=bar.time,
        开盘价=bar.open,
        最高价=bar.high,
        最低价=bar.low,
        收盘价=bar.close,
        成交量=bar.volume_lots,
        序号=index,
        周期=period_seconds,
    )

# 批量转换
def fetch_and_convert(client: TdxClient, symbol: str, period: str, count: int) -> list[Kline]:
    """从 eltdx 获取 K 线并转换为 chanlun 格式"""
    ...
```

**关键映射：**
| eltdx KlineBar | chanlun K线 |
|---|---|
| `bar.time` | `时间戳` (datetime) |
| `bar.open` | `开盘价` |
| `bar.high` | `最高价` |
| `bar.low` | `最低价` |
| `bar.close` | `收盘价` |
| `bar.volume_lots` | `成交量` |
| (自动生成) | `序号` (递增) |
| (参数传入) | `周期` (秒数) |
| (参数传入) | `标识` (股票代码) |

### 2. `core/analyzer.py` — 多周期分析引擎

基于 `chanlun.立体分析器` 实现多周期联动分析。

```python
class ChanlunAnalyzer:
    def __init__(self, symbol: str, periods: list[int], config: 缠论配置 = None):
        self.symbol = symbol
        self.periods = periods
        self.engine = 立体分析器(symbol, periods, config or 缠论配置())

    def feed_from_eltdx(self, client: TdxClient, period: str, count: int = 800):
        """从 eltdx 获取数据并投喂到分析引擎"""
        bars = client.bars.get(self.symbol, period=period, count=count)
        for i, bar in enumerate(bars.bars):
            k = kline_to_chanlun(bar, self.symbol, self._period_to_seconds(period), i)
            self.engine.投喂K线(k)

    def get_signals(self) -> dict:
        """获取分析结果"""
        # 返回各周期的笔/线段/中枢/买卖点
        ...
```

**周期映射：**
| eltdx period | chanlun 周期(秒) |
|---|---|
| `"1m"` | 60 |
| `"5m"` | 300 |
| `"15m"` | 900 |
| `"30m"` | 1800 |
| `"60m"` | 3600 |
| `"day"` | 86400 |
| `"week"` | 604800 |

### 3. `core/config.py` — 配置管理

提供预设配置和自定义配置。

```python
class SkillConfig:
    # 默认周期组：5m / 30m / 日线
    DEFAULT_PERIODS = ["5m", "30m", "day"]

    # 预设配置
    @staticmethod
    def default() -> 缠论配置:
        cfg = 缠论配置()
        cfg.计算指标 = True
        cfg.分析笔 = True
        cfg.分析线段 = True
        cfg.分析笔中枢 = True
        cfg.分析线段中枢 = True
        return cfg

    @staticmethod
    def minimal() -> 缠论配置:
        """轻量配置：仅笔和中枢，不计算指标"""
        cfg = 缠论配置.不推送()
        return cfg
```

### 4. `signals/text.py` — 文本信号输出

将分析结果格式化为可读文本。

```python
def format_signals(analyzer: ChanlunAnalyzer) -> str:
    """格式化输出分析结果"""
    lines = []
    lines.append(f"=== {analyzer.symbol} 缠论分析 ===\n")

    for period_name, observer in analyzer.get_observers().items():
        lines.append(f"--- {period_name} ---")

        # 最近笔
        笔序列 = observer.笔序列[-5:]  # 最近5笔
        for 笔 in 笔序列:
            direction = "↑" if 笔.线段方向 == 相对方向.向上 else "↓"
            lines.append(f"  笔 {direction}: {笔.文.中.时间戳} ~ {笔.武.中.时间戳}")

        # 中枢
        中枢序列 = observer.笔_中枢序列[-3:]
        for 中 in 中枢序列:
            lines.append(f"  中枢: {中.基础序列[0].文.中.收盘价:.2f} ~ {中.基础序列[0].武.中.收盘价:.2f}")

        # 买卖点
        # ...

    return "\n".join(lines)
```

### 5. `cli.py` — 命令行入口

```python
# 使用方式
# python -m chanlun_skill sz000001
# python -m chanlun_skill sz000001 --periods 5m,30m,day
# python -m chanlun_skill sz000001 --count 500
```

## 实施步骤

### Step 1: 安装依赖
```bash
.venv\Scripts\pip install eltdx
```

### Step 2: 创建项目结构
创建 `pyproject.toml`、目录和 `__init__.py` 文件。

### Step 3: 实现 `core/adapter.py`
eltdx KlineBar → chanlun K线 的格式转换。

### Step 4: 实现 `core/config.py`
预设配置管理。

### Step 5: 实现 `core/analyzer.py`
多周期分析引擎，封装 `立体分析器`。

### Step 6: 实现 `signals/text.py`
文本格式化输出。

### Step 7: 实现 `cli.py`
命令行入口，串联数据获取→分析→输出。

### Step 8: 测试
```bash
python -m chanlun_skill sz000001
```

## 使用示例

```python
from chanlun_skill import ChanlunAnalyzer
from eltdx import TdxClient

with TdxClient(timeout=3) as client:
    analyzer = ChanlunAnalyzer("sz000001", periods=["5m", "30m", "day"])
    analyzer.feed_from_eltdx(client, period="day", count=500)
    analyzer.feed_from_eltdx(client, period="30m", count=500)
    analyzer.feed_from_eltdx(client, period="5m", count=500)

    print(analyzer.format_text())
```

## 注意事项

1. eltdx 仅允许个人学习和非商业研究使用
2. 周期组从小到大排列，小周期数据驱动大周期合成
3. `立体分析器` 内部会自动通过 `K线合成器` 从最小周期合成大周期
4. 实际使用中建议先加载足够历史数据再进行分析
