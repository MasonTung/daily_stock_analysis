"""
FastAPI Web Server - 大宗商品量化助手的 Web 仪表盘后端

提供 REST API 供前端调用:
- GET  /                       主页 (仪表盘 HTML)
- POST /api/analyze            触发完整分析 (耗时 7-10 秒)
- GET  /api/kline/{commodity}  K线 + 技术指标数据
- GET  /api/backtest           全部策略回测结果
- GET  /api/geopolitical       地缘政治风险
- GET  /api/snapshot           市场快照
- GET  /api/status             分析状态
"""

import asyncio
import logging
import threading
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

from ..backtest_engine import WalkForwardBacktester
from ..config import (
    COMMODITIES,
    BacktestConfig,
    DataConfig,
    IndicatorConfig,
)
from ..data_fetcher import CommodityDataFetcher
from ..geopolitical import GeopoliticalAnalyzer
from ..indicators import TechnicalIndicators
from ..strategies import NON_GEO_STRATEGIES, GeopoliticalAdjustedStrategy

logger = logging.getLogger(__name__)

# 路径配置
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


# ============================================================
# 全局分析状态 (单例)
# ============================================================
class AnalysisState:
    """保存分析结果的全局状态"""

    def __init__(self):
        self.is_running = False
        self.last_run_time: Optional[str] = None
        self.commodity_data: Dict[str, pd.DataFrame] = {}
        self.reference_data: Dict[str, pd.DataFrame] = {}
        self.indicators_data: Dict[str, pd.DataFrame] = {}
        self.backtest_results: Dict[str, Dict] = {}
        self.risk_assessment = None
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self.is_running:
                return False
            self.is_running = True
            self.error = None
            return True

    def finish(self, error=None):
        with self._lock:
            self.is_running = False
            self.error = error
            if not error:
                self.last_run_time = pd.Timestamp.now().isoformat()


STATE = AnalysisState()


# ============================================================
# 分析任务 (在后台线程中运行)
# ============================================================
def run_full_analysis(interval: str = "5m", lookback_days: int = 59):
    """在后台线程中执行完整分析"""
    try:
        logger.info(f"Starting analysis: interval={interval}, lookback={lookback_days}")

        # 1. 获取数据
        data_config = DataConfig(interval=interval, lookback_days=lookback_days)
        fetcher = CommodityDataFetcher(data_config)

        commodity_data = {}
        for key in COMMODITIES:
            try:
                commodity_data[key] = fetcher.fetch_commodity(key)
            except Exception as e:
                logger.error(f"Failed to fetch {key}: {e}")

        reference_data = fetcher.fetch_all_references()

        # 2. 地缘政治评估
        geo_analyzer = GeopoliticalAnalyzer()
        risk_assessment = geo_analyzer.analyze(commodity_data, reference_data)

        # 3. 计算指标
        indicator_calc = TechnicalIndicators()
        indicators_data = {}
        for key, df in commodity_data.items():
            indicators_data[key] = indicator_calc.compute_all(df.copy())

        # 4. 回测
        bt_config = BacktestConfig()
        backtester = WalkForwardBacktester(bt_config)
        backtest_results = {}

        for commodity_key, df in commodity_data.items():
            backtest_results[commodity_key] = {}

            for strat_name, strat_cls in NON_GEO_STRATEGIES.items():
                try:
                    strategy = strat_cls(bt_config)
                    result = backtester.run(df, strategy, commodity_key)
                    backtest_results[commodity_key][strat_name] = _serialize_result(result)
                except Exception as e:
                    logger.error(f"Backtest failed: {commodity_key}/{strat_name}: {e}")

            # 地缘调整策略
            try:
                geo_strategy = GeopoliticalAdjustedStrategy(
                    config=bt_config,
                    commodity_type=commodity_key,
                    risk_score=risk_assessment.overall_score,
                )
                result = backtester.run(df, geo_strategy, commodity_key)
                backtest_results[commodity_key]["geo_adjusted"] = _serialize_result(result)
            except Exception as e:
                logger.error(f"Geo strategy failed: {e}")

        # 保存到全局状态
        STATE.commodity_data = commodity_data
        STATE.reference_data = reference_data
        STATE.indicators_data = indicators_data
        STATE.backtest_results = backtest_results
        STATE.risk_assessment = risk_assessment
        STATE.finish()

        logger.info("Analysis completed successfully")

    except Exception as e:
        logger.exception("Analysis failed")
        STATE.finish(error=str(e))


