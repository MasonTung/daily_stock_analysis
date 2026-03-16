# -*- coding: utf-8 -*-
"""
===================================
薯条交易 (Fries Trading) API
===================================

职责：
1. 标的维度管理 - 股票/群组/标签 CRUD
2. Persona 维度管理 - 人格/策略 CRUD
3. 跨维度关系管理 - 股票-Persona 绑定
4. 图谱数据接口 - 2D/3D 可视化数据
5. 多模态输入 - 图片识别 + 文本解析
6. 分析触发 - 按 Persona 分析股票
"""

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


# ========================================
# Request / Response Models
# ========================================

class AddStockRequest(BaseModel):
    symbol: str = Field(..., description="股票代码 (e.g. AAPL)")
    name: str = Field("", description="股票名称")
    market: str = Field("US", description="市场 (US/CN/HK)")
    sector: str = Field("", description="行业板块")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    group: str = Field("", description="所属群组")
    properties: Optional[Dict[str, Any]] = None


class AddStockBatchRequest(BaseModel):
    stocks: List[AddStockRequest]


class CreateGroupRequest(BaseModel):
    name: str = Field(..., description="群组名称")
    parent_group: str = Field("", description="父群组名称")
    description: str = Field("", description="群组描述")


class CreateTagRequest(BaseModel):
    name: str = Field(..., description="标签名称")
    color: str = Field("#f39c12", description="标签颜色")


class TagStockRequest(BaseModel):
    symbol: str
    tag_name: str


class MoveStockRequest(BaseModel):
    symbol: str
    group_name: str


class PersonaRequest(BaseModel):
    persona_id: str = Field(..., description="Persona 唯一标识")
    name: str = Field(..., description="Persona 名称")
    description: str = Field("", description="描述")
    strategies: Optional[List[str]] = Field(None, description="关联策略 ID 列表")
    properties: Optional[Dict[str, Any]] = None


class UpdatePersonaRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    strategies: Optional[List[str]] = None
    properties: Optional[Dict[str, Any]] = None


class BindPersonaRequest(BaseModel):
    persona_id: str
    symbol: str
    weight: float = Field(1.0, description="关系权重")
    properties: Optional[Dict[str, Any]] = None


class RecommendRequest(BaseModel):
    persona_id: str
    symbol: str
    score: float = Field(0.0, description="推荐评分")
    reason: str = Field("", description="推荐理由")


class AnalyzeRequest(BaseModel):
    stock_codes: List[str] = Field(..., description="待分析股票代码列表")
    personas: Optional[List[str]] = Field(None, description="使用的 Persona 列表")
    persona_overrides: Optional[Dict[str, str]] = Field(
        None, description="每只股票的 Persona 覆盖 {symbol: persona_id}"
    )


class GraphQueryRequest(BaseModel):
    dimension: Optional[str] = Field(None, description="维度过滤: stocks/personas/cross")
    center_node: Optional[str] = Field(None, description="中心节点 ID")
    depth: int = Field(2, description="展开深度")
    limit: int = Field(200, description="最大节点数")


class NodeResponse(BaseModel):
    success: bool = True
    node: Optional[Dict] = None


class NodesResponse(BaseModel):
    success: bool = True
    nodes: List[Dict] = []
    total: int = 0


class GraphResponse(BaseModel):
    success: bool = True
    nodes: List[Dict] = []
    edges: List[Dict] = []
    dimension: str = "cross"
    stats: Dict[str, int] = {}


class PersonasResponse(BaseModel):
    personas: List[Dict] = []


# ========================================
# 标的维度 (Stocks Dimension)
# ========================================

