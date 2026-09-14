"""多周期缠论分析引擎。"""

from __future__ import annotations

from typing import Optional, Dict, List, Any

from chanlun import 缠论配置, 立体分析器, 虚线, 背驰分析, 相对方向

from chanlun_skill.core.adapter import (
    eltdx_to_chanlun,
    fetch_klines,
    feed_klines_to_observer,
    period_to_seconds,
)
from chanlun_skill.core.config import DEFAULT_PERIODS, default_config


class ChanlunAnalyzer:
    """多周期缠论分析器。

    封装 chanlun.立体分析器，提供从 eltdx 获取数据并分析的一站式接口。
    支持买卖点识别和背驰分析。

    :param symbol: 股票代码 (如 "sz000001")
    :param periods: 分析周期列表 (如 ["1m", "5m", "30m", "day"])
    :param config: 缠论配置，为 None 时使用默认配置
    """

    def __init__(
        self,
        symbol: str,
        periods: list[str] | None = None,
        config: 缠论配置 | None = None,
    ):
        self.symbol = symbol
        self.periods = periods or DEFAULT_PERIODS
        self._config = config or default_config()

        # 转换为秒数，从小到大排列
        self._period_seconds = sorted(period_to_seconds(p) for p in self.periods)

        # 创建立体分析器
        self._engine = 立体分析器(
            self.symbol,
            self._period_seconds,
            self._config,
        )

    @property
    def engine(self) -> 立体分析器:
        """底层立体分析器实例。"""
        return self._engine

    # ==================== 数据投喂接口 ====================

    def feed_from_eltdx(
        self,
        client,
        period: str,
        count: int = 800,
        adjust: str | None = None,
    ) -> int:
        """从 eltdx 获取数据并投喂到分析引擎。

        :param client: eltdx TdxClient 实例
        :param period: 周期字符串 (如 "day", "5m", "1m")
        :param count: K线数量
        :param adjust: 复权模式
        :return: 投喂的 K线 数量
        """
        series = fetch_klines(client, self.symbol, period, count, adjust)
        return feed_klines_to_observer(self._engine, series)

    def feed_batch(
        self,
        client,
        counts: dict[str, int] | None = None,
        adjust: str | None = None,
    ) -> dict[str, int]:
        """批量投喂所有周期的数据。

        :param client: eltdx TdxClient 实例
        :param counts: 每个周期的 K线数量，如 {"day": 500, "5m": 500}
        :param adjust: 复权模式
        :return: 每个周期实际投喂的 K线 数量
        """
        if counts is None:
            counts = {p: 800 for p in self.periods}

        result = {}
        for period in self.periods:
            n = counts.get(period, 800)
            result[period] = self.feed_from_eltdx(client, period, n, adjust)
        return result

    # ==================== 结构数据获取接口 ====================

    def get_structure(self, period_seconds: int) -> Dict[str, Any]:
        """获取指定周期的缠论结构数据。

        :param period_seconds: 周期秒数
        :return: 结构数据字典
        """
        obs = self._engine._单体分析器[period_seconds]
        
        return {
            "symbol": self.symbol,
            "period": period_seconds,
            "kline_count": len(obs.普通K线序列),
            "chan_kline_count": len(obs.缠论K线序列),
            "fractal_count": len(obs.分型序列),
            "stroke_count": len(obs.笔序列),
            "hub_count": len(obs.笔_中枢序列),
            "segment_levels": len(obs.线段序列组) if hasattr(obs, "线段序列组") else 0,
            "segment_counts": [len(segs) for segs in obs.线段序列组] if hasattr(obs, "线段序列组") else [],
        }

    def get_strokes(self, period_seconds: int) -> List[Dict[str, Any]]:
        """获取指定周期的笔序列数据。

        :param period_seconds: 周期秒数
        :return: 笔序列列表
        """
        obs = self._engine._单体分析器[period_seconds]
        strokes = []
        
        for stroke in obs.笔序列:
            try:
                direction = str(stroke.方向)
                start_time = stroke.文.中.标的K线.时间戳 if stroke.文 else None
                end_time = stroke.武.中.标的K线.时间戳 if stroke.武 else None
                start_price = stroke.文.中.标的K线.收盘价 if stroke.文 else 0
                end_price = stroke.武.中.标的K线.收盘价 if stroke.武 else 0
                
                strokes.append({
                    "index": stroke.序号,
                    "direction": direction,
                    "start_time": start_time,
                    "end_time": end_time,
                    "start_price": start_price,
                    "end_price": end_price,
                    "stroke": stroke,
                })
            except Exception:
                pass
        
        return strokes

    def get_segments(self, period_seconds: int, level: int = 0) -> List[Dict[str, Any]]:
        """获取指定周期的线段序列数据。

        :param period_seconds: 周期秒数
        :param level: 线段级别 (0=线段, 1=线段<线段>)
        :return: 线段序列列表
        """
        obs = self._engine._单体分析器[period_seconds]
        segments = []
        
        if level < len(obs.线段序列组):
            for seg in obs.线段序列组[level]:
                try:
                    direction = str(seg.方向)
                    start_time = seg.文.中.标的K线.时间戳 if seg.文 else None
                    end_time = seg.武.中.标的K线.时间戳 if seg.武 else None
                    
                    segments.append({
                        "index": seg.序号,
                        "level": level,
                        "direction": direction,
                        "start_time": start_time,
                        "end_time": end_time,
                        "segment": seg,
                    })
                except Exception:
                    pass
        
        return segments

    def get_hubs(self, period_seconds: int) -> List[Dict[str, Any]]:
        """获取指定周期的中枢序列数据。

        :param period_seconds: 周期秒数
        :return: 中枢序列列表
        """
        obs = self._engine._单体分析器[period_seconds]
        hubs = []
        
        for hub in obs.笔_中枢序列:
            try:
                low = hub.基础序列[0].武.中.标的K线.收盘价 if hub.基础序列 else 0
                high = hub.基础序列[0].文.中.标的K线.收盘价 if hub.基础序列 else 0
                
                hubs.append({
                    "index": hub.序号,
                    "low": low,
                    "high": high,
                    "hub": hub,
                })
            except Exception:
                pass
        
        return hubs

    # ==================== 信号检测接口 ====================

    def get_signals(self, period_seconds: int) -> List[Dict[str, Any]]:
        """获取指定周期的买卖点信号。

        :param period_seconds: 周期秒数
        :return: 信号列表
        """
        obs = self._engine._单体分析器[period_seconds]
        signals = []

        for stroke in obs.笔序列:
            try:
                is_signal, reason = 虚线.买卖意义(stroke, obs)
                if is_signal:
                    direction = str(stroke.方向)
                    is_buy = "向上" in direction

                    start_time = stroke.文.中.标的K线.时间戳 if stroke.文 else None
                    end_time = stroke.武.中.标的K线.时间戳 if stroke.武 else None
                    start_price = stroke.文.中.标的K线.收盘价 if stroke.文 else 0
                    end_price = stroke.武.中.标的K线.收盘价 if stroke.武 else 0

                    signals.append({
                        "type": "buy" if is_buy else "sell",
                        "reason": reason,
                        "start_time": start_time,
                        "end_time": end_time,
                        "start_price": start_price,
                        "end_price": end_price,
                        "stroke": stroke,
                    })
            except Exception:
                pass

        return signals

    def get_segment_signals(self, period_seconds: int, level: int = 0) -> List[Dict[str, Any]]:
        """获取指定周期的线段买卖点信号。

        :param period_seconds: 周期秒数
        :param level: 线段级别 (0=线段, 1=线段<线段>)
        :return: 信号列表
        """
        obs = self._engine._单体分析器[period_seconds]
        signals = []

        if level < len(obs.线段序列组):
            segments = obs.线段序列组[level]
        else:
            return signals

        for seg in segments:
            try:
                is_signal, reason = 虚线.买卖意义(seg, obs)
                if is_signal:
                    direction = str(seg.方向)
                    is_buy = "向上" in direction

                    start_time = seg.文.中.标的K线.时间戳 if seg.文 else None
                    end_time = seg.武.中.标的K线.时间戳 if seg.武 else None
                    start_price = seg.文.中.标的K线.收盘价 if seg.文 else 0
                    end_price = seg.武.中.标的K线.收盘价 if seg.武 else 0

                    signals.append({
                        "type": "buy" if is_buy else "sell",
                        "reason": reason,
                        "level": level,
                        "start_time": start_time,
                        "end_time": end_time,
                        "start_price": start_price,
                        "end_price": end_price,
                        "segment": seg,
                    })
            except Exception:
                pass

        return signals

    # ==================== 背驰检测接口 ====================

    def get_divergence(self, period_seconds: int, segment_level: int = 0) -> List[Dict[str, Any]]:
        """获取指定周期的背驰信号。

        :param period_seconds: 周期秒数
        :param segment_level: 线段级别
        :return: 背驰信号列表
        """
        obs = self._engine._单体分析器[period_seconds]
        results = []

        if segment_level >= len(obs.线段序列组):
            return results

        segments = obs.线段序列组[segment_level]

        for i in range(1, len(segments)):
            prev_seg = segments[i - 1]
            curr_seg = segments[i]

            try:
                macd_div = 背驰分析.MACD背驰(prev_seg, curr_seg, obs.普通K线序列)
                slope_div = 背驰分析.斜率背驰(prev_seg, curr_seg)
                measure_div = 背驰分析.测度背驰(prev_seg, curr_seg)

                if macd_div or slope_div or measure_div:
                    direction = str(curr_seg.方向)
                    results.append({
                        "segment_index": i,
                        "direction": direction,
                        "macd_divergence": macd_div,
                        "slope_divergence": slope_div,
                        "measure_divergence": measure_div,
                        "segment": curr_seg,
                    })
            except Exception:
                pass

        return results

    # ==================== 指标获取接口 ====================

    def get_indicators(self, period_seconds: int) -> Dict[str, Any]:
        """获取指定周期的技术指标数据。

        :param period_seconds: 周期秒数
        :return: 指标数据字典
        """
        obs = self._engine._单体分析器[period_seconds]
        
        return {
            "macd": {
                "fast": self._config.平滑异同移动平均线_快线周期,
                "slow": self._config.平滑异同移动平均线_慢线周期,
                "signal": self._config.平滑异同移动平均线_信号周期,
            },
            "rsi": {
                "period": self._config.相对强弱指数_周期,
                "overbought": self._config.相对强弱指数_超买阈值,
                "oversold": self._config.相对强弱指数_超卖阈值,
            },
            "kdj": {
                "rsv_period": self._config.随机指标_RSV周期,
                "k_smooth": self._config.随机指标_K值平滑周期,
                "d_smooth": self._config.随机指标_D值平滑周期,
                "overbought": self._config.随机指标_超买阈值,
                "oversold": self._config.随机指标_超卖阈值,
            },
        }

    # ==================== 摘要接口 ====================

    def summary(self) -> Dict[str, Any]:
        """获取分析结果摘要。"""
        result = {"symbol": self.symbol, "periods": {}}

        for period_sec, obs in self.get_observers().items():
            period_name = self._seconds_to_name(period_sec)

            period_data = {
                "kline_count": len(obs.普通K线序列),
                "chan_kline_count": len(obs.缠论K线序列),
                "fractal_count": len(obs.分型序列),
                "stroke_count": len(obs.笔序列),
                "hub_count": len(obs.笔_中枢序列),
            }

            if hasattr(obs, "线段序列组") and obs.线段序列组:
                period_data["segment_levels"] = len(obs.线段序列组)
                period_data["segment_counts"] = [len(segs) for segs in obs.线段序列组]
            else:
                period_data["segment_levels"] = 0
                period_data["segment_counts"] = []

            stroke_signals = self.get_signals(period_sec)
            period_data["stroke_signal_count"] = len(stroke_signals)
            period_data["stroke_buys"] = sum(1 for s in stroke_signals if s["type"] == "buy")
            period_data["stroke_sells"] = sum(1 for s in stroke_signals if s["type"] == "sell")

            divergence = self.get_divergence(period_sec)
            period_data["divergence_count"] = len(divergence)

            result["periods"][period_name] = period_data

        return result

    # ==================== 级别查询接口 ====================

    def get_level_structure(self, period_seconds: int, level: int = 0) -> Dict[str, Any]:
        """获取指定周期和级别的结构数据。

        :param period_seconds: 周期秒数
        :param level: 递归层级 (0=笔→线段, 1=线段→线段<线段>)
        :return: 结构数据字典
        """
        obs = self._engine._单体分析器[period_seconds]
        
        if level < len(obs.线段序列组):
            segments = obs.线段序列组[level]
            hubs = obs.中枢序列组[level] if level < len(obs.中枢序列组) else []
        else:
            segments = []
            hubs = []
        
        return {
            "symbol": self.symbol,
            "period": period_seconds,
            "level": level,
            "level_name": f"级别{level + 2}" if level > 0 else "线段级别",
            "segment_count": len(segments),
            "hub_count": len(hubs),
            "segments": [
                {
                    "index": seg.序号,
                    "direction": str(seg.方向),
                    "level": seg.级别,
                    "stroke_count": len(seg.基础序列) if hasattr(seg, "基础序列") else 0,
                }
                for seg in segments[:10]  # 最近10个
            ],
        }

    def get_level_signals(self, period_seconds: int, level: int = 0) -> List[Dict[str, Any]]:
        """获取指定周期和级别的买卖点信号。

        :param period_seconds: 周期秒数
        :param level: 递归层级
        :return: 信号列表
        """
        obs = self._engine._单体分析器[period_seconds]
        signals = []

        if level < len(obs.线段序列组):
            segments = obs.线段序列组[level]
        else:
            return signals

        for seg in segments:
            try:
                is_signal, reason = 虚线.买卖意义(seg, obs)
                if is_signal:
                    direction = str(seg.方向)
                    is_buy = "向上" in direction

                    signals.append({
                        "type": "buy" if is_buy else "sell",
                        "reason": reason,
                        "level": level,
                        "level_name": f"级别{level + 2}" if level > 0 else "线段级别",
                        "direction": direction,
                        "segment_index": seg.序号,
                    })
            except Exception:
                pass

        return signals

    def get_multi_level_summary(self, period_seconds: int) -> Dict[str, Any]:
        """获取多级别结构摘要。

        :param period_seconds: 周期秒数
        :return: 各级别摘要
        """
        obs = self._engine._单体分析器[period_seconds]
        
        result = {
            "symbol": self.symbol,
            "period": period_seconds,
            "period_name": self._seconds_to_name(period_seconds),
            "levels": {}
        }
        
        # 笔级别
        stroke_signals = self.get_signals(period_seconds)
        result["levels"]["笔级别"] = {
            "count": len(obs.笔序列),
            "signal_count": len(stroke_signals),
            "buys": sum(1 for s in stroke_signals if s["type"] == "buy"),
            "sells": sum(1 for s in stroke_signals if s["type"] == "sell"),
        }
        
        # 线段级别
        for i, segs in enumerate(obs.线段序列组):
            level_name = f"级别{i + 2}"
            level_signals = self.get_level_signals(period_seconds, i)
            result["levels"][level_name] = {
                "count": len(segs),
                "signal_count": len(level_signals),
                "buys": sum(1 for s in level_signals if s["type"] == "buy"),
                "sells": sum(1 for s in level_signals if s["type"] == "sell"),
            }
        
        return result

    # ==================== 工具方法 ====================

    def get_observer(self, period_seconds: int):
        """获取指定周期的观察者。"""
        return self._engine._单体分析器[period_seconds]

    def get_observers(self) -> dict[int, object]:
        """获取所有周期的观察者。"""
        return dict(self._engine._单体分析器)

    def _seconds_to_name(self, seconds: int) -> str:
        """将秒数转换为周期名称。"""
        _map = {
            60: "1m", 300: "5m", 900: "15m",
            1800: "30m", 3600: "60m", 86400: "day",
        }
        return _map.get(seconds, f"{seconds}s")

    # ==================== 标准买卖点识别 ====================

    def identify_standard_signals(self, period_seconds: int) -> List[Dict[str, Any]]:
        """识别标准缠论买卖点（一买、二买、三买等）。

        :param period_seconds: 周期秒数
        :return: 标准买卖点列表
        """
        obs = self._engine._单体分析器[period_seconds]
        signals = []

        # 获取笔和中枢
        strokes = obs.笔序列
        hubs = obs.笔_中枢序列

        if len(strokes) < 3 or len(hubs) < 1:
            return signals

        # 遍历笔序列识别买卖点
        for i in range(2, len(strokes)):
            stroke = strokes[i]
            prev_stroke = strokes[i - 1]
            prev_prev_stroke = strokes[i - 2]

            try:
                # 识别一买：下跌趋势末端背驰
                if self._is_first_buy(stroke, prev_stroke, prev_prev_stroke, hubs, obs):
                    signals.append(self._create_signal(
                        "一买", stroke, period_seconds,
                        "下跌趋势背驰，可能反转"
                    ))

                # 识别一卖：上涨趋势末端背驰
                if self._is_first_sell(stroke, prev_stroke, prev_prev_stroke, hubs, obs):
                    signals.append(self._create_signal(
                        "一卖", stroke, period_seconds,
                        "上涨趋势背驰，可能反转"
                    ))

                # 识别二买：回调不破一买低点
                if self._is_second_buy(stroke, prev_stroke, strokes, i):
                    signals.append(self._create_signal(
                        "二买", stroke, period_seconds,
                        "回调不破前低，趋势延续"
                    ))

                # 识别二卖：反弹不破一卖高点
                if self._is_second_sell(stroke, prev_stroke, strokes, i):
                    signals.append(self._create_signal(
                        "二卖", stroke, period_seconds,
                        "反弹不破前高，趋势延续"
                    ))

                # 识别三买：中枢突破后回踩不破中枢上沿
                if self._is_third_buy(stroke, hubs, obs):
                    signals.append(self._create_signal(
                        "三买", stroke, period_seconds,
                        "中枢突破后回踩确认"
                    ))

                # 识别三卖：中枢跌破后反弹不破中枢下沿
                if self._is_third_sell(stroke, hubs, obs):
                    signals.append(self._create_signal(
                        "三卖", stroke, period_seconds,
                        "中枢跌破后反弹确认"
                    ))

            except Exception:
                pass

        return signals

    def _is_first_buy(self, stroke, prev_stroke, prev_prev_stroke, hubs, obs) -> bool:
        """判断是否是一买：下跌趋势末端背驰"""
        # 1. 确认下跌趋势：连续向下笔
        if stroke.方向 != 相对方向.向下:
            return False
        if prev_stroke.方向 != 相对方向.向上:
            return False
        if prev_prev_stroke.方向 != 相对方向.向下:
            return False

        # 2. 检查背驰
        try:
            macd_div = 背驰分析.MACD背驰(prev_prev_stroke, stroke, obs.普通K线序列)
            if macd_div:
                return True
        except Exception:
            pass

        return False

    def _is_first_sell(self, stroke, prev_stroke, prev_prev_stroke, hubs, obs) -> bool:
        """判断是否是一卖：上涨趋势末端背驰"""
        # 1. 确认上涨趋势：连续向上笔
        if stroke.方向 != 相对方向.向上:
            return False
        if prev_stroke.方向 != 相对方向.向下:
            return False
        if prev_prev_stroke.方向 != 相对方向.向上:
            return False

        # 2. 检查背驰
        try:
            macd_div = 背驰分析.MACD背驰(prev_prev_stroke, stroke, obs.普通K线序列)
            if macd_div:
                return True
        except Exception:
            pass

        return False

    def _is_second_buy(self, stroke, prev_stroke, strokes, current_index) -> bool:
        """判断是否是二买：回调不破一买低点"""
        if stroke.方向 != 相对方向.向上:
            return False

        # 找到前一个向下笔的低点
        for i in range(current_index - 1, -1, -1):
            if strokes[i].方向 == 相对方向.向下:
                # 检查当前笔的低点是否高于前一个向下笔的低点
                current_low = stroke.武.中.标的K线.低 if stroke.武 else 0
                prev_low = strokes[i].武.中.标的K线.低 if strokes[i].武 else 0
                if current_low > prev_low:
                    return True
                break

        return False

    def _is_second_sell(self, stroke, prev_stroke, strokes, current_index) -> bool:
        """判断是否是二卖：反弹不破一卖高点"""
        if stroke.方向 != 相对方向.向下:
            return False

        # 找到前一个向上笔的高点
        for i in range(current_index - 1, -1, -1):
            if strokes[i].方向 == 相对方向.向上:
                # 检查当前笔的高点是否低于前一个向上笔的高点
                current_high = stroke.武.中.标的K线.高 if stroke.武 else 0
                prev_high = strokes[i].武.中.标的K线.高 if strokes[i].武 else 0
                if current_high < prev_high:
                    return True
                break

        return False

    def _is_third_buy(self, stroke, hubs, obs) -> bool:
        """判断是否是三买：中枢突破后回踩不破中枢上沿"""
        if stroke.方向 != 相对方向.向上 or len(hubs) == 0:
            return False

        # 获取最近的中枢
        last_hub = hubs[-1]
        try:
            # 中枢上沿
            hub_high = max(hub.文.中.标的K线.高 for hub in last_hub.基础序列 if hub.文)
            # 当前笔的低点高于中枢上沿
            current_low = stroke.武.中.标的K线.低 if stroke.武 else 0
            if current_low > hub_high:
                return True
        except Exception:
            pass

        return False

    def _is_third_sell(self, stroke, hubs, obs) -> bool:
        """判断是否是三卖：中枢跌破后反弹不破中枢下沿"""
        if stroke.方向 != 相对方向.向下 or len(hubs) == 0:
            return False

        # 获取最近的中枢
        last_hub = hubs[-1]
        try:
            # 中枢下沿
            hub_low = min(hub.文.中.标的K线.低 for hub in last_hub.基础序列 if hub.文)
            # 当前笔的高点低于中枢下沿
            current_high = stroke.武.中.标的K线.高 if stroke.武 else 0
            if current_high < hub_low:
                return True
        except Exception:
            pass

        return False

    def _create_signal(self, signal_type: str, stroke, period_seconds: int, reason: str) -> Dict[str, Any]:
        """创建标准买卖点信号"""
        direction = str(stroke.方向)
        start_time = stroke.文.中.标的K线.时间戳 if stroke.文 else None
        end_time = stroke.武.中.标的K线.时间戳 if stroke.武 else None
        start_price = stroke.文.中.标的K线.收盘价 if stroke.文 else 0
        end_price = stroke.武.中.标的K线.收盘价 if stroke.武 else 0

        return {
            "signal_type": signal_type,
            "direction": direction,
            "period": period_seconds,
            "period_name": self._seconds_to_name(period_seconds),
            "start_time": start_time,
            "end_time": end_time,
            "start_price": start_price,
            "end_price": end_price,
            "reason": reason,
            "stroke": stroke,
        }

    def get_standard_signal_summary(self, period_seconds: int) -> Dict[str, Any]:
        """获取标准买卖点摘要。

        :param period_seconds: 周期秒数
        :return: 标准买卖点摘要
        """
        signals = self.identify_standard_signals(period_seconds)

        summary = {
            "symbol": self.symbol,
            "period": period_seconds,
            "period_name": self._seconds_to_name(period_seconds),
            "total_signals": len(signals),
            "buy_signals": [],
            "sell_signals": [],
        }

        for sig in signals:
            if "买" in sig["signal_type"]:
                summary["buy_signals"].append(sig)
            else:
                summary["sell_signals"].append(sig)

        return summary