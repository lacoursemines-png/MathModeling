"""资源感知原始节点拓扑序生成器与局部移动。"""

from __future__ import annotations

import heapq
from collections import defaultdict, deque

from problem2.model import Graph


SUPPORTED_STRATEGIES = frozenset(
    {"critical_path", "earliest_finish", "pipe_balance", "memory_controlled", "hybrid"}
)


def _topological_order(graph: Graph) -> tuple[int, ...]:
    indegree = {node_id: 0 for node_id in graph.nodes}
    for _, target in graph.original_edges:
        indegree[target] += 1
    ready = [node_id for node_id, value in indegree.items() if value == 0]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        node_id = heapq.heappop(ready)
        order.append(node_id)
        for target in graph.original_successors[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    if len(order) != graph.node_count:
        raise ValueError("原始图不是DAG")
    return tuple(order)


def remaining_critical_lengths(graph: Graph) -> dict[int, int]:
    order = _topological_order(graph)
    values: dict[int, int] = {}
    for node_id in reversed(order):
        node = graph.nodes[node_id]
        tail = max((values[target] for target in graph.original_successors[node_id]), default=0)
        values[node_id] = node.cycles + tail
    return values


def generate_resource_aware_schedule(
    graph: Graph,
    reference_schedule: tuple[int, ...],
    strategy: str,
) -> tuple[int, ...]:
    if strategy not in SUPPORTED_STRATEGIES:
        raise ValueError(f"未知调度策略：{strategy}")
    rank = {node_id: index for index, node_id in enumerate(reference_schedule)}
    predecessors: dict[int, list[int]] = {node_id: [] for node_id in graph.nodes}
    indegree = {node_id: 0 for node_id in graph.nodes}
    for source, target in graph.original_edges:
        predecessors[target].append(source)
        indegree[target] += 1
    remaining = remaining_critical_lengths(graph)
    estimated_finish: dict[int, int] = {}
    pipe_available: dict[str, int] = defaultdict(int)
    pipe_total_cycles: dict[str, int] = defaultdict(int)
    for node in graph.nodes.values():
        if node.pipe:
            pipe_total_cycles[node.pipe] += node.cycles
    result: list[int] = []

    def metrics(node_id: int):
        node = graph.nodes[node_id]
        dependency_ready = max((estimated_finish[p] for p in predecessors[node_id]), default=0)
        # 优先级只使用节点进入ready时已经确定的前驱完成时刻，避免就绪集合
        # 随Pipe状态反复全量重排。真正的估计完成时刻仍按资源可用时刻更新。
        est = dependency_ready
        eft = dependency_ready + node.cycles
        if node.is_free:
            kind = 0
            memory_delta = -(node.size or 0)
        elif node.is_operation:
            kind = 1
            memory_delta = 0
        else:
            kind = 2
            memory_delta = node.size or 0
        return node, est, eft, kind, memory_delta

    def key(node_id: int):
        node, est, eft, kind, memory_delta = metrics(node_id)
        pipe_load = pipe_total_cycles[node.pipe] if node.pipe else 0
        if strategy == "critical_path":
            return -remaining[node_id], eft, kind, rank[node_id], node_id
        if strategy == "earliest_finish":
            return eft, -remaining[node_id], kind, rank[node_id], node_id
        if strategy == "pipe_balance":
            return kind if kind != 1 else 1, -pipe_load, eft, -remaining[node_id], rank[node_id]
        if strategy == "memory_controlled":
            return kind, memory_delta, -remaining[node_id], eft, rank[node_id]
        return kind if kind == 0 else 1, eft, -remaining[node_id], -pipe_load, rank[node_id]

    ready_heap: list[tuple[tuple[int, ...], int]] = []
    for node_id, degree in indegree.items():
        if degree == 0:
            heapq.heappush(ready_heap, (key(node_id), node_id))

    while ready_heap:
        _, node_id = heapq.heappop(ready_heap)
        node, dependency_ready, _, _, _ = metrics(node_id)
        actual_start = (
            max(dependency_ready, pipe_available[node.pipe])
            if node.pipe
            else dependency_ready
        )
        estimated_finish[node_id] = actual_start + node.cycles
        if node.pipe:
            pipe_available[node.pipe] = estimated_finish[node_id]
        result.append(node_id)
        for target in graph.original_successors[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready_heap, (key(target), target))
    if len(result) != graph.node_count:
        raise RuntimeError("资源感知列表调度未生成完整拓扑序")
    return tuple(result)


def local_earlier_moves(
    graph: Graph,
    schedule: tuple[int, ...],
    preferred_nodes: tuple[int, ...],
    window: int,
    limit: int,
) -> tuple[tuple[int, ...], ...]:
    predecessors: dict[int, list[int]] = {node_id: [] for node_id in graph.nodes}
    for source, target in graph.original_edges:
        predecessors[target].append(source)
    generated: list[tuple[int, ...]] = []
    seen = {schedule}
    position = {value: index for index, value in enumerate(schedule)}
    for node_id in preferred_nodes:
        if node_id not in graph.nodes:
            continue
        old = position[node_id]
        earliest = max((position[pred] + 1 for pred in predecessors[node_id]), default=0)
        new = max(earliest, old - window)
        if new >= old:
            continue
        values = list(schedule)
        values.pop(old)
        values.insert(new, node_id)
        candidate = tuple(values)
        if candidate not in seen:
            seen.add(candidate)
            generated.append(candidate)
            if len(generated) >= limit:
                break
    return tuple(generated)