@router.post("/stocks", response_model=NodeResponse, summary="添加股票标的")
def add_stock(req: AddStockRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    node = svc.add_stock(
        symbol=req.symbol, name=req.name, market=req.market,
        sector=req.sector, tags=req.tags, group=req.group,
        properties=req.properties,
    )
    return NodeResponse(node=node.to_dict())


@router.post("/stocks/batch", response_model=NodesResponse, summary="批量添加股票")
def add_stock_batch(req: AddStockBatchRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    nodes = svc.add_stock_batch([s.model_dump() for s in req.stocks])
    return NodesResponse(nodes=[n.to_dict() for n in nodes], total=len(nodes))


@router.post("/groups", response_model=NodeResponse, summary="创建群组")
def create_group(req: CreateGroupRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    node = svc.create_group(name=req.name, parent_group=req.parent_group, description=req.description)
    return NodeResponse(node=node.to_dict())


@router.post("/tags", response_model=NodeResponse, summary="创建标签")
def create_tag(req: CreateTagRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    node = svc.create_tag(name=req.name, color=req.color)
    return NodeResponse(node=node.to_dict())


@router.post("/stocks/tag", summary="为股票添加标签")
def tag_stock(req: TagStockRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    edge = svc.tag_stock(req.symbol, req.tag_name)
    return {"success": True, "edge": edge.to_dict()}


@router.post("/stocks/move", summary="移动股票到群组")
def move_stock(req: MoveStockRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    edge = svc.move_stock_to_group(req.symbol, req.group_name)
    return {"success": True, "edge": edge.to_dict()}


@router.get("/stocks/hierarchy", summary="获取标的层级结构")
def get_hierarchy():
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    return svc.get_stock_hierarchy()


@router.get("/stocks/{symbol}/personas", summary="获取股票关联的 Personas")
def get_stock_personas(symbol: str):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    return {"personas": svc.get_stock_personas(symbol)}


@router.delete("/stocks/{symbol}", summary="删除股票标的")
def delete_stock(symbol: str):
    from mirofish.graph_service import FriesGraphService
    from mirofish.graph_models import make_node_id
    svc = FriesGraphService()
    node_id = make_node_id("stock", symbol.upper())
    count = svc.store.delete_node(node_id)
    return {"success": count > 0, "deleted": count}


# ========================================
# Persona 维度 (Personas Dimension)
# ========================================

@router.get("/personas", response_model=PersonasResponse, summary="列出所有 Personas")
def list_personas():
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    nodes = svc.list_personas()
    return PersonasResponse(personas=[n.to_dict() for n in nodes])


@router.post("/personas", response_model=NodeResponse, summary="添加 Persona")
def add_persona(req: PersonaRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    node = svc.add_persona(
        persona_id=req.persona_id, name=req.name,
        description=req.description, strategies=req.strategies,
        properties=req.properties,
    )
    return NodeResponse(node=node.to_dict())


@router.put("/personas/{persona_id}", response_model=NodeResponse, summary="更新 Persona")
def update_persona(persona_id: str, req: UpdatePersonaRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    node = svc.update_persona(
        persona_id=persona_id, name=req.name,
        description=req.description, strategies=req.strategies,
        properties=req.properties,
    )
    if not node:
        raise HTTPException(status_code=404, detail=f"Persona '{persona_id}' not found")
    return NodeResponse(node=node.to_dict())


@router.delete("/personas/{persona_id}", summary="删除 Persona")
def delete_persona(persona_id: str):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    success = svc.delete_persona(persona_id)
    return {"success": success}


@router.get("/personas/{persona_id}/stocks", summary="获取 Persona 关联的股票")
def get_persona_stocks(persona_id: str):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    return {"stocks": svc.get_persona_stocks(persona_id)}


@router.get("/personas/{persona_id}/strategies", summary="获取 Persona 的策略")
def get_persona_strategies(persona_id: str):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    strategies = svc.get_persona_strategies(persona_id)
    return {"strategies": [s.to_dict() for s in strategies]}


# ========================================
# 跨维度关系管理
# ========================================

@router.post("/bindings", summary="绑定 Persona 到股票")
def bind_persona(req: BindPersonaRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    edge = svc.bind_persona_to_stock(
        req.persona_id, req.symbol,
        weight=req.weight, properties=req.properties,
    )
    return {"success": True, "edge": edge.to_dict()}


@router.delete("/bindings/{persona_id}/{symbol}", summary="解绑 Persona 与股票")
def unbind_persona(persona_id: str, symbol: str):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    success = svc.unbind_persona_from_stock(persona_id, symbol)
    return {"success": success}


@router.post("/recommendations", summary="Persona 推荐股票")
def add_recommendation(req: RecommendRequest):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    edge = svc.add_persona_recommendation(
        req.persona_id, req.symbol,
        score=req.score, reason=req.reason,
    )
    return {"success": True, "edge": edge.to_dict()}


# ========================================
# 图谱数据接口
# ========================================

@router.get("/graph/stocks", response_model=GraphResponse, summary="标的维度2D图谱")
def get_stocks_graph(limit: int = Query(200, ge=1, le=1000)):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    data = svc.get_stocks_graph(limit=limit)
    return GraphResponse(
        nodes=data.nodes, edges=data.edges,
        dimension=data.dimension, stats=data.stats,
    )


@router.get("/graph/personas", response_model=GraphResponse, summary="Persona维度2D图谱")
def get_personas_graph(limit: int = Query(200, ge=1, le=1000)):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    data = svc.get_personas_graph(limit=limit)
    return GraphResponse(
        nodes=data.nodes, edges=data.edges,
        dimension=data.dimension, stats=data.stats,
    )


@router.get("/graph/cross", response_model=GraphResponse, summary="跨维度3D图谱")
def get_cross_graph(limit: int = Query(300, ge=1, le=2000)):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    data = svc.get_cross_graph(limit=limit)
    return GraphResponse(
        nodes=data.nodes, edges=data.edges,
        dimension=data.dimension, stats=data.stats,
    )


@router.get("/graph/ego/{node_id}", response_model=GraphResponse, summary="节点邻域图谱")
def get_ego_graph(node_id: str, depth: int = Query(2, ge=1, le=4)):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    data = svc.get_ego_graph(node_id, depth=depth)
    return GraphResponse(
        nodes=data.nodes, edges=data.edges,
        dimension=data.dimension, stats=data.stats,
    )


@router.get("/graph/search", summary="搜索图谱节点")
def search_graph(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    nodes = svc.store.search_nodes(q, limit=limit)
    return {"nodes": [n.to_dict() for n in nodes]}


@router.get("/graph/rag/{symbol}", summary="获取 Graph RAG 上下文")
def get_rag_context(symbol: str, persona_id: Optional[str] = None):
    from mirofish.graph_service import FriesGraphService
    svc = FriesGraphService()
    context = svc.build_rag_context(symbol, persona_id=persona_id)
    return {"symbol": symbol, "context": context}


# ========================================
# 分析触发
# ========================================

@router.post("/analyze", summary="触发薯条交易分析")
async def trigger_analysis(req: AnalyzeRequest):
    """
    触发分析任务，支持：
    - 指定 Persona 列表（全局）
    - 每只股票单独指定 Persona Override
    """
    from src.config import get_config
    config = get_config()

    if not req.stock_codes:
        raise HTTPException(status_code=400, detail="stock_codes is required")

    # Build analysis tasks
    tasks = []
    for code in req.stock_codes:
        persona = None
        if req.persona_overrides and code in req.persona_overrides:
            persona = req.persona_overrides[code]
        elif req.personas:
            persona = req.personas[0] if len(req.personas) == 1 else None

        strategies = None
        if persona:
            # 获取 Persona 的策略
            from mirofish.graph_service import FriesGraphService
            svc = FriesGraphService()
            strategy_nodes = svc.get_persona_strategies(persona)
            if strategy_nodes:
                strategies = [s.properties.get("strategy_id", s.label) for s in strategy_nodes]
        elif req.personas:
            strategies = req.personas

        tasks.append({
            "stock_code": code,
            "strategies": strategies,
            "persona": persona,
        })

    # 提交分析任务
    task_id = str(uuid.uuid4())[:8]

    try:
        from src.services.task_queue import TaskQueue
        tq = TaskQueue.get_instance()

        submitted = []
        for task in tasks:
            try:
                tid = tq.submit(
                    stock_code=task["stock_code"],
                    strategies=task.get("strategies"),
                )
                submitted.append({"stock_code": task["stock_code"], "task_id": tid})
            except Exception as e:
                submitted.append({
                    "stock_code": task["stock_code"],
                    "error": str(e),
                })

        return {
            "success": True,
            "task_id": task_id,
            "tasks": submitted,
            "total": len(submitted),
        }
    except Exception as e:
        logger.error(f"Analysis trigger failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
