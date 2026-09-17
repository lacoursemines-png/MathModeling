"""第二问的无SPILL分配与失败驱动SPILL搜索。"""

from __future__ import annotations

import copy
import bisect
import heapq
import time
from dataclasses import dataclass

from .allocator import IntervalAllocator
from .model import (
    ActiveSegment,
    AllocationFailure,
    CAPACITIES,
    Graph,
    Node,
    Problem2Solution,
    ResidentSegment,
    SearchConfig,
    SpillEvent,
    WorkSpillEvent,
    WorkState,
    spill_cost,
    spill_cycles,
)


@dataclass(frozen=True, slots=True)
class SearchAttempt:
    allocation_strategy: str
    success: bool
    movement: int | None
    spill_count: int
    expanded_states: int
    runtime_seconds: float
    stop_reason: str
    failure: AllocationFailure | None = None


@dataclass(frozen=True, slots=True)
class SearchResult:
    solution: Problem2Solution
    attempts: tuple[SearchAttempt, ...]
    runtime_seconds: float


@dataclass(frozen=True, slots=True)
class ScheduleIndex:
    base_schedule: tuple[int, ...]
    rank: dict[int, int]
    deadlines_by_buf: dict[int, tuple[int, ...]]

    @classmethod
    def build(cls, graph: Graph, schedule: tuple[int, ...]) -> "ScheduleIndex":
        rank = {node_id: index for index, node_id in enumerate(schedule)}
        values: dict[int, list[int]] = {buf_id: [] for buf_id in graph.buffers}
        for index, node_id in enumerate(schedule):
            node = graph.nodes[node_id]
            if node.is_operation:
                for buf_id in node.bufs:
                    values[buf_id].append(index)
            elif node.is_free and node.buf_id is not None:
                values[node.buf_id].append(index)
        return cls(schedule, rank, {k: tuple(v) for k, v in values.items()})

    def progress_rank(self, state: WorkState) -> int:
        for index in range(state.index, len(state.schedule)):
            node_id = state.schedule[index]
            if node_id >= 0:
                return self.rank[node_id]
        return len(self.base_schedule)

    def next_deadline_rank(self, buf_id: int, progress: int) -> int | None:
        values = self.deadlines_by_buf[buf_id]
        index = bisect.bisect_left(values, progress)
        return values[index] if index < len(values) else None


