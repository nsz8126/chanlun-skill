#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论综合分析工具（直接基于 chanlun 核心库）

本脚本是 chanlun-skill 的唯一分析入口，直接调用 chanlun 核心库的完整能力，
不再依赖任何中间封装包。核心库的 API 面（__init__.pyi / chan.py）：

  - 立体分析器：多周期合成。声明周期组（长度 ≥2），只投喂最小周期的 K 线，
    引擎自动合成更大周期。单周期会触发 Rust 侧 PanicException（继承 BaseException，
    普通 except Exception 抓不到）。
  - 观察者：22 个结构序列（普通K线/缠K/分型/笔/线段/扩展线段/扩展中枢/各级线段组…）。
  - 买卖点类型：18 种（一/二/三买卖 + T1/T1P/T2/T2S/T3A/T3B 买卖），
    附 `是买点` / `是卖点` 布尔属性。
  - 虚线.买卖意义(线, 观察者) -> (bool, str)：仅返回「此处是否具备买卖意义」与理由，
    不返回方向、不返回类型。方向由分型结构（顶/底）或 K 线 MACD 柱正负判定。
  - 背驰分析：MACD/斜率/测度/全量/任意/配置/任选 14 个方法，均为 classmethod，
    实例必须作为第一个参数传入（如 线段.判断线段内部是否背驰(段, 观察者)）。
  - 指标：MACD/RSI/KDJ/BOLL 挂载在每根 K 线上（K线.macd / .rsi / .kdj / .指标）。

用法：
    python chan_analyzer.py --source csv --input test_data.csv --symbol 000001 --freq day
    python chan_analyzer.py --source csv --input test_data.csv --symbol 000001 --freq day --json
    python chan_analyzer.py --source eltdx --code sh600519 --freq day

