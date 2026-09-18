"""第三问确定性Pipe边与最长路时间评价器。"""

from __future__ import annotations

from collections import defaultdict

from problem2.model import Graph, Problem2Solution

from .model import TimingResult


def build_pipe_edges(solution: Problem2Solution) -> tuple[tuple[int, int], ...]:
    last: dict[str, int] = {}
    edges: list[tuple[int, int]] = []
    for node_id in solution.schedule:
        node = solution.extended_nodes[node_id]
        if not node.pipe:
            continue
        previous = last.get(node.pipe)
        if previous is not None:
            edges.append((previous, node_id))
        last[node.pipe] = node_id
    return tuple(edges)


def _longest_path(
    schedule: tuple[int, ...],
    nodes,
    edges: set[tuple[int, int]],
) -> tuple[dict[int, int], dict[int, int], dict[int, int | None], int]:
    position = {node_id: index for index, node_id in enumerate(schedule)}
    predecessors: dict[int, list[int]] = {node_id: [] for node_id in schedule}
    for source, target in edges:
        if source not in position or target not in position:
            raise ValueError(f"时间图依赖引用非法节点：{source}->{target}")
        if position[source] >= position[target]:
            raise ValueError(f"时间图依赖不满足提交顺序或形成环：{source}->{target}")
        predecessors[target].append(source)
    start: dict[int, int] = {}
    finish: dict[int, int] = {}
    critical_predecessor: dict[int, int | None] = {}
    for node_id in schedule:
        preds = predecessors[node_id]
        if not preds:
            start[node_id] = 0
            critical_predecessor[node_id] = None
        else:
            best_finish = max(finish[pred] for pred in preds)
            tied = [pred for pred in preds if finish[pred] == best_finish]
            start[node_id] = best_finish
            critical_predecessor[node_id] = min(tied)
        finish[node_id] = start[node_id] + nodes[node_id].cycles
    total = max(finish.values(), default=0)
    return start, finish, critical_predecessor, total


def evaluate_timing(graph: Graph, solution: Problem2Solution) -> TimingResult:
    pipe_edges = build_pipe_edges(solution)
    dependency_edges = set(graph.original_edges) | set(solution.spill_edges) | set(solution.reuse_edges)
    all_edges = dependency_edges | set(pipe_edges)
    start, finish, critical_predecessor, total = _longest_path(
        solution.schedule, solution.extended_nodes, all_edges
    )
    _, _, _, dependency_lb = _longest_path(
        solution.schedule, solution.extended_nodes, dependency_edges
    )

    successors: dict[int, list[int]] = {node_id: [] for node_id in solution.schedule}
    for source, target in all_edges:
        successors[source].append(target)
    latest_start: dict[int, int] = {}
    for node_id in reversed(solution.schedule):
        if successors[node_id]:
            latest_finish = min(latest_start[target] for target in successors[node_id])
        else:
            latest_finish = total
        latest_start[node_id] = latest_finish - solution.extended_nodes[node_id].cycles
    slack = {node_id: latest_start[node_id] - start[node_id] for node_id in solution.schedule}
    critical_nodes = frozenset(node_id for node_id, value in slack.items() if value == 0)

    if solution.schedule:
        end_candidates = [node_id for node_id in solution.schedule if finish[node_id] == total]
        current = min(end_candidates)
        path: list[int] = []
        while True:
            path.append(current)
            predecessor = critical_predecessor[current]
            if predecessor is None:
                break
            current = predecessor
        representative = tuple(reversed(path))
    else:
        representative = ()

    intervals: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    busy: dict[str, int] = defaultdict(int)
    for node_id in solution.schedule:
        node = solution.extended_nodes[node_id]
        if node.pipe:
            intervals[node.pipe].append((node_id, start[node_id], finish[node_id]))
            busy[node.pipe] += node.cycles
    utilization = {
        pipe: (cycles / total if total else 0.0) for pipe, cycles in sorted(busy.items())
    }
    pipe_lb = max(busy.values(), default=0)
    return TimingResult(
        total,
        start,
        finish,
        latest_start,
        slack,
        critical_predecessor,
        representative,
        critical_nodes,
        tuple(pipe_edges),
        tuple(sorted(all_edges)),
        {pipe: tuple(values) for pipe, values in sorted(intervals.items())},
        dict(sorted(busy.items())),
        utilization,
        dependency_lb,
        pipe_lb,
    )
