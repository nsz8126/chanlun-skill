# 测试目录

- `unit/`：不依赖 Rust 扩展的轻量契约测试。
- `integration/`：分析器、fixtures 和可选在线数据的集成回归。
- `fixtures/`：CSV 样例及 GG/DD 回归 cases。
- `../references/standard-signal.schema.json`：标准信号 `signal-1.0` 的 JSON Schema（Draft 2020-12）。

运行测试前安装 `tests/requirements.txt` 中的测试依赖；运行时依赖仍单独由 `scripts/requirements.txt` 管理。

从 Skill 根目录执行：

```bash
python tests/unit/test_contract.py
python tests/integration/golden_regression.py
python tests/integration/gray_test.py
python tests/integration/test_data_loader.py
python tests/integration/test_rust_adapter.py
```

`ggdd_regression.py` 需要网络和 eltdx 数据源，不纳入默认离线回归。
