"""Text rendering for structured Chan analysis results."""


def render_text(result: dict) -> str:
    """Render the analysis payload as the human-readable CLI report."""
    lines = []
    lines.append("=" * 64)
    lines.append(f"  {result['symbol']} 缠论分析（{result['freq']}，周期组 {result['periods']}）")
    source_meta = result.get("data_source", {})
    if source_meta:
        lines.append(
            f"  数据源={source_meta.get('source', '-')}"
            f"  复权={source_meta.get('复权模式', '-')}"
            + (
                f"  锚定日期={source_meta['anchor_date']}"
                if source_meta.get("anchor_date") else ""
            )
        )
    lines.append("=" * 64)

    for name, detail in result["periods_detail"].items():
        lines.append("")
        lines.append(f"--- {name} ---")
        lines.append(f"  K线 {detail['普通K线']}  缠K {detail['缠论K线']}  分型 {detail['分型']}  "
                     f"笔 {detail['笔']}  笔中枢 {detail['笔中枢']}")
        lines.append(
            f"  笔中枢口径：{detail.get('笔中枢口径', '未知')}"
            f"（原始全局笔中枢 {detail.get('原始全局笔中枢', 0)}，仅审计）"
        )
        lines.append(f"  线段 {detail['线段']}  中枢 {detail['中枢']}  扩展线段 {detail['扩展线段']}  "
                     f"扩展中枢 {detail['扩展中枢']}")
        lines.append(f"  走势类型：{detail.get('走势类型', '未知')} "
                     f"方向={detail.get('走势方向', '未知')}")
        trend_evidence = detail.get("走势判据", {})
        if trend_evidence:
            lines.append(
                f"  走势判据：{trend_evidence.get('判据来源', '未知')} "
                f"上移={trend_evidence.get('上移次数', 0)} "
                f"下移={trend_evidence.get('下移次数', 0)} "
                f"重叠={trend_evidence.get('重叠次数', 0)}"
            )
        quality = detail.get("数据质量", {})
        if quality.get("问题"):
            lines.append(f"  数据质量警告：{len(quality['问题'])} 项")
        contract = detail.get("标准信号校验", {})
        if contract:
            lines.append(
                f"  标准信号校验：{'通过' if contract.get('有效') else '失败'}"
                f"（错误 {len(contract.get('错误', []))} 项）"
            )
        semantic = detail.get("语义摘要", {})
        for interpretation in semantic.get("解释", [])[:2]:
            lines.append(f"  语义判断：{interpretation.get('结论', '-')}"
                         f"（{interpretation.get('确定性', '未知')}）")

        if detail["笔序列"]:
            lines.append("  最近笔：")
            for stroke in detail["笔序列"]:
                lines.append(f"    笔#{stroke['序号']} {stroke['方向']} {stroke['文']}→{stroke['武']} "
                             f"[{stroke['低']:.2f} ~ {stroke['高']:.2f}]")
        if detail["中枢序列"]:
            lines.append("  中枢：")
            for hub in detail["中枢序列"]:
                lines.append(f"    中枢#{hub['序号']} 区间 [{hub['低']:.2f} ~ {hub['高']:.2f}] "
                             f"极值 [{hub['低低']:.2f} ~ {hub['高高']:.2f}] {hub['状态']}")
        if detail.get("线段内部笔中枢"):
            lines.append("  线段内部笔中枢：")
            for hub in detail["线段内部笔中枢"]:
                segment = hub.get("所属线段", "-")
                lines.append(
                    f"    线段#{segment} 笔中枢#{hub['序号']} "
                    f"区间 [{hub['低']:.2f} ~ {hub['高']:.2f}] "
                    f"极值 [{hub['低低']:.2f} ~ {hub['高高']:.2f}] {hub['状态']}"
                )
        if detail["买卖点"]:
            lines.append("  买卖点（T 系列）：")
            for signal in detail["买卖点"]:
                line = (f"    {signal['kind']}（{signal['base']}） 笔#{signal['index']} {signal['direction']} "
                        f"[{signal['low']:.2f} ~ {signal['high']:.2f}] "
                        f"失效边界 {signal.get('结构失效边界', '-')!s} 时间={signal.get('time', '-')}")
                line += (
                    f" [结构={signal.get('结构来源', '-')}|类型={signal.get('类型来源', '-')}"
                    f"|确认={signal.get('确认级别', '-')}]"
                )
                line += f" [条件={signal.get('结构失效条件', '-')} ]"
                line += f" 理由={signal['reason'] or '-'}"
                lines.append(line)
        if detail["背驰"]:
            lines.append("  背驰：")
            for divergence in detail["背驰"]:
                matrix = divergence.get("证据矩阵", {})
                strength = divergence.get("强度")
                extra = f" 强度={strength}" if strength else ""
                if isinstance(matrix, dict) and matrix.get("命中"):
                    hits = matrix["命中"]
                    hit_text = ",".join(hits.get("原子", []) + hits.get("组合", []))
                    if hit_text:
                        extra += f" 命中={hit_text}"
                lines.append(
                    f"    {divergence['kind']} #{divergence['index']} "
                    f"{divergence['direction']}{extra}"
                )
        if detail.get("MACD面积"):
            lines.append(f"  MACD面积（全序列）: {detail['MACD面积']}")
        multi_level = detail.get("多级别展开", {})
        if multi_level.get("扩展线段层"):
            lines.append("  扩展级别（多级别递归）：")
            for level in multi_level["扩展线段层"]:
                lines.append(f"    L{level['层级']}（{level['数量']} 条）：")
                for segment in level["线段"]:
                    lines.append(
                        f"      线段#{segment['序号']} {segment['方向']} "
                        f"[{segment['低']:.2f}~{segment['高']:.2f}] "
                        f"{segment['起点']}→{segment['终点']}"
                    )
        if detail.get("指标_最近"):
            lines.append("  最近指标：")
            for row in detail["指标_最近"]:
                line = (f"    {row['time']} 收 {row['close']:.2f} "
                        f"MACD(DIF {row['macd_dif']}, BAR {row['macd_bar']}) "
                        f"RSI {row['rsi']} KDJ(K {row['kdj_k']}, D {row['kdj_d']}, J {row['kdj_j']})")
                if row.get("boll_mid") is not None:
                    line += f" BOLL({row['boll_low']:.2f}/{row['boll_mid']:.2f}/{row['boll_up']:.2f})"
                if row.get("均线"):
                    line += f" 均线{row['均线']}"
                lines.append(line)

    if result.get("跨周期共振"):
        lines.append("")
        lines.append("  跨周期共振（多级别同向买卖点）：")
        for event in result["跨周期共振"]:
            lines.append(f"    [{event['direction']}] 强度={event['strength']} @ {event['primary_time']}")
            for match in event["matches"]:
                extra = f"（距{match['距离天数']}天）" if "距离天数" in match else ""
                lines.append(f"      - {match['period']} {match['kind']} {match['time']}{extra}")

    lines.append("")
    lines.append("=" * 64)
    return "\n".join(lines)


__all__ = ["render_text"]
