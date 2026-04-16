"""
Walk-Forward 回测引擎 - 严格防过拟合

核心设计:
1. Walk-Forward Analysis (前推分析):
   - 将数据分为多个连续窗口
   - 每个窗口: 前 70% 为训练集, 后 30% 为测试集
   - 只报告测试集 (样本外) 的绩效
   - 模拟真实交易中的 "未来不可知" 场景

2. 交易成本模型:
   - 点差 (bid-ask spread)
   - 佣金
   - 滑点

3. 信号执行延迟:
   - 信号在 t 时刻产生
   - 在 t+1 时刻的开盘价执行
   - 避免使用当前K线的收盘价入场 (不现实)

4. 无未来函数保证:
   - 指标只用 [0, t] 的数据
   - 信号只用 [0, t] 的指标
   - 执行价格用 t+1 的开盘价
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import BacktestConfig, COMMODITIES
from .indicators import TechnicalIndicators
from .strategies import BaseStrategy

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """单笔交易记录"""
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: int           # +1 多, -1 空
    entry_price: float
    exit_price: float
    size: float              # 仓位大小 (金额)
    pnl: float               # 盈亏 (扣除成本后)
    pnl_pct: float           # 收益率 (%)
    cost: float              # 交易成本
    exit_reason: str          # signal / stop_loss / take_profit / trailing_stop / timeout
    bars_held: int            # 持仓K线数


@dataclass
class WalkForwardResult:
    """单个 Walk-Forward 窗口的结果"""
    split_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    trades: List[Trade]
    equity_curve: pd.Series

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def avg_pnl_pct(self) -> float:
        if not self.trades:
            return 0.0
        return np.mean([t.pnl_pct for t in self.trades])


@dataclass
class BacktestResult:
    """完整回测结果"""
    strategy_name: str
    commodity: str
    config: BacktestConfig
    walk_forward_results: List[WalkForwardResult]
    all_trades: List[Trade] = field(default_factory=list)

    # 汇总指标 (在 compute_summary 中填充)
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    avg_trade_pnl_pct: float = 0.0
    avg_bars_held: float = 0.0
    oos_consistency: float = 0.0  # 样本外一致性

    def compute_summary(self):
        """计算汇总统计指标"""
        # 合并所有测试集交易
        self.all_trades = []
        for wf in self.walk_forward_results:
            self.all_trades.extend(wf.trades)

        self.total_trades = len(self.all_trades)

        if self.total_trades == 0:
            return

        pnls = [t.pnl for t in self.all_trades]
        pnl_pcts = [t.pnl_pct for t in self.all_trades]

        # 胜率
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        self.win_rate = len(wins) / self.total_trades if self.total_trades > 0 else 0

        # 盈亏比
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 1
        self.profit_factor = avg_win / avg_loss if avg_loss > 0 else 0

        # 平均交易收益
        self.avg_trade_pnl_pct = np.mean(pnl_pcts)

        # 平均持仓时间
        self.avg_bars_held = np.mean([t.bars_held for t in self.all_trades])

        # 构建合并的权益曲线
        equity_curves = []
        for wf in self.walk_forward_results:
            if not wf.equity_curve.empty:
                equity_curves.append(wf.equity_curve)

        if equity_curves:
            combined_equity = pd.concat(equity_curves).sort_index()
            combined_equity = combined_equity[~combined_equity.index.duplicated(keep="last")]

            # 总收益
            self.total_return_pct = (
                (combined_equity.iloc[-1] / combined_equity.iloc[0]) - 1
            ) * 100

            # 最大回撤
            running_max = combined_equity.cummax()
            drawdown = (combined_equity - running_max) / running_max * 100
            self.max_drawdown_pct = drawdown.min()

            # Sharpe Ratio - 基于权益曲线的日收益率 (标准方法)
            daily_equity = combined_equity.resample("D").last().dropna()
            daily_returns = daily_equity.pct_change().dropna()
            # 过滤掉非交易日的零收益
            daily_returns = daily_returns[daily_returns != 0]
            if len(daily_returns) >= 5 and daily_returns.std() > 0:
                self.sharpe_ratio = (
                    daily_returns.mean() / daily_returns.std()
                    * np.sqrt(252)
                )

        # OOS 一致性: 有多少个窗口的测试集是盈利的
        profitable_windows = sum(
            1 for wf in self.walk_forward_results if wf.total_pnl > 0
        )
        total_windows = len(self.walk_forward_results)
        self.oos_consistency = (
            profitable_windows / total_windows if total_windows > 0 else 0
        )


class WalkForwardBacktester:
    """
    Walk-Forward 回测引擎

    工作流程:
    1. 将数据按时间切分为 n_splits 个窗口
    2. 每个窗口内: 前 train_ratio 用于 "训练" (策略参数固定，仅计算指标)
    3. 后 (1-train_ratio) 用于测试: 产生信号并模拟交易
    4. 只汇报测试集的绩效

    为什么用 Walk-Forward 而不是简单回测:
    - 简单回测: 整个数据集一次性回测 → 过拟合风险极高
    - Walk-Forward: 多次样本外验证 → 接近真实表现
    """

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.indicator_calc = TechnicalIndicators()

    def run(
        self,
        df: pd.DataFrame,
        strategy: BaseStrategy,
        commodity_key: str = "gold",
    ) -> BacktestResult:
        """
        执行 Walk-Forward 回测

        Args:
            df: 原始 OHLCV 数据
            strategy: 交易策略实例
            commodity_key: 商品键名 (用于成本计算)

        Returns:
            BacktestResult
        """
        commodity_info = COMMODITIES.get(commodity_key, COMMODITIES["gold"])

        # 计算技术指标
        df_with_indicators = self.indicator_calc.compute_all(df)

        # 生成交易信号
        signals = strategy.generate_signals(df_with_indicators)

        # Walk-Forward 分割
        splits = self._create_walk_forward_splits(df_with_indicators)

        wf_results = []
        for split_id, (train_idx, test_idx) in enumerate(splits):
            logger.info(
                f"Walk-Forward Split {split_id + 1}/{len(splits)}: "
                f"Train [{train_idx[0]}:{train_idx[-1]}] "
                f"Test [{test_idx[0]}:{test_idx[-1]}]"
            )

            # 只在测试集上模拟交易
            test_df = df_with_indicators.iloc[test_idx]
            test_signals = signals.iloc[test_idx]

            trades, equity = self._simulate_trades(
                test_df, test_signals, commodity_info
            )

            wf_result = WalkForwardResult(
                split_id=split_id,
                train_start=df_with_indicators.index[train_idx[0]],
                train_end=df_with_indicators.index[train_idx[-1]],
                test_start=test_df.index[0],
                test_end=test_df.index[-1],
                trades=trades,
                equity_curve=equity,
            )
            wf_results.append(wf_result)

        result = BacktestResult(
            strategy_name=strategy.name,
            commodity=commodity_key,
            config=self.config,
            walk_forward_results=wf_results,
        )
        result.compute_summary()
        return result

    def _create_walk_forward_splits(
        self, df: pd.DataFrame
    ) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        创建 Walk-Forward 分割

        方法: 滚动窗口 (非扩展窗口)
        每个窗口大小固定，向前滚动

        示例 (n_splits=3, train_ratio=0.7):
        |=====Train=====|==Test==|
                  |=====Train=====|==Test==|
                            |=====Train=====|==Test==|
        """
        n = len(df)
        n_splits = self.config.n_splits

        # 每个窗口的大小
        window_step = n // (n_splits + 1)
        window_size = int(n * 0.8)  # 每个窗口占总数据的80%
        window_size = min(window_size, n - window_step)

        splits = []
        for i in range(n_splits):
            start = i * window_step
            end = min(start + window_size, n)

            if end - start < 100:  # 窗口太小则跳过
                continue

            train_end = start + int((end - start) * self.config.train_ratio)

            train_idx = np.arange(start, train_end)
            test_idx = np.arange(train_end, end)

            if len(test_idx) < 30:  # 测试集太小则跳过
                continue

            splits.append((train_idx, test_idx))

        if not splits:
            # 降级: 简单 70/30 分割
            split_point = int(n * self.config.train_ratio)
            splits = [
                (np.arange(0, split_point), np.arange(split_point, n))
            ]

        return splits

    def _simulate_trades(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        commodity_info: dict,
    ) -> Tuple[List[Trade], pd.Series]:
        """
        模拟交易执行

        关键防过拟合措施:
        1. 信号延迟执行: signal[t] 在 t+1 的开盘价执行
        2. 包含交易成本 (点差 + 佣金 + 滑点)
        3. 严格止损止盈
        4. 最大回撤保护
        """
        capital = self.config.initial_capital
        equity_curve = pd.Series(capital, index=df.index, dtype=float)
        trades = []

        position = 0        # 当前持仓方向
        entry_price = 0.0
        entry_time = None
        entry_idx = 0
        stop_loss = 0.0
        take_profit = 0.0
        trailing_stop = 0.0
        position_size = 0.0
        peak_equity = capital
        cooldown_until = 0   # 回撤强平后冷却期 (禁止交易直到此索引)

        spread = commodity_info.get("spread_pips", 0.1)
        commission = commodity_info.get("commission_per_lot", 2.0)

        for i in range(1, len(df)):
            current = df.iloc[i]
            prev_signal = signals.iloc[i - 1]  # 使用前一根K线的信号 (延迟执行)

            # 冷却期内禁止新开仓
            if position == 0 and i < cooldown_until:
                equity_curve.iloc[i] = capital
                continue

            # 检查止损/止盈
            if position != 0:
                hit_sl = False
                hit_tp = False
                hit_trail = False
                exit_price = 0.0

                if position == 1:  # 多头
                    if current["low"] <= stop_loss:
                        hit_sl = True
                        exit_price = stop_loss
                    elif current["high"] >= take_profit:
                        hit_tp = True
                        exit_price = take_profit
                    elif trailing_stop > 0 and current["low"] <= trailing_stop:
                        hit_trail = True
                        exit_price = trailing_stop
                    else:
                        # 更新移动止损
                        if "atr" in df.columns:
                            new_trail = current["high"] - self.config.trailing_stop_atr_mult * df["atr"].iloc[i]
                            trailing_stop = max(trailing_stop, new_trail)

                elif position == -1:  # 空头
                    if current["high"] >= stop_loss:
                        hit_sl = True
                        exit_price = stop_loss
                    elif current["low"] <= take_profit:
                        hit_tp = True
                        exit_price = take_profit
                    elif trailing_stop > 0 and current["high"] >= trailing_stop:
                        hit_trail = True
                        exit_price = trailing_stop
                    else:
                        if "atr" in df.columns:
                            new_trail = current["low"] + self.config.trailing_stop_atr_mult * df["atr"].iloc[i]
                            trailing_stop = min(trailing_stop, new_trail) if trailing_stop > 0 else new_trail

                # 处理止损/止盈/移动止损
                if hit_sl or hit_tp or hit_trail:
                    reason = "stop_loss" if hit_sl else ("take_profit" if hit_tp else "trailing_stop")
                    trade = self._close_position(
                        entry_time, df.index[i], position, entry_price,
                        exit_price, position_size, spread, commission, reason,
                        i - entry_idx
                    )
                    trades.append(trade)
                    capital += trade.pnl
                    position = 0
                    continue

            # 处理信号
            if prev_signal != 0 and position == 0:
                # 开仓 - 使用当前K线开盘价 (信号延迟1根)
                exec_price = current["open"]
                # 加上滑点
                slippage = exec_price * self.config.slippage_pct
                if prev_signal == 1:
                    exec_price += slippage + spread / 2
                else:
                    exec_price -= slippage + spread / 2

                # 仓位大小: 基于风险的固定百分比
                # 并限制最大杠杆为 1x (名义价值 <= 资金)
                risk_amount = capital * self.config.position_size_pct
                if "atr" in df.columns and df["atr"].iloc[i] > 0:
                    atr_val = df["atr"].iloc[i]
                    sl_distance = self.config.stop_loss_atr_mult * atr_val
                    position_size = risk_amount / sl_distance if sl_distance > 0 else 0
                else:
                    position_size = risk_amount / (exec_price * 0.02)

                # 杠杆上限: 名义价值不超过当前资金
                max_size = capital / exec_price if exec_price > 0 else 0
                position_size = min(position_size, max_size)

                position = prev_signal
                entry_price = exec_price
                entry_time = df.index[i]
                entry_idx = i

                # 设置止损止盈
                if "atr" in df.columns:
                    atr_val = df["atr"].iloc[i]
                    if position == 1:
                        stop_loss = exec_price - self.config.stop_loss_atr_mult * atr_val
                        take_profit = exec_price + self.config.take_profit_atr_mult * atr_val
                        trailing_stop = exec_price - self.config.trailing_stop_atr_mult * atr_val
                    else:
                        stop_loss = exec_price + self.config.stop_loss_atr_mult * atr_val
                        take_profit = exec_price - self.config.take_profit_atr_mult * atr_val
                        trailing_stop = exec_price + self.config.trailing_stop_atr_mult * atr_val

            elif prev_signal != 0 and position != 0 and prev_signal != position:
                # 反向信号 → 先平仓
                exec_price = current["open"]
                slippage = exec_price * self.config.slippage_pct
                if position == 1:
                    exec_price -= slippage + spread / 2
                else:
                    exec_price += slippage + spread / 2

                trade = self._close_position(
                    entry_time, df.index[i], position, entry_price,
                    exec_price, position_size, spread, commission, "signal",
                    i - entry_idx
                )
                trades.append(trade)
                capital += trade.pnl
                position = 0

            # 更新权益曲线
            if position != 0:
                unrealized = position * (current["close"] - entry_price) * position_size
                equity_curve.iloc[i] = capital + unrealized
            else:
                equity_curve.iloc[i] = capital
                # 无仓位时重置峰值跟踪 (每次新交易独立计算回撤)
                peak_equity = capital

            # 最大回撤保护
            if position != 0:
                peak_equity = max(peak_equity, equity_curve.iloc[i])
                current_dd = (equity_curve.iloc[i] - peak_equity) / peak_equity
                if current_dd < -self.config.max_drawdown_pct:
                    exec_price = current["close"]
                    trade = self._close_position(
                        entry_time, df.index[i], position, entry_price,
                        exec_price, position_size, spread, commission, "max_drawdown",
                        i - entry_idx
                    )
                    trades.append(trade)
                    capital += trade.pnl
                    position = 0
                    # 重置峰值并进入冷却期 (20根K线)
                    peak_equity = capital
                    cooldown_until = i + 20
                    logger.debug(f"Max drawdown hit ({current_dd*100:.1f}%), forced close")

        # 收尾: 如果还有持仓则平仓
        if position != 0:
            last_price = df["close"].iloc[-1]
            trade = self._close_position(
                entry_time, df.index[-1], position, entry_price,
                last_price, position_size, spread, commission, "end_of_data",
                len(df) - 1 - entry_idx
            )
            trades.append(trade)
            capital += trade.pnl

        equity_curve.iloc[-1] = capital
        return trades, equity_curve

    def _close_position(
        self,
        entry_time, exit_time, direction, entry_price, exit_price,
        size, spread, commission, reason, bars_held
    ) -> Trade:
        """关闭仓位，计算盈亏"""
        gross_pnl = direction * (exit_price - entry_price) * size
        cost = spread * size + commission * 2  # 开仓+平仓佣金
        net_pnl = gross_pnl - cost

        pnl_pct = (net_pnl / (entry_price * size)) * 100 if entry_price * size > 0 else 0

        return Trade(
            entry_time=entry_time,
            exit_time=exit_time,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            cost=cost,
            exit_reason=reason,
            bars_held=bars_held,
        )
