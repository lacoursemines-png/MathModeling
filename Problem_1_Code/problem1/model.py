"""第一问使用的只读数据对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


MANAGEMENT_OPS = frozenset({"ALLOC", "FREE"})
L0_TYPES = frozenset({"L0A", "L0B", "L0C"})
PEAK_TYPES = frozenset({"L1", "UB"})
MEMORY_TYPES = frozenset({"L1", "UB", "L0A", "L0B", "L0C"})


@dataclass(frozen=True, slots=True)
class Node:
    """标准化后的节点。缓存管理节点和普通操作节点共用同一结构。"""

    id: int
    op: str
    buf_id: int | None = None
    size: int | None = None
    memory_type: str | None = None
    pipe: str | None = None
    cycles: int = 0
    bufs: tuple[int, ...] = ()

    @property
    def is_alloc(self) -> bool:
        return self.op == "ALLOC"

    @property
    def is_free(self) -> bool:
        return self.op == "FREE"

    @property
    def is_management(self) -> bool:
        return self.op in MANAGEMENT_OPS


@dataclass(frozen=True, slots=True)
class Buffer:
    """由ALLOC/FREE节点和普通操作的Bufs字段派生出的缓冲区信息。"""

    id: int
    size: int
    memory_type: str
    alloc_node: int
    free_node: int
    use_nodes: tuple[int, ...]
    from_copy_in: bool


@dataclass(frozen=True, slots=True)
class Graph:
    """原图及第一问调度使用的增强DAG。"""

    name: str
    nodes: Mapping[int, Node]
    buffers: Mapping[int, Buffer]
    original_edges: tuple[tuple[int, int], ...]
    original_successors: Mapping[int, tuple[int, ...]]
    # 增强边 = 原始边 + ALLOC->使用/FREE + 使用->FREE。
    schedule_edges: tuple[tuple[int, int], ...]
    schedule_successors: Mapping[int, tuple[int, ...]]
    schedule_indegree: Mapping[int, int]
    topological_order: tuple[int, ...]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.original_edges)
