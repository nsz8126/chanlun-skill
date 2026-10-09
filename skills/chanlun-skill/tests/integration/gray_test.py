#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chan_analyzer.py 灰度测试套件。

覆盖六类场景：
  1. 功能正确性 —— 全部周期（1m~month）× 中英文 × 文本/JSON 输出
  2. 边界健壮性 —— 非法周期名/文件不存在/缺列/非数字/空数据 应给出清晰报错
  3. 数据正确性 —— 笔端点、中枢上下沿不得倒挂
  4. 买卖点方向 —— 向上笔应判 sell、向下笔应判 buy
    5. Rust observer adapter —— 独立观察者构造与 K 线投喂
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
from collections import defaultdict
from datetime import date

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNTIME_DIR = os.path.join(SKILL_ROOT, "scripts")
FIXTURES_DIR = os.path.join(SKILL_ROOT, "tests", "fixtures")
PY = sys.executable
SCRIPT = os.path.join(RUNTIME_DIR, "chan_analyzer.py")
CSV = os.path.join(FIXTURES_DIR, "test_data.csv")

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
    structure_fixture = os.path.join(FIXTURES_DIR, "test_data_t3a.csv")
    code, txt = run([
        "--source", "csv", "--input", structure_fixture,
        "--symbol", "000001", "--freq", "day", "--json",
    ])
    if code == 0:
        d = json.loads(txt)
        bad_stroke = bad_hub = total_stroke = total_hub = 0
        for pname, det in d["periods_detail"].items():
            for s in det["笔序列"]:
                total_stroke += 1
                if s["低"] > s["高"]:
                    bad_stroke += 1
            hubs = list(det["中枢序列"])
            hubs.extend(det.get("线段内部笔中枢", []))
            for z in hubs:
                total_hub += 1
                if z["低"] > z["高"] or z["低低"] > z["高高"]:
                    bad_hub += 1
        check(f"笔端点倒挂（{total_stroke} 条）", total_stroke > 0 and bad_stroke == 0,
              f"倒挂 {bad_stroke} 条")
        check(f"中枢区间倒挂（{total_hub} 个）", total_hub > 0 and bad_hub == 0,
              f"异常 {bad_hub} 个")
    else:
        check("数据正确性（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 4  买卖点方向：向上笔→卖类，向下笔→买类")
    print("=" * 78)
    total_sig = first_second_checked = third_checked = wrong = 0
    direction_errors = []
    for fixture in ("test_data_t3a.csv", "test_data_t3b.csv"):
        code, txt = run([
            "--source", "csv", "--input", os.path.join(FIXTURES_DIR, fixture),
            "--symbol", "000001", "--freq", "day", "--json",
        ])
        if code != 0:
            direction_errors.append(f"{fixture}: {head(txt)}")
            continue
        d = json.loads(txt)
        for det in d["periods_detail"].values():
            for signal in det["买卖点"]:
                total_sig += 1
                kind_is_buy = signal["kind"].endswith("买")
                base_is_buy = signal["base"].endswith("买")
                if kind_is_buy != base_is_buy:
                    wrong += 1
                if signal["base"].startswith(("一", "二")):
                    first_second_checked += 1
                    expected_direction = "向下" if base_is_buy else "向上"
                    if signal["direction"] != expected_direction:
                        wrong += 1
                elif signal["base"].startswith("三"):
                    third_checked += 1
                    position = signal.get("核心判据", {}).get("中枢位置")
                    expected_buy = position == "上方"
                    if position not in ("上方", "下方") or kind_is_buy != expected_buy:
                        wrong += 1
    check(
        f"买卖点方向（{total_sig} 个，一/二类方向 {first_second_checked}，三类位置 {third_checked}）",
        not direction_errors and total_sig > 0 and first_second_checked > 0
        and third_checked > 0 and wrong == 0,
        f"错 {wrong} 个；" + "; ".join(direction_errors),
    )

    print("")
    print("=" * 78)
    print("PART 5  新增能力：买卖点类型 / MACD面积 / BOLL / 序列组")
    print("=" * 78)
    code, txt = run([
        "--source", "csv", "--input", structure_fixture,
        "--symbol", "000001", "--freq", "day", "--boll", "--均线", "5,20", "--json",
    ])
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
        has_sig_types = bool(det.get("买卖点")) and has_sig_types
        check("MACD 面积量", has_area)
        check("BOLL 布林带", has_boll)
        check("均线", has_ma)
        check("级别递归序列组", has_groups)
        check("T 系列类型化", has_sig_types)
    else:
        check("新增能力（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 6  一类结构门槛验证（未满足结构模板不得误报 T1）")
    print("=" * 78)
    trend_csv = os.path.join(FIXTURES_DIR, "test_data_trend.csv")
    if os.path.exists(trend_csv):
        code, txt = run(["--source", "csv", "--input", trend_csv,
                         "--symbol", "000001", "--freq", "day", "--json"])
        if code == 0:
            d = json.loads(txt)
            det = list(d["periods_detail"].values())[0]
            kinds = [s["kind"] for s in det.get("买卖点", [])]
            hubs = det.get("线段内部笔中枢", [])
            has_t1 = any(k.startswith("T1") and not k.startswith("T1P") for k in kinds)
            has_2hub = len(hubs) >= 2
            check("≥2 个线段内部笔中枢（趋势结构）", has_2hub,
                  f"线段内部笔中枢数 {len(hubs)}")
            check("未满足结构模板不误判 T1", not has_t1,
                  f"买卖点 {kinds}")
        else:
            check("趋势数据（无法运行）", False, head(txt))
    else:
        check("趋势数据（缺失 test_data_trend.csv）", False)

    print("")
    print("=" * 78)
    print("PART 7  T3A / T3B 时序验证（严格一类语境）")
    print("=" * 78)
    for label, csv_name, expect in (
        ("T3B（老中枢突破）", "test_data_t3b.csv", "T3B"),
        ("T3A（突破反转后新中枢）", "test_data_t3a.csv", "T3A"),
    ):
        fpath = os.path.join(FIXTURES_DIR, csv_name)
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
    print("PART 8  结构失效边界与条件")
    print("=" * 78)
    code, txt = run([
        "--source", "csv", "--input", structure_fixture,
        "--symbol", "000001", "--freq", "day", "--json",
    ])
    if code == 0:
        d = json.loads(txt)
        det = list(d["periods_detail"].values())[0]
        sigs = det.get("买卖点", [])
        has_boundary = bool(sigs) and all(
            s.get("结构失效边界") is not None for s in sigs
        )
        has_condition = bool(sigs) and all(
            isinstance(s.get("结构失效条件"), str) and s["结构失效条件"]
            for s in sigs
        )
        check(f"结构失效边界存在（{len(sigs)} 个信号）", has_boundary)
        check(f"结构失效条件存在（{len(sigs)} 个信号）", has_condition)
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
        has_mixed_seg = "混合扩展线段层" in ml
        has_mixed_hub = "混合扩展中枢层" in ml
        # 至少 L1 应有数量
        l1_count = ml.get("扩展线段层", [{}])[0].get("数量", 0) if has_seg else 0
        # 与 序列组 一致性
        seq_group_count = det.get("扩展线段序列组", [0])[0]
        consistent = l1_count == seq_group_count
        check("扩展线段层存在", has_seg)
        check("扩展中枢层存在", has_hub)
        check("混合扩展线段层存在", has_mixed_seg)
        check("混合扩展中枢层存在", has_mixed_hub)
        if has_seg and ml["扩展线段层"][0].get("线段"):
            segment_detail = ml["扩展线段层"][0]["线段"][0]
            fine_fields = {"四象", "特征分型终结", "特征序列状态", "缺口"}
            check("线段细粒度字段存在", fine_fields.issubset(segment_detail))
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
        sys.path.insert(0, RUNTIME_DIR)
        import chan_analyzer
        daily = chan_analyzer.load_csv_data(structure_fixture)

        def aggregate(rows, period_key):
            groups = defaultdict(list)
            for row in rows:
                groups[period_key(date.fromisoformat(row["date"]))].append(row)
            return [
                {
                    "date": group[-1]["date"],
                    "open": group[0]["open"],
                    "high": max(row["high"] for row in group),
                    "low": min(row["low"] for row in group),
                    "close": group[-1]["close"],
                    "volume": sum(row["volume"] for row in group),
                }
                for group in groups.values()
            ]

        weekly = aggregate(daily, lambda day: day.isocalendar()[:2])
        monthly = aggregate(daily, lambda day: (day.year, day.month))
        multi_result = chan_analyzer.analyze(
            "000001",
            {86400: daily, 604800: weekly, 2592000: monthly},
        )
        resonances = multi_result.get("跨周期共振", [])
        periods = multi_result.get("periods", [])
        details = multi_result.get("periods_detail", {})
        counts = [details[p]["数据质量"]["K线数量"] for p in ("day", "week", "month")]
        realistic_periods = (
            set(periods) == {"day", "week", "month"}
            and counts[0] > counts[1] > counts[2] > 0
        )
        check(f"真实日/周/月聚合可分析（K线数量 {counts}）", realistic_periods)
        check(f"共振列表存在", isinstance(resonances, list))
        # 聚合后的长周期 fixture 未必自然共振；另用确定性合成信号覆盖命中分支。
        synthetic = chan_analyzer._resonance({
            "day": {"买卖点": [{"kind": "T2买", "time": "2026-01-10 08:00", "index": 3}]},
            "week": {"买卖点": [{"kind": "T3A买", "time": "2026-01-12 08:00", "index": 1}]},
            "month": {"买卖点": [{"kind": "T1卖", "time": "2026-01-10 08:00", "index": 0}]},
        })
        valid_events = bool(synthetic) and all(
            ev.get("strength", 0) >= 2
            and all(k in ev for k in ("primary_time", "direction", "strength", "matches"))
            and len(ev.get("matches", [])) == ev.get("strength")
            for ev in synthetic
        )
        check("跨周期共振命中与事件契约", valid_events,
              f"合成信号产生 {len(synthetic)} 个共振事件")
    except BaseException as e:
        check(f"跨周期共振（异常 {type(e).__name__}）", False, head(str(e)))

    print("")
    print("=" * 78)
    print("PART 11  CLI 参数杠杆（Stage 3-12）")
    print("=" * 78)
    # 固定样例保证有足够的 K 线；验证指标数值变化而非买卖点数量变化。
    indicator_base = [
        "--source", "csv", "--input", structure_fixture,
        "--symbol", "000001", "--freq", "day", "--json",
    ]
    code1, txt1 = run(indicator_base)
    code2, txt2 = run(indicator_base + ["--指标计算方式", "高"])
    if code1 == 0 and code2 == 0:
        d1 = json.loads(txt1)
        d2 = json.loads(txt2)
        rows1 = d1["periods_detail"]["day"].get("指标_最近", [])
        rows2 = d2["periods_detail"]["day"].get("指标_最近", [])
        compared = min(len(rows1), len(rows2))
        changed = any(
            rows1[i].get(field) != rows2[i].get(field)
            for i in range(compared)
            for field in ("macd_dif", "macd_dea", "macd_bar")
            if rows1[i].get(field) is not None and rows2[i].get(field) is not None
        )
        check(f"--指标计算方式 高 改变 MACD 数值（比较 {compared} 根）",
              compared > 0 and changed)
    else:
        check("--指标计算方式", False)

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
    print("PART 13  结构信号溯源与走势判据")
    print("=" * 78)
    if code == 0:
        d = json.loads(txt)
        provenance_ok = trend_ok = True
        for pname, det in d["periods_detail"].items():
            trend_ok = trend_ok and all(
                key in det for key in ("走势类型", "走势方向", "走势判据")
            )
            for sig in det.get("买卖点", []):
                provenance_ok = provenance_ok and all(
                    key in sig for key in (
                        "结构来源", "类型来源", "确认级别",
                        "结构失效边界", "结构失效条件",
                    )
                )
        check("走势类型判据字段", trend_ok)
        check("结构买卖点来源与失效字段", provenance_ok)
    else:
        check("结构信号溯源（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 14  黄金样例回归与标准信号契约")
    print("=" * 78)
    golden_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_regression.py")
    if os.path.exists(golden_script):
        golden = subprocess.run(
            [PY, "-X", "utf8", golden_script],
            capture_output=True,
            timeout=120,
        )
        golden_text = (golden.stdout + golden.stderr).decode("utf-8", "replace")
        check("黄金样例回归", golden.returncode == 0, head(golden_text))
    else:
        check("黄金样例回归脚本存在", False)

    print("")
    print("=" * 78)
    print("PART 15  标准信号 schema 与确认状态机")
    print("=" * 78)
    if code == 0:
        d = json.loads(txt)
        schema_ok = all(
            det.get("标准信号校验", {}).get("有效") is True
            for det in d.get("periods_detail", {}).values()
        )
        state_ok = all(
            all(
                sig.get("确认状态") in ("候选", "已确认", "已失效")
                and sig.get("状态轨迹")
                and sig["状态轨迹"][-1].get("状态") == sig.get("确认状态")
                for sig in det.get("标准信号", [])
            )
            for det in d.get("periods_detail", {}).values()
        )
        check("标准信号 schema 校验", schema_ok)
        check("确认状态轨迹一致", state_ok)
    else:
        check("标准信号 schema 与状态机（无法运行）", False, head(txt))

    print("")
    print("=" * 78)
    print("PART 16  eltdx 分页取数层（离线假客户端）")
    print("=" * 78)
    loader_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data_loader.py")
    if os.path.exists(loader_script):
        loader = subprocess.run(
            [PY, "-X", "utf8", loader_script],
            capture_output=True,
            timeout=60,
        )
        loader_text = (loader.stdout + loader.stderr).decode("utf-8", "replace")
        check("800 根上限分页、合并、排序与参数校验",
              loader.returncode == 0, head(loader_text))
    else:
        check("分页取数层测试脚本存在", False)

    print("")
    print("=" * 78)
    print(f"结果：{'全部通过' if FAIL_COUNT == 0 else f'{FAIL_COUNT} 项失败'}")
    print("=" * 78)
    return 1 if FAIL_COUNT else 0


if __name__ == "__main__":
    sys.exit(main())