def _serialize_result(result) -> Dict:
    """将回测结果转换为 JSON 友好格式"""
    return {
        "strategy_name": result.strategy_name,
        "commodity": result.commodity,
        "total_return_pct": round(result.total_return_pct, 3),
        "sharpe_ratio": round(result.sharpe_ratio, 3),
        "max_drawdown_pct": round(result.max_drawdown_pct, 3),
        "win_rate": round(result.win_rate, 4),
        "profit_factor": round(result.profit_factor, 3),
        "total_trades": result.total_trades,
        "avg_bars_held": round(result.avg_bars_held, 1),
        "oos_consistency": round(result.oos_consistency, 3),
        "wf_splits": [
            {
                "split_id": wf.split_id,
                "n_trades": wf.n_trades,
                "win_rate": round(wf.win_rate, 3),
                "avg_pnl_pct": round(wf.avg_pnl_pct, 4),
                "total_pnl": round(wf.total_pnl, 2),
                "train_period": f"{wf.train_start.date()} → {wf.train_end.date()}",
                "test_period": f"{wf.test_start.date()} → {wf.test_end.date()}",
            }
            for wf in result.walk_forward_results
        ],
        "recent_trades": [
            {
                "entry_time": str(t.entry_time),
                "exit_time": str(t.exit_time),
                "direction": "LONG" if t.direction == 1 else "SHORT",
                "entry_price": round(t.entry_price, 4),
                "exit_price": round(t.exit_price, 4),
                "pnl_pct": round(t.pnl_pct, 4),
                "exit_reason": t.exit_reason,
                "bars_held": t.bars_held,
            }
            for t in result.all_trades[-10:]
        ],
    }


