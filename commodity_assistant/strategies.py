"""
交易策略模块 - 大宗商品分钟级策略集

策略设计原则:
1. 参数少且固定 (使用经典参数，不做优化以防过拟合)
2. 逻辑简洁可解释
3. 严格止损止盈，风险可控
4. 所有信号只使用当前及历史数据 (零未来函数)
5. 包含交易成本和滑点

策略信号约定:
  +1 = 做多信号
  -1 = 做空信号
   0 = 无信号 / 平仓
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import BacktestConfig

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """交易信号"""
    timestamp: pd.Timestamp
    direction: int          # +1 多, -1 空, 0 平
    strength: float         # 信号强度 0~1
    strategy_name: str
    reason: str
    stop_loss: float = 0.0
    take_profit: float = 0.0


class BaseStrategy(ABC):
    """策略基类"""

    name: str = "base"
    description: str = ""

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        生成交易信号序列

        Args:
            df: 包含 OHLCV + 技术指标的 DataFrame

        Returns:
            pd.Series: 索引与 df 对齐, 值为 +1/0/-1

        重要: 信号 signal[t] 只能使用 df.iloc[:t+1] 的数据
        在实际回测中，signal[t] 在 t+1 时刻执行
        """
        pass

    def get_stop_loss(self, df: pd.DataFrame, entry_idx: int, direction: int) -> float:
        """计算止损价 (基于 ATR)"""
        if "atr" not in df.columns:
            return 0.0
        atr = df["atr"].iloc[entry_idx]
        price = df["close"].iloc[entry_idx]
        if direction == 1:  # 多头止损在下方
            return price - self.config.stop_loss_atr_mult * atr
        else:  # 空头止损在上方
            return price + self.config.stop_loss_atr_mult * atr

    def get_take_profit(self, df: pd.DataFrame, entry_idx: int, direction: int) -> float:
        """计算止盈价 (基于 ATR)"""
        if "atr" not in df.columns:
            return 0.0
        atr = df["atr"].iloc[entry_idx]
        price = df["close"].iloc[entry_idx]
        if direction == 1:
            return price + self.config.take_profit_atr_mult * atr
        else:
            return price - self.config.take_profit_atr_mult * atr


class MomentumStrategy(BaseStrategy):
    """
    动量策略 - 趋势跟随

    逻辑:
    - 做多: EMA5 > EMA20 且 RSI 在 40~70 之间 且 MACD柱 > 0 且放大
    - 做空: EMA5 < EMA20 且 RSI 在 30~60 之间 且 MACD柱 < 0 且放大
    - 过滤: ATR 百分比需要足够大 (有波动才有趋势)

    为什么这些参数:
    - EMA5/20 是经典短中期均线组合
    - RSI 过滤极端超买超卖区 (避免追高杀低)
    - MACD柱方向确认动量
    """

    name = "momentum"
    description = "动量趋势跟随策略 (EMA交叉 + RSI过滤 + MACD确认)"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index, dtype=int)

        required = ["ema_5", "ema_20", "rsi", "macd_hist", "atr_pct"]
        if not all(c in df.columns for c in required):
            logger.warning(f"[{self.name}] Missing columns, returning empty signals")
            return signals

        ema_fast = df["ema_5"]
        ema_slow = df["ema_20"]
        rsi = df["rsi"]
        macd_h = df["macd_hist"]
        atr_pct = df["atr_pct"]

        # 做多条件
        long_cond = (
            (ema_fast > ema_slow)          # 快线在慢线上方
            & (rsi > 40) & (rsi < 70)       # RSI 不超买不超卖
            & (macd_h > 0)                   # MACD 柱为正
            & (atr_pct > 0.05)              # 有足够波动
        )

        # 做空条件
        short_cond = (
            (ema_fast < ema_slow)
            & (rsi > 30) & (rsi < 60)
            & (macd_h < 0)
            & (atr_pct > 0.05)
        )

        signals[long_cond] = 1
        signals[short_cond] = -1

        return signals


