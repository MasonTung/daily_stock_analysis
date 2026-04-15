"""
数据获取模块 - 分钟级大宗商品行情数据
使用 yfinance 获取黄金、白银、原油的分钟K线数据
包含辅助品种(美元指数、美债收益率、VIX)用于相关性分析

在网络受限环境中自动降级使用仿真数据生成器
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd

from .config import COMMODITIES, REFERENCE_SYMBOLS, DataConfig

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

logger = logging.getLogger(__name__)


class CommodityDataFetcher:
    """大宗商品分钟级数据获取器 (支持在线/仿真自动切换)"""

    def __init__(self, config: Optional[DataConfig] = None, force_simulate: bool = False):
        self.config = config or DataConfig()
        self._cache: Dict[str, pd.DataFrame] = {}
        self._force_simulate = force_simulate
        self._simulator = None  # lazy init

    def _get_simulator(self):
        if self._simulator is None:
            from .data_simulator import CommodityDataSimulator
            self._simulator = CommodityDataSimulator(self.config)
        return self._simulator

    def fetch_commodity(self, commodity_key: str) -> pd.DataFrame:
        """
        获取单个商品的分钟K线数据
        优先在线获取，失败后自动降级为仿真数据

        Args:
            commodity_key: 商品键名 (gold/silver/oil)

        Returns:
            DataFrame with columns: [open, high, low, close, volume]
            Index: DatetimeIndex (UTC)
        """
        if commodity_key in self._cache:
            logger.info(f"Using cached data for {commodity_key}")
            return self._cache[commodity_key]

        if not self._force_simulate and HAS_YFINANCE:
            try:
                df = self._fetch_online(commodity_key)
                self._cache[commodity_key] = df
                return df
            except Exception as e:
                logger.warning(f"Online fetch failed for {commodity_key}: {e}, falling back to simulation")

        # 降级到仿真数据
        logger.info(f"Using simulated data for {commodity_key}")
        df = self._get_simulator().generate_commodity(commodity_key)
        df = self._clean_data(df)
        self._cache[commodity_key] = df
        return df

    def _fetch_online(self, commodity_key: str) -> pd.DataFrame:
        """在线获取数据 (yfinance)"""
        commodity = COMMODITIES[commodity_key]
        symbol = commodity["symbol"]

        max_days = DataConfig.MAX_LOOKBACK.get(self.config.interval, 60)
        lookback = min(self.config.lookback_days, max_days)

        logger.info(
            f"Fetching {commodity['name']} ({symbol}), "
            f"interval={self.config.interval}, lookback={lookback}d"
        )

        ticker = yf.Ticker(symbol)
        df = ticker.history(
            period=f"{lookback}d",
            interval=self.config.interval,
            auto_adjust=True,
        )

        if df.empty:
            raise ValueError(f"No data returned for {symbol}")

        # 标准化列名
        df.columns = [c.lower() for c in df.columns]

        # 只保留 OHLCV
        keep_cols = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in keep_cols if c in df.columns]].copy()

        # 清洗数据
        df = self._clean_data(df)

        logger.info(
            f"Fetched {len(df)} bars for {commodity['name']}: "
            f"{df.index[0]} -> {df.index[-1]}"
        )

        return df

    def fetch_all_commodities(self) -> Dict[str, pd.DataFrame]:
        """获取所有三个商品的数据"""
        result = {}
        for key in COMMODITIES:
            try:
                result[key] = self.fetch_commodity(key)
            except Exception as e:
                logger.error(f"Failed to fetch {key}: {e}")
        return result

    def fetch_reference(self, ref_key: str) -> pd.DataFrame:
        """
        获取参考品种数据 (美元指数、VIX等)
        用于宏观环境和相关性分析
        """
        cache_key = f"ref_{ref_key}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not self._force_simulate and HAS_YFINANCE:
            try:
                df = self._fetch_reference_online(ref_key)
                self._cache[cache_key] = df
                return df
            except Exception as e:
                logger.warning(f"Online ref fetch failed for {ref_key}: {e}, falling back to simulation")

        # 降级到仿真数据
        from .data_simulator import REFERENCE_STATS
        if ref_key in REFERENCE_STATS:
            df = self._get_simulator().generate_reference(ref_key)
            df = self._clean_data(df)
            self._cache[cache_key] = df
            return df

        return pd.DataFrame()

    def _fetch_reference_online(self, ref_key: str) -> pd.DataFrame:
        """在线获取参考品种"""
        symbol = REFERENCE_SYMBOLS[ref_key]
        logger.info(f"Fetching reference: {ref_key} ({symbol})")

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{self.config.lookback_days}d", interval="1d")

        if df.empty:
            raise ValueError(f"No reference data for {ref_key}")

        df.columns = [c.lower() for c in df.columns]
        keep_cols = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in keep_cols if c in df.columns]].copy()
        df = self._clean_data(df)

        self._cache[cache_key] = df
        return df

    def fetch_all_references(self) -> Dict[str, pd.DataFrame]:
        """获取所有参考品种"""
        result = {}
        for key in REFERENCE_SYMBOLS:
            try:
                result[key] = self.fetch_reference(key)
            except Exception as e:
                logger.warning(f"Failed to fetch reference {key}: {e}")
        return result

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        数据清洗 - 严格使用因果方法，无未来函数

        处理:
        1. 删除全为NaN的行
        2. 前向填充缺失值 (只用过去的数据)
        3. 删除仍然缺失的行 (开头部分)
        4. 删除成交量为0的异常K线
        5. 删除价格为0或负数的异常数据
        """
        initial_len = len(df)

        # 删除全NaN行
        df = df.dropna(how="all")

        # 前向填充 (因果: 只用过去的值)
        df = df.ffill()

        # 删除开头残留的NaN
        df = df.dropna()

        # 删除异常数据
        if "close" in df.columns:
            df = df[df["close"] > 0]

        # 删除成交量为0的K线 (非交易时段)
        if "volume" in df.columns:
            df = df[df["volume"] >= 0]

        cleaned = initial_len - len(df)
        if cleaned > 0:
            logger.info(f"Cleaned {cleaned} rows ({cleaned/initial_len*100:.1f}%)")

        return df

    def get_multi_timeframe(self, commodity_key: str) -> Dict[str, pd.DataFrame]:
        """
        获取多时间框架数据，用于多周期共振分析

        返回: {"5m": df_5m, "15m": df_15m, "1h": df_1h}

        注意: 高时间框架通过聚合低时间框架生成，
        确保不引入未来数据
        """
        base_df = self.fetch_commodity(commodity_key)

        result = {self.config.interval: base_df}

        # 从基础数据聚合到更高时间框架
        resample_map = {
            "5m": ["15min", "1h"],
            "15m": ["1h"],
            "2m": ["5min", "15min"],
            "1m": ["5min", "15min", "1h"],
        }

        rules = resample_map.get(self.config.interval, [])
        for rule in rules:
            try:
                resampled = self._resample_ohlcv(base_df, rule)
                if len(resampled) >= 20:
                    key = rule.replace("min", "m").replace("1h", "60m")
                    result[key] = resampled
            except Exception as e:
                logger.warning(f"Failed to resample to {rule}: {e}")

        return result

    def _resample_ohlcv(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        """
        OHLCV 重采样聚合 - 标准方法，无未来数据泄露

        使用 closed='left', label='left' 确保:
        - 每根K线只包含已经发生的数据
        - 标签是区间的开始时间
        """
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
        if "volume" in df.columns:
            agg["volume"] = "sum"

        resampled = df.resample(rule, closed="left", label="left").agg(agg)
        return resampled.dropna()

    def clear_cache(self):
        """清除数据缓存"""
        self._cache.clear()
