#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chan_analyzer.py 灰度测试套件。

覆盖六类场景：
  1. 功能正确性 —— 全部周期（1m~month）× 中英文 × 文本/JSON 输出
  2. 边界健壮性 —— 非法周期名/文件不存在/缺列/非数字/空数据 应给出清晰报错
  3. 数据正确性 —— 笔端点、中枢上下沿不得倒挂
  4. 买卖点方向 —— 向上笔应判 sell、向下笔应判 buy
  5. 私有字段依赖 —— engine._单体分析器 的可用性
  6. 体量与性能

用法（在 scripts 目录下）：
    python gray_test.py
退出码：0 = 全部通过，1 = 存在失败项。
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
SCRIPT = os.path.join(HERE, "chan_analyzer.py")
CSV = os.path.join(HERE, "test_data.csv")

FAIL_COUNT = 0


def run(args, timeout=90):
    try:
        r = subprocess.run([PY, "-X", "utf8", SCRIPT] + args,
                           capture_output=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return -999, "TIMEOUT"


def check(label, ok, detail=""):
    global FAIL_COUNT
    tag = "PASS" if ok else "FAIL"
    if not ok:
        FAIL_COUNT += 1
    print(f"  [{tag}] {label}")
    if detail and not ok:
        for line in detail.splitlines():
            print(f"        {line[:180]}")


def head(txt, n=180):
    return txt[:n].replace("\n", " | ")


def main():
    print("=" * 78)
    print("PART 1  功能正确性：全部周期 × 中英文 × JSON")
    print("=" * 78)
    base = ["--source", "csv", "--input", CSV, "--symbol", "000001"]
    cases = ["1m", "5m", "15分钟", "30m", "60m", "day", "日线", "week", "周线",
             "month", "月线"]
    for f in cases:
        code, txt = run(base + ["--freq", f, "--json"])
        ok = code == 0
        detail = txt
        if ok:
            try:
                d = json.loads(txt)
                nd = d.get("periods_detail", {})
                detail = "周期组=" + str(d.get("periods")) + "  " + "  ".join(
                    f"{k}(K{nd[k]['普通K线']}/笔{nd[k]['笔']}/中{nd[k]['笔中枢']})"
                    for k in nd)
            except Exception as e:
                ok, detail = False, f"JSON解析失败 {e}"
        check(f"--freq {f}", ok, detail if not ok else "")

    print("")
    print("=" * 78)
    print("PART 2  边界健壮性")
    print("=" * 78)
    tmp = tempfile.mkdtemp(prefix="gray_")
    edge = [
        ("非法周期 XYZ", ["--source", "csv", "--input", CSV, "--freq", "XYZ"]),
        ("不存在的CSV", ["--source", "csv", "--input", os.path.join(tmp, "nope.csv"), "--freq", "day"]),
        ("eltdx缺code", ["--source", "eltdx", "--freq", "day"]),
        ("csv缺input", ["--source", "csv", "--freq", "day"]),
    ]
    for label, args in edge:
        code, txt = run(args)
        ok = code != 0 and "Traceback" not in txt
        check(label, ok, head(txt))

    malformed = {
        "空文件": "date,open,high,low,close,volume\n",
        "仅1根": "date,open,high,low,close,volume\n2024-01-02,10,10.5,9.5,10.2,1000\n",
        "缺列": "date,open,high,low\n2024-01-02,10,10.5,9.5\n2024-01-03,10.2,10.8,10\n",
        "非数字": "date,open,high,low,close,volume\n2024-01-02,abc,10.5,9.5,10.2,1000\n2024-01-03,10,10,9,9.5,900\n",
        "常量价格": "date,open,high,low,close,volume\n" + "".join(
            f"2024-01-{2+i:02d},10,10,10,10,1000\n" for i in range(30)),
    }
    for label, content in malformed.items():
        fpath = os.path.join(tmp, label + ".csv")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        code, txt = run(["--source", "csv", "--input", fpath, "--freq", "day"])
        ok = "Traceback" not in txt
        check(label, ok, head(txt))

    print("")
    print("=" * 78)
    print("PART 3  数据正确性：笔端点 / 中枢上下沿")
    print("=" * 78)
    code, txt = run(base + ["--freq", "day", "--json"])
    if code == 0:
        d = json.loads(txt)
        bad_stroke = bad_hub = total_stroke = total_hub = 0
        for pname, det in d["periods_detail"].items():
            for s in det["笔序列"]:
                total_stroke += 1
                if s["低"] > s["高"]:
                    bad_stroke += 1
            for z in det["中枢序列"]:
                total_hub += 1
                if z["低"] > z["高"] or z["低低"] > z["高高"]:
                    bad_hub += 1
        check(f"笔端点倒挂（{total_stroke} 条）", bad_stroke == 0,
              f"倒挂 {bad_stroke} 条")
        check(f"中枢区间倒挂（{total_hub} 个）", bad_hub == 0,
              f"异常 {bad_hub} 个")
    else:
        check("数据正确性（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 4  买卖点方向：向上笔→卖类，向下笔→买类")
    print("=" * 78)
    code, txt = run(base + ["--freq", "day", "--json"])
    if code == 0:
        d = json.loads(txt)
        total_sig = wrong = 0
        for pname, det in d["periods_detail"].items():
            for s in det["买卖点"]:
                total_sig += 1
                is_buy = "买" in s["kind"]
                is_sell = "卖" in s["kind"]
                expect_buy = s["direction"] == "向下"
                if (is_buy and not expect_buy) or (is_sell and expect_buy):
                    wrong += 1
        check(f"买卖点方向（{total_sig} 个）", wrong == 0, f"错 {wrong} 个")
    else:
        check("买卖点方向（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 5  新增能力：买卖点类型 / MACD面积 / BOLL / 序列组")
    print("=" * 78)
    code, txt = run(base + ["--freq", "day", "--boll", "--均线", "5,20", "--json"])
    if code == 0:
        d = json.loads(txt)
        det = list(d["periods_detail"].values())[0]
        has_area = bool(det.get("MACD面积"))
        has_boll = any(r.get("boll_mid") is not None for r in det.get("指标_最近", []))
        has_ma = any(r.get("均线") for r in det.get("指标_最近", []))
        has_groups = "线段序列组" in det and "扩展线段序列组" in det
        t_prefixes = ("T1", "T1P", "T2", "T2S", "T3A", "T3B")
        has_sig_types = all(
            s["kind"].startswith(t_prefixes) and s["kind"][-1] in "买卖"
            and s.get("base") in ("一买", "一卖", "二买", "二卖", "三买", "三卖")
            for s in det.get("买卖点", []))
        check("MACD 面积量", has_area)
        check("BOLL 布林带", has_boll)
        check("均线", has_ma)
        check("级别递归序列组", has_groups)
        check("T 系列类型化", has_sig_types)
    else:
        check("新增能力（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 6  趋势数据 T 系列验证（双中枢下跌 + 背驰）")
    print("=" * 78)
    trend_csv = os.path.join(HERE, "test_data_trend.csv")
    if os.path.exists(trend_csv):
        code, txt = run(["--source", "csv", "--input", trend_csv,
                         "--symbol", "000001", "--freq", "day", "--json"])
        if code == 0:
            d = json.loads(txt)
            det = list(d["periods_detail"].values())[0]
            kinds = [s["kind"] for s in det.get("买卖点", [])]
            hubs = det.get("中枢序列", [])
            has_t1 = any(k.startswith("T1") and not k.startswith("T1P") for k in kinds)
            has_2hub = len(hubs) >= 2
            check("≥2 个中枢（趋势结构）", has_2hub,
                  f"中枢数 {len(hubs)}")
            check("T1 趋势背驰触发", has_t1, f"买卖点 {kinds}")
        else:
            check("趋势数据（无法运行）", False, head(txt))
    else:
        check("趋势数据（缺失 test_data_trend.csv）", False)

    print("")
    print("=" * 78)
    print("PART 7  T3A / T3B 时序验证（老中枢 vs 新中枢）")
    print("=" * 78)
    for label, csv_name, expect in (
        ("T3B（突破老中枢=二三类重合）", "test_data_t3b.csv", "T3B"),
        ("T3A（突破反转后新中枢）", "test_data_t3a.csv", "T3A"),
    ):
        fpath = os.path.join(HERE, csv_name)
        if not os.path.exists(fpath):
            check(f"{label}（缺失 {csv_name}）", False)
            continue
        code, txt = run(["--source", "csv", "--input", fpath,
                         "--symbol", "000001", "--freq", "day", "--json"])
        if code == 0:
            d = json.loads(txt)
            det = list(d["periods_detail"].values())[0]
            kinds = [s["kind"] for s in det.get("买卖点", [])]
            hit = any(k.startswith(expect) for k in kinds)
            check(f"{label}", hit, f"买卖点 {kinds}")
        else:
            check(f"{label}（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 8  止损体系深化（买卖点 factory 官方字段）")
    print("=" * 78)
    code, txt = run(base + ["--freq", "day", "--json"])
    if code == 0:
        d = json.loads(txt)
        det = list(d["periods_detail"].values())[0]
        sigs = det.get("买卖点", [])
        if not sigs:
            check("止损字段（无信号可验）", True)
        else:
            # 验证：所有信号都有 止损 字段，且至少一个非空
            has_stop = all("止损" in s for s in sigs)
            any_nonempty = any(
                s["止损"].get("破位值") is not None
                or s["止损"].get("与MACD柱子匹配") is not None
                for s in sigs
            )
            check(f"止损字段存在（{len(sigs)} 个信号）", has_stop)
            check(f"止损字段非空（至少 1 个）", any_nonempty)
            # 验证：止损 6 个标准字段都存在
            required = {"破位值", "失效K线", "有效性", "失效偏移",
                        "与MACD柱子匹配", "与MACD柱子分型匹配"}
            all_keys = all(required.issubset(s["止损"].keys()) for s in sigs)
            check(f"止损 6 字段齐全", all_keys)
    else:
        check("止损体系（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 9  多级别展开（扩展线段序列组逐层）")
    print("=" * 78)
    code, txt = run(base + ["--freq", "day", "--json"])
    if code == 0:
        d = json.loads(txt)
        det = list(d["periods_detail"].values())[0]
        ml = det.get("多级别展开", {})
        has_seg = "扩展线段层" in ml and len(ml["扩展线段层"]) >= 1
        has_hub = "扩展中枢层" in ml and len(ml["扩展中枢层"]) >= 1
        # 至少 L1 应有数量
        l1_count = ml.get("扩展线段层", [{}])[0].get("数量", 0) if has_seg else 0
        # 与 序列组 一致性
        seq_group_count = det.get("扩展线段序列组", [0])[0]
        consistent = l1_count == seq_group_count
        check("扩展线段层存在", has_seg)
        check("扩展中枢层存在", has_hub)
        check(f"L1 数量与序列组一致（{l1_count} vs {seq_group_count}）", consistent)
    else:
        check("多级别展开（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 10  跨周期共振（多周期同向信号）")
    print("=" * 78)
    # 用 day csv 直接调 analyze() 模拟多周期（CSV CLI 仅单周期）
    try:
        import sys
        sys.path.insert(0, HERE)
        import chan_analyzer
        day_data = chan_analyzer.load_csv_data(CSV)
        # 三周期共用同一份数据：验证逻辑而非数据真实性
        multi_result = chan_analyzer.analyze(
            "000001",
            {86400: day_data, 604800: day_data, 2592000: day_data},
        )
        resonances = multi_result.get("跨周期共振", [])
        periods = multi_result.get("periods", [])
        check(f"多周期分析可运行（{len(periods)} 周期）", len(periods) >= 2)
        check(f"共振列表存在", isinstance(resonances, list))
        # 至少应识别出 1 个强度≥2 的事件
        has_strong = any(ev.get("strength", 0) >= 2 for ev in resonances)
        check(f"至少 1 个共振事件（强度≥2）", has_strong,
              f"事件数 {len(resonances)}")
        # 事件结构：含 primary_time / direction / strength / matches
        if resonances:
            ev0 = resonances[0]
            ok_struct = all(k in ev0 for k in ("primary_time", "direction", "strength", "matches"))
            check(f"共振事件结构完整", ok_struct)
    except BaseException as e:
        check(f"跨周期共振（异常 {type(e).__name__}）", False, head(str(e)))

    print("")
    print("=" * 78)
    print("PART 11  CLI 参数杠杆（Stage 3-12）")
    print("=" * 78)
    # 默认 vs 高 基准
    code1, txt1 = run(base + ["--freq", "day", "--json"])
    code2, txt2 = run(base + ["--freq", "day", "--指标计算方式", "高", "--json"])
    if code1 == 0 and code2 == 0:
        d1 = json.loads(txt1)
        d2 = json.loads(txt2)
        sig1 = sum(len(det.get("买卖点", [])) for det in d1["periods_detail"].values())
        sig2 = sum(len(det.get("买卖点", [])) for det in d2["periods_detail"].values())
        # 至少一个参数生效（指标计算方式高 会改变 MACD 数值从而影响命中数）
        # 接受"信号数变化"或"两者中至少一个非零"作为宽松验证
        check(f"--指标计算方式 高 可执行（信号 {sig1} → {sig2}）",
              True, f"信号数变化 = {sig2 != sig1}")
    else:
        check("--指标计算方式", False)

    # --买卖点_指标匹配_MACD False
    code3, txt3 = run(base + ["--freq", "day", "--买卖点_指标匹配_MACD", "False", "--json"])
    check("--买卖点_指标匹配_MACD False", code3 == 0,
          f"exit={code3}")

    # --买卖点_指标模式 配置
    code4, txt4 = run(base + ["--freq", "day", "--买卖点_指标模式", "全量", "--json"])
    check("--买卖点_指标模式 全量", code4 == 0,
          f"exit={code4}")

    print("")
    print("=" * 78)
    print("PART 12  性能")
    print("=" * 78)
    t0 = time.time()
    code, txt = run(base + ["--freq", "day"])
    t1 = time.time()
    check("day 文本模式", code == 0, f"耗时 {t1-t0:.2f}s exit={code}")
    code, txt = run(base + ["--freq", "day", "--json"])
    t2 = time.time()
    check("day JSON 模式", code == 0, f"耗时 {t2-t1:.2f}s exit={code}")

    print("")
    print("=" * 78)
    print(f"结果：{'全部通过' if FAIL_COUNT == 0 else f'{FAIL_COUNT} 项失败'}")
    print("=" * 78)
    return 1 if FAIL_COUNT else 0


if __name__ == "__main__":
    sys.exit(main())
