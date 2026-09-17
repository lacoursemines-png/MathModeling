"""第一问的多策略Kahn调度和峰值窗口局部改进。"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .evaluator import EvaluationResult, compute_peak, validate_problem1
from .model import Graph, L0_TYPES, PEAK_TYPES, Node


DEFAULT_STRATEGIES = (
    "id",
    "min_growth",
    "free_first",
    "lifecycle",
    "unlock_free",
    "l0_close",
)


@dataclass(slots=True)
class _ScheduleState:
    resident: set[int]
    l0_resident: dict[str, int | None]
    current_memory: int
    peak: int

    @classmethod
    def empty(cls) -> "_ScheduleState":
        return cls(set(), {memory_type: None for memory_type in L0_TYPES}, 0, 0)

    def copy(self) -> "_ScheduleState":
        return _ScheduleState(
            set(self.resident), dict(self.l0_resident), self.current_memory, self.peak
        )


@dataclass(frozen=True, slots=True)
class StrategyRun:
    strategy: str
    success: bool
    schedule: tuple[int, ...]
    peak: int | None
    runtime_seconds: float
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    schedule: tuple[int, ...]
    evaluation: EvaluationResult
    selected_strategy: str
    strategy_runs: tuple[StrategyRun, ...]
    local_improvements: int
    runtime_seconds: float


def _can_execute(node: Node, state: _ScheduleState) -> bool:
    if node.is_alloc:
        assert node.buf_id is not None and node.memory_type is not None
        if node.buf_id in state.resident:
            return False
        if node.memory_type in L0_TYPES and state.l0_resident[node.memory_type] is not None:
            return False
        return True
    if node.is_free:
        assert node.buf_id is not None
        return node.buf_id in state.resident
    return all(buf_id in state.resident for buf_id in node.bufs)


def _execute(node: Node, state: _ScheduleState) -> None:
    if node.is_alloc:
        assert node.buf_id is not None and node.memory_type is not None and node.size is not None
        state.resident.add(node.buf_id)
        if node.memory_type in L0_TYPES:
            state.l0_resident[node.memory_type] = node.buf_id
        if node.memory_type in PEAK_TYPES:
            state.current_memory += node.size
            state.peak = max(state.peak, state.current_memory)
    elif node.is_free:
        assert node.buf_id is not None and node.memory_type is not None and node.size is not None
        state.resident.remove(node.buf_id)
        if node.memory_type in L0_TYPES:
            state.l0_resident[node.memory_type] = None
        if node.memory_type in PEAK_TYPES:
            state.current_memory -= node.size


def _memory_delta(node: Node) -> int:
    if node.memory_type not in PEAK_TYPES or node.size is None:
        return 0
    if node.is_alloc:
        return node.size
    if node.is_free:
        return -node.size
    return 0


def _reverse_depth(graph: Graph) -> dict[int, int]:
    depth = {node_id: 0 for node_id in graph.nodes}
    for node_id in reversed(graph.topological_order):
        successors = graph.schedule_successors[node_id]
        if successors:
            depth[node_id] = 1 + max(depth[nxt] for nxt in successors)
    return depth


def _build_key_functions(graph: Graph) -> dict[str, Callable[[int], tuple[int, ...]]]:
    depth = _reverse_depth(graph)
    free_unlock_size: dict[int, int] = {}
    free_unlock_count: dict[int, int] = {}
    for node_id, successors in graph.schedule_successors.items():
        free_nodes = [graph.nodes[nxt] for nxt in successors if graph.nodes[nxt].is_free]
        free_unlock_size[node_id] = sum(
            node.size or 0 for node in free_nodes if node.memory_type in PEAK_TYPES
        )
        free_unlock_count[node_id] = len(free_nodes)

    def kind_rank(node: Node) -> int:
        if node.is_free:
            return 0
        if not node.is_management:
            return 1
        return 2

    def id_key(node_id: int) -> tuple[int, ...]:
        return (node_id,)

    def min_growth(node_id: int) -> tuple[int, ...]:
        node = graph.nodes[node_id]
        delta = _memory_delta(node)
        return (max(delta, 0), delta, kind_rank(node), node_id)

    def free_first(node_id: int) -> tuple[int, ...]:
        node = graph.nodes[node_id]
        released = -_memory_delta(node) if node.is_free else 0
        return (kind_rank(node), -released, max(_memory_delta(node), 0), node_id)

    def lifecycle(node_id: int) -> tuple[int, ...]:
        node = graph.nodes[node_id]
        if node.is_free:
            rank = 0
        elif not node.is_management and free_unlock_count[node_id] > 0:
            rank = 1
        elif not node.is_management:
            rank = 2
        else:
            rank = 3
        return (rank, -free_unlock_size[node_id], -free_unlock_count[node_id], node_id)

    def unlock_free(node_id: int) -> tuple[int, ...]:
        node = graph.nodes[node_id]
        return (
            -free_unlock_size[node_id],
            -free_unlock_count[node_id],
            kind_rank(node),
            -len(graph.schedule_successors[node_id]),
            node_id,
        )

    def l0_close(node_id: int) -> tuple[int, ...]:
        node = graph.nodes[node_id]
        uses_l0 = any(graph.buffers[buf_id].memory_type in L0_TYPES for buf_id in node.bufs)
        if node.is_free and node.memory_type in L0_TYPES:
            rank = 0
        elif not node.is_management and uses_l0:
            rank = 1
        elif node.is_free:
            rank = 2
        elif not node.is_management:
            rank = 3
        elif node.is_alloc and node.memory_type not in L0_TYPES:
            rank = 4
        else:
            rank = 5
        return (rank, -free_unlock_size[node_id], -depth[node_id], node_id)

    return {
        "id": id_key,
        "min_growth": min_growth,
        "free_first": free_first,
        "lifecycle": lifecycle,
        "unlock_free": unlock_free,
        "l0_close": l0_close,
    }


def _schedule_nodes(
    graph: Graph,
    node_ids: set[int],
    initial_state: _ScheduleState,
    key: Callable[[int], tuple[int, ...]],
) -> tuple[tuple[int, ...] | None, str | None]:
    """对全图或一个连续窗口内的节点做Kahn调度。"""

    indegree = {node_id: 0 for node_id in node_ids}
    for source in node_ids:
        for target in graph.schedule_successors[source]:
            if target in node_ids:
                indegree[target] += 1

    # L0 ALLOC在对应L0仍被占用时只是“暂不可执行”，不是拓扑未就绪。
    # 若把它们和普通节点放在同一个堆中，每一步都可能反复弹出大量被阻塞的
    # L0 ALLOC，最坏会退化为平方复杂度。这里为三类L0申请分别维护堆；
    # 只有对应槽位为空时，该堆顶部才参与本轮候选比较。
    ready_regular: list[tuple[tuple[int, ...], int]] = []
    ready_l0_alloc: dict[str, list[tuple[tuple[int, ...], int]]] = {
        memory_type: [] for memory_type in L0_TYPES
    }

    def enqueue(node_id: int) -> None:
        node = graph.nodes[node_id]
        entry = (key(node_id), node_id)
        if node.is_alloc and node.memory_type in L0_TYPES:
            assert node.memory_type is not None
            heapq.heappush(ready_l0_alloc[node.memory_type], entry)
        else:
            heapq.heappush(ready_regular, entry)

    for node_id, value in indegree.items():
        if value == 0:
            enqueue(node_id)
    state = initial_state.copy()
    schedule: list[int] = []

    while len(schedule) < len(node_ids):
        candidates: list[tuple[tuple[int, ...], int, str | None]] = []
        if ready_regular:
            entry = ready_regular[0]
            candidates.append((entry[0], entry[1], None))
        for memory_type, heap in ready_l0_alloc.items():
            if state.l0_resident[memory_type] is None and heap:
                entry = heap[0]
                candidates.append((entry[0], entry[1], memory_type))

        if not candidates:
            blocked_ids = sorted(
                node_id
                for heap in ready_l0_alloc.values()
                for _, node_id in heap
            )[:20]
            if blocked_ids:
                return None, (
                    "存在拓扑就绪节点，但均为当前L0槽位阻塞的ALLOC："
                    f"{blocked_ids}"
                )
            remaining = sorted(node_ids - set(schedule))[:20]
            return None, f"增强DAG未能继续调度，剩余节点：{remaining}"

        _, chosen, source_type = min(candidates)
        if source_type is None:
            heapq.heappop(ready_regular)
        else:
            heapq.heappop(ready_l0_alloc[source_type])
        if not _can_execute(graph.nodes[chosen], state):
            return None, f"内部状态异常：拓扑就绪节点{chosen}不满足驻留语义"

        schedule.append(chosen)
        _execute(graph.nodes[chosen], state)
        for target in graph.schedule_successors[chosen]:
            if target not in indegree:
                continue
            indegree[target] -= 1
            if indegree[target] == 0:
                enqueue(target)

    if len(schedule) != len(node_ids):
        remaining = sorted(node_ids - set(schedule))[:20]
        return None, f"增强DAG未能完成调度，剩余节点：{remaining}"
    return tuple(schedule), None


def _replay_prefix(graph: Graph, schedule: Sequence[int]) -> _ScheduleState:
    state = _ScheduleState.empty()
    for node_id in schedule:
        node = graph.nodes[node_id]
        if not _can_execute(node, state):
            raise ValueError(f"内部错误：前缀回放到节点{node_id}时状态非法")
        _execute(node, state)
    return state


def _profile_signature(evaluation: EvaluationResult) -> tuple[int, ...]:
    """峰值相同时，用完整降序驻留剖面比较“次峰值”。"""

    return tuple(sorted(evaluation.trace, reverse=True))


def _improve_peak_window(
    graph: Graph,
    schedule: tuple[int, ...],
    key_functions: dict[str, Callable[[int], tuple[int, ...]]],
    radius: int,
    passes: int,
) -> tuple[tuple[int, ...], EvaluationResult, int]:
    current_schedule = schedule
    current_eval = compute_peak(graph, current_schedule)
    improvements = 0
    if radius <= 0 or passes <= 0:
        return current_schedule, current_eval, improvements

    local_strategies = ("min_growth", "free_first", "lifecycle", "unlock_free", "l0_close")
    for _ in range(passes):
        center = max(0, current_eval.first_peak_position - 1)
        start = max(0, center - radius)
        end = min(graph.node_count, center + radius + 1)
        if end - start < 2:
            break
        prefix = current_schedule[:start]
        window = current_schedule[start:end]
        suffix = current_schedule[end:]
        initial_state = _replay_prefix(graph, prefix)
        best_schedule = current_schedule
        best_eval = current_eval
        best_signature = _profile_signature(current_eval)

        for strategy in local_strategies:
            new_window, _ = _schedule_nodes(
                graph, set(window), initial_state, key_functions[strategy]
            )
            if new_window is None or new_window == window:
                continue
            candidate = tuple(prefix) + new_window + tuple(suffix)
            validation = validate_problem1(graph, candidate)
            if not validation.valid:
                continue
            candidate_eval = compute_peak(graph, candidate)
            candidate_signature = _profile_signature(candidate_eval)
            if candidate_signature < best_signature:
                best_schedule = candidate
                best_eval = candidate_eval
                best_signature = candidate_signature

        if best_schedule == current_schedule:
            break
        current_schedule = best_schedule
        current_eval = best_eval
        improvements += 1

    return current_schedule, current_eval, improvements


def solve_problem1(
    graph: Graph,
    strategies: Iterable[str] = DEFAULT_STRATEGIES,
    *,
    local_window_radius: int = 100,
    local_passes: int = 2,
) -> SearchResult:
    """运行多种确定性策略，统一验证后选择峰值最小的合法结果。"""

    started = time.perf_counter()
    strategy_names = tuple(dict.fromkeys(strategies))
    if not strategy_names:
        raise ValueError("至少需要指定一种调度策略")
    key_functions = _build_key_functions(graph)
    unknown = sorted(set(strategy_names) - set(key_functions))
    if unknown:
        raise ValueError(f"未知策略：{unknown}；可用策略={sorted(key_functions)}")

    runs: list[StrategyRun] = []
    best_schedule: tuple[int, ...] | None = None
    best_eval: EvaluationResult | None = None
    best_strategy: str | None = None
    best_signature: tuple[int, ...] | None = None

    all_nodes = set(graph.nodes)
    for strategy in strategy_names:
        run_started = time.perf_counter()
        schedule, failure = _schedule_nodes(
            graph, all_nodes, _ScheduleState.empty(), key_functions[strategy]
        )
        runtime = time.perf_counter() - run_started
        if schedule is None:
            runs.append(StrategyRun(strategy, False, (), None, runtime, failure))
            continue
        validation = validate_problem1(graph, schedule)
        if not validation.valid:
            reason = "；".join(validation.errors[:5])
            runs.append(StrategyRun(strategy, False, schedule, None, runtime, reason))
            continue
        evaluation = compute_peak(graph, schedule)
        signature = _profile_signature(evaluation)
        runs.append(StrategyRun(strategy, True, schedule, evaluation.peak, runtime))
        if best_signature is None or signature < best_signature:
            best_schedule = schedule
            best_eval = evaluation
            best_strategy = strategy
            best_signature = signature

    if best_schedule is None or best_eval is None or best_strategy is None:
        reasons = "; ".join(
            f"{run.strategy}: {run.failure_reason}" for run in runs if not run.success
        )
        raise RuntimeError(f"所有第一问策略都未产生合法完整序列。{reasons}")

    improved_schedule, improved_eval, improvement_count = _improve_peak_window(
        graph,
        best_schedule,
        key_functions,
        local_window_radius,
        local_passes,
    )
    final_validation = validate_problem1(graph, improved_schedule)
    final_validation.require_valid()
    return SearchResult(
        schedule=improved_schedule,
        evaluation=improved_eval,
        selected_strategy=best_strategy,
        strategy_runs=tuple(runs),
        local_improvements=improvement_count,
        runtime_seconds=time.perf_counter() - started,
    )