依赖：chanlun（核心库）、eltdx（在线数据源，可选）。
"""

import argparse
import csv
import json
import sys
from datetime import datetime

from chanlun import K线, 立体分析器, 缠论配置, 观察者, 虚线, 笔, 线段, 中枢, 背驰分析

# ---------------------------------------------------------------------------
# 周期映射：中文/英文名 -> 秒
# ---------------------------------------------------------------------------
_PERIOD_SECONDS = {
    "1m": 60, "1分钟": 60, "60s": 60,
    "5m": 300, "5分钟": 300,
    "15m": 900, "15分钟": 900,
    "30m": 1800, "30分钟": 1800,
    "60m": 3600, "60分钟": 3600, "1h": 3600,
    "day": 86400, "日线": 86400, "日": 86400,
    "week": 604800, "周线": 604800, "周": 604800,
    "month": 2592000, "月线": 2592000, "月": 2592000,
}
# 由小到大排列，用于自动补上级周期
_PERIOD_ORDER = [60, 300, 900, 1800, 3600, 86400, 604800, 2592000]

_SECONDS_NAME = {
    60: "1m", 300: "5m", 900: "15m", 1800: "30m",
    3600: "60m", 86400: "day", 604800: "week", 2592000: "month",
}


def period_to_seconds(freq: str) -> int:
    """周期名 -> 秒，支持中文与英文别名。"""
    key = str(freq).strip().lower()
    if key in _PERIOD_SECONDS:
        return _PERIOD_SECONDS[key]
    # 兼容 "N分钟"/"Nm"/"Nmin" 数字前缀
    if key.endswith(("分钟", "m", "min")):
        digits = "".join(ch for ch in key if ch.isdigit())
        if digits:
            return int(digits) * 60
    raise ValueError(f"不支持的周期: {freq!r}，可选：1m/5m/15m/30m/60m/day/week/month 或中文（1分钟/日线/周线/月线）")


def seconds_to_name(seconds: int) -> str:
    return _SECONDS_NAME.get(seconds, f"{seconds}s")


def upper_period(seconds: int) -> int:
    """返回严格大于当前周期的最小标准周期，用于补足周期组（单周期会 panic）。"""
    for p in _PERIOD_ORDER:
        if p > seconds:
            return p
    return seconds  # 已是最大周期则回退


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_csv_data(file_path: str) -> list:
    data = []
    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append({
                "date": row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    return data


def load_eltdx_data(code: str, freq: str, start_date: str = None, end_date: str = None, count: int = 800) -> list:
    """从 eltdx（通达信协议）获取 K 线。需要 `pip install eltdx` 且网络可达。"""
    try:
        from eltdx import TdxClient
    except ImportError:
        raise SystemExit("错误：需要安装 eltdx 库：pip install eltdx")

    period_map = {
        60: "1m", 300: "5m", 900: "15m", 1800: "30m",
        3600: "60m", 86400: "day", 604800: "week", 2592000: "month",
    }
    seconds = period_to_seconds(freq)
    period = period_map.get(seconds, "day")

    data = []
    try:
        with TdxClient() as client:
            from eltdx.constant import KLINE_TYPE  # 兼容不同 eltdx 版本
            # 不同版本 API 略有差异，这里用最通用的方式
            try:
                series = client.get_kline(code, period, count=count)
            except TypeError:
                series = client.get_kline(code, period, count)
            for bar in series:
                data.append({
                    "date": bar.time.strftime("%Y-%m-%d"),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": getattr(bar, "volume_lots", getattr(bar, "volume", 0)),
                })
    except Exception as e:
        raise SystemExit(f"错误：从 eltdx 获取数据失败：{e}")

    # 按日期范围裁剪
    if start_date:
        data = [d for d in data if d["date"] >= start_date]
    if end_date:
        data = [d for d in data if d["date"] <= end_date]
    return data


# ---------------------------------------------------------------------------
# 取数：全部走核心库原生字段，不做二次推断
# ---------------------------------------------------------------------------
def _fmt_ts(ts) -> str:
    """时间戳 -> 可读日期。核心库时间戳为 datetime 或 int。"""
    if ts is None:
        return "-"
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return str(ts)


def _dir_name(d) -> str:
    """相对方向对象 -> 简洁中文（向上/向下/缺口/衔接/包含）。

    运行时该对象是 Rust 绑定类型（chanlun._chanlun.相对方向），
    其 name/value 均为 None，str() 返回形如 "相对方向.向下"。
    因此这里优先调用布尔方法（返回 builtin method 对象时再退回字符串解析）。
    """
    # 优先尝试布尔方法（部分版本返回 method 对象，需调用）
    for attr in ("是否向上", "是否向下", "是否缺口", "是否衔接", "是否包含"):
        m = getattr(d, attr, None)
        if callable(m):
            try:
                if m():
                    return {"是否向上": "向上", "是否向下": "向下",
                            "是否缺口": "缺口", "是否衔接": "衔接", "是否包含": "包含"}[attr]
            except Exception:
                pass
    s = str(d)
    for kw in ("向上", "向下", "缺口", "衔接", "包含", "顺", "逆", "同"):
        if kw in s:
            return kw
    return s


def _buy_sell_info(obs: 观察者) -> list:
    """从缠论K线序列中提取买卖点信息（核心库原生 `缠论K线.买卖点信息`）。"""
    infos = []
    for ck in obs.缠论K线序列:
        info = getattr(ck, "买卖点信息", None)
        if info is not None:
            infos.append(info)
    return infos


def _stroke_signals(obs: 观察者) -> list:
    """基于核心库 `虚线.买卖意义` 提取具备买卖意义的笔级信号。

    核心语义：买卖意义只返回「此处是否具备买卖意义 + 理由」。
    方向判定：笔的方向（向上=顶分型终点→卖出语境，向下=底分型终点→买入语境）。
    这是官方正确口径，不再用「向上=买」的反向推断。
    """
    signals = []
    for s in obs.笔序列:
        try:
            meaningful, reason = 虚线.买卖意义(s, obs)
        except Exception:
            meaningful, reason = False, ""
        if not meaningful:
            continue
        direction = s.方向
        # 向上笔终点是顶分型 → 卖出语境；向下笔终点是底分型 → 买入语境
        is_up = _dir_name(direction) == "向上"
        signals.append({
            "kind": "sell" if is_up else "buy",
            "index": s.序号,
            "high": s.高,
            "low": s.低,
            "direction": _dir_name(direction),
            "reason": reason,
        })
    return signals


def _divergences(obs: 观察者) -> list:
    """基于核心库 `背驰分析` 与 `线段.判断线段内部是否背驰` 检测背驰。

    线段对象的方法为 classmethod，实例必须作第一个参数传入。
    """
    results = []
    # 线段级内部背驰（最贴近原文的「线段内部背驰」）
    for seg in obs.线段序列:
        try:
            inner = 线段.判断线段内部是否背驰(seg, obs)
        except Exception:
            inner = None
        if inner:
            results.append({
                "kind": "线段内部背驰",
                "index": seg.序号,
                "direction": _dir_name(seg.方向),
                "high": seg.高, "low": seg.低,
            })
    # 相邻线段对之间的 MACD/斜率/测度背驰
    segs = obs.线段序列
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        if a.方向 != b.方向:
            continue
        kinds = []
        for name, fn in (
            ("MACD", lambda: 背驰分析.MACD背驰_OBS(a, b, obs)),
            ("斜率", lambda: 背驰分析.斜率背驰(a, b)),
            ("测度", lambda: 背驰分析.测度背驰(a, b)),
        ):
            try:
                if fn():
                    kinds.append(name)
            except Exception:
                pass
        if kinds:
            results.append({
                "kind": "+".join(kinds),
                "index": b.序号,
                "direction": _dir_name(b.方向),
                "high": b.高, "low": b.低,
            })
    return results


def _indicator_tail(obs: 观察者, n: int = 3) -> list:
    """提取最近 N 根 K 线的技术指标值（挂在 K 线上）。"""
    rows = []
    for k in obs.普通K线序列[-n:]:
        macd = getattr(k, "macd", None)
        rsi = getattr(k, "rsi", None)
        kdj = getattr(k, "kdj", None)
        rows.append({
            "time": _fmt_ts(k.时间戳),
            "close": k.收盘价,
            "macd_dif": getattr(macd, "DIF", None),
            "macd_dea": getattr(macd, "DEA", None),
            "macd_bar": getattr(macd, "MACD柱", None),
            "rsi": getattr(rsi, "RSI", None),
            "kdj_k": getattr(kdj, "K", None),
            "kdj_d": getattr(kdj, "D", None),
            "kdj_j": getattr(kdj, "J", None),
        })
    return rows


# ---------------------------------------------------------------------------
# 结构化结果
# ---------------------------------------------------------------------------
def analyze(symbol: str, data: list, freq: str, config: 缠论配置 = None) -> dict:
    """投喂数据并产出结构化结果。"""
    seconds = period_to_seconds(freq)
    periods = [seconds]
    up = upper_period(seconds)
    if up != seconds and up not in periods:
        periods.append(up)  # 保证周期组长度 ≥2，避免单周期 panic

    cfg = config if config is not None else 缠论配置.不推送()
    engine = 立体分析器(symbol, periods, cfg)

    for i, row in enumerate(data):
        ts = _parse_date(row["date"], i)
        k = K线.创建普K(
            symbol, ts, row["open"], row["high"], row["low"], row["close"],
            row["volume"], i, seconds,
        )
        try:
            engine.投喂K线(k)
        except BaseException:
            # PanicException 继承 BaseException，这里兜底让错误可见而非静默崩
            raise

    # 每个周期一个观察者
    observers = {p: engine._单体分析器[p] for p in periods}

    result = {
        "symbol": symbol,
        "freq": seconds_to_name(seconds),
        "periods": [seconds_to_name(p) for p in periods],
        "kline_count": len(data),
        "periods_detail": {},
    }

    for p, obs in observers.items():
        name = seconds_to_name(p)
        detail = {
            "普通K线": len(obs.普通K线序列),
            "缠论K线": len(obs.缠论K线序列),
            "分型": len(obs.分型序列),
            "笔": len(obs.笔序列),
            "笔中枢": len(obs.笔_中枢序列),
            "线段": len(obs.线段序列),
            "中枢": len(obs.中枢序列),
            "扩展线段": len(obs.扩展线段序列),
            "扩展中枢": len(obs.扩展中枢序列),
            "线段_线段": len(obs.线段_线段序列),
            "线段_中枢": len(obs.线段_中枢序列),
            "扩展线段_扩展线段": len(obs.扩展线段序列_扩展线段),
            "扩展中枢_扩展线段": len(obs.扩展中枢序列_扩展线段),
        }
        detail["笔序列"] = [
            {"序号": s.序号, "方向": _dir_name(s.方向), "高": s.高, "低": s.低,
             "文": _fmt_ts(s.文.时间戳), "武": _fmt_ts(s.武.时间戳)}
            for s in obs.笔序列[-10:]
        ]
        detail["中枢序列"] = [
            {"序号": z.序号, "高": z.高, "低": z.低, "高高": z.高高, "低低": z.低低,
             "状态": z.当前状态() if hasattr(z, "当前状态") else ""}
            for z in obs.笔_中枢序列[-5:]
        ]
        detail["买卖点"] = _stroke_signals(obs)[-10:]
        detail["背驰"] = _divergences(obs)[-10:]
        detail["指标_最近"] = _indicator_tail(obs, 3)
        result["periods_detail"][name] = detail

    return result


def _parse_date(date_str: str, fallback: int) -> int:
    try:
        return int(datetime.strptime(date_str, "%Y-%m-%d").timestamp())
    except (ValueError, TypeError):
        return fallback


# ---------------------------------------------------------------------------
# 文本报告
# ---------------------------------------------------------------------------
def render_text(result: dict) -> str:
    lines = []
    lines.append("=" * 64)
    lines.append(f"  {result['symbol']} 缠论分析（{result['freq']}，周期组 {result['periods']}）")
    lines.append("=" * 64)

    for name, d in result["periods_detail"].items():
        lines.append("")
        lines.append(f"--- {name} ---")
        lines.append(f"  K线 {d['普通K线']}  缠K {d['缠论K线']}  分型 {d['分型']}  "
                     f"笔 {d['笔']}  笔中枢 {d['笔中枢']}")
        lines.append(f"  线段 {d['线段']}  中枢 {d['中枢']}  扩展线段 {d['扩展线段']}  "
                     f"扩展中枢 {d['扩展中枢']}")

        if d["笔序列"]:
            lines.append("  最近笔：")
            for s in d["笔序列"]:
                lines.append(f"    笔#{s['序号']} {s['方向']} {s['文']}→{s['武']} "
                             f"[{s['低']:.2f} ~ {s['高']:.2f}]")
        if d["中枢序列"]:
            lines.append("  中枢：")
            for z in d["中枢序列"]:
                lines.append(f"    中枢#{z['序号']} 区间 [{z['低']:.2f} ~ {z['高']:.2f}] "
                             f"极值 [{z['低低']:.2f} ~ {z['高高']:.2f}] {z['状态']}")
        if d["买卖点"]:
            lines.append("  买卖点（核心库 买卖意义）：")
            for s in d["买卖点"]:
                icon = "S" if s["kind"] == "sell" else "B"
                lines.append(f"    [{icon}] 笔#{s['index']} {s['direction']} "
                             f"理由={s['reason'] or '-'}")
        if d["背驰"]:
            lines.append("  背驰：")
            for v in d["背驰"]:
                lines.append(f"    {v['kind']} #{v['index']} {v['direction']}")
        if d["指标_最近"]:
            lines.append("  最近指标：")
            for r in d["指标_最近"]:
                lines.append(f"    {r['time']} 收 {r['close']:.2f} "
                             f"MACD(DIF {r['macd_dif']}, BAR {r['macd_bar']}) "
                             f"RSI {r['rsi']} KDJ(K {r['kdj_k']}, D {r['kdj_d']}, J {r['kdj_j']})")

    lines.append("")
    lines.append("=" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="缠论综合分析工具（chanlun 核心库）")
    parser.add_argument("--source", choices=["csv", "eltdx"], default="csv", help="数据源")
    parser.add_argument("--input", type=str, help="CSV 文件路径（csv 模式）")
    parser.add_argument("--code", type=str, help="股票代码（eltdx 模式，如 sh600519）")
    parser.add_argument("--symbol", type=str, default="000001", help="标的标识")
    parser.add_argument("--start_date", type=str, help="开始日期 YYYY-MM-DD（eltdx）")
    parser.add_argument("--end_date", type=str, help="结束日期 YYYY-MM-DD（eltdx）")
    parser.add_argument("--freq", type=str, default="day", help="分析周期（1m/5m/.../day/week/month 或中文）")
    parser.add_argument("--count", type=int, default=800, help="eltdx 拉取 K 线数量")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    parser.add_argument("--output", type=str, help="输出文件路径")
    parser.add_argument("--cal_indicators", action="store_true", default=True,
                        help="计算技术指标（默认开）")

    args = parser.parse_args()

    # 加载数据
    if args.source == "csv":
        if not args.input:
            print("错误：csv 模式需要 --input", file=sys.stderr)
            sys.exit(1)
        data = load_csv_data(args.input)
    else:
        if not args.code:
            print("错误：eltdx 模式需要 --code", file=sys.stderr)
            sys.exit(1)
        data = load_eltdx_data(args.code, args.freq, args.start_date, args.end_date, args.count)

    if len(data) < 2:
        print("错误：数据不足（<2 根 K 线），无法分析", file=sys.stderr)
        sys.exit(1)

    # 配置：默认开启指标，关闭推送
    config = 缠论配置.不推送()
    config.计算指标 = args.cal_indicators

    # 分析
    result = analyze(args.symbol, data, args.freq, config)

    # 输出
    if args.json:
        out = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    else:
        out = render_text(result)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"报告已保存到 {args.output}")
    else:
        print(out)


if __name__ == "__main__":
    main()