def capacity_aware_topological_order(
    graph: Graph, reference_schedule: tuple[int, ...]
) -> tuple[int, ...]:
    """生成面向第二问的确定性拓扑序。

    FREE优先释放空间，已就绪的计算/搬运节点次之，ALLOC尽量延后；
    多个ALLOC同时就绪时，优先选择最接近解锁后继的节点。第一问序列仅
    作为完全并列时的稳定次序，不改动第一问文件。
    """
    rank = {node_id: index for index, node_id in enumerate(reference_schedule)}
    indegree = {node_id: 0 for node_id in graph.nodes}
    predecessors: dict[int, list[int]] = {node_id: [] for node_id in graph.nodes}
    for source, target in graph.original_edges:
        indegree[target] += 1
        predecessors[target].append(source)
    result: list[int] = []

    def key(node_id: int) -> tuple[int, int, int, int]:
        node = graph.nodes[node_id]
        if node.is_free:
            kind = 0
        elif node.is_operation:
            kind = 1
        else:
            kind = 2
        successors = graph.original_successors[node_id]
        unlock_distance = min(
            (indegree[target] - 1 for target in successors), default=10**9
        )
        successor_rank = min((rank[target] for target in successors), default=10**9)
        return kind, unlock_distance, successor_rank, rank[node_id]

    ready_set = {node_id for node_id, degree in indegree.items() if degree == 0}
    ready_heap = [(*key(node_id), node_id) for node_id in ready_set]
    heapq.heapify(ready_heap)
    while ready_set:
        while True:
            *stored_key, node_id = heapq.heappop(ready_heap)
            if node_id in ready_set and tuple(stored_key) == key(node_id):
                break
        ready_set.remove(node_id)
        result.append(node_id)
        for target in graph.original_successors[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready_set.add(target)
                heapq.heappush(ready_heap, (*key(target), target))
            # target剩余前驱数改变后，仍在ready中的其他前驱优先级可能提高。
            for predecessor in predecessors[target]:
                if predecessor in ready_set:
                    heapq.heappush(ready_heap, (*key(predecessor), predecessor))
    if len(result) != graph.node_count:
        raise RuntimeError("容量感知拓扑排序失败：原始图可能存在环")
    return tuple(result)


def _node_for(state: WorkState, graph: Graph, node_id: int) -> Node:
    return graph.nodes[node_id] if node_id >= 0 else state.temp_nodes[node_id]


def _new_state(graph: Graph, original_schedule: tuple[int, ...]) -> WorkState:
    return WorkState(
        schedule=list(original_schedule),
        temp_nodes={},
        index=0,
        allocators={name: IntervalAllocator.empty(capacity) for name, capacity in CAPACITIES.items()},
        resident={},
        ddr=set(),
        initial_offsets={},
        events=[],
        movement=0,
        next_serial=1,
    )


def _clone_state(state: WorkState) -> WorkState:
    return WorkState(
        schedule=list(state.schedule),
        temp_nodes=dict(state.temp_nodes),
        index=state.index,
        allocators={name: allocator.clone() for name, allocator in state.allocators.items()},
        resident={buf_id: copy.copy(segment) for buf_id, segment in state.resident.items()},
        ddr=set(state.ddr),
        initial_offsets=dict(state.initial_offsets),
        events=[copy.copy(event) for event in state.events],
        movement=state.movement,
        next_serial=state.next_serial,
        segment_counts=dict(state.segment_counts),
        failure_history=list(state.failure_history),
    )


def _event_for_temp_id(state: WorkState, node_id: int) -> WorkSpillEvent:
    if node_id < 0:
        serial = (abs(node_id) + 1) // 2
        if 1 <= serial <= len(state.events):
            event = state.events[serial - 1]
            if node_id in (event.out_temp_id, event.in_temp_id):
                return event
    raise KeyError(f"找不到临时SPILL节点{node_id}对应的事件")


def _acquire(
    state: WorkState,
    graph: Graph,
    node: Node,
    strategy: str,
) -> AllocationFailure | None:
    assert node.buf_id is not None
    buffer = graph.buffers[node.buf_id]
    allocator: IntervalAllocator = state.allocators[buffer.memory_type]
    offset = allocator.allocate(buffer.size, strategy)
    if offset is None:
        return AllocationFailure(
            schedule_position=state.index,
            acquire_node=node.id,
            buf_id=buffer.id,
            memory_type=buffer.memory_type,
            required_size=buffer.size,
            total_free=allocator.total_free,
            largest_hole=allocator.largest_hole,
            resident_buf_ids=tuple(
                sorted(
                    buf_id
                    for buf_id in state.resident
                    if graph.buffers[buf_id].memory_type == buffer.memory_type
                )
            ),
            reason="没有足够大的连续空闲区间",
        )
    segment_index = state.segment_counts.get(buffer.id, 0)
    state.segment_counts[buffer.id] = segment_index + 1
    state.resident[buffer.id] = ActiveSegment(buffer.id, node.id, offset, segment_index)
    if node.is_alloc:
        state.initial_offsets[buffer.id] = offset
    else:
        state.ddr.discard(buffer.id)
        _event_for_temp_id(state, node.id).new_offset = offset
    return None


def _release(state: WorkState, graph: Graph, node: Node) -> str | None:
    assert node.buf_id is not None
    active = state.resident.get(node.buf_id)
    if active is None:
        return f"节点{node.id}释放了未驻留BufId {node.buf_id}"
    buffer = graph.buffers[node.buf_id]
    allocator: IntervalAllocator = state.allocators[buffer.memory_type]
    allocator.release(active.offset, buffer.size)
    del state.resident[node.buf_id]
    if node.is_spill_out:
        state.ddr.add(node.buf_id)
    return None


def _advance_until_failure(
    state: WorkState,
    graph: Graph,
    strategy: str,
) -> tuple[str, AllocationFailure | str | None]:
    while state.index < len(state.schedule):
        node_id = state.schedule[state.index]
        node = _node_for(state, graph, node_id)
        if node.is_alloc or node.is_spill_in:
            failure = _acquire(state, graph, node, strategy)
            if failure is not None:
                state.failure_history.append(failure)
                return "allocation_failure", failure
        elif node.is_free or node.is_spill_out:
            error = _release(state, graph, node)
            if error:
                return "invalid", error
        elif node.is_operation:
            missing = [buf_id for buf_id in node.bufs if buf_id not in state.resident]
            if missing:
                return "invalid", f"操作节点{node.id}使用未驻留Buffer {missing}"
        state.index += 1
    if state.resident:
        return "invalid", f"扫描结束后仍有未释放Buffer：{sorted(state.resident)[:20]}"
    return "complete", None


def _candidate_buffers(
    state: WorkState,
    graph: Graph,
    failure: AllocationFailure,
    limit: int,
    schedule_index: ScheduleIndex,
) -> list[int]:
    allocator: IntervalAllocator = state.allocators[failure.memory_type]
    progress = schedule_index.progress_rank(state)
    ranked: list[tuple[tuple[int, ...], int]] = []
    for buf_id, active in state.resident.items():
        buffer = graph.buffers[buf_id]
        if buffer.memory_type != failure.memory_type:
            continue
        deadline = schedule_index.next_deadline_rank(buf_id, progress)
        if deadline is None:
            continue
        simulated = allocator.clone()
        simulated.release(active.offset, buffer.size)
        solves = simulated.largest_hole >= failure.required_size
        hole_gain = simulated.largest_hole - allocator.largest_hole
        distance = deadline - state.index
        # Belady式优先级：优先换出距离下一次使用（或最终FREE）最远的对象。
        # 不能只偏好“一次即可腾出足够空间”的大Buffer，否则当相邻操作
        # 需要两个大Buffer同时驻留时，会在二者之间反复换入换出。
        cost_factor = 1 if buffer.from_copy_in else 2
        key = (
            -distance,
            cost_factor,
            0 if solves else 1,
            -hole_gain,
            -buffer.size,
            buf_id,
        )
        ranked.append((key, buf_id))
    ranked.sort()
    return [buf_id for _, buf_id in ranked[:limit]]


def _insert_spill_in_place(
    branch: WorkState, graph: Graph, buf_id: int, schedule_index: ScheduleIndex
) -> None:
    buffer = graph.buffers[buf_id]
    serial = branch.next_serial
    branch.next_serial += 1
    out_temp_id = -(2 * serial - 1)
    in_temp_id = -(2 * serial)
    out_cycles, in_cycles = spill_cycles(buffer)
    branch.temp_nodes[out_temp_id] = Node(
        out_temp_id,
        "SPILL_OUT",
        buf_id=buf_id,
        size=buffer.size,
        memory_type=buffer.memory_type,
        pipe="MTE3",
        cycles=out_cycles,
        bufs=(buf_id,),
    )
    branch.temp_nodes[in_temp_id] = Node(
        in_temp_id,
        "SPILL_IN",
        buf_id=buf_id,
        size=buffer.size,
        memory_type=buffer.memory_type,
        pipe="MTE2",
        cycles=in_cycles,
        bufs=(buf_id,),
    )
    event = WorkSpillEvent(serial, buf_id, out_temp_id, in_temp_id)
    branch.events.append(event)
    branch.movement += spill_cost(buffer)

    # OUT紧邻失败Acquire之前；IN位于OUT之后第一次使用该Buffer的原始操作之前。
    branch.schedule.insert(branch.index, out_temp_id)
    progress = schedule_index.progress_rank(branch)
    deadline_rank = schedule_index.next_deadline_rank(buf_id, progress)
    if deadline_rank is None:
        raise RuntimeError(f"内部错误：候选BufId {buf_id}不存在后续使用或FREE")
    deadline_node = schedule_index.base_schedule[deadline_rank]
    deadline = branch.schedule.index(deadline_node, branch.index + 1)
    branch.schedule.insert(deadline, in_temp_id)
 

def _branch_with_spill(
    state: WorkState, graph: Graph, buf_id: int, schedule_index: ScheduleIndex
) -> WorkState:
    branch = _clone_state(state)
    _insert_spill_in_place(branch, graph, buf_id, schedule_index)
    return branch


def _finalize_solution(
    graph: Graph,
    original_schedule: tuple[int, ...],
    state: WorkState,
    strategy: str,
) -> Problem2Solution:
    temp_position = {node_id: index for index, node_id in enumerate(state.schedule)}
    ordered_events = sorted(state.events, key=lambda event: temp_position[event.out_temp_id])
    id_map: dict[int, int] = {}
    final_events: list[SpillEvent] = []
    extended_nodes: dict[int, Node] = dict(graph.nodes)
    for k, event in enumerate(ordered_events, start=1):
        out_id = graph.node_count + 2 * k - 2
        in_id = graph.node_count + 2 * k - 1
        id_map[event.out_temp_id] = out_id
        id_map[event.in_temp_id] = in_id
        buffer = graph.buffers[event.buf_id]
        out_cycles, in_cycles = spill_cycles(buffer)
        if event.new_offset is None:
            raise RuntimeError(f"SPILL事件{k}尚未获得NewOffset")
        final_events.append(
            SpillEvent(k, event.buf_id, out_id, in_id, event.new_offset, out_cycles, in_cycles)
        )
        extended_nodes[out_id] = Node(
            out_id,
            "SPILL_OUT",
            buf_id=event.buf_id,
            size=buffer.size,
            memory_type=buffer.memory_type,
            pipe="MTE3",
            cycles=out_cycles,
            bufs=(event.buf_id,),
        )
        extended_nodes[in_id] = Node(
            in_id,
            "SPILL_IN",
            buf_id=event.buf_id,
            size=buffer.size,
            memory_type=buffer.memory_type,
            pipe="MTE2",
            cycles=in_cycles,
            bufs=(event.buf_id,),
        )
    final_schedule = tuple(id_map.get(node_id, node_id) for node_id in state.schedule)
    return Problem2Solution(
        schedule=final_schedule,
        extended_nodes=extended_nodes,
        initial_offsets=dict(state.initial_offsets),
        spill_events=tuple(final_events),
        resident_segments=(),
        movement=state.movement,
        allocation_strategy=strategy,
        original_schedule=original_schedule,
    )


def _search_one_strategy(
    graph: Graph,
    original_schedule: tuple[int, ...],
    strategy: str,
    config: SearchConfig,
) -> tuple[Problem2Solution | None, SearchAttempt]:
    started = time.perf_counter()
    schedule_index = ScheduleIndex.build(graph, original_schedule)
    # 先构造确定性的贪心可行上界。后续分支搜索即使达到状态/时间上限，
    # 也能返回一个已经完整验证的候选，而不是因尚未走到叶节点而无结果。
    greedy = _new_state(graph, original_schedule)
    greedy_complete = False
    while len(greedy.events) < config.max_spills:
        if time.perf_counter() - started >= config.time_limit_seconds:
            break
        status, detail = _advance_until_failure(greedy, graph, strategy)
        if status == "complete":
            greedy_complete = True
            break
        if status == "invalid":
            break
        assert isinstance(detail, AllocationFailure)
        candidates = _candidate_buffers(greedy, graph, detail, 1, schedule_index)
        if not candidates:
            break
        _insert_spill_in_place(greedy, graph, candidates[0], schedule_index)

    counter = 0
    frontier: list[tuple[int, int, int, WorkState]] = []
    initial = _new_state(graph, original_schedule)
    heapq.heappush(frontier, (0, 0, counter, initial))
    expanded = 0
    best_state: WorkState | None = greedy if greedy_complete else None
    last_failure: AllocationFailure | None = None
    stop_reason = "frontier_exhausted"

    while frontier and expanded < config.max_states:
        if time.perf_counter() - started >= config.time_limit_seconds:
            stop_reason = "time_limit"
            break
        _, _, _, state = heapq.heappop(frontier)
        if best_state is not None and state.movement > best_state.movement:
            continue
        expanded += 1
        status, detail = _advance_until_failure(state, graph, strategy)
        if status == "complete":
            if best_state is None or (state.movement, len(state.events)) < (
                best_state.movement,
                len(best_state.events),
            ):
                best_state = state
                stop_reason = "best_feasible_found"
            # Best-first frontier按movement排序；更大movement不可能改进主目标。
            if not frontier or frontier[0][0] > state.movement:
                break
            continue
        if status == "invalid":
            continue
        assert isinstance(detail, AllocationFailure)
        last_failure = detail
        if len(state.events) >= config.max_spills:
            continue
        candidates = _candidate_buffers(
            state, graph, detail, config.spill_candidate_limit, schedule_index
        )
        for buf_id in candidates:
            branch = _branch_with_spill(state, graph, buf_id, schedule_index)
            counter += 1
            heapq.heappush(
                frontier,
                (branch.movement, len(branch.events), counter, branch),
            )

    if expanded >= config.max_states:
        stop_reason = "state_limit"
    runtime = time.perf_counter() - started
    if best_state is None:
        return None, SearchAttempt(
            strategy,
            False,
            None,
            0,
            expanded,
            runtime,
            stop_reason,
            last_failure,
        )
    solution = _finalize_solution(graph, original_schedule, best_state, strategy)
    return solution, SearchAttempt(
        strategy,
        True,
        solution.movement,
        len(solution.spill_events),
        expanded,
        runtime,
        stop_reason,
        last_failure,
    )


def solve_problem2(
    graph: Graph,
    original_schedule: tuple[int, ...],
    config: SearchConfig,
) -> SearchResult:
    from .validator import validate_problem2

    started = time.perf_counter()
    if config.schedule_policy == "capacity_aware":
        working_schedule = capacity_aware_topological_order(graph, original_schedule)
    elif config.schedule_policy == "reference":
        working_schedule = original_schedule
    else:
        raise ValueError(f"未知schedule_policy：{config.schedule_policy}")
    attempts: list[SearchAttempt] = []
    best: Problem2Solution | None = None
    for strategy in config.allocation_strategies:
        solution, attempt = _search_one_strategy(graph, working_schedule, strategy, config)
        attempts.append(attempt)
        if solution is None:
            continue
        validation = validate_problem2(graph, solution, config.enforce_l0_single)
        if not validation.valid:
            attempts[-1] = SearchAttempt(
                attempt.allocation_strategy,
                False,
                None,
                attempt.spill_count,
                attempt.expanded_states,
                attempt.runtime_seconds,
                "final_validation_failed: " + "; ".join(validation.errors[:3]),
                attempt.failure,
            )
            continue
        solution = Problem2Solution(
            schedule=solution.schedule,
            extended_nodes=solution.extended_nodes,
            initial_offsets=solution.initial_offsets,
            spill_events=solution.spill_events,
            resident_segments=validation.resident_segments,
            movement=validation.movement or 0,
            allocation_strategy=solution.allocation_strategy,
            original_schedule=solution.original_schedule,
            reuse_edges=validation.reuse_edges,
            spill_edges=validation.spill_edges,
        )
        if best is None or (
            solution.movement,
            len(solution.spill_events),
            solution.allocation_strategy,
        ) < (best.movement, len(best.spill_events), best.allocation_strategy):
            best = solution
    if best is None:
        detail = "; ".join(
            f"{attempt.allocation_strategy}={attempt.stop_reason}" for attempt in attempts
        )
        raise RuntimeError(f"本次搜索未找到第二问可行方案：{detail}")
    return SearchResult(best, tuple(attempts), time.perf_counter() - started)