class BreakoutStrategy(BaseStrategy):
    """
    波动率突破策略

    逻辑:
    - 计算过去 N 根K线的最高价/最低价通道
    - 收盘价突破通道上轨 + 成交量放大 → 做多
    - 收盘价跌破通道下轨 + 成交量放大 → 做空
    - 布林带宽度收窄后突破更有效 (Squeeze)

    参数:
    - channel_period = 20 (经典Donchian通道)
    - volume_threshold = 1.5 (量比阈值)
    """

    name = "breakout"
    description = "波动率突破策略 (通道突破 + 量能确认 + 布林带Squeeze)"

    CHANNEL_PERIOD = 20
    VOLUME_THRESHOLD = 1.5

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index, dtype=int)

        if "volume_ratio" not in df.columns or "bb_width" not in df.columns:
            return signals

        # Donchian 通道 (只用过去数据)
        # rolling max/min 用 min_periods 确保不提前计算
        upper_channel = df["high"].rolling(
            window=self.CHANNEL_PERIOD, min_periods=self.CHANNEL_PERIOD
        ).max().shift(1)  # shift(1): 使用截止到上一根K线的数据
        lower_channel = df["low"].rolling(
            window=self.CHANNEL_PERIOD, min_periods=self.CHANNEL_PERIOD
        ).min().shift(1)

        # 布林带宽度 (用于 Squeeze 检测)
        bb_width = df["bb_width"]
        bb_squeeze = bb_width < bb_width.rolling(50, min_periods=20).quantile(0.2)

        # 量能确认
        vol_confirm = df["volume_ratio"] > self.VOLUME_THRESHOLD

        # 突破做多: 收盘突破上轨 + 量能
        long_cond = (
            (df["close"] > upper_channel)
            & vol_confirm
        )

        # 突破做空: 收盘跌破下轨 + 量能
        short_cond = (
            (df["close"] < lower_channel)
            & vol_confirm
        )

        signals[long_cond] = 1
        signals[short_cond] = -1

        return signals


class MeanReversionStrategy(BaseStrategy):
    """
    均值回归策略

    逻辑:
    - 价格触及布林带下轨 + RSI超卖 → 做多 (回归中轨)
    - 价格触及布林带上轨 + RSI超买 → 做空 (回归中轨)
    - VWAP偏离度作为辅助确认
    - 在趋势市场中自动降级 (用MA斜率判断)

    适用场景: 震荡市
    """

    name = "mean_reversion"
    description = "均值回归策略 (布林带 + RSI极端 + VWAP辅助)"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index, dtype=int)

        required = ["bb_pct_b", "rsi", "bb_middle", "sma_50"]
        if not all(c in df.columns for c in required):
            return signals

        # 趋势过滤: SMA50 斜率平缓才适合均值回归
        sma_slope = (df["sma_50"] - df["sma_50"].shift(10)) / df["sma_50"].shift(10) * 100
        is_ranging = sma_slope.abs() < 0.5  # 斜率小于0.5%认为是震荡

        # 做多: 价格在布林带下轨附近 + RSI超卖 + 震荡市
        long_cond = (
            (df["bb_pct_b"] < 0.1)          # %B < 10%, 接近下轨
            & (df["rsi"] < 35)               # RSI 超卖
            & is_ranging                      # 震荡市场
        )

        # 做空: 价格在布林带上轨附近 + RSI超买 + 震荡市
        short_cond = (
            (df["bb_pct_b"] > 0.9)
            & (df["rsi"] > 65)
            & is_ranging
        )

        # VWAP 辅助确认 (如果有)
        if "vwap_deviation" in df.columns:
            vwap_dev = df["vwap_deviation"]
            # 价格大幅低于VWAP加强做多信号
            long_cond = long_cond | (
                (vwap_dev < -0.5)
                & (df["rsi"] < 40)
                & is_ranging
            )
            short_cond = short_cond | (
                (vwap_dev > 0.5)
                & (df["rsi"] > 60)
                & is_ranging
            )

        signals[long_cond] = 1
        signals[short_cond] = -1

        return signals


class MultiTimeframeTrendStrategy(BaseStrategy):
    """
    多周期共振策略

    逻辑:
    - 在基础时间框架产生信号
    - 但只在高时间框架趋势一致时才执行
    - 用多条均线排列判断趋势状态

    趋势状态:
    - 多头排列: SMA5 > SMA10 > SMA20 > SMA50
    - 空头排列: SMA5 < SMA10 < SMA20 < SMA50

    这模拟了在更高周期图表上做方向判断、
    在低周期图表上找入场点的经典做法
    """

    name = "multi_tf_trend"
    description = "多周期共振趋势策略 (多均线排列 + 动量确认)"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index, dtype=int)

        required = ["sma_5", "sma_10", "sma_20", "sma_50", "rsi", "macd_hist"]
        if not all(c in df.columns for c in required):
            return signals

        # 多头排列
        bull_alignment = (
            (df["sma_5"] > df["sma_10"])
            & (df["sma_10"] > df["sma_20"])
            & (df["sma_20"] > df["sma_50"])
        )

        # 空头排列
        bear_alignment = (
            (df["sma_5"] < df["sma_10"])
            & (df["sma_10"] < df["sma_20"])
            & (df["sma_20"] < df["sma_50"])
        )

        # 入场确认: RSI + MACD方向一致
        long_entry = (
            bull_alignment
            & (df["rsi"] > 45) & (df["rsi"] < 75)
            & (df["macd_hist"] > 0)
        )

        short_entry = (
            bear_alignment
            & (df["rsi"] > 25) & (df["rsi"] < 55)
            & (df["macd_hist"] < 0)
        )

        signals[long_entry] = 1
        signals[short_entry] = -1

        return signals


