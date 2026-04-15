"""
仿真数据生成器 - 用于回测验证和策略开发

当无法访问 yfinance (网络受限) 时，自动降级使用仿真数据。
仿真数据具有以下真实市场特征:
1. 基于 GBM (几何布朗运动) + 跳跃扩散模型
2. 波动率聚集 (GARCH-like)
3. 日内季节性 (开盘/收盘波动大，午间平淡)
4. 价格水平和波动率匹配各品种的真实统计特征
5. 成交量的日内U型分布
6. 趋势和均值回归的混合特性

注意: 仿真数据仅用于系统验证，不代表真实市场预测。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd

from .config import COMMODITIES, DataConfig

logger = logging.getLogger(__name__)

# 各品种的真实统计特征 (基于历史数据)
COMMODITY_STATS = {
    "gold": {
        "base_price": 3200.0,        # 基准价格 (2025-2026年黄金约3000-3300)
        "annual_vol": 0.15,          # 年化波动率 ~15%
        "annual_drift": 0.08,        # 年化漂移 ~8%
        "mean_volume": 50000,        # 平均5分钟成交量
        "jump_intensity": 0.005,     # 跳跃频率
        "jump_size_std": 0.005,      # 跳跃幅度标准差
    },
    "silver": {
        "base_price": 38.0,          # 基准价格 (2025-2026年白银约32-40)
        "annual_vol": 0.25,          # 年化波动率 ~25% (白银波动大于黄金)
        "annual_drift": 0.05,
        "mean_volume": 30000,
        "jump_intensity": 0.008,
        "jump_size_std": 0.008,
    },
    "oil": {
        "base_price": 65.0,          # 基准价格 (2025-2026年WTI约55-75)
        "annual_vol": 0.30,          # 年化波动率 ~30% (原油波动最大)
        "annual_drift": -0.02,
        "mean_volume": 80000,
        "jump_intensity": 0.010,
        "jump_size_std": 0.010,
    },
}

# 参考品种统计特征
REFERENCE_STATS = {
    "dxy": {"base_price": 100.0, "annual_vol": 0.06, "annual_drift": 0.0, "mean_volume": 10000},
    "us10y": {"base_price": 4.2, "annual_vol": 0.15, "annual_drift": 0.0, "mean_volume": 5000},
    "vix": {"base_price": 18.0, "annual_vol": 0.80, "annual_drift": 0.0, "mean_volume": 20000},
    "sp500": {"base_price": 5800.0, "annual_vol": 0.16, "annual_drift": 0.10, "mean_volume": 100000},
}


class CommodityDataSimulator:
    """
    大宗商品仿真数据生成器

    使用 Merton 跳跃扩散模型 + 波动率聚集 + 日内季节性
    """

    def __init__(self, config: Optional[DataConfig] = None, seed: int = 42):
        self.config = config or DataConfig()
        self.rng = np.random.RandomState(seed)

    def generate_commodity(self, commodity_key: str) -> pd.DataFrame:
        """生成单个商品的分钟级仿真数据"""
        stats = COMMODITY_STATS[commodity_key]
        return self._generate_ohlcv(
            base_price=stats["base_price"],
            annual_vol=stats["annual_vol"],
            annual_drift=stats["annual_drift"],
            mean_volume=stats["mean_volume"],
            jump_intensity=stats["jump_intensity"],
            jump_size_std=stats["jump_size_std"],
            interval=self.config.interval,
            lookback_days=self.config.lookback_days,
        )

    def generate_all_commodities(self) -> Dict[str, pd.DataFrame]:
        """生成所有商品数据"""
        result = {}
        for key in COMMODITY_STATS:
            result[key] = self.generate_commodity(key)
            logger.info(f"Generated {len(result[key])} bars for {key}")
        return result

    def generate_reference(self, ref_key: str) -> pd.DataFrame:
        """生成参考品种的日线数据"""
        stats = REFERENCE_STATS[ref_key]
        return self._generate_ohlcv(
            base_price=stats["base_price"],
            annual_vol=stats["annual_vol"],
            annual_drift=stats["annual_drift"],
            mean_volume=stats["mean_volume"],
            jump_intensity=0.003,
            jump_size_std=0.003,
            interval="1d",
            lookback_days=self.config.lookback_days,
        )

    def generate_all_references(self) -> Dict[str, pd.DataFrame]:
        """生成所有参考品种"""
        result = {}
        for key in REFERENCE_STATS:
            result[key] = self.generate_reference(key)
        return result

    def _generate_ohlcv(
        self,
        base_price: float,
        annual_vol: float,
        annual_drift: float,
        mean_volume: int,
        jump_intensity: float,
        jump_size_std: float,
        interval: str,
        lookback_days: int,
    ) -> pd.DataFrame:
        """
        生成 OHLCV 数据

        模型: dS/S = (mu - lambda*k)*dt + sigma*dW + J*dN

        其中:
        - mu: 漂移率
        - sigma: 波动率 (带GARCH聚集)
        - dW: 维纳过程
        - J: 跳跃幅度 (正态分布)
        - dN: 泊松过程 (强度 lambda)
        """
        # 计算K线数量
        interval_minutes = self._parse_interval(interval)
        if interval == "1d":
            n_bars = lookback_days
            bars_per_day = 1
        else:
            bars_per_day = int(6.5 * 60 / interval_minutes)  # 6.5小时交易时间
            n_bars = lookback_days * bars_per_day

        # 时间步长 (年)
        dt = interval_minutes / (252 * 6.5 * 60) if interval != "1d" else 1/252

        # 生成收盘价路径
        closes = np.zeros(n_bars)
        closes[0] = base_price

        # GARCH-like 波动率
        vol = annual_vol
        vol_persistence = 0.94
        vol_reaction = 0.06

        for i in range(1, n_bars):
            # 波动率聚集 (简化 GARCH)
            if i > 1:
                ret_prev = (closes[i-1] - closes[i-2]) / closes[i-2]
                vol = np.sqrt(
                    vol_persistence * vol**2
                    + vol_reaction * (ret_prev / np.sqrt(dt))**2 * dt
                )
                vol = np.clip(vol, annual_vol * 0.5, annual_vol * 2.5)

            # 日内季节性 (开盘和收盘波动更大)
            if interval != "1d":
                bar_of_day = i % bars_per_day
                day_pct = bar_of_day / bars_per_day
                # U型波动率: 开盘/收盘高, 午间低
                intraday_mult = 1.0 + 0.5 * (
                    np.exp(-10 * day_pct) + np.exp(-10 * (1 - day_pct)) - 0.2
                )
            else:
                intraday_mult = 1.0

            # GBM 增量
            dW = self.rng.normal(0, 1) * np.sqrt(dt)
            drift = (annual_drift - 0.5 * vol**2) * dt
            diffusion = vol * intraday_mult * dW

            # 跳跃
            jump = 0
            if self.rng.random() < jump_intensity:
                jump = self.rng.normal(0, jump_size_std)

            closes[i] = closes[i-1] * np.exp(drift + diffusion + jump)

        # 从收盘价生成 OHLC
        opens = np.zeros(n_bars)
        highs = np.zeros(n_bars)
        lows = np.zeros(n_bars)
        volumes = np.zeros(n_bars)

        opens[0] = closes[0] * (1 + self.rng.normal(0, 0.0005))

        for i in range(1, n_bars):
            # 开盘价 = 前收 + 微小随机偏移
            gap = self.rng.normal(0, 0.0002)
            opens[i] = closes[i-1] * (1 + gap)

            # 最高/最低价
            bar_range = abs(closes[i] - opens[i])
            extra = abs(self.rng.normal(0, bar_range * 0.5)) if bar_range > 0 else abs(closes[i] * 0.0003)

            highs[i] = max(opens[i], closes[i]) + extra
            lows[i] = min(opens[i], closes[i]) - extra

            # 确保 low <= open/close <= high
            highs[i] = max(highs[i], opens[i], closes[i])
            lows[i] = min(lows[i], opens[i], closes[i])

        highs[0] = max(opens[0], closes[0]) * 1.001
        lows[0] = min(opens[0], closes[0]) * 0.999

        # 成交量 (U型日内分布)
        for i in range(n_bars):
            if interval != "1d":
                bar_of_day = i % bars_per_day
                day_pct = bar_of_day / bars_per_day
                vol_mult = 1.0 + 0.8 * (
                    np.exp(-8 * day_pct) + np.exp(-8 * (1 - day_pct)) - 0.3
                )
            else:
                vol_mult = 1.0

            volumes[i] = max(1, int(
                mean_volume * vol_mult * (1 + self.rng.normal(0, 0.3))
            ))

        # 构建 DataFrame
        index = self._generate_datetime_index(n_bars, interval, bars_per_day, lookback_days)

        df = pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes.astype(int),
        }, index=index)

        return df

    def _generate_datetime_index(
        self, n_bars: int, interval: str, bars_per_day: int, lookback_days: int
    ) -> pd.DatetimeIndex:
        """生成交易时段的时间索引"""
        interval_minutes = self._parse_interval(interval)
        end_date = datetime(2026, 4, 15, 16, 0)  # 今天收盘

        if interval == "1d":
            dates = pd.bdate_range(
                end=end_date.date(),
                periods=n_bars,
                freq="B",
            )
            return pd.DatetimeIndex(dates)

        # 分钟级: 生成每个交易日的交易时段
        timestamps = []
        current_date = end_date - timedelta(days=lookback_days + 10)

        while len(timestamps) < n_bars:
            # 跳过周末
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            # 交易时段: 09:30 - 16:00 (美国市场)
            market_open = current_date.replace(hour=9, minute=30, second=0, microsecond=0)

            for bar in range(bars_per_day):
                ts = market_open + timedelta(minutes=bar * interval_minutes)
                if ts.hour >= 16:
                    break
                timestamps.append(ts)
                if len(timestamps) >= n_bars:
                    break

            current_date += timedelta(days=1)

        return pd.DatetimeIndex(timestamps[:n_bars])

    @staticmethod
    def _parse_interval(interval: str) -> int:
        """解析时间间隔为分钟数"""
        mapping = {
            "1m": 1, "2m": 2, "5m": 5, "15m": 15,
            "30m": 30, "60m": 60, "1h": 60, "1d": 1440,
        }
        return mapping.get(interval, 5)
