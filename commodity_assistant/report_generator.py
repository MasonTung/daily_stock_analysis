"""
绩效报告生成模块

生成全面的回测分析报告:
1. 各策略 × 各品种的绩效矩阵
2. Walk-Forward 样本外一致性分析
3. 风险指标 (最大回撤, Sharpe, 盈亏比)
4. 地缘政治风险评估报告
5. 最优策略推荐
6. 过拟合检测报告
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .backtest_engine import BacktestResult
from .geopolitical import RiskAssessment

logger = logging.getLogger(__name__)


class ReportGenerator:
    """绩效分析报告生成器"""

    def generate_full_report(
        self,
        results: Dict[str, Dict[str, BacktestResult]],
        risk_assessment: Optional[RiskAssessment] = None,
    ) -> str:
        """
        生成完整分析报告

        Args:
            results: {commodity: {strategy: BacktestResult}}
            risk_assessment: 地缘政治风险评估结果

        Returns:
            str: 格式化报告文本
        """
        sections = []

        # 标题
        sections.append(self._header())

        # 地缘政治风险评估
        if risk_assessment:
            sections.append(self._geopolitical_section(risk_assessment))

        # 绩效概览矩阵
        sections.append(self._performance_matrix(results))

        # 各品种详细分析
        for commodity, strat_results in results.items():
            sections.append(self._commodity_detail(commodity, strat_results))

        # 最优策略推荐
        sections.append(self._strategy_recommendation(results, risk_assessment))

        # 过拟合检测报告
        sections.append(self._overfitting_report(results))

        # 风险提示
        sections.append(self._risk_disclaimer())

        return "\n".join(sections)

    def _header(self) -> str:
        return "\n".join([
            "=" * 80,
            "  大宗商品量化分析报告 - Commodity Trading Assistant",
            "  品种: 黄金(XAUUSD) | 白银(XAGUSD) | 原油(WTI)",
            "  周期: 5分钟K线 | 最近2个月",
            "  方法: Walk-Forward Analysis (防过拟合)",
            "=" * 80,
            "",
        ])

    def _geopolitical_section(self, assessment: RiskAssessment) -> str:
        lines = [
            "┌─────────────────────────────────────────────────┐",
            "│           地缘政治风险评估                       │",
            "└─────────────────────────────────────────────────┘",
            "",
            f"  综合风险等级: {assessment.overall_level.value.upper()}",
            f"  综合风险得分: {assessment.overall_score:.1f}/100",
            "",
            "  品种偏好:",
        ]

        for commodity, bias in assessment.commodity_bias.items():
            direction = "偏多 ↑" if bias > 0.1 else ("偏空 ↓" if bias < -0.1 else "中性 →")
            lines.append(f"    {commodity:8s}: {direction} ({bias:+.2f})")

        lines.append("")
        lines.append("  仓位缩放:")
        for commodity, scale in assessment.position_scale.items():
            bar = "█" * int(scale * 10) + "░" * (10 - int(scale * 10))
            lines.append(f"    {commodity:8s}: [{bar}] {scale:.0%}")

        if assessment.active_factors:
            lines.append("")
            lines.append("  活跃风险因子:")
            for factor in assessment.active_factors:
                lines.append(f"    ⚠ {factor}")

        lines.append("")
        return "\n".join(lines)

    def _performance_matrix(self, results: Dict[str, Dict[str, BacktestResult]]) -> str:
        """绩效概览矩阵"""
        lines = [
            "┌─────────────────────────────────────────────────┐",
            "│           策略绩效矩阵 (样本外)                  │",
            "└─────────────────────────────────────────────────┘",
            "",
        ]

        # 构建表头
        commodities = list(results.keys())
        strategies = set()
        for cr in results.values():
            strategies.update(cr.keys())
        strategies = sorted(strategies)

        # 表头
        header = f"{'策略':<20s}"
        for c in commodities:
            header += f"{'|':>2s} {c:>10s}"
        lines.append(header)
        lines.append("-" * len(header))

        # 每行: 一个策略
        for strat in strategies:
            row = f"{strat:<20s}"
            for c in commodities:
                if strat in results.get(c, {}):
                    r = results[c][strat]
                    cell = f"{r.total_return_pct:+.2f}%"
                else:
                    cell = "N/A"
                row += f"{'|':>2s} {cell:>10s}"
            lines.append(row)

        lines.append("")

        # Sharpe Ratio 矩阵
        lines.append("  Sharpe Ratio:")
        header2 = f"{'策略':<20s}"
        for c in commodities:
            header2 += f"{'|':>2s} {c:>10s}"
        lines.append(header2)
        lines.append("-" * len(header2))

        for strat in strategies:
            row = f"{strat:<20s}"
            for c in commodities:
                if strat in results.get(c, {}):
                    r = results[c][strat]
                    cell = f"{r.sharpe_ratio:.2f}"
                else:
                    cell = "N/A"
                row += f"{'|':>2s} {cell:>10s}"
            lines.append(row)

        lines.append("")
        return "\n".join(lines)

    def _commodity_detail(
        self, commodity: str, strat_results: Dict[str, BacktestResult]
    ) -> str:
        """单品种详细分析"""
        names = {"gold": "黄金 (Gold)", "silver": "白银 (Silver)", "oil": "原油 (Crude Oil)"}
        display_name = names.get(commodity, commodity)

        lines = [
            f"┌─────────────────────────────────────────────────┐",
            f"│  {display_name:^46s}│",
            f"└─────────────────────────────────────────────────┘",
            "",
        ]

        for strat_name, result in strat_results.items():
            lines.append(f"  --- {strat_name} ({result.strategy_name}) ---")
            lines.append(f"    总收益率:     {result.total_return_pct:+.2f}%")
            lines.append(f"    Sharpe Ratio: {result.sharpe_ratio:.2f}")
            lines.append(f"    最大回撤:     {result.max_drawdown_pct:.2f}%")
            lines.append(f"    胜率:         {result.win_rate:.1%}")
            lines.append(f"    盈亏比:       {result.profit_factor:.2f}")
            lines.append(f"    总交易次数:   {result.total_trades}")
            lines.append(f"    平均持仓:     {result.avg_bars_held:.0f} 根K线")
            lines.append(f"    OOS一致性:    {result.oos_consistency:.0%}")

            # Walk-Forward 分窗口详情
            lines.append(f"    Walk-Forward 分窗口:")
            for wf in result.walk_forward_results:
                lines.append(
                    f"      Split {wf.split_id + 1}: "
                    f"交易 {wf.n_trades:3d} | "
                    f"胜率 {wf.win_rate:.0%} | "
                    f"平均收益 {wf.avg_pnl_pct:+.3f}% | "
                    f"总盈亏 ${wf.total_pnl:+.2f}"
                )

            # 最近的交易
            if result.all_trades:
                lines.append(f"    最近 5 笔交易:")
                for t in result.all_trades[-5:]:
                    dir_str = "LONG" if t.direction == 1 else "SHORT"
                    lines.append(
                        f"      {dir_str:5s} | "
                        f"入 {t.entry_price:.2f} → 出 {t.exit_price:.2f} | "
                        f"盈亏 {t.pnl_pct:+.3f}% | "
                        f"{t.exit_reason}"
                    )

            lines.append("")

        return "\n".join(lines)

    def _strategy_recommendation(
        self,
        results: Dict[str, Dict[str, BacktestResult]],
        risk_assessment: Optional[RiskAssessment],
    ) -> str:
        """最优策略推荐"""
        lines = [
            "┌─────────────────────────────────────────────────┐",
            "│           最优策略推荐                           │",
            "└─────────────────────────────────────────────────┘",
            "",
        ]

        # 对每个品种找出最优策略
        for commodity, strat_results in results.items():
            lines.append(f"  {commodity.upper()}:")

            # 综合评分: Sharpe * 0.4 + 胜率 * 0.2 + OOS一致性 * 0.3 - 回撤 * 0.1
            scored = []
            for name, r in strat_results.items():
                if r.total_trades < self.config_min_trades(r):
                    lines.append(f"    {name}: 交易次数不足 ({r.total_trades}), 不纳入评价")
                    continue

                score = (
                    r.sharpe_ratio * 0.4
                    + r.win_rate * 0.2
                    + r.oos_consistency * 0.3
                    + (r.max_drawdown_pct / 100) * 0.1  # 回撤为负数，自动惩罚
                )
                scored.append((name, r, score))

            scored.sort(key=lambda x: x[2], reverse=True)

            if scored:
                best_name, best_r, best_score = scored[0]
                lines.append(f"    推荐策略: {best_name}")
                lines.append(f"    综合得分: {best_score:.3f}")
                lines.append(f"    收益: {best_r.total_return_pct:+.2f}% | "
                           f"Sharpe: {best_r.sharpe_ratio:.2f} | "
                           f"回撤: {best_r.max_drawdown_pct:.2f}%")

                # 地缘政治调整
                if risk_assessment:
                    scale = risk_assessment.position_scale.get(commodity, 1.0)
                    bias = risk_assessment.commodity_bias.get(commodity, 0.0)
                    lines.append(f"    地缘调整: 仓位×{scale:.0%}, 偏向={bias:+.2f}")
            else:
                lines.append(f"    无可推荐策略 (交易次数均不足)")

            lines.append("")

        return "\n".join(lines)

    def _overfitting_report(self, results: Dict[str, Dict[str, BacktestResult]]) -> str:
        """过拟合检测报告"""
        lines = [
            "┌─────────────────────────────────────────────────┐",
            "│           过拟合检测报告                         │",
            "└─────────────────────────────────────────────────┘",
            "",
            "  检测方法: Walk-Forward 样本外一致性分析",
            "",
        ]

        for commodity, strat_results in results.items():
            for name, r in strat_results.items():
                is_sufficient = r.total_trades >= 10
                is_consistent = r.oos_consistency >= 0.5
                sharpe_reasonable = -1 < r.sharpe_ratio < 5

                status = "PASS" if (is_sufficient and is_consistent and sharpe_reasonable) else "WARN"
                flag = "[OK]" if status == "PASS" else "[!!]"

                lines.append(f"  {flag} {commodity}/{name}:")
                lines.append(f"      交易次数: {r.total_trades:3d} {'(足够)' if is_sufficient else '(不足 <10)'}")
                lines.append(f"      OOS一致性: {r.oos_consistency:.0%} {'(稳定)' if is_consistent else '(不稳定)'}")
                lines.append(f"      Sharpe: {r.sharpe_ratio:.2f} {'(合理)' if sharpe_reasonable else '(可疑)'}")

                if not is_consistent:
                    lines.append(f"      ⚠ 样本外表现不一致，可能存在过拟合风险")
                if r.sharpe_ratio > 3:
                    lines.append(f"      ⚠ Sharpe Ratio 过高，高度可疑")
                if not is_sufficient:
                    lines.append(f"      ⚠ 交易样本不足，统计意义有限")

                lines.append("")

        lines.append("  说明: 只有同时满足 交易次数>=10, OOS一致性>=50%, Sharpe<5 的策略")
        lines.append("        才被视为通过过拟合检测。")
        lines.append("")
        return "\n".join(lines)

    def _risk_disclaimer(self) -> str:
        return "\n".join([
            "=" * 80,
            "  风险提示",
            "=" * 80,
            "  1. 历史表现不代表未来收益",
            "  2. 本报告基于 Walk-Forward 分析，已尽可能减少过拟合",
            "  3. 实盘交易需考虑: 流动性、极端行情、系统故障等额外风险",
            "  4. 地缘政治事件具有突发性，模型无法完全预测",
            "  5. 建议从小仓位开始验证，逐步放量",
            "  6. 所有技术指标均使用因果计算，无未来函数",
            "=" * 80,
        ])

    @staticmethod
    def config_min_trades(result: BacktestResult) -> int:
        """最少交易次数要求"""
        return result.config.min_trades_required


def format_trade_log(trades: list) -> str:
    """格式化交易日志"""
    if not trades:
        return "  (无交易记录)"

    lines = [
        f"  {'时间':<22s} {'方向':<6s} {'入场价':>10s} {'出场价':>10s} "
        f"{'盈亏%':>8s} {'原因':<15s}",
        "  " + "-" * 80,
    ]

    for t in trades:
        dir_str = "LONG" if t.direction == 1 else "SHORT"
        entry_str = str(t.entry_time)[:19]
        lines.append(
            f"  {entry_str:<22s} {dir_str:<6s} {t.entry_price:>10.2f} "
            f"{t.exit_price:>10.2f} {t.pnl_pct:>+8.3f} {t.exit_reason:<15s}"
        )

    return "\n".join(lines)
