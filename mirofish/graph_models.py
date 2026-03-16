# -*- coding: utf-8 -*-
"""
===================================
薯条交易 - Graph Data Models
===================================

两大维度的图谱数据模型：
1. 标的维度 (Stocks Dimension) - 股票标的，支持 tag 群组层级
2. Persona 维度 (Personas Dimension) - 交易分析人格/策略

两个维度之间通过关系边(Edge)连接，支持：
- 2D 平面图谱展示
- 3D 立体空间图谱展示
- Graph RAG 知识检索
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ========================================
# 枚举定义
# ========================================

class NodeType(str, Enum):
    """图谱节点类型"""
    STOCK = "stock"              # 股票标的
    TAG = "tag"                  # 标签
    GROUP = "group"              # 群组
    SECTOR = "sector"            # 行业板块
    PERSONA = "persona"          # 交易人格
    STRATEGY = "strategy"        # 交易策略
    MARKET = "market"            # 市场 (US/CN/HK)


class EdgeType(str, Enum):
    """图谱边类型"""
    BELONGS_TO = "belongs_to"          # 股票 → 群组/标签
    TAGGED_WITH = "tagged_with"        # 股票 → 标签
    IN_SECTOR = "in_sector"            # 股票 → 行业
    IN_MARKET = "in_market"            # 股票 → 市场
    ANALYZED_BY = "analyzed_by"        # 股票 → Persona 分析关系
    CORRELATED = "correlated"          # 股票 → 股票 相关性
    PARENT_OF = "parent_of"            # 群组层级关系
    USES_STRATEGY = "uses_strategy"    # Persona → Strategy
    SIMILAR_TO = "similar_to"          # Persona → Persona 相似性
    RECOMMENDS = "recommends"          # Persona → 股票 推荐关系


class Dimension(str, Enum):
    """维度"""
    STOCKS = "stocks"
    PERSONAS = "personas"
    CROSS = "cross"   # 跨维度


# ========================================
# 数据类
# ========================================

@dataclass
class GraphNode:
    """图谱节点"""
    id: str
    node_type: str                      # NodeType value
    label: str                          # 显示名称
    dimension: str                      # 所属维度
    properties: Dict[str, Any] = field(default_factory=dict)
    # 可视化属性
    color: Optional[str] = None
    size: float = 1.0
    # 3D 坐标 (初始可为 None，由布局算法计算)
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    # 层级信息
    parent_id: Optional[str] = None
    depth: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        if isinstance(d.get("properties"), str):
            d["properties"] = json.loads(d["properties"])
        return d


@dataclass
class GraphEdge:
    """图谱边"""
    id: str
    source_id: str
    target_id: str
    edge_type: str                      # EdgeType value
    weight: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)
    label: Optional[str] = None
    created_at: Optional[str] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        if isinstance(d.get("properties"), str):
            d["properties"] = json.loads(d["properties"])
        return d


@dataclass
class GraphData:
    """完整图谱数据 - 用于前端渲染"""
    nodes: List[Dict] = field(default_factory=list)
    edges: List[Dict] = field(default_factory=list)
    # 元信息
    dimension: str = "cross"
    stats: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


# ========================================
# 颜色方案
# ========================================

NODE_COLORS = {
    NodeType.STOCK.value: "#53c1de",
    NodeType.TAG.value: "#f39c12",
    NodeType.GROUP.value: "#9b59b6",
    NodeType.SECTOR.value: "#2ecc71",
    NodeType.PERSONA.value: "#e94560",
    NodeType.STRATEGY.value: "#e67e22",
    NodeType.MARKET.value: "#1abc9c",
}

NODE_SIZES = {
    NodeType.STOCK.value: 1.0,
    NodeType.TAG.value: 0.8,
    NodeType.GROUP.value: 1.5,
    NodeType.SECTOR.value: 1.2,
    NodeType.PERSONA.value: 1.3,
    NodeType.STRATEGY.value: 1.0,
    NodeType.MARKET.value: 2.0,
}


# ========================================
# Graph Store (SQLite)
# ========================================

class GraphStore:
    """SQLite-based graph storage for 薯条交易"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: Optional[str] = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if self._initialized:
            return
        self._db_path = db_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "fries_graph.db"
        )
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._local = threading.local()
        self._init_db()
        self._initialized = True

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                label TEXT NOT NULL,
                dimension TEXT NOT NULL,
                properties TEXT DEFAULT '{}',
                color TEXT,
                size REAL DEFAULT 1.0,
                x REAL,
                y REAL,
                z REAL,
                parent_id TEXT,
                depth INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS graph_edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                properties TEXT DEFAULT '{}',
                label TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (source_id) REFERENCES graph_nodes(id) ON DELETE CASCADE,
                FOREIGN KEY (target_id) REFERENCES graph_nodes(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_type ON graph_nodes(node_type);
            CREATE INDEX IF NOT EXISTS idx_nodes_dimension ON graph_nodes(dimension);
            CREATE INDEX IF NOT EXISTS idx_nodes_parent ON graph_nodes(parent_id);
            CREATE INDEX IF NOT EXISTS idx_edges_source ON graph_edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON graph_edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_type ON graph_edges(edge_type);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique
                ON graph_edges(source_id, target_id, edge_type);
        """)
        conn.commit()

    # ---- Node CRUD ----

    def upsert_node(self, node: GraphNode) -> GraphNode:
        conn = self._get_conn()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        node.updated_at = now
        if not node.created_at:
            node.created_at = now
        if not node.color:
            node.color = NODE_COLORS.get(node.node_type, "#888")
        if node.size <= 0:
            node.size = NODE_SIZES.get(node.node_type, 1.0)
        props = json.dumps(node.properties, ensure_ascii=False) if isinstance(node.properties, dict) else node.properties
        conn.execute("""
            INSERT INTO graph_nodes (id, node_type, label, dimension, properties,
                                     color, size, x, y, z, parent_id, depth,
                                     created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                label=excluded.label,
                properties=excluded.properties,
                color=excluded.color,
                size=excluded.size,
                x=excluded.x, y=excluded.y, z=excluded.z,
                parent_id=excluded.parent_id,
                depth=excluded.depth,
                updated_at=excluded.updated_at
        """, (
            node.id, node.node_type, node.label, node.dimension,
            props, node.color, node.size,
            node.x, node.y, node.z,
            node.parent_id, node.depth,
            node.created_at, node.updated_at,
        ))
        conn.commit()
        return node

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        row = self._get_conn().execute(
            "SELECT * FROM graph_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return self._row_to_node(row) if row else None

    def list_nodes(
        self,
        dimension: Optional[str] = None,
        node_type: Optional[str] = None,
        parent_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[GraphNode]:
        sql = "SELECT * FROM graph_nodes WHERE 1=1"
        params: list = []
        if dimension:
            sql += " AND dimension = ?"
            params.append(dimension)
        if node_type:
            sql += " AND node_type = ?"
            params.append(node_type)
        if parent_id is not None:
            sql += " AND parent_id = ?"
            params.append(parent_id)
        sql += " ORDER BY depth, label LIMIT ?"
        params.append(limit)
        rows = self._get_conn().execute(sql, params).fetchall()
        return [self._row_to_node(r) for r in rows]

    def delete_node(self, node_id: str) -> int:
        conn = self._get_conn()
        # Cascade edges
        conn.execute("DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?",
                      (node_id, node_id))
        cur = conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
        conn.commit()
        return cur.rowcount

    def search_nodes(self, query: str, limit: int = 20) -> List[GraphNode]:
        rows = self._get_conn().execute(
            "SELECT * FROM graph_nodes WHERE label LIKE ? OR id LIKE ? LIMIT ?",
            (f"%{query}%", f"%{query}%", limit)
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    # ---- Edge CRUD ----

    def upsert_edge(self, edge: GraphEdge) -> GraphEdge:
        conn = self._get_conn()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if not edge.created_at:
            edge.created_at = now
        props = json.dumps(edge.properties, ensure_ascii=False) if isinstance(edge.properties, dict) else edge.properties
        conn.execute("""
            INSERT INTO graph_edges (id, source_id, target_id, edge_type, weight,
                                     properties, label, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, target_id, edge_type) DO UPDATE SET
                weight=excluded.weight,
                properties=excluded.properties,
                label=excluded.label
        """, (
            edge.id, edge.source_id, edge.target_id, edge.edge_type,
            edge.weight, props, edge.label, edge.created_at,
        ))
        conn.commit()
        return edge

    def get_edges(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        edge_type: Optional[str] = None,
        limit: int = 1000,
    ) -> List[GraphEdge]:
        sql = "SELECT * FROM graph_edges WHERE 1=1"
        params: list = []
        if source_id:
            sql += " AND source_id = ?"
            params.append(source_id)
        if target_id:
            sql += " AND target_id = ?"
            params.append(target_id)
        if edge_type:
            sql += " AND edge_type = ?"
            params.append(edge_type)
        sql += " LIMIT ?"
        params.append(limit)
        rows = self._get_conn().execute(sql, params).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def delete_edge(self, edge_id: str) -> int:
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM graph_edges WHERE id = ?", (edge_id,))
        conn.commit()
        return cur.rowcount

    # ---- Graph Queries ----

    def get_graph_data(
        self,
        dimension: Optional[str] = None,
        center_node_id: Optional[str] = None,
        max_depth: int = 2,
        limit: int = 200,
    ) -> GraphData:
        """获取图谱数据，支持按维度过滤或从中心节点展开"""
        if center_node_id:
            return self._get_ego_graph(center_node_id, max_depth, limit)

        nodes = self.list_nodes(dimension=dimension, limit=limit)
        node_ids = {n.id for n in nodes}

        # 获取这些节点之间的边
        if not node_ids:
            return GraphData(dimension=dimension or "cross")

        placeholders = ",".join("?" * len(node_ids))
        ids = list(node_ids)
        rows = self._get_conn().execute(f"""
            SELECT * FROM graph_edges
            WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})
            LIMIT ?
        """, ids + ids + [limit * 3]).fetchall()
        edges = [self._row_to_edge(r) for r in rows]

        stats = {}
        for n in nodes:
            t = n.node_type
            stats[t] = stats.get(t, 0) + 1

        return GraphData(
            nodes=[n.to_dict() for n in nodes],
            edges=[e.to_dict() for e in edges],
            dimension=dimension or "cross",
            stats=stats,
        )

    def _get_ego_graph(self, center_id: str, max_depth: int, limit: int) -> GraphData:
        """从中心节点展开获取邻域图"""
        visited_nodes: set = set()
        visited_edges: set = set()
        queue = [(center_id, 0)]
        all_nodes: List[GraphNode] = []
        all_edges: List[GraphEdge] = []

        while queue and len(all_nodes) < limit:
            node_id, depth = queue.pop(0)
            if node_id in visited_nodes:
                continue
            visited_nodes.add(node_id)

            node = self.get_node(node_id)
            if node:
                all_nodes.append(node)

            if depth >= max_depth:
                continue

            # Get connected edges
            rows = self._get_conn().execute("""
                SELECT * FROM graph_edges
                WHERE source_id = ? OR target_id = ?
            """, (node_id, node_id)).fetchall()

            for row in rows:
                edge = self._row_to_edge(row)
                if edge.id not in visited_edges:
                    visited_edges.add(edge.id)
                    all_edges.append(edge)
                    neighbor = edge.target_id if edge.source_id == node_id else edge.source_id
                    if neighbor not in visited_nodes:
                        queue.append((neighbor, depth + 1))

        stats = {}
        for n in all_nodes:
            t = n.node_type
            stats[t] = stats.get(t, 0) + 1

        return GraphData(
            nodes=[n.to_dict() for n in all_nodes],
            edges=[e.to_dict() for e in all_edges],
            dimension="cross",
            stats=stats,
        )

    def get_neighbors(self, node_id: str) -> List[Tuple[GraphNode, GraphEdge]]:
        """获取节点的所有邻居"""
        edges = self._get_conn().execute("""
            SELECT * FROM graph_edges WHERE source_id = ? OR target_id = ?
        """, (node_id, node_id)).fetchall()

        result = []
        for row in edges:
            edge = self._row_to_edge(row)
            neighbor_id = edge.target_id if edge.source_id == node_id else edge.source_id
            neighbor = self.get_node(neighbor_id)
            if neighbor:
                result.append((neighbor, edge))
        return result

    # ---- Helpers ----

    def _row_to_node(self, row) -> GraphNode:
        props = row["properties"]
        if isinstance(props, str):
            try:
                props = json.loads(props)
            except json.JSONDecodeError:
                props = {}
        return GraphNode(
            id=row["id"],
            node_type=row["node_type"],
            label=row["label"],
            dimension=row["dimension"],
            properties=props,
            color=row["color"],
            size=row["size"],
            x=row["x"],
            y=row["y"],
            z=row["z"],
            parent_id=row["parent_id"],
            depth=row["depth"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_edge(self, row) -> GraphEdge:
        props = row["properties"]
        if isinstance(props, str):
            try:
                props = json.loads(props)
            except json.JSONDecodeError:
                props = {}
        return GraphEdge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            edge_type=row["edge_type"],
            weight=row["weight"],
            properties=props,
            label=row["label"],
            created_at=row["created_at"],
        )


# ========================================
# Helper functions
# ========================================

def get_graph_store() -> GraphStore:
    """获取图谱存储单例"""
    return GraphStore()


def make_node_id(node_type: str, identifier: str) -> str:
    """生成确定性节点 ID"""
    return f"{node_type}:{identifier}"


def make_edge_id() -> str:
    """生成边 ID"""
    return str(uuid.uuid4())[:12]
