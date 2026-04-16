"""
技术指标模块 - 严格因果计算，零未来函数

所有指标遵循以下原则:
1. 只使用当前及过去的数据 (t, t-1, t-2, ...)
2. 不使用任何前向填充或后向窗口
3. 指标在数据不足时返回 NaN，不做任何插值
4. 所有移动平均、标准差等使用 min_periods 参数
"""

import numpy as np
import pandas as pd

from .config import IndicatorConfig


class TechnicalIndicators:
    """
    技术指标计算器 - 所有指标严格因果

    每个方法接收 DataFrame，返回新增列的 DataFrame
    不修改原始数据
    """

    def __init__(self, config: IndicatorConfig = None):
        self.config = config or IndicatorConfig()

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算全部技术指标"""
        df = df.copy()
        df = self.add_moving_averages(df)
        df = self.add_rsi(df)
        df = self.add_macd(df)
        df = self.add_bollinger_bands(df)
        df = self.add_atr(df)
        df = self.add_vwap(df)
        df = self.add_volume_features(df)
        df = self.add_price_features(df)
        df = self.add_momentum(df)
        return df

    def add_moving_averages(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        简单移动均线 (SMA) 和指数移动均线 (EMA)

        SMA_n[t] = mean(close[t-n+1:t+1])  -- 只用过去 n 根K线
        EMA_n[t] = alpha * close[t] + (1-alpha) * EMA_n[t-1]  -- 递归因果
        """
        for period in self.config.ma_periods:
            # SMA: min_periods=period 确保数据不足时为 NaN
            df[f"sma_{period}"] = (
                df["close"]
                .rolling(window=period, min_periods=period)
                .mean()
            )
            # EMA: 自然因果递归
            df[f"ema_{period}"] = (
                df["close"]
                .ewm(span=period, min_periods=period, adjust=False)
                .mean()
            )
        return df

    def add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        RSI (Relative Strength Index)

        RSI[t] = 100 - 100 / (1 + RS[t])
        RS[t] = avg_gain[t] / avg_loss[t]

        使用 Wilder 平滑 (EWM with alpha=1/period)，严格因果
        """
        period = self.config.rsi_period
        delta = df["close"].diff()

        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        # Wilder 平滑: com = period - 1 等价于 alpha = 1/period
        avg_gain = gain.ewm(com=period - 1, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        return df

    def add_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        MACD (Moving Average Convergence Divergence)

        MACD_line[t] = EMA_fast[t] - EMA_slow[t]
        Signal[t] = EMA(MACD_line, signal_period)[t]
        Histogram[t] = MACD_line[t] - Signal[t]

        所有 EMA 均为因果递归计算
        """
        fast = self.config.macd_fast
        slow = self.config.macd_slow
        signal = self.config.macd_signal

        ema_fast = df["close"].ewm(span=fast, min_periods=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, min_periods=slow, adjust=False).mean()

        df["macd_line"] = ema_fast - ema_slow
        df["macd_signal"] = (
            df["macd_line"]
            .ewm(span=signal, min_periods=signal, adjust=False)
            .mean()
        )
        df["macd_hist"] = df["macd_line"] - df["macd_signal"]
        return df

    def add_bollinger_bands(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        布林带 (Bollinger Bands)

        Middle[t] = SMA(close, period)[t]
        Upper[t] = Middle[t] + k * StdDev(close, period)[t]
        Lower[t] = Middle[t] - k * StdDev(close, period)[t]
        %B[t] = (close[t] - Lower[t]) / (Upper[t] - Lower[t])

        rolling 窗口确保只用过去数据
        """
        period = self.config.bb_period
        k = self.config.bb_std

        middle = df["close"].rolling(window=period, min_periods=period).mean()
        std = df["close"].rolling(window=period, min_periods=period).std(ddof=0)

        df["bb_upper"] = middle + k * std
        df["bb_middle"] = middle
        df["bb_lower"] = middle - k * std

        bb_width = df["bb_upper"] - df["bb_lower"]
        df["bb_pct_b"] = (df["close"] - df["bb_lower"]) / bb_width.replace(0, np.nan)
        df["bb_width"] = bb_width / middle  # 带宽百分比
        return df

    def add_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        ATR (Average True Range)

        TR[t] = max(
            high[t] - low[t],
            abs(high[t] - close[t-1]),
            abs(low[t] - close[t-1])
        )
        ATR[t] = EMA(TR, period)[t]

        使用 t-1 的 close 确保因果
        """
        period = self.config.atr_period

        prev_close = df["close"].shift(1)  # shift(1) = 过去一根K线
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - prev_close).abs()
        tr3 = (df["low"] - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = true_range.ewm(
            com=period - 1, min_periods=period, adjust=False
        ).mean()

        # ATR 百分比 (相对于收盘价)
        df["atr_pct"] = df["atr"] / df["close"] * 100
        return df

    def add_vwap(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        VWAP (Volume Weighted Average Price) - 日内指标

        VWAP[t] = cumsum(typical_price * volume)[从当日开始到t]
                  / cumsum(volume)[从当日开始到t]

        每个交易日重置，严格因果:
        在时刻 t，VWAP 只使用当日 [0, t] 的数据
        """
        if "volume" not in df.columns or not self.config.vwap_enabled:
            return df

        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        tp_vol = typical_price * df["volume"]

        # 按交易日分组重置累积
        df["_date"] = df.index.date
        cum_tp_vol = tp_vol.groupby(df["_date"]).cumsum()
        cum_vol = df["volume"].groupby(df["_date"]).cumsum()

        df["vwap"] = cum_tp_vol / cum_vol.replace(0, np.nan)

        # VWAP 偏离度
        df["vwap_deviation"] = (df["close"] - df["vwap"]) / df["vwap"] * 100

        df = df.drop(columns=["_date"])
        return df

    def add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        成交量特征

        volume_sma[t] = SMA(volume, period)[t]
        volume_ratio[t] = volume[t] / volume_sma[t]
        """
        if "volume" not in df.columns:
            return df

        period = self.config.volume_ma_period

        df["volume_sma"] = (
            df["volume"].rolling(window=period, min_periods=period).mean()
        )
        df["volume_ratio"] = df["volume"] / df["volume_sma"].replace(0, np.nan)

        # 成交量变化率
        df["volume_change"] = df["volume"].pct_change()

        return df

    def add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        价格派生特征

        所有特征严格使用 shift 或 rolling 历史窗口
        """
        # 收益率
        df["returns"] = df["close"].pct_change()

        # 对数收益率
        df["log_returns"] = np.log(df["close"] / df["close"].shift(1))

        # 已实现波动率 (过去20根K线的标准差)
        df["realized_vol"] = (
            df["log_returns"]
            .rolling(window=20, min_periods=20)
            .std()
            * np.sqrt(252 * 78)  # 年化 (78 = 一天约78根5分钟K线)
        )

        # K线实体大小
        df["body_size"] = abs(df["close"] - df["open"]) / df["open"] * 100

        # 上下影线
        df["upper_shadow"] = (df["high"] - df[["open", "close"]].max(axis=1)) / df["open"] * 100
        df["lower_shadow"] = (df[["open", "close"]].min(axis=1) - df["low"]) / df["open"] * 100

        return df

    def add_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        动量指标

        ROC_n[t] = (close[t] - close[t-n]) / close[t-n] * 100
        只使用 shift 获取历史数据，严格因果
        """
        for lookback in [5, 10, 20]:
            df[f"roc_{lookback}"] = (
                (df["close"] - df["close"].shift(lookback))
                / df["close"].shift(lookback)
                * 100
            )

        # Williams %R (类似随机指标，只用过去数据)
        period = 14
        highest_high = df["high"].rolling(window=period, min_periods=period).max()
        lowest_low = df["low"].rolling(window=period, min_periods=period).min()
        df["williams_r"] = (
            (highest_high - df["close"])
            / (highest_high - lowest_low).replace(0, np.nan)
            * -100
        )

        return df


def verify_no_future_leak(df: pd.DataFrame, indicator_col: str) -> bool:
    """
    未来函数检测工具

    验证方法: 删除最后 N 根K线后重新计算指标，
    检查历史值是否发生变化。如果变化则存在未来函数泄露。

    Args:
        df: 包含指标列的完整 DataFrame
        indicator_col: 待检测的指标列名

    Returns:
        True = 无泄露, False = 存在未来函数
    """
    if indicator_col not in df.columns:
        return True

    n_test = 10  # 删除最后10根K线
    full_values = df[indicator_col].iloc[:-n_test].copy()

    # 用截断数据重新计算
    calc = TechnicalIndicators()
    truncated = df.iloc[:-n_test].copy()
    # 先移除该列，重新计算
    base_cols = ["open", "high", "low", "close", "volume"]
    truncated = truncated[[c for c in base_cols if c in truncated.columns]]
    truncated = calc.compute_all(truncated)

    if indicator_col not in truncated.columns:
        return True

    recomputed = truncated[indicator_col]

    # 比较: 允许浮点误差
    valid_mask = full_values.notna() & recomputed.notna()
    if valid_mask.sum() == 0:
        return True

    max_diff = (full_values[valid_mask] - recomputed[valid_mask]).abs().max()
    is_clean = max_diff < 1e-10

    if not is_clean:
        print(f"[FUTURE LEAK DETECTED] {indicator_col}: max_diff={max_diff:.2e}")

    return is_clean