class GeopoliticalAdjustedStrategy(BaseStrategy):
    """
    地缘政治调整策略

    逻辑:
    - 以动量策略为基础
    - 根据地缘政治风险评分调整仓位大小和方向偏好
    - 高风险时期: 黄金偏多，原油谨慎
    - 使用 VIX/美元指数等作为实时代理指标

    这不是独立策略，而是对基础策略的风险调整层
    回测中通过传入地缘参数来模拟
    """

    name = "geo_adjusted"
    description = "地缘政治调整策略 (基础动量 + 风险缩放)"

    def __init__(
        self,
        config: BacktestConfig = None,
        commodity_type: str = "gold",
        risk_score: float = 50.0,
    ):
        super().__init__(config)
        self.commodity_type = commodity_type
        self.risk_score = risk_score
        self._base_strategy = MomentumStrategy(config)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        # 获取基础动量信号
        base_signals = self._base_strategy.generate_signals(df)

        # 根据地缘风险调整
        if self.risk_score >= 75:
            # 极端风险: 黄金偏多，原油偏空
            if self.commodity_type == "gold":
                # 保留多头信号，过滤空头
                base_signals[base_signals == -1] = 0
            elif self.commodity_type == "oil":
                # 保留空头信号，过滤多头
                base_signals[base_signals == 1] = 0
        elif self.risk_score >= 50:
            # 中高风险: 减少交易频率 (只保留强信号)
            if "rsi" in df.columns:
                weak_long = (base_signals == 1) & (df["rsi"] < 50)
                weak_short = (base_signals == -1) & (df["rsi"] > 50)
                base_signals[weak_long] = 0
                base_signals[weak_short] = 0

        return base_signals


class VWAPReversionStrategy(BaseStrategy):
    """
    VWAP 回归策略 - 日内专用

    逻辑:
    - VWAP 是机构大量使用的日内基准价格
    - 价格偏离 VWAP 过远后倾向于回归
    - 结合成交量确认偏离的可靠性

    特别适合分钟级交易
    """

    name = "vwap_reversion"
    description = "VWAP回归策略 (日内均价回归 + 量能确认)"

    DEVIATION_THRESHOLD = 0.3  # VWAP偏离阈值 (%)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=df.index, dtype=int)

        if "vwap_deviation" not in df.columns or "volume_ratio" not in df.columns:
            return signals

        vwap_dev = df["vwap_deviation"]
        vol_ratio = df["volume_ratio"]

        # 做多: 价格大幅低于 VWAP + 量能配合
        long_cond = (
            (vwap_dev < -self.DEVIATION_THRESHOLD)
            & (vol_ratio > 1.2)
            & (df["rsi"] < 45) if "rsi" in df.columns
            else (vwap_dev < -self.DEVIATION_THRESHOLD) & (vol_ratio > 1.2)
        )

        # 做空: 价格大幅高于 VWAP + 量能配合
        short_cond = (
            (vwap_dev > self.DEVIATION_THRESHOLD)
            & (vol_ratio > 1.2)
            & (df["rsi"] > 55) if "rsi" in df.columns
            else (vwap_dev > self.DEVIATION_THRESHOLD) & (vol_ratio > 1.2)
        )

        signals[long_cond] = 1
        signals[short_cond] = -1

        return signals


# ============================================================
# 策略集合管理
# ============================================================

ALL_STRATEGIES = {
    "momentum": MomentumStrategy,
    "breakout": BreakoutStrategy,
    "mean_reversion": MeanReversionStrategy,
    "multi_tf_trend": MultiTimeframeTrendStrategy,
    "vwap_reversion": VWAPReversionStrategy,
    "geo_adjusted": GeopoliticalAdjustedStrategy,
}

NON_GEO_STRATEGIES = {
    k: v for k, v in ALL_STRATEGIES.items() if k != "geo_adjusted"
}


def get_strategy(name: str, **kwargs) -> BaseStrategy:
    """工厂方法获取策略实例"""
    if name not in ALL_STRATEGIES:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(ALL_STRATEGIES.keys())}")
    return ALL_STRATEGIES[name](**kwargs)
