"""
地缘政治风险分析模块

基于多维度评估框架，为大宗商品交易提供地缘政治风险信号:
1. 结构化地缘事件数据库 (历史高影响事件模式)
2. 市场隐含风险指标 (VIX, 美元指数, 金油比等)
3. 跨品种相关性异常检测
4. 风险事件日历

所有指标严格因果: 只使用当前及历史数据
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import GeopoliticalConfig

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass
class GeopoliticalEvent:
    """地缘政治事件定义"""
    name: str
    category: str               # war, sanction, trade_war, opec, central_bank, election
    affected_commodities: List[str]  # gold, silver, oil
    expected_impact: Dict[str, str]  # commodity -> "bullish" / "bearish" / "volatile"
    risk_weight: float          # 0.0 ~ 1.0
    description: str = ""


@dataclass
class RiskAssessment:
    """风险评估结果"""
    overall_level: RiskLevel
    overall_score: float            # 0-100
    commodity_bias: Dict[str, float]  # commodity -> bias (-1 bearish ~ +1 bullish)
    position_scale: Dict[str, float]  # commodity -> position multiplier
    active_factors: List[str]       # 当前活跃的风险因子
    detail: str                     # 详细分析说明


class GeopoliticalAnalyzer:
    """
    地缘政治风险分析器

    三层分析架构:
    Layer 1 - 市场隐含指标 (定量，实时)
    Layer 2 - 跨品种异常检测 (定量，准实时)
    Layer 3 - 结构化事件模式 (定性 + 定量)
    """

    def __init__(self, config: GeopoliticalConfig = None):
        self.config = config or GeopoliticalConfig()
        self._event_patterns = self._build_event_patterns()

    def analyze(
        self,
        commodity_data: Dict[str, pd.DataFrame],
        reference_data: Dict[str, pd.DataFrame],
    ) -> RiskAssessment:
        """
        综合地缘政治风险评估

        Args:
            commodity_data: {"gold": df, "silver": df, "oil": df}
            reference_data: {"dxy": df, "vix": df, "us10y": df, "sp500": df}

        Returns:
            RiskAssessment 综合评估结果
        """
        scores = []
        factors = []
        commodity_bias = {"gold": 0.0, "silver": 0.0, "oil": 0.0}

        # Layer 1: 市场隐含风险指标
        market_risk, market_factors, market_bias = self._analyze_market_implied_risk(
            commodity_data, reference_data
        )
        scores.append(("market_implied", market_risk, 0.5))
        factors.extend(market_factors)
        for k in commodity_bias:
            commodity_bias[k] += market_bias.get(k, 0) * 0.5

        # Layer 2: 跨品种异常检测
        anomaly_risk, anomaly_factors, anomaly_bias = self._analyze_cross_asset_anomalies(
            commodity_data, reference_data
        )
        scores.append(("cross_asset", anomaly_risk, 0.3))
        factors.extend(anomaly_factors)
        for k in commodity_bias:
            commodity_bias[k] += anomaly_bias.get(k, 0) * 0.3

        # Layer 3: 结构化模式检测
        pattern_risk, pattern_factors, pattern_bias = self._analyze_structural_patterns(
            commodity_data
        )
        scores.append(("structural", pattern_risk, 0.2))
        factors.extend(pattern_factors)
        for k in commodity_bias:
            commodity_bias[k] += pattern_bias.get(k, 0) * 0.2

        # 加权汇总
        overall_score = sum(s * w for _, s, w in scores)

        # 确定风险等级
        if overall_score >= 75:
            level = RiskLevel.EXTREME
        elif overall_score >= 50:
            level = RiskLevel.HIGH
        elif overall_score >= 25:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        # 仓位缩放
        position_scale = {}
        for commodity in ["gold", "silver", "oil"]:
            base_scale = self.config.risk_position_scale[level.value]
            # 黄金在高风险时有避险溢价
            if commodity == "gold" and level in (RiskLevel.HIGH, RiskLevel.EXTREME):
                base_scale = min(1.0, base_scale + self.config.gold_risk_premium)
            position_scale[commodity] = round(base_scale, 2)

        detail = self._format_detail(scores, factors, overall_score, level)

        return RiskAssessment(
            overall_level=level,
            overall_score=round(overall_score, 1),
            commodity_bias=commodity_bias,
            position_scale=position_scale,
            active_factors=factors,
            detail=detail,
        )

    def _analyze_market_implied_risk(
        self,
        commodity_data: Dict[str, pd.DataFrame],
        reference_data: Dict[str, pd.DataFrame],
    ) -> Tuple[float, List[str], Dict[str, float]]:
        """
        Layer 1: 市场隐含风险

        基于:
        - VIX 恐慌指数水平和变化
        - 金油比 (Gold/Oil ratio) 异常
        - 美元指数趋势
        - 金银比 (Gold/Silver ratio)
        """
        score = 0.0
        factors = []
        bias = {"gold": 0.0, "silver": 0.0, "oil": 0.0}

        # --- VIX 分析 ---
        if "vix" in reference_data and not reference_data["vix"].empty:
            vix_df = reference_data["vix"]
            vix_current = vix_df["close"].iloc[-1]
            vix_ma20 = vix_df["close"].rolling(20, min_periods=10).mean().iloc[-1]

            if vix_current > 30:
                score += 30
                factors.append(f"VIX={vix_current:.1f} (>30 恐慌区)")
                bias["gold"] += 0.3  # 避险利好黄金
                bias["oil"] -= 0.2   # 恐慌利空原油(需求担忧)
            elif vix_current > 20:
                score += 15
                factors.append(f"VIX={vix_current:.1f} (偏高)")
                bias["gold"] += 0.1

            # VIX 急涨 (日变化超过20%)
            if len(vix_df) >= 2:
                vix_change = (vix_current - vix_df["close"].iloc[-2]) / vix_df["close"].iloc[-2]
                if vix_change > 0.20:
                    score += 20
                    factors.append(f"VIX 单日飙升 {vix_change*100:.1f}%")
                    bias["gold"] += 0.4

        # --- 美元指数分析 ---
        if "dxy" in reference_data and not reference_data["dxy"].empty:
            dxy_df = reference_data["dxy"]
            if len(dxy_df) >= 20:
                dxy_current = dxy_df["close"].iloc[-1]
                dxy_ma20 = dxy_df["close"].rolling(20, min_periods=10).mean().iloc[-1]

                # 美元走强利空大宗商品 (以美元计价)
                if dxy_current > dxy_ma20 * 1.02:
                    factors.append(f"美元指数偏强 ({dxy_current:.1f} > MA20 {dxy_ma20:.1f})")
                    bias["gold"] -= 0.15
                    bias["silver"] -= 0.2
                    bias["oil"] -= 0.1
                elif dxy_current < dxy_ma20 * 0.98:
                    factors.append(f"美元指数偏弱 ({dxy_current:.1f} < MA20 {dxy_ma20:.1f})")
                    bias["gold"] += 0.15
                    bias["silver"] += 0.2
                    bias["oil"] += 0.1

        # --- 金油比分析 ---
        if "gold" in commodity_data and "oil" in commodity_data:
            gold_df = commodity_data["gold"]
            oil_df = commodity_data["oil"]
            if not gold_df.empty and not oil_df.empty:
                gold_price = gold_df["close"].iloc[-1]
                oil_price = oil_df["close"].iloc[-1]
                if oil_price > 0:
                    gold_oil_ratio = gold_price / oil_price
                    # 历史平均金油比约 15-25
                    if gold_oil_ratio > 35:
                        score += 15
                        factors.append(f"金油比={gold_oil_ratio:.1f} (>35, 极端避险)")
                        bias["gold"] += 0.2
                        bias["oil"] -= 0.2
                    elif gold_oil_ratio < 12:
                        score += 10
                        factors.append(f"金油比={gold_oil_ratio:.1f} (<12, 油价泡沫风险)")
                        bias["oil"] -= 0.3

        # --- 金银比分析 ---
        if "gold" in commodity_data and "silver" in commodity_data:
            gold_df = commodity_data["gold"]
            silver_df = commodity_data["silver"]
            if not gold_df.empty and not silver_df.empty:
                g_price = gold_df["close"].iloc[-1]
                s_price = silver_df["close"].iloc[-1]
                if s_price > 0:
                    gold_silver_ratio = g_price / s_price
                    # 金银比 > 80 表示避险情绪浓厚
                    if gold_silver_ratio > 90:
                        score += 10
                        factors.append(f"金银比={gold_silver_ratio:.1f} (>90, 极端避险)")
                        bias["gold"] += 0.2
                        bias["silver"] -= 0.1
                    elif gold_silver_ratio > 80:
                        score += 5
                        factors.append(f"金银比={gold_silver_ratio:.1f} (偏高)")

        return min(score, 100), factors, bias

    def _analyze_cross_asset_anomalies(
        self,
        commodity_data: Dict[str, pd.DataFrame],
        reference_data: Dict[str, pd.DataFrame],
    ) -> Tuple[float, List[str], Dict[str, float]]:
        """
        Layer 2: 跨品种相关性异常检测

        当常规相关性被打破时，通常意味着有地缘事件驱动:
        - 黄金和美元同涨 → 极端避险
        - 原油和股市反向背离 → 供给冲击
        - 黄金白银比值急变 → 避险切换
        """
        score = 0.0
        factors = []
        bias = {"gold": 0.0, "silver": 0.0, "oil": 0.0}

        # 黄金-美元同向异常
        if "gold" in commodity_data and "dxy" in reference_data:
            gold_df = commodity_data["gold"]
            dxy_df = reference_data["dxy"]
            if len(gold_df) >= 5 and len(dxy_df) >= 5:
                gold_ret = gold_df["close"].pct_change().iloc[-5:].mean()
                dxy_ret = dxy_df["close"].pct_change().iloc[-5:].mean()

                # 正常情况: 黄金和美元负相关
                # 异常: 两者都上涨 = 极端避险
                if gold_ret > 0.002 and dxy_ret > 0.002:
                    score += 25
                    factors.append("黄金+美元同涨 → 极端避险信号")
                    bias["gold"] += 0.4

        # 原油-股市背离检测
        if "oil" in commodity_data and "sp500" in reference_data:
            oil_df = commodity_data["oil"]
            sp_df = reference_data["sp500"]
            if len(oil_df) >= 5 and len(sp_df) >= 5:
                oil_ret = oil_df["close"].pct_change().iloc[-5:].mean()
                sp_ret = sp_df["close"].pct_change().iloc[-5:].mean()

                # 原油涨+股市跌 = 供给冲击 (地缘风险)
                if oil_ret > 0.005 and sp_ret < -0.005:
                    score += 20
                    factors.append("原油涨+股市跌 → 供给冲击/地缘风险")
                    bias["oil"] += 0.3
                    bias["gold"] += 0.2

        # 三品种波动率同步飙升
        vol_spikes = 0
        for key, df in commodity_data.items():
            if len(df) >= 20:
                recent_vol = df["close"].pct_change().iloc[-5:].std()
                hist_vol = df["close"].pct_change().iloc[-20:-5].std()
                if hist_vol > 0 and recent_vol > hist_vol * 2:
                    vol_spikes += 1

        if vol_spikes >= 3:
            score += 20
            factors.append("三品种波动率同时飙升 → 系统性地缘事件")
            bias["gold"] += 0.3
        elif vol_spikes >= 2:
            score += 10
            factors.append(f"{vol_spikes}个品种波动率飙升")

        return min(score, 100), factors, bias

    def _analyze_structural_patterns(
        self,
        commodity_data: Dict[str, pd.DataFrame],
    ) -> Tuple[float, List[str], Dict[str, float]]:
        """
        Layer 3: 结构化价格模式检测

        基于历史地缘事件的价格行为模式:
        - 黄金急涨 + 成交量放大 → 地缘避险驱动
        - 原油跳空 + 波动放大 → 供给中断信号
        - 价格在关键整数关口附近 → 心理价位博弈
        """
        score = 0.0
        factors = []
        bias = {"gold": 0.0, "silver": 0.0, "oil": 0.0}

        for key, df in commodity_data.items():
            if len(df) < 50:
                continue

            # 急涨检测 (5根K线涨幅超过2%)
            recent_return = (df["close"].iloc[-1] / df["close"].iloc[-5] - 1) * 100
            if abs(recent_return) > 2.0:
                direction = "急涨" if recent_return > 0 else "急跌"
                score += 10
                factors.append(f"{key} 5根K线{direction} {recent_return:+.2f}%")
                if key == "gold" and recent_return > 2:
                    bias["gold"] += 0.2

            # 成交量异常 (最近5根K线平均量超过20根平均量2倍)
            if "volume" in df.columns:
                recent_vol = df["volume"].iloc[-5:].mean()
                hist_vol = df["volume"].iloc[-25:-5].mean()
                if hist_vol > 0 and recent_vol > hist_vol * 2:
                    score += 5
                    factors.append(f"{key} 成交量异常放大 ({recent_vol/hist_vol:.1f}x)")

            # 关键整数价位检测
            price = df["close"].iloc[-1]
            round_levels = self._get_round_levels(key, price)
            for level in round_levels:
                if abs(price - level) / level < 0.005:
                    factors.append(f"{key} 接近整数关口 {level}")
                    break

        return min(score, 100), factors, bias

    def _get_round_levels(self, commodity: str, current_price: float) -> List[float]:
        """获取关键整数价位"""
        if commodity == "gold":
            base = round(current_price / 50) * 50
            return [base - 100, base - 50, base, base + 50, base + 100]
        elif commodity == "silver":
            base = round(current_price / 1) * 1
            return [base - 2, base - 1, base, base + 1, base + 2]
        elif commodity == "oil":
            base = round(current_price / 5) * 5
            return [base - 10, base - 5, base, base + 5, base + 10]
        return []

    def _build_event_patterns(self) -> List[GeopoliticalEvent]:
        """构建地缘事件模式库"""
        return [
            GeopoliticalEvent(
                name="中东冲突升级",
                category="war",
                affected_commodities=["gold", "oil"],
                expected_impact={"gold": "bullish", "oil": "bullish", "silver": "bullish"},
                risk_weight=0.9,
                description="中东地区军事冲突导致避险需求激增和石油供给担忧"
            ),
            GeopoliticalEvent(
                name="OPEC减产决议",
                category="opec",
                affected_commodities=["oil"],
                expected_impact={"oil": "bullish", "gold": "volatile"},
                risk_weight=0.6,
                description="OPEC及盟友减产协议推升油价"
            ),
            GeopoliticalEvent(
                name="美联储紧急降息",
                category="central_bank",
                affected_commodities=["gold", "silver"],
                expected_impact={"gold": "bullish", "silver": "bullish", "oil": "volatile"},
                risk_weight=0.8,
                description="紧急降息表明经济风险，利好贵金属"
            ),
            GeopoliticalEvent(
                name="贸易战升级",
                category="trade_war",
                affected_commodities=["gold", "silver", "oil"],
                expected_impact={"gold": "bullish", "oil": "bearish", "silver": "volatile"},
                risk_weight=0.7,
                description="贸易摩擦加剧推升避险需求，打压原油需求预期"
            ),
            GeopoliticalEvent(
                name="主权债务危机",
                category="financial_crisis",
                affected_commodities=["gold", "silver"],
                expected_impact={"gold": "bullish", "silver": "bullish", "oil": "bearish"},
                risk_weight=0.8,
                description="主权债务风险推升贵金属避险需求"
            ),
            GeopoliticalEvent(
                name="能源制裁",
                category="sanction",
                affected_commodities=["oil"],
                expected_impact={"oil": "bullish", "gold": "bullish"},
                risk_weight=0.7,
                description="对产油国制裁导致供给收缩"
            ),
        ]

    def _format_detail(
        self,
        scores: list,
        factors: List[str],
        overall: float,
        level: RiskLevel,
    ) -> str:
        """格式化详细分析报告"""
        lines = [
            f"=== 地缘政治风险评估 ===",
            f"综合风险得分: {overall:.1f}/100 ({level.value.upper()})",
            "",
            "--- 分层得分 ---",
        ]
        for name, s, w in scores:
            lines.append(f"  {name}: {s:.1f} (权重 {w:.0%})")

        if factors:
            lines.append("")
            lines.append("--- 活跃风险因子 ---")
            for f in factors:
                lines.append(f"  - {f}")

        return "\n".join(lines)
