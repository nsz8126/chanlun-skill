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
    print("PART 8  性能")
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
