#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
薯条交易 (Fries Trading) - 独立演示服务器

无需完整依赖，只需 FastAPI + uvicorn 即可运行薯条交易图谱演示。

启动方式:
    python3 fries_demo.py

访问:
    http://127.0.0.1:8000/fries     - 图谱可视化页面
    http://127.0.0.1:8000/docs      - API 文档
"""

import os
import sys

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path


def create_demo_app() -> FastAPI:
    app = FastAPI(
        title="薯条交易 Fries Trading",
        description="双维度图谱交易分析系统 - 标的 × Persona",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册 mirofish API
    from api.v1.endpoints.mirofish import router as mirofish_router
    app.include_router(mirofish_router, prefix="/api/v1/mirofish", tags=["薯条交易"])

    # 图片提取 API（如果依赖可用）
    try:
        from api.v1.endpoints.stocks import router as stocks_router
        app.include_router(stocks_router, prefix="/api/v1/stocks", tags=["Stocks"])
    except Exception:
        pass

    # 薯条交易页面
    template_path = Path(__file__).parent / "mirofish" / "templates" / "fries_trading.html"

    @app.get("/fries", include_in_schema=False)
    async def fries_page():
        if template_path.exists():
            return FileResponse(template_path, media_type="text/html")
        return HTMLResponse("<h1>Template not found</h1>", status_code=404)

    @app.get("/", include_in_schema=False)
    async def root():
        return HTMLResponse("""
        <html><head><meta http-equiv="refresh" content="0;url=/fries"></head>
        <body>Redirecting to <a href="/fries">薯条交易</a>...</body></html>
        """)

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    return app


def load_demo_data():
    """加载示例数据"""
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()

    # 检查是否已有数据
    existing = svc.store.list_nodes(limit=1)
    if existing:
        print(f"  已有 {len(svc.store.list_nodes(limit=999))} 个节点，跳过加载")
        return

    print("  加载示例数据...")

    # 群组
    svc.create_group("FAANG", description="美国科技巨头")
    svc.create_group("中概股", description="中概互联网")
    svc.create_group("半导体", parent_group="FAANG", description="芯片相关")

    # 标签
    for tag in ["mega-cap", "growth", "AI", "EV"]:
        svc.create_tag(tag)

    # 股票
    stocks = [
        ("AAPL", "Apple", "Technology", ["mega-cap", "AI"], "FAANG"),
        ("GOOGL", "Google", "Technology", ["mega-cap", "AI"], "FAANG"),
        ("MSFT", "Microsoft", "Technology", ["mega-cap", "AI"], "FAANG"),
        ("AMZN", "Amazon", "E-Commerce", ["mega-cap"], "FAANG"),
        ("META", "Meta", "Social Media", ["mega-cap", "AI"], "FAANG"),
        ("TSLA", "Tesla", "EV", ["growth", "EV"], ""),
        ("NVDA", "NVIDIA", "Semiconductor", ["mega-cap", "AI"], "半导体"),
        ("AMD", "AMD", "Semiconductor", ["growth", "AI"], "半导体"),
        ("BABA", "Alibaba", "E-Commerce", ["growth"], "中概股"),
        ("PDD", "PDD Holdings", "E-Commerce", ["growth"], "中概股"),
        ("JD", "JD.com", "E-Commerce", [], "中概股"),
        ("BIDU", "Baidu", "AI", ["AI"], "中概股"),
    ]
    for sym, name, sector, tags, group in stocks:
        svc.add_stock(sym, name, market="US", sector=sector, tags=tags, group=group)

    # Personas
    personas = [
        ("trend_hunter", "趋势猎手", "追踪强势趋势股，突破买入", ["bull_trend", "ma_golden_cross"]),
        ("value_picker", "价值挖掘者", "低估值选股，长线持有", ["shrink_pullback"]),
        ("swing_trader", "波段操盘手", "中短期波段操作", ["volume_breakout", "box_oscillation"]),
        ("ai_believer", "AI信仰者", "专注AI赛道投资", ["bull_trend"]),
    ]
    for pid, name, desc, strategies in personas:
        svc.add_persona(pid, name, description=desc, strategies=strategies)

    # 绑定关系
    bindings = [
        ("trend_hunter", ["NVDA", "TSLA", "META"]),
        ("value_picker", ["BABA", "JD", "PDD"]),
        ("swing_trader", ["AMD", "AAPL"]),
        ("ai_believer", ["NVDA", "GOOGL", "MSFT", "BIDU"]),
    ]
    for persona, symbols in bindings:
        for sym in symbols:
            svc.bind_persona_to_stock(persona, sym)

    # 推荐
    svc.add_persona_recommendation("ai_believer", "NVDA", score=95, reason="AI算力龙头")
    svc.add_persona_recommendation("trend_hunter", "TSLA", score=80, reason="突破关键阻力位")
    svc.add_persona_recommendation("value_picker", "BABA", score=75, reason="估值处于历史低位")

    graph = svc.get_cross_graph()
    print(f"  加载完成: {len(graph.nodes)} nodes, {len(graph.edges)} edges")


if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print("  🍟 薯条交易 Fries Trading")
    print("=" * 50)

    load_demo_data()

    print()
    print("  启动服务...")
    print("  📊 图谱页面: http://127.0.0.1:8000/fries")
    print("  📖 API 文档: http://127.0.0.1:8000/docs")
    print("=" * 50)

    uvicorn.run(
        create_demo_app(),
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
