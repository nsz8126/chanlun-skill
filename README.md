# chanlun-skill

基于 `chanlun` 核心库的 A 股缠论分析 Skill。脚本直接调用核心库完整能力，无中间封装层。

## 依赖

```bash
pip install chanlun eltdx
```

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
```

`--freq` 支持中英文周期名（`1m`/`5m`/`30m`/`day`/`week`/`日线`/`周线`/`N分钟`），并自动补上级周期以合成多周期。

## 能力

- **多周期**：`立体分析器` 自动由小周期合成大周期
- **结构**：笔 / 笔中枢 / 线段 / 扩展结构全层级计数与端点
- **买卖点**：`虚线.买卖意义` 官方语义（向上笔→卖、向下笔→买）
- **背驰**：`线段.判断线段内部是否背驰` + `背驰分析`
- **指标**：MACD / RSI / KDJ 逐根 K 线真实数值
- **输出**：文本报告 + `--json` 结构化

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
