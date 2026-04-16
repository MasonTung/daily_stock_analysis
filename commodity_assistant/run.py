#!/usr/bin/env python3
"""
大宗商品量化助手 - 主入口

执行流程:
1. 获取黄金、白银、原油的分钟级数据 (最近2个月)
2. 获取参考品种数据 (美元指数、VIX、美债、标普500)
3. 执行地缘政治风险评估
4. 对每个品种运行所有策略的 Walk-Forward 回测
5. 验证未来函数
6. 生成综合分析报告
7. 推荐最优策略

使用方法:
    python -m commodity_assistant.run
    python -m commodity_assistant.run --interval 15m
    python -m commodity_assistant.run --commodity gold
"""

import argparse
import logging

import numpy as np
import pandas as pd
import sys
import time
from typing import Dict

from .backtest_engine import BacktestResult, WalkForwardBacktester
from .config import (
    COMMODITIES,
    BacktestConfig,
    DataConfig,
    GeopoliticalConfig,
    IndicatorConfig,
)
from .data_fetcher import CommodityDataFetcher
from .geopolitical import GeopoliticalAnalyzer
from .indicators import TechnicalIndicators, verify_no_future_leak
from .report_generator import ReportGenerator
from .strategies import NON_GEO_STRATEGIES, GeopoliticalAdjustedStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_analysis(
    interval: str = "5m",
    commodities: list = None,
    lookback_days: int = 59,
):
    """
    执行完整的量化分析流程

    Args:
        interval: K线周期 (1m/2m/5m/15m/30m/60m)
        commodities: 要分析的品种列表, 默认全部
        lookback_days: 回望天数
    """
    start_time = time.time()

    if commodities is None:
        commodities = list(COMMODITIES.keys())

    # ========================================
    # Step 1: 数据获取
    # ========================================
    print("\n" + "=" * 60)
    print("  Step 1/6: 获取市场数据")
    print("=" * 60)

    data_config = DataConfig(interval=interval, lookback_days=lookback_days)
    fetcher = CommodityDataFetcher(data_config)

    commodity_data = {}
    for key in commodities:
        try:
            df = fetcher.fetch_commodity(key)
            commodity_data[key] = df
            print(f"  [OK] {key}: {len(df)} bars, {df.index[0]} -> {df.index[-1]}")
        except Exception as e:
            print(f"  [FAIL] {key}: {e}")

    if not commodity_data:
        print("\n[ERROR] 无法获取任何商品数据，程序退出")
        return

    # 获取参考品种
    print("\n  获取参考品种数据...")
    reference_data = fetcher.fetch_all_references()
    for key, df in reference_data.items():
        if not df.empty:
            print(f"  [OK] {key}: {len(df)} bars")
        else:
            print(f"  [WARN] {key}: 无数据")

    # ========================================
    # Step 2: 地缘政治风险评估
    # ========================================
    print("\n" + "=" * 60)
    print("  Step 2/6: 地缘政治风险评估")
    print("=" * 60)

    geo_analyzer = GeopoliticalAnalyzer()
    risk_assessment = geo_analyzer.analyze(commodity_data, reference_data)

    print(f"\n  风险等级: {risk_assessment.overall_level.value.upper()}")
    print(f"  风险得分: {risk_assessment.overall_score:.1f}/100")
    for factor in risk_assessment.active_factors:
        print(f"  - {factor}")

    # ========================================
    # Step 3: 未来函数验证
    # ========================================
    print("\n" + "=" * 60)
    print("  Step 3/6: 未来函数验证")
    print("=" * 60)

    indicator_calc = TechnicalIndicators()
    sample_key = list(commodity_data.keys())[0]
    sample_df = indicator_calc.compute_all(commodity_data[sample_key].copy())

    test_cols = [
        "sma_5", "ema_5", "rsi", "macd_line", "macd_signal", "macd_hist",
        "bb_upper", "bb_lower", "bb_pct_b", "atr", "vwap",
        "roc_5", "williams_r", "realized_vol",
    ]
    all_clean = True
    for col in test_cols:
        if col in sample_df.columns:
            is_clean = verify_no_future_leak(sample_df, col)
            status = "PASS" if is_clean else "FAIL"
            print(f"  [{status}] {col}")
            if not is_clean:
                all_clean = False

    if all_clean:
        print("\n  [ALL PASS] 所有指标通过未来函数检测")
    else:
        print("\n  [WARNING] 存在未来函数泄露，请检查!")

    # ========================================
    # Step 4: Walk-Forward 回测
    # ========================================
    print("\n" + "=" * 60)
    print("  Step 4/6: Walk-Forward 回测")
    print("=" * 60)

    bt_config = BacktestConfig()
    backtester = WalkForwardBacktester(bt_config)

    all_results: Dict[str, Dict[str, BacktestResult]] = {}

    for commodity_key, df in commodity_data.items():
        print(f"\n  === {commodity_key.upper()} ===")
        all_results[commodity_key] = {}

        # 运行所有非地缘策略
        for strat_name, strat_cls in NON_GEO_STRATEGIES.items():
            try:
                strategy = strat_cls(bt_config)
                result = backtester.run(df, strategy, commodity_key)

                all_results[commodity_key][strat_name] = result
                print(
                    f"  [{strat_name:20s}] "
                    f"收益: {result.total_return_pct:+7.2f}% | "
                    f"Sharpe: {result.sharpe_ratio:6.2f} | "
                    f"回撤: {result.max_drawdown_pct:7.2f}% | "
                    f"交易: {result.total_trades:3d} | "
                    f"OOS: {result.oos_consistency:.0%}"
                )
            except Exception as e:
                print(f"  [{strat_name:20s}] ERROR: {e}")
                logger.exception(f"Backtest failed for {commodity_key}/{strat_name}")

        # 运行地缘调整策略
        try:
            geo_strategy = GeopoliticalAdjustedStrategy(
                config=bt_config,
                commodity_type=commodity_key,
                risk_score=risk_assessment.overall_score,
            )
            result = backtester.run(df, geo_strategy, commodity_key)
            all_results[commodity_key]["geo_adjusted"] = result
            print(
                f"  [{'geo_adjusted':20s}] "
                f"收益: {result.total_return_pct:+7.2f}% | "
                f"Sharpe: {result.sharpe_ratio:6.2f} | "
                f"回撤: {result.max_drawdown_pct:7.2f}% | "
                f"交易: {result.total_trades:3d} | "
                f"OOS: {result.oos_consistency:.0%}"
            )
        except Exception as e:
            print(f"  [geo_adjusted          ] ERROR: {e}")

    # ========================================
    # Step 5: 生成报告
    # ========================================
    print("\n" + "=" * 60)
    print("  Step 5/6: 生成分析报告")
    print("=" * 60)

    reporter = ReportGenerator()
    report = reporter.generate_full_report(all_results, risk_assessment)
    print(report)

    # ========================================
    # Step 6: 市场快照
    # ========================================
    print("\n" + "=" * 60)
    print("  Step 6/6: 当前市场快照")
    print("=" * 60)

    for commodity_key, df in commodity_data.items():
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        change_pct = (latest["close"] - prev["close"]) / prev["close"] * 100

        indicator_df = indicator_calc.compute_all(df)
        latest_ind = indicator_df.iloc[-1]

        print(f"\n  {commodity_key.upper()}:")
        print(f"    最新价: {latest['close']:.2f}")
        print(f"    变动:   {change_pct:+.3f}%")

        if "rsi" in latest_ind.index and not pd.isna(latest_ind["rsi"]):
            rsi_val = latest_ind["rsi"]
            rsi_status = "超买" if rsi_val > 70 else ("超卖" if rsi_val < 30 else "中性")
            print(f"    RSI:    {rsi_val:.1f} ({rsi_status})")

        if "macd_hist" in latest_ind.index and not pd.isna(latest_ind["macd_hist"]):
            macd_h = latest_ind["macd_hist"]
            macd_dir = "看多" if macd_h > 0 else "看空"
            print(f"    MACD:   {macd_h:.4f} ({macd_dir})")

        if "bb_pct_b" in latest_ind.index and not pd.isna(latest_ind["bb_pct_b"]):
            bb_pct = latest_ind["bb_pct_b"]
            bb_status = "上轨附近" if bb_pct > 0.8 else ("下轨附近" if bb_pct < 0.2 else "中轨附近")
            print(f"    布林%B: {bb_pct:.2f} ({bb_status})")

        if "atr_pct" in latest_ind.index and not pd.isna(latest_ind["atr_pct"]):
            print(f"    ATR%:   {latest_ind['atr_pct']:.3f}%")

    elapsed = time.time() - start_time
    print(f"\n  分析完成，耗时 {elapsed:.1f} 秒")
    print("=" * 60)

    return all_results, risk_assessment


def main():
    parser = argparse.ArgumentParser(
        description="大宗商品量化分析助手 - 黄金/白银/原油"
    )
    parser.add_argument(
        "--interval", "-i",
        default="5m",
        choices=["1m", "2m", "5m", "15m", "30m", "60m"],
        help="K线周期 (默认: 5m)",
    )
    parser.add_argument(
        "--commodity", "-c",
        nargs="+",
        choices=["gold", "silver", "oil"],
        default=None,
        help="指定品种 (默认: 全部)",
    )
    parser.add_argument(
        "--lookback", "-l",
        type=int,
        default=59,
        help="回望天数 (默认: 59)",
    )

    args = parser.parse_args()

    run_analysis(
        interval=args.interval,
        commodities=args.commodity,
        lookback_days=args.lookback,
    )


if __name__ == "__main__":
    main()