# ============================================================
# FastAPI App
# ============================================================
def create_app() -> FastAPI:
    app = FastAPI(
        title="Commodity Trading Assistant",
        description="大宗商品量化助手 - Web 仪表盘",
        version="1.0.0",
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---------- 主页 ----------
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"commodities": list(COMMODITIES.keys())},
        )

    # ---------- API: 触发分析 ----------
    @app.post("/api/analyze")
    async def start_analysis(interval: str = "5m", lookback_days: int = 59):
        if not STATE.start():
            raise HTTPException(status_code=409, detail="Analysis already running")

        # 后台线程执行
        thread = threading.Thread(
            target=run_full_analysis,
            args=(interval, lookback_days),
            daemon=True,
        )
        thread.start()

        return {"status": "started", "message": "Analysis started in background"}

    # ---------- API: 分析状态 ----------
    @app.get("/api/status")
    async def get_status():
        return {
            "is_running": STATE.is_running,
            "last_run_time": STATE.last_run_time,
            "error": STATE.error,
            "has_data": bool(STATE.commodity_data),
        }

    # ---------- API: K线 + 指标 ----------
    @app.get("/api/kline/{commodity}")
    async def get_kline(commodity: str, limit: int = 500):
        if commodity not in STATE.commodity_data:
            raise HTTPException(status_code=404, detail=f"No data for {commodity}")

        df = STATE.indicators_data.get(commodity, STATE.commodity_data[commodity])
        # 取最后 N 根K线，减少数据传输
        df = df.tail(limit)

        candles = []
        for ts, row in df.iterrows():
            candles.append({
                "time": ts.isoformat(),
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
                "volume": int(row.get("volume", 0)),
            })

        # 附加指标 (可能为 NaN)
        indicators = {}
        for col in ["sma_5", "sma_20", "sma_50", "ema_5", "ema_20",
                    "bb_upper", "bb_lower", "bb_middle",
                    "rsi", "macd_line", "macd_signal", "macd_hist",
                    "atr", "atr_pct", "vwap"]:
            if col in df.columns:
                values = df[col].values
                indicators[col] = [
                    round(float(v), 4) if not pd.isna(v) else None
                    for v in values
                ]

        info = COMMODITIES[commodity]
        return {
            "commodity": commodity,
            "name": info["name"],
            "symbol": info["symbol"],
            "candles": candles,
            "indicators": indicators,
            "latest_price": round(float(df["close"].iloc[-1]), 4),
            "change_pct": round(
                float((df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100),
                3
            ) if len(df) >= 2 else 0,
        }

    # ---------- API: 回测结果 ----------
    @app.get("/api/backtest")
    async def get_backtest():
        if not STATE.backtest_results:
            raise HTTPException(status_code=404, detail="No backtest data. Run analysis first.")
        return STATE.backtest_results

    # ---------- API: 地缘政治 ----------
    @app.get("/api/geopolitical")
    async def get_geopolitical():
        if STATE.risk_assessment is None:
            raise HTTPException(status_code=404, detail="No risk assessment. Run analysis first.")

        ra = STATE.risk_assessment
        return {
            "overall_level": ra.overall_level.value,
            "overall_score": round(ra.overall_score, 1),
            "commodity_bias": {k: round(v, 3) for k, v in ra.commodity_bias.items()},
            "position_scale": ra.position_scale,
            "active_factors": ra.active_factors,
            "detail": ra.detail,
        }

    # ---------- API: 市场快照 ----------
    @app.get("/api/snapshot")
    async def get_snapshot():
        if not STATE.indicators_data:
            raise HTTPException(status_code=404, detail="No data. Run analysis first.")

        snapshot = {}
        for commodity, df in STATE.indicators_data.items():
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest

            rsi_val = latest.get("rsi", float("nan"))
            macd_h = latest.get("macd_hist", float("nan"))
            bb_pct = latest.get("bb_pct_b", float("nan"))
            atr_pct = latest.get("atr_pct", float("nan"))

            snapshot[commodity] = {
                "name": COMMODITIES[commodity]["name"],
                "latest_price": round(float(latest["close"]), 4),
                "change_pct": round(
                    float((latest["close"] - prev["close"]) / prev["close"] * 100), 3
                ),
                "rsi": round(float(rsi_val), 2) if not pd.isna(rsi_val) else None,
                "macd_hist": round(float(macd_h), 4) if not pd.isna(macd_h) else None,
                "bb_pct_b": round(float(bb_pct), 3) if not pd.isna(bb_pct) else None,
                "atr_pct": round(float(atr_pct), 3) if not pd.isna(atr_pct) else None,
            }

        return snapshot

    # ---------- API: 最优策略推荐 ----------
    @app.get("/api/recommendations")
    async def get_recommendations():
        if not STATE.backtest_results:
            raise HTTPException(status_code=404, detail="No backtest data")

        recommendations = {}
        for commodity, strats in STATE.backtest_results.items():
            scored = []
            for name, r in strats.items():
                if r["total_trades"] < 10:
                    continue
                score = (
                    r["sharpe_ratio"] * 0.4
                    + r["win_rate"] * 0.2
                    + r["oos_consistency"] * 0.3
                    + (r["max_drawdown_pct"] / 100) * 0.1
                )
                scored.append((name, r, score))

            scored.sort(key=lambda x: x[2], reverse=True)

            if scored:
                best_name, best_r, best_score = scored[0]
                recommendations[commodity] = {
                    "strategy": best_name,
                    "score": round(best_score, 3),
                    "return_pct": best_r["total_return_pct"],
                    "sharpe": best_r["sharpe_ratio"],
                    "max_dd": best_r["max_drawdown_pct"],
                    "oos_consistency": best_r["oos_consistency"],
                    "passes_overfit_check": bool(
                        best_r["total_trades"] >= 10
                        and best_r["oos_consistency"] >= 0.5
                        and -1 < best_r["sharpe_ratio"] < 5
                    ),
                }
            else:
                recommendations[commodity] = None

        return recommendations

    return app


app = create_app()
