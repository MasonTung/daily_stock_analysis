# -*- coding: utf-8 -*-
"""
===================================
薯条交易 - Graph Service
===================================

业务逻辑层：管理标的和 Persona 两大维度的图谱操作。
支持：
- 标的维度的 tag/group 层级管理
- Persona 维度的策略/人格管理
- 跨维度关系绑定（股票-Persona 分析关系）
- Graph RAG 上下文构建
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any, Dict, List, Optional

from mirofish.graph_models import (
    Dimension,
    EdgeType,
    GraphData,
    GraphEdge,
    GraphNode,
    GraphStore,
    NodeType,
    get_graph_store,
    make_edge_id,
    make_node_id,
)

logger = logging.getLogger(__name__)


class FriesGraphService:
    """薯条交易图谱服务"""

    def __init__(self, store: Optional[GraphStore] = None):
        self.store = store or get_graph_store()

    # ========================================
    # 标的维度 (Stocks Dimension)
    # ========================================

    def add_stock(
        self,
        symbol: str,
        name: str = "",
        market: str = "US",
        sector: str = "",
        tags: Optional[List[str]] = None,
        group: str = "",
        properties: Optional[Dict] = None,
    ) -> GraphNode:
        """添加股票标的节点"""
        node_id = make_node_id("stock", symbol.upper())
        props = {
            "symbol": symbol.upper(),
            "market": market,
            "sector": sector,
            **(properties or {}),
        }
        node = GraphNode(
            id=node_id,
            node_type=NodeType.STOCK.value,
            label=name or symbol.upper(),
            dimension=Dimension.STOCKS.value,
            properties=props,
        )
        self.store.upsert_node(node)

        # 市场关系
        if market:
            market_node = self._ensure_market_node(market)
            self._ensure_edge(node_id, market_node.id, EdgeType.IN_MARKET.value)

        # 行业关系
        if sector:
            sector_node = self._ensure_sector_node(sector)
            self._ensure_edge(node_id, sector_node.id, EdgeType.IN_SECTOR.value)

        # 标签关系
        for tag in (tags or []):
            tag_node = self._ensure_tag_node(tag)
            self._ensure_edge(node_id, tag_node.id, EdgeType.TAGGED_WITH.value)

        # 群组关系
        if group:
            group_node = self._ensure_group_node(group)
            self._ensure_edge(node_id, group_node.id, EdgeType.BELONGS_TO.value)

        return node

    def add_stock_batch(self, stocks: List[Dict]) -> List[GraphNode]:
        """批量添加股票"""
        nodes = []
        for s in stocks:
            node = self.add_stock(
                symbol=s.get("symbol", ""),
                name=s.get("name", ""),
                market=s.get("market", "US"),
                sector=s.get("sector", ""),
                tags=s.get("tags"),
                group=s.get("group", ""),
                properties=s.get("properties"),
            )
            nodes.append(node)
        return nodes

    def create_group(
        self,
        name: str,
        parent_group: str = "",
        description: str = "",
    ) -> GraphNode:
        """创建群组节点（支持层级）"""
        node_id = make_node_id("group", name)
        parent_id = make_node_id("group", parent_group) if parent_group else None
        parent_depth = 0
        if parent_id:
            parent = self.store.get_node(parent_id)
            if parent:
                parent_depth = parent.depth

        node = GraphNode(
            id=node_id,
            node_type=NodeType.GROUP.value,
            label=name,
            dimension=Dimension.STOCKS.value,
            properties={"description": description},
            parent_id=parent_id,
            depth=parent_depth + 1 if parent_id else 0,
        )
        self.store.upsert_node(node)

        if parent_id:
            self._ensure_edge(parent_id, node_id, EdgeType.PARENT_OF.value)

        return node

    def create_tag(self, name: str, color: str = "#f39c12") -> GraphNode:
        """创建标签节点"""
        node = self._ensure_tag_node(name)
        if color != "#f39c12":
            node.color = color
            self.store.upsert_node(node)
        return node

    def tag_stock(self, symbol: str, tag_name: str) -> GraphEdge:
        """为股票添加标签"""
        stock_id = make_node_id("stock", symbol.upper())
        tag_node = self._ensure_tag_node(tag_name)
        return self._ensure_edge(stock_id, tag_node.id, EdgeType.TAGGED_WITH.value)

    def move_stock_to_group(self, symbol: str, group_name: str) -> GraphEdge:
        """将股票移动到群组"""
        stock_id = make_node_id("stock", symbol.upper())
        group_node = self._ensure_group_node(group_name)
        # Remove old group edges
        old_edges = self.store.get_edges(source_id=stock_id, edge_type=EdgeType.BELONGS_TO.value)
        for e in old_edges:
            self.store.delete_edge(e.id)
        return self._ensure_edge(stock_id, group_node.id, EdgeType.BELONGS_TO.value)

    def get_stocks_in_group(self, group_name: str) -> List[GraphNode]:
        """获取群组内的所有股票"""
        group_id = make_node_id("group", group_name)
        edges = self.store.get_edges(target_id=group_id, edge_type=EdgeType.BELONGS_TO.value)
        result = []
        for e in edges:
            node = self.store.get_node(e.source_id)
            if node and node.node_type == NodeType.STOCK.value:
                result.append(node)
        return result

    def get_stocks_by_tag(self, tag_name: str) -> List[GraphNode]:
        """获取具有某标签的所有股票"""
        tag_id = make_node_id("tag", tag_name)
        edges = self.store.get_edges(target_id=tag_id, edge_type=EdgeType.TAGGED_WITH.value)
        result = []
        for e in edges:
            node = self.store.get_node(e.source_id)
            if node and node.node_type == NodeType.STOCK.value:
                result.append(node)
        return result

    def get_stock_hierarchy(self) -> List[Dict]:
        """获取标的维度的完整层级结构"""
        groups = self.store.list_nodes(
            dimension=Dimension.STOCKS.value,
            node_type=NodeType.GROUP.value,
        )
        tags = self.store.list_nodes(
            dimension=Dimension.STOCKS.value,
            node_type=NodeType.TAG.value,
        )

        hierarchy = []
        root_groups = [g for g in groups if not g.parent_id]
        for g in root_groups:
            hierarchy.append(self._build_group_tree(g, groups))

        return {
            "groups": hierarchy,
            "tags": [t.to_dict() for t in tags],
        }

    def _build_group_tree(self, group: GraphNode, all_groups: List[GraphNode]) -> Dict:
        children = [g for g in all_groups if g.parent_id == group.id]
        stocks = self.get_stocks_in_group(group.label)
        return {
            **group.to_dict(),
            "children": [self._build_group_tree(c, all_groups) for c in children],
            "stocks": [s.to_dict() for s in stocks],
        }

    # ========================================
    # Persona 维度 (Personas Dimension)
    # ========================================

    def add_persona(
        self,
        persona_id: str,
        name: str,
        description: str = "",
        strategies: Optional[List[str]] = None,
        properties: Optional[Dict] = None,
    ) -> GraphNode:
        """添加交易人格节点"""
        node_id = make_node_id("persona", persona_id)
        props = {
            "persona_id": persona_id,
            "description": description,
            **(properties or {}),
        }
        node = GraphNode(
            id=node_id,
            node_type=NodeType.PERSONA.value,
            label=name,
            dimension=Dimension.PERSONAS.value,
            properties=props,
        )
        self.store.upsert_node(node)

        # 策略关系
        for strategy_id in (strategies or []):
            strategy_node = self._ensure_strategy_node(strategy_id)
            self._ensure_edge(node_id, strategy_node.id, EdgeType.USES_STRATEGY.value)

        return node

    def update_persona(
        self,
        persona_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        strategies: Optional[List[str]] = None,
        properties: Optional[Dict] = None,
    ) -> Optional[GraphNode]:
        """单独更新 Persona"""
        node_id = make_node_id("persona", persona_id)
        node = self.store.get_node(node_id)
        if not node:
            return None

        if name:
            node.label = name
        if description:
            node.properties["description"] = description
        if properties:
            node.properties.update(properties)
        self.store.upsert_node(node)

        if strategies is not None:
            # 清除旧策略关系，添加新的
            old = self.store.get_edges(source_id=node_id, edge_type=EdgeType.USES_STRATEGY.value)
            for e in old:
                self.store.delete_edge(e.id)
            for sid in strategies:
                sn = self._ensure_strategy_node(sid)
                self._ensure_edge(node_id, sn.id, EdgeType.USES_STRATEGY.value)

        return node

    def list_personas(self) -> List[GraphNode]:
        """列出所有 Persona"""
        return self.store.list_nodes(
            dimension=Dimension.PERSONAS.value,
            node_type=NodeType.PERSONA.value,
        )

    def delete_persona(self, persona_id: str) -> bool:
        """删除 Persona"""
        node_id = make_node_id("persona", persona_id)
        return self.store.delete_node(node_id) > 0

    def get_persona_strategies(self, persona_id: str) -> List[GraphNode]:
        """获取 Persona 关联的策略"""
        node_id = make_node_id("persona", persona_id)
        edges = self.store.get_edges(source_id=node_id, edge_type=EdgeType.USES_STRATEGY.value)
        result = []
        for e in edges:
            node = self.store.get_node(e.target_id)
            if node:
                result.append(node)
        return result

    # ========================================
    # 跨维度关系 (Cross-Dimension)
    # ========================================

    def bind_persona_to_stock(
        self,
        persona_id: str,
        symbol: str,
        weight: float = 1.0,
        properties: Optional[Dict] = None,
    ) -> GraphEdge:
        """绑定 Persona 到股票（分析关系）"""
        stock_node_id = make_node_id("stock", symbol.upper())
        persona_node_id = make_node_id("persona", persona_id)
        return self._ensure_edge(
            stock_node_id, persona_node_id,
            EdgeType.ANALYZED_BY.value,
            weight=weight,
            properties=properties,
        )

    def unbind_persona_from_stock(self, persona_id: str, symbol: str) -> bool:
        """解绑 Persona 与股票"""
        stock_node_id = make_node_id("stock", symbol.upper())
        persona_node_id = make_node_id("persona", persona_id)
        edges = self.store.get_edges(
            source_id=stock_node_id,
            target_id=persona_node_id,
            edge_type=EdgeType.ANALYZED_BY.value,
        )
        for e in edges:
            self.store.delete_edge(e.id)
        return len(edges) > 0

    def get_stock_personas(self, symbol: str) -> List[Dict]:
        """获取某股票关联的所有 Persona"""
        stock_id = make_node_id("stock", symbol.upper())
        edges = self.store.get_edges(source_id=stock_id, edge_type=EdgeType.ANALYZED_BY.value)
        result = []
        for e in edges:
            node = self.store.get_node(e.target_id)
            if node:
                result.append({
                    "persona": node.to_dict(),
                    "edge": e.to_dict(),
                })
        return result

    def get_persona_stocks(self, persona_id: str) -> List[Dict]:
        """获取某 Persona 关联的所有股票"""
        persona_node_id = make_node_id("persona", persona_id)
        edges = self.store.get_edges(target_id=persona_node_id, edge_type=EdgeType.ANALYZED_BY.value)
        result = []
        for e in edges:
            node = self.store.get_node(e.source_id)
            if node:
                result.append({
                    "stock": node.to_dict(),
                    "edge": e.to_dict(),
                })
        return result

    def add_persona_recommendation(
        self,
        persona_id: str,
        symbol: str,
        score: float = 0.0,
        reason: str = "",
    ) -> GraphEdge:
        """Persona 推荐某只股票"""
        persona_node_id = make_node_id("persona", persona_id)
        stock_node_id = make_node_id("stock", symbol.upper())
        return self._ensure_edge(
            persona_node_id, stock_node_id,
            EdgeType.RECOMMENDS.value,
            weight=score,
            properties={"reason": reason},
        )

    # ========================================
    # 图谱数据获取 (Graph Data Retrieval)
    # ========================================

    def get_stocks_graph(self, limit: int = 200) -> GraphData:
        """获取标的维度的2D平面图谱数据"""
        data = self.store.get_graph_data(dimension=Dimension.STOCKS.value, limit=limit)
        self._apply_2d_layout(data)
        return data

    def get_personas_graph(self, limit: int = 200) -> GraphData:
        """获取 Persona 维度的2D平面图谱数据"""
        data = self.store.get_graph_data(dimension=Dimension.PERSONAS.value, limit=limit)
        self._apply_2d_layout(data)
        return data

    def get_cross_graph(self, limit: int = 300) -> GraphData:
        """获取跨维度3D立体图谱数据"""
        # 获取两个维度的全部节点
        stock_nodes = self.store.list_nodes(dimension=Dimension.STOCKS.value, limit=limit)
        persona_nodes = self.store.list_nodes(dimension=Dimension.PERSONAS.value, limit=limit)
        all_nodes = stock_nodes + persona_nodes
        node_ids = {n.id for n in all_nodes}

        if not node_ids:
            return GraphData(dimension="cross")

        # 获取所有节点间的边
        placeholders = ",".join("?" * len(node_ids))
        ids = list(node_ids)
        conn = self.store._get_conn()
        rows = conn.execute(f"""
            SELECT * FROM graph_edges
            WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})
            LIMIT ?
        """, ids + ids + [limit * 5]).fetchall()
        edges = [self.store._row_to_edge(r) for r in rows]
        # Filter to edges where both endpoints are in our node set
        edges = [e for e in edges if e.source_id in node_ids and e.target_id in node_ids]

        stats = {}
        for n in all_nodes:
            t = n.node_type
            stats[t] = stats.get(t, 0) + 1

        data = GraphData(
            nodes=[n.to_dict() for n in all_nodes],
            edges=[e.to_dict() for e in edges],
            dimension="cross",
            stats=stats,
        )
        self._apply_3d_layout(data)
        return data

    def get_ego_graph(self, node_id: str, depth: int = 2) -> GraphData:
        """以某节点为中心展开的邻域图"""
        data = self.store.get_graph_data(center_node_id=node_id, max_depth=depth)
        self._apply_3d_layout(data)
        return data

    # ========================================
    # Graph RAG 上下文构建
    # ========================================

    def build_rag_context(self, symbol: str, persona_id: Optional[str] = None) -> str:
        """为 Graph RAG 构建知识上下文"""
        stock_id = make_node_id("stock", symbol.upper())
        stock_node = self.store.get_node(stock_id)
        if not stock_node:
            return f"Stock {symbol} not found in graph."

        lines = [f"## Stock: {stock_node.label} ({symbol.upper()})"]

        # 属性
        props = stock_node.properties
        if props.get("market"):
            lines.append(f"- Market: {props['market']}")
        if props.get("sector"):
            lines.append(f"- Sector: {props['sector']}")

        # 邻居信息
        neighbors = self.store.get_neighbors(stock_id)
        tags = [n for n, e in neighbors if n.node_type == NodeType.TAG.value]
        groups = [n for n, e in neighbors if n.node_type == NodeType.GROUP.value]
        personas = [n for n, e in neighbors if n.node_type == NodeType.PERSONA.value]
        correlated = [n for n, e in neighbors if n.node_type == NodeType.STOCK.value]

        if tags:
            lines.append(f"- Tags: {', '.join(t.label for t in tags)}")
        if groups:
            lines.append(f"- Groups: {', '.join(g.label for g in groups)}")
        if correlated:
            lines.append(f"- Correlated stocks: {', '.join(c.label for c in correlated)}")

        # Persona 信息
        if personas:
            lines.append("\n### Assigned Personas:")
            for p in personas:
                lines.append(f"- **{p.label}**: {p.properties.get('description', '')}")
                # 获取该 Persona 的策略
                strategies = self.get_persona_strategies(p.properties.get("persona_id", ""))
                if strategies:
                    lines.append(f"  Strategies: {', '.join(s.label for s in strategies)}")

        # 如果指定了 Persona，添加该 Persona 详细信息
        if persona_id:
            p_node = self.store.get_node(make_node_id("persona", persona_id))
            if p_node:
                lines.append(f"\n### Active Persona: {p_node.label}")
                lines.append(f"  {p_node.properties.get('description', '')}")

        return "\n".join(lines)

    # ========================================
    # 布局算法
    # ========================================

    def _apply_2d_layout(self, data: GraphData):
        """力导向 2D 布局 (简化版)"""
        nodes = data.nodes
        if not nodes:
            return

        # 按类型分组布局
        type_groups: Dict[str, list] = {}
        for n in nodes:
            t = n.get("node_type", "unknown")
            type_groups.setdefault(t, []).append(n)

        angle_step = 2 * math.pi / max(len(type_groups), 1)
        for i, (ntype, group_nodes) in enumerate(type_groups.items()):
            cx = math.cos(angle_step * i) * 300
            cy = math.sin(angle_step * i) * 300
            r = 50 + len(group_nodes) * 15
            for j, n in enumerate(group_nodes):
                theta = 2 * math.pi * j / max(len(group_nodes), 1)
                n["x"] = cx + r * math.cos(theta) + random.uniform(-10, 10)
                n["y"] = cy + r * math.sin(theta) + random.uniform(-10, 10)
                n["z"] = 0

    def _apply_3d_layout(self, data: GraphData):
        """3D 空间布局 - 标的和 Persona 在不同平面"""
        nodes = data.nodes
        if not nodes:
            return

        stock_nodes = [n for n in nodes if n.get("dimension") == Dimension.STOCKS.value]
        persona_nodes = [n for n in nodes if n.get("dimension") == Dimension.PERSONAS.value]

        # 标的维度在 z=0 平面
        self._layout_circle(stock_nodes, z=0, radius=400)
        # Persona 维度在 z=300 平面
        self._layout_circle(persona_nodes, z=300, radius=300)

    def _layout_circle(self, nodes: list, z: float, radius: float):
        """环形布局"""
        n = len(nodes)
        if n == 0:
            return
        for i, node in enumerate(nodes):
            theta = 2 * math.pi * i / n
            node["x"] = radius * math.cos(theta) + random.uniform(-20, 20)
            node["y"] = radius * math.sin(theta) + random.uniform(-20, 20)
            node["z"] = z + random.uniform(-10, 10)

    # ========================================
    # 内部辅助
    # ========================================

    def _ensure_market_node(self, market: str) -> GraphNode:
        node_id = make_node_id("market", market.upper())
        existing = self.store.get_node(node_id)
        if existing:
            return existing
        node = GraphNode(
            id=node_id,
            node_type=NodeType.MARKET.value,
            label=market.upper(),
            dimension=Dimension.STOCKS.value,
        )
        return self.store.upsert_node(node)

    def _ensure_sector_node(self, sector: str) -> GraphNode:
        node_id = make_node_id("sector", sector)
        existing = self.store.get_node(node_id)
        if existing:
            return existing
        node = GraphNode(
            id=node_id,
            node_type=NodeType.SECTOR.value,
            label=sector,
            dimension=Dimension.STOCKS.value,
        )
        return self.store.upsert_node(node)

    def _ensure_tag_node(self, tag: str) -> GraphNode:
        node_id = make_node_id("tag", tag)
        existing = self.store.get_node(node_id)
        if existing:
            return existing
        node = GraphNode(
            id=node_id,
            node_type=NodeType.TAG.value,
            label=tag,
            dimension=Dimension.STOCKS.value,
        )
        return self.store.upsert_node(node)

    def _ensure_group_node(self, name: str) -> GraphNode:
        node_id = make_node_id("group", name)
        existing = self.store.get_node(node_id)
        if existing:
            return existing
        node = GraphNode(
            id=node_id,
            node_type=NodeType.GROUP.value,
            label=name,
            dimension=Dimension.STOCKS.value,
        )
        return self.store.upsert_node(node)

    def _ensure_strategy_node(self, strategy_id: str) -> GraphNode:
        node_id = make_node_id("strategy", strategy_id)
        existing = self.store.get_node(node_id)
        if existing:
            return existing
        node = GraphNode(
            id=node_id,
            node_type=NodeType.STRATEGY.value,
            label=strategy_id,
            dimension=Dimension.PERSONAS.value,
        )
        return self.store.upsert_node(node)

    def _ensure_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        weight: float = 1.0,
        properties: Optional[Dict] = None,
    ) -> GraphEdge:
        existing = self.store.get_edges(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
        )
        if existing:
            return existing[0]
        edge = GraphEdge(
            id=make_edge_id(),
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            weight=weight,
            properties=properties or {},
        )
        return self.store.upsert_edge(edge)
