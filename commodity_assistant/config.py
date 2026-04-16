"""
配置模块 - 大宗商品量化助手参数定义
"""

from dataclasses import dataclass, field
from typing import Dict, List

# ============================================================
# 交易品种定义
# ============================================================
COMMODITIES = {
    "gold": {
        "symbol": "GC=F",           # COMEX 黄金期货
        "name": "黄金 (Gold)",
        "currency": "USD",
        "tick_size": 0.10,           # 最小价格变动
        "contract_size": 100,        # 合约乘数 (盎司)
        "spread_pips": 0.30,         # 典型点差
        "commission_per_lot": 2.0,   # 每手佣金
        "margin_rate": 0.05,         # 保证金率 5%
    },
    "silver": {
        "symbol": "SI=F",           # COMEX 白银期货
        "name": "白银 (Silver)",
        "currency": "USD",
        "tick_size": 0.005,
        "contract_size": 5000,
        "spread_pips": 0.02,
        "commission_per_lot": 2.0,
        "margin_rate": 0.07,
    },
    "oil": {
        "symbol": "CL=F",           # WTI 原油期货
        "name": "原油 (Crude Oil)",
        "currency": "USD",
        "tick_size": 0.01,
        "contract_size": 1000,
        "spread_pips": 0.03,
        "commission_per_lot": 2.0,
        "margin_rate": 0.06,
    },
}

# 辅助参考品种 (用于相关性分析和地缘政治信号)
REFERENCE_SYMBOLS = {
    "dxy": "DX-Y.NYB",     # 美元指数
    "us10y": "^TNX",        # 美国10年期国债收益率
    "vix": "^VIX",          # 恐慌指数
    "sp500": "^GSPC",       # 标普500
}

# ============================================================
# 数据获取配置
# ============================================================
@dataclass
class DataConfig:
    """数据获取参数"""
    interval: str = "5m"             # 默认5分钟K线 (yfinance: 1m/2m/5m/15m/30m/60m)
    lookback_days: int = 59          # 回望天数 (yfinance 5m最多60天)
    min_bars_required: int = 500     # 最少K线数量

    # yfinance interval -> 最大回望天数
    MAX_LOOKBACK = {
        "1m": 7, "2m": 60, "5m": 60,
        "15m": 60, "30m": 60, "60m": 730,
    }

# ============================================================
# 技术指标参数 (保守设置，防止过拟合)
# ============================================================
@dataclass
class IndicatorConfig:
    """技术指标参数 - 均使用经典参数，不做优化"""
    # 移动均线
    ma_periods: List[int] = field(default_factory=lambda: [5, 10, 20, 50])

    # RSI
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0

    # MACD (经典参数)
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # 布林带
    bb_period: int = 20
    bb_std: float = 2.0

    # ATR
    atr_period: int = 14

    # VWAP (分钟级专用)
    vwap_enabled: bool = True

    # 成交量
    volume_ma_period: int = 20

# ============================================================
# 回测配置 (防过拟合核心)
# ============================================================
@dataclass
class BacktestConfig:
    """回测参数 - Walk-Forward 分析"""
    initial_capital: float = 100000.0     # 初始资金 $100,000
    position_size_pct: float = 0.02       # 单笔风险 2%
    max_positions: int = 1                 # 最大持仓数
    slippage_pct: float = 0.0001          # 滑点 0.01%

    # Walk-Forward 参数
    train_ratio: float = 0.7              # 训练集占比
    n_splits: int = 3                     # 前推分割数
    min_trades_required: int = 10         # 最少交易次数 (防过拟合)

    # 风控
    max_drawdown_pct: float = 0.10        # 最大回撤 10% 停止
    stop_loss_atr_mult: float = 2.0       # 止损 = 2 * ATR
    take_profit_atr_mult: float = 3.0     # 止盈 = 3 * ATR (盈亏比 1.5:1)
    trailing_stop_atr_mult: float = 1.5   # 移动止损 = 1.5 * ATR

# ============================================================
# 地缘政治风险配置
# ============================================================
@dataclass
class GeopoliticalConfig:
    """地缘政治风险评估参数"""
    # 风险等级对仓位的缩放
    risk_position_scale = {
        "low": 1.0,       # 低风险：正常仓位
        "medium": 0.7,    # 中风险：缩减30%
        "high": 0.4,      # 高风险：缩减60%
        "extreme": 0.1,   # 极端风险：仅保留10%
    }

    # 黄金在地缘风险升级时的偏多权重
    gold_risk_premium: float = 0.3

    # 石油地缘敏感区域
    oil_sensitive_regions: List[str] = field(default_factory=lambda: [
        "中东", "俄罗斯", "委内瑞拉", "利比亚", "伊朗",
        "Middle East", "Russia", "Venezuela", "Libya", "Iran",
        "OPEC", "Strait of Hormuz", "霍尔木兹海峡",
    ])
