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
from datetime import datetime, timezone

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


def lower_period(seconds: int) -> int:
    """返回严格小于当前周期的最大标准周期。

    当目标周期已是最大周期（month）时，无法向上补足，需向下补一个「占位周期」
    使周期组长度 ≥2 以满足 `立体分析器` 的硬约束；此时该占位周期不会被投喂数据。
    """
    prev = None
    for p in _PERIOD_ORDER:
        if p >= seconds:
            break
        prev = p
    return prev


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_csv_data(file_path: str) -> list:
    data = []
    try:
        f = open(file_path, "r", encoding="utf-8-sig")
    except FileNotFoundError:
        raise SystemExit(f"错误：找不到文件 {file_path!r}")
    except OSError as e:
        raise SystemExit(f"错误：无法读取文件 {file_path!r}：{e}")

    required = {"date", "open", "high", "low", "close", "volume"}
    with f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SystemExit(f"错误：{file_path!r} 无表头")
        missing = required - set(reader.fieldnames)
        if missing:
            raise SystemExit(
                f"错误：{file_path!r} 缺少必需列 {sorted(missing)}，"
                f"需要 {sorted(required)}")
        for i, row in enumerate(reader, start=2):
            try:
                data.append({
                    "date": row["date"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                })
            except (KeyError, ValueError, TypeError) as e:
                raise SystemExit(
                    f"错误：{file_path!r} 第 {i} 行数据非法（{e}）：{row!r}")
    return data


def load_eltdx_data(code: str, freq: str, start_date: str = None, end_date: str = None, count: int = 800) -> list:
    """从 eltdx（通达信 7709 协议）获取 K 线。需要 `pip install eltdx` 且网络可达。

    eltdx 3.x API：`TdxClient` 支持上下文管理器（自动连接/关闭），
    取 K 线走 `client.bars.get(code, period=..., count=...)`，返回对象含 `.bars`
    （KlineBar 元组，字段 time/open/high/low/close/volume_lots）。
    """
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
        with TdxClient(timeout=15) as client:
            series = client.bars.get(code, period=period, count=count)
            for bar in series.bars:
                data.append({
                    "date": bar.time.strftime("%Y-%m-%d"),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume_lots,
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
    """时间戳 -> 可读日期。

    核心库（Rust 绑定）内部把时间戳对齐到 UTC 日边界（即北京时间 08:00），
    因此这里必须用 UTC 时区反解，否则日期会整体偏移 +8 小时导致错位。
    """
    if ts is None:
        return "-"
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
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


def _ts_val(ts) -> int:
    """时间戳统一为可比较的秒级数值。"""
    if ts is None:
        return 0
    try:
        if isinstance(ts, (int, float)):
            return int(ts)
        return int(ts.timestamp())
    except (ValueError, OSError, OverflowError, AttributeError):
        return 0


def _trend_type(obs: 观察者) -> str:
    """走势类型判定：盘整 / 趋势（上涨/下跌）。

    缠论标准：≥2 个依次同向、区间无重叠的中枢 = 趋势；否则 = 盘整。
    判据用「相邻中枢区间的位置关系」（依次上移/下移且无重叠），
    而非中枢的「方向」字段（下跌趋势的中枢方向翻转后可能不一致）。
    """
    hubs = obs.笔_中枢序列
    if len(hubs) < 2:
        return "盘整"
    up = down = 0
    for i in range(len(hubs) - 1):
        z0, z1 = hubs[i], hubs[i + 1]
        if z1.低 > z0.高:      # z1 整体在 z0 上方 → 上移
            up += 1
        elif z1.高 < z0.低:    # z1 整体在 z0 下方 → 下移
            down += 1
        # 否则区间重叠 = 中枢扩展（盘整）
    if up >= 1 and down == 0:
        return "趋势"
    if down >= 1 and up == 0:
        return "趋势"
    return "盘整"


def _first_type_ts(obs: 观察者):
    """找第一个一类买卖点（背驰点）的时间戳，用于 T3A/T3B 时序判定。"""
    for s in obs.笔序列:
        try:
            meaningful, reason = 虚线.买卖意义(s, obs)
        except Exception:
            meaningful, reason = False, ""
        if meaningful and "背驰" in reason:
            return _ts_val(s.武.时间戳)
    return None


def _classify_signals(obs: 观察者) -> list:
    """识别 T 系列买卖点（六类买卖点 = 走势类型 + 背驰信息对基础买卖点的精确化）。

    在 6 类基础买卖点（一/二/三 × 买/卖）之上，按走势类型与回踩次序二次细分：
    - 一类买卖点（背驰点）：
        T1  = 趋势背驰（≥2 个依次同向、区间无重叠的中枢）
        T1P = 盘整背驰（0~1 个中枢）
    - 二类买卖点（有买卖意义、非背驰）：
        T2  = 标准二类（一类之后的第一次回踩不破）
        T2S = 类二类（一类之后的后续回踩不破）
    - 三类买卖点（中枢第三买卖线非空）：
        T3A = 中枢在一类之后形成（反转后新建中枢再突破）
        T3B = 中枢在一类之前形成（突破老中枢 = 二三类重合）

    方向口径：向下笔终点（底分型）= 买；向上笔终点（顶分型）= 卖。
    第三买卖线：按相对中枢的位置（缺口方向）判买/卖——在中枢上方 = 三买，
    在中枢下方 = 三卖（注意不是第三买卖线自身的笔方向）。
    """
    signals = []
    trend = _trend_type(obs)
    first_ts = _first_type_ts(obs)

    # 三类买卖点：来自中枢第三买卖线
    for z in obs.笔_中枢序列:
        line = z.第三买卖线
        if line is None:
            continue
        # 第三买卖线相对中枢的位置（缺口方向），不是它自身的笔方向：
        # 在中枢上方（向上缺口）= 三买；在中枢下方（向下缺口）= 三卖
        is_buy = line.低 >= z.高
        hub_start_ts = _ts_val(z.文.时间戳)  # 中枢起点分型时间戳（形成时序）
        if first_ts is not None and hub_start_ts < first_ts:
            base = "T3B"  # 中枢起点在一类之前 = 老中枢
        else:
            base = "T3A"  # 中枢起点在一类之后 = 新中枢（或无一类参考）
        reason_text = f"中枢#{z.序号} 第三买卖线（走势={trend}"
        if base == "T3B":
            reason_text += "，二三类重合"
        reason_text += "）"
        signals.append({
            "kind": base + ("买" if is_buy else "卖"),
            "base": "三买" if is_buy else "三卖",
            "index": line.序号,
            "direction": "向上" if is_buy else "向下",
            "high": line.高, "low": line.低,
            "break": z.高 if is_buy else z.低,  # 中枢上沿/下沿，回踩跌破即失效
            "reason": reason_text,
        })

    # 一/二类：来自具备买卖意义的笔
    # 二类按「一类之后的回踩次序」区分：第一次回踩 = T2，后续回踩 = T2S
    buy_stage = 0   # 一买之后出现过的非背驰买点计数
    sell_stage = 0  # 一卖之后出现过的非背驰卖点计数
    for s in obs.笔序列:
        try:
            meaningful, reason = 虚线.买卖意义(s, obs)
        except Exception:
            meaningful, reason = False, ""
        if not meaningful:
            continue
        d = _dir_name(s.方向)
        is_buy = d == "向下"  # 向下笔终点是底分型 → 买点语境
        is_first = "背驰" in reason  # 背驰 → 一类
        if is_first:
            base = "T1" if trend == "趋势" else "T1P"
            base_label = "一买" if is_buy else "一卖"
            # 一类点出现后，重置对应方向的二类回踩计数
            if is_buy:
                buy_stage = 0
            else:
                sell_stage = 0
        else:
            if is_buy:
                buy_stage += 1
                base = "T2" if buy_stage == 1 else "T2S"
            else:
                sell_stage += 1
                base = "T2" if sell_stage == 1 else "T2S"
            base_label = "二买" if is_buy else "二卖"
        signals.append({
            "kind": base + ("买" if is_buy else "卖"),
            "base": base_label,
            "index": s.序号,
            "direction": d,
            "high": s.高, "low": s.低,
            "break": s.低 if is_buy else s.高,  # 跌破/涨破端点即失效
            "reason": reason,
        })

    signals.sort(key=lambda x: x["index"])
    return signals


def _divergences(obs: 观察者) -> list:
    """基于核心库 `背驰分析` 与 `线段.判断线段内部是否背驰` 检测背驰。

    线段/笔对象的方法为 classmethod，实例必须作第一个参数传入。
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
    # 笔内 MACD 趋向背驰（笔.是否背驰过）
    for s in obs.笔序列:
        try:
            positions = 笔.是否背驰过(s, obs)
        except Exception:
            positions = []
        if positions:
            results.append({
                "kind": "笔内背驰",
                "index": s.序号,
                "direction": _dir_name(s.方向),
                "high": s.高, "low": s.低,
            })
    # 相邻线段对之间的 MACD/斜率/测度/全量背驰
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
            ("全量", lambda: 背驰分析.全量背驰_OBS(a, b, obs)),
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


def _get_container(k, name):
    """从 K 线指标容器取子指标，兼容 Rust 绑定（dict）与属性访问。"""
    指标 = getattr(k, "指标", None)
    if 指标 is None:
        return None
    if isinstance(指标, dict):
        return 指标.get(name)
    return getattr(指标, name, None)


def _indicator_tail(obs: 观察者, n: int = 3) -> list:
    """提取最近 N 根 K 线的技术指标值（挂在 K 线上）。"""
    rows = []
    for k in obs.普通K线序列[-n:]:
        macd = getattr(k, "macd", None)
        rsi = getattr(k, "rsi", None)
        kdj = getattr(k, "kdj", None)
        boll = _get_container(k, "boll")
        均线 = _get_container(k, "均线")
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
            "boll_up": getattr(boll, "上轨", None),
            "boll_mid": getattr(boll, "中轨", None),
            "boll_low": getattr(boll, "下轨", None),
            "均线": dict(均线) if isinstance(均线, dict) else None,
        })
    return rows


def _macd_area(obs: 观察者) -> dict:
    """用 `K线.获取MACD` 计算全序列 MACD 柱面积分向统计（量化背驰的原料）。

    注意：该方法要求普 `K线` 序列（非缠论K线），且 `始`/`终` 是 K 线对象而非索引。
    """
    ks = obs.普通K线序列
    if len(ks) < 2:
        return {}
    try:
        return K线.获取MACD(ks, ks[0], ks[-1])
    except BaseException:
        return {}


# ---------------------------------------------------------------------------
# 结构化结果
# ---------------------------------------------------------------------------
def analyze(symbol: str, data: list, freq: str, config: 缠论配置 = None) -> dict:
    """投喂数据并产出结构化结果。

    周期组必须长度 ≥2，否则 `立体分析器` 会触发 Rust 侧 PanicException。
    - 常规：`[目标周期, 更大周期]`，走 `投喂K线` 自动合成大周期。
    - 目标已是最大周期（month）：`[更小周期, month]`，直接对 month 观察者
      `增加原始K线` 投喂（`投喂K线` 会校验周期 == 周期组最小值，month 无法作为
      最小值投喂），更小周期作为占位留空。
    """
    seconds = period_to_seconds(freq)
    up = upper_period(seconds)
    is_max_period = (up == seconds)  # 无更大周期可补

    if is_max_period:
        periods = [lower_period(seconds), seconds]
    else:
        periods = [seconds, up]

    cfg = config if config is not None else 缠论配置.不推送()
    engine = 立体分析器(symbol, periods, cfg)

    if is_max_period:
        # 直接对目标观察者投喂，绕过 投喂K线 的周期校验
        target_obs = engine._单体分析器[seconds]
        for i, row in enumerate(data):
            ts = _parse_date(row["date"], i)
            k = K线.创建普K(
                symbol, ts, row["open"], row["high"], row["low"], row["close"],
                row["volume"], i, seconds,
            )
            target_obs.增加原始K线(k)
    else:
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

        # flush 最后一根 pending K 线。核心库的 `投喂K线`（立体分析器合成器）
        # 会把最后一根 K 线留在「当前K线」状态（未确认、不进序列），需投喂一根
        # 下一周期的占位 K 线触发它完成进序列。占位 K 线自身成为新的 pending，
        # 不会进入观察者序列、不污染结构/指标。month 模式（直接 `增加原始K线`）
        # 无此问题，故仅在常规周期下 flush。
        if data:
            last = data[-1]
            last_ts = _parse_date(last["date"], len(data) - 1)
            flush_ts = last_ts + seconds
            flush_k = K线.创建普K(
                symbol, flush_ts,
                last["close"], last["close"], last["close"], last["close"],
                0, len(data), seconds,
            )
            engine.投喂K线(flush_k)

    # 每个周期一个观察者（空周期会被过滤）
    observers = {p: engine._单体分析器[p] for p in periods}

    result = {
        "symbol": symbol,
        "freq": seconds_to_name(seconds),
        "periods": [seconds_to_name(p) for p in periods],
        "kline_count": len(data),
        "periods_detail": {},
    }

    for p, obs in observers.items():
        if len(obs.普通K线序列) == 0:
            continue  # 占位周期无数据，跳过
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
        # 级别递归序列组（多级别结构，逐层展开计数）
        detail["线段序列组"] = [len(g) for g in obs.线段序列组]
        detail["中枢序列组"] = [len(g) for g in obs.中枢序列组]
        detail["扩展线段序列组"] = [len(g) for g in obs.扩展线段序列组]
        detail["扩展中枢序列组"] = [len(g) for g in obs.扩展中枢序列组]
        detail["混合扩展线段序列组"] = [len(g) for g in obs.混合扩展线段序列组]
        detail["混合扩展中枢序列组"] = [len(g) for g in obs.混合扩展中枢序列组]
        detail["买卖点"] = _classify_signals(obs)[-10:]
        detail["背驰"] = _divergences(obs)[-10:]
        detail["MACD面积"] = _macd_area(obs)
        detail["指标_最近"] = _indicator_tail(obs, 3)
        result["periods_detail"][name] = detail

    return result


def _parse_date(date_str: str, fallback: int) -> int:
    """日期字符串 -> 秒级时间戳。

    关键：核心库（Rust 绑定）把时间戳按 UTC 对齐到周期边界。若用本地时区
    （北京时间）的 00:00 生成时间戳，会被向下对齐到「前一个 UTC 日」，导致
    日期整体偏移 -1 天。因此这里用 UTC 00:00 生成时间戳（等价于本地时间戳 +8h）。
    """
    try:
        return int(datetime.strptime(date_str, "%Y-%m-%d")
                   .replace(tzinfo=timezone.utc).timestamp())
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
            lines.append("  买卖点（T 系列）：")
            for s in d["买卖点"]:
                lines.append(f"    {s['kind']}（{s['base']}） 笔#{s['index']} {s['direction']} "
                             f"[{s['low']:.2f} ~ {s['high']:.2f}] "
                             f"破位 {s['break']:.2f} 理由={s['reason'] or '-'}")
        if d["背驰"]:
            lines.append("  背驰：")
            for v in d["背驰"]:
                lines.append(f"    {v['kind']} #{v['index']} {v['direction']}")
        if d.get("MACD面积"):
            lines.append(f"  MACD面积（全序列）: {d['MACD面积']}")
        if d.get("指标_最近"):
            lines.append("  最近指标：")
            for r in d["指标_最近"]:
                line = (f"    {r['time']} 收 {r['close']:.2f} "
                        f"MACD(DIF {r['macd_dif']}, BAR {r['macd_bar']}) "
                        f"RSI {r['rsi']} KDJ(K {r['kdj_k']}, D {r['kdj_d']}, J {r['kdj_j']})")
                if r.get("boll_mid") is not None:
                    line += f" BOLL({r['boll_low']:.2f}/{r['boll_mid']:.2f}/{r['boll_up']:.2f})"
                if r.get("均线"):
                    line += f" 均线{r['均线']}"
                lines.append(line)

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
    parser.add_argument("--symbol", type=str, default=None,
                        help="标的标识（默认：csv 模式为 000001，eltdx 模式为 code）")
    parser.add_argument("--start_date", type=str, help="开始日期 YYYY-MM-DD（eltdx）")
    parser.add_argument("--end_date", type=str, help="结束日期 YYYY-MM-DD（eltdx）")
    parser.add_argument("--freq", type=str, default="day", help="分析周期（1m/5m/.../day/week/month 或中文）")
    parser.add_argument("--count", type=int, default=800, help="eltdx 拉取 K 线数量")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    parser.add_argument("--output", type=str, help="输出文件路径")
    parser.add_argument("--cal_indicators", action="store_true", default=True,
                        help="计算技术指标（默认开）")
    parser.add_argument("--笔内元素数量", type=int, default=None,
                        help="成笔最低 K 线数（默认 5，改 3 笔数可增加约 2.9 倍）")
    parser.add_argument("--买卖点激进识别", action="store_true", default=None,
                        help="买卖点激进识别（不考虑分型完整性）")
    parser.add_argument("--boll", action="store_true", help="计算 BOLL 布林带")
    parser.add_argument("--均线", type=str, default=None,
                        help="计算均线，逗号分隔周期（如 5,20,60）")
    parser.add_argument("--均线类型", type=str, default="SMA",
                        help="均线类型（SMA/EMA，逗号分隔，如 SMA,EMA）")

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
    if args.笔内元素数量 is not None:
        config.笔内元素数量 = args.笔内元素数量
    if args.买卖点激进识别 is not None:
        config.买卖点激进识别 = args.买卖点激进识别
    if args.boll:
        config.计算BOLL = True
    if args.均线:
        periods = [int(x) for x in args.均线.split(",") if x.strip()]
        types = [t.strip().upper() for t in args.均线类型.split(",") if t.strip()]
        types = [t for t in types if t in ("SMA", "EMA")] or ["SMA"]
        config.均线_类型列表 = types
        config.均线_周期列表 = periods

    # 分析
    symbol = args.symbol or (args.code if args.source == "eltdx" else "000001")
    try:
        result = analyze(symbol, data, args.freq, config)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except BaseException as e:
        # 兜底：PanicException 继承 BaseException，这里让错误可见而非无声猝死
        print(f"错误：分析失败（{type(e).__name__}）：{e}", file=sys.stderr)
        sys.exit(1)

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
