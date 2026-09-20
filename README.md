# chanlun-skill

基于 `chanlun` 核心库的 A 股缠论分析 Skill。生产路径采用 Rust 核心 + PyO3
绑定，外围通过适配层、数据质量层和语义摘要层为 AI 提供可审计的缠论事实与条件化策略输入。

## 依赖

```bash
# 只读检查（默认不安装）
python skills/chanlun-skill/scripts/check_dependencies.py --json

# 经用户明确授权后安装固定版本
python skills/chanlun-skill/scripts/check_dependencies.py --install
```

Claude Code/Codex 安装 Skill 时不会自动执行 `requirements.txt`。首次使用前请运行自检；
只有显式使用 `--install` 才会调用 pip。

## 快速开始

```bash
# 从 CSV 分析（内置样例数据）
python skills/chanlun-skill/scripts/chan_analyzer.py \
    --source csv \
    --input skills/chanlun-skill/scripts/test_data.csv \
    --symbol 000001 \
    --freq 日线

# 输出结构化 JSON
python skills/chanlun-skill/scripts/chan_analyzer.py \
    --source csv \
    --input skills/chanlun-skill/scripts/test_data.csv \
    --symbol 000001 \
    --freq day \
    --json

# 多周期 CSV，用于本地跨周期共振
python skills/chanlun-skill/scripts/chan_analyzer.py \
    --source csv \
    --input_periods day=day.csv,week=week.csv \
    --symbol 000001 \
    --json
```

`--freq` 支持中英文周期名（`1m`/`5m`/`30m`/`day`/`week`/`日线`/`周线`/`N分钟`），并自动补上级周期以合成多周期。

在线 `eltdx` 取数支持超过 800 根 K 线：`--count` 是总数量，取数层会自动分页，
合并、去重、按时间排序后再交给 Rust 递归分析。例如：

```bash
python skills/chanlun-skill/scripts/chan_analyzer.py \
  --source eltdx --code sh600519 --freq day --count 2000 \
  --page-size 800 --max-pages 10
```

页面不会被分别分析，因此不会因 800 根的接口边界切断笔、线段或中枢。
`eltdx` 默认使用前复权 `--adjust qfq`，以保持历史走势连续；如需与未复权真实价格
对齐，可显式加 `--adjust none`。定点复权使用 `--adjust fixed_qfq --anchor-date YYYY-MM-DD`。

当前验证基线固定为 Python `3.14.7`、`chanlun==2606.73`、`eltdx==3.2.2`、
`PyYAML==6.0.3`。

## 能力

- **多周期**：`立体分析器` 自动由小周期合成大周期
- **结构**：笔 / 线段内部笔中枢 / 线段 / 扩展结构全层级计数与端点；原始全局笔中枢仅作审计计数
- **买卖点**：按缠论结构识别一/二/三类；一类遵循 `a+A+b+B+c` /
  `a+A+b`，A/B 统一取线段内部笔中枢，要求已形成且仍有效；
  核心 `完整性("实")` 仅作辅助证据；背驰仅作辅助确认（向上笔→卖、向下笔→买）
- **背驰**：`线段.判断线段内部是否背驰` + `背驰分析`
- **背驰证据矩阵**：MACD/斜率/测度/组合/模式判据逐项输出
- **指标**：MACD / RSI / KDJ 逐根 K 线真实数值
- **数据质量**：缺字段、非法数值、OHLC、时间、重复、乱序和大间隔检查
- **复权口径**：eltdx 默认前复权 qfq，支持 none/hfq/fixed_qfq/fixed_hfq 并写入输出元数据
- **语义摘要**：为 AI 输出事实、解释、条件化情景和失效条件
- **证据来源拆分**：区分 Rust 结构、Skill 分类、Rust factory 止损和确认级别
- **核心匹配审计**：保留配置/任意/全量/相对买卖点指标匹配结果
- **回归验证**：16 个 PART 覆盖结构、信号来源、schema、策略输入契约与 eltdx 分页取数
- **标准信号契约**：统一类型、确认状态、证据、来源、止损和可执行性；独立 schema 校验器
- **确认状态机**：候选→已确认/已失效，已确认→已失效，保留状态轨迹并禁止已失效信号复活
- **输出**：文本报告 + `--json` 结构化，JSON 包含 `schema_version` 和 Rust 引擎元数据

## 项目结构

```
chanlun.rs/
├── skills/chanlun-skill/     # Skill 主体
│   ├── SKILL.md              # 主文档（含核心库能力速查）
│   ├── agents/openai.yaml    # AI 配置
│   ├── examples/             # 实战案例
│   ├── references/           # 缠论理论参考
│   └── scripts/              # 工具脚本
│       ├── chan_analyzer.py  # 分析入口（直连核心库）
│       ├── rust_adapter.py   # Rust/PyO3 访问适配层
│       ├── data_quality.py   # 输入数据质量检查
│       ├── semantic.py       # AI 语义摘要（事实/解释/情景）
│       ├── signal_contract.py # 标准信号契约与确认状态机
│       ├── signal_schema.py   # 独立标准信号 schema 校验器
│       ├── strategy_plan.py  # 无未来数据的策略计划
│       ├── golden_regression.py # 黄金样例回归
│       ├── test_contract.py  # 不依赖 Rust 扩展的轻量契约测试
│       ├── test_data_loader.py # eltdx 分页取数层离线契约测试
│       ├── test_data.csv     # 样例数据
│       └── requirements.txt
└── 核心库能力评估与Skill优化建议.md  # 审计报告
```

## 文档

- [SKILL.md](skills/chanlun-skill/SKILL.md) - 完整使用文档
- [缠论核心理论](skills/chanlun-skill/references/chan-theory-core.md) - 理论基础
- [使用场景示例](skills/chanlun-skill/examples/usage-scenarios.md) - 实战案例

## 许可证

MIT License
