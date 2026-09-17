"""从最终方案与提交文件独立重建并验证第二问。"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from .allocator import IntervalAllocator
from .model import (
    ActiveSegment,
    CAPACITIES,
    Graph,
    Problem2Solution,
    ResidentSegment,
    SpillEvent,
    spill_cost,
    spill_cycles,
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]
    movement: int | None
    resident_segments: tuple[ResidentSegment, ...]
    spill_edges: tuple[tuple[int, int], ...]
    reuse_edges: tuple[tuple[int, int], ...]

    def require_valid(self) -> None:
        if not self.valid:
            raise ValueError("第二问验证失败：\n" + "\n".join(f"- {e}" for e in self.errors[:30]))


def _has_cycle(node_ids: set[int], edges: set[tuple[int, int]]) -> bool:
    successors: dict[int, list[int]] = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for source, target in edges:
        if source not in node_ids or target not in node_ids:
            return True
        successors[source].append(target)
        indegree[target] += 1
    ready = deque(node_id for node_id in node_ids if indegree[node_id] == 0)
    seen = 0
    while ready:
        node_id = ready.popleft()
        seen += 1
        for target in successors[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    return seen != len(node_ids)


def validate_problem2(
    graph: Graph,
    solution: Problem2Solution,
    enforce_l0_single: bool = False,
) -> ValidationResult:
    errors: list[str] = []
    schedule = tuple(solution.schedule)
    k_count = len(solution.spill_events)
    expected_ids = set(range(graph.node_count + 2 * k_count))
    if len(schedule) != graph.node_count + 2 * k_count:
        errors.append("schedule长度不等于N+2K")
    if len(set(schedule)) != len(schedule):
        errors.append("schedule含重复节点")
    if set(schedule) != expected_ids:
        errors.append("schedule节点集合不等于0至N+2K-1")
    if errors:
        return ValidationResult(False, tuple(errors), None, (), (), ())

    position = {node_id: index for index, node_id in enumerate(schedule)}
    for source, target in graph.original_edges:
        if position[source] >= position[target]:
            errors.append(f"违反原始依赖边：{source}->{target}")
            if len(errors) >= 30:
                break

    event_by_out: dict[int, SpillEvent] = {}
    event_by_in: dict[int, SpillEvent] = {}
    last_out_position = -1
    for k, event in enumerate(solution.spill_events, start=1):
        expected_out = graph.node_count + 2 * k - 2
        expected_in = graph.node_count + 2 * k - 1
        if event.event_index != k or event.out_id != expected_out or event.in_id != expected_in:
            errors.append(f"第{k}个SPILL事件编号不连续")
        if position[event.out_id] >= position[event.in_id]:
            errors.append(f"第{k}个SPILL事件IN不在OUT之后")
        if position[event.out_id] <= last_out_position:
            errors.append("SPILL事件没有按最终schedule中的OUT顺序编号")
        last_out_position = position[event.out_id]
        buffer = graph.buffers.get(event.buf_id)
        if buffer is None:
            errors.append(f"第{k}个SPILL引用非法BufId {event.buf_id}")
            continue
        expected_out_cycles, expected_in_cycles = spill_cycles(buffer)
        out_node = solution.extended_nodes.get(event.out_id)
        in_node = solution.extended_nodes.get(event.in_id)
        if out_node is None or in_node is None:
            errors.append(f"第{k}个SPILL缺少扩展节点")
        else:
            if out_node.op != "SPILL_OUT" or out_node.pipe != "MTE3" or out_node.cycles != expected_out_cycles:
                errors.append(f"第{k}个SPILL_OUT属性错误")
            if in_node.op != "SPILL_IN" or in_node.pipe != "MTE2" or in_node.cycles != expected_in_cycles:
                errors.append(f"第{k}个SPILL_IN属性错误")
            if out_node.bufs != (event.buf_id,) or in_node.bufs != (event.buf_id,):
                errors.append(f"第{k}个SPILL节点Bufs错误")
        event_by_out[event.out_id] = event
        event_by_in[event.in_id] = event

    allocators = {name: IntervalAllocator.empty(capacity) for name, capacity in CAPACITIES.items()}
    resident: dict[int, ActiveSegment] = {}
    ddr: set[int] = set()
    segment_counts: dict[int, int] = defaultdict(int)
    segments: list[ResidentSegment] = []
    spill_edges: set[tuple[int, int]] = set()
    reuse_edges: set[tuple[int, int]] = set()
    last_release_by_address: dict[str, list[int | None]] = {
        name: [None] * capacity for name, capacity in CAPACITIES.items()
    }
    use_by_segment: dict[tuple[int, int], list[int]] = defaultdict(list)

    for pos, node_id in enumerate(schedule):
        node = solution.extended_nodes[node_id]
        if node.is_alloc or node.is_spill_in:
            assert node.buf_id is not None
            buffer = graph.buffers[node.buf_id]
            if node.buf_id in resident:
                errors.append(f"位置{pos}重复申请已驻留BufId {node.buf_id}")
                continue
            if node.is_alloc:
                offset = solution.initial_offsets.get(node.buf_id)
                if offset is None:
                    errors.append(f"memory缺少BufId {node.buf_id}")
                    continue
            else:
                event = event_by_in.get(node_id)
                if event is None:
                    errors.append(f"SPILL_IN节点{node_id}没有事件")
                    continue
                if node.buf_id not in ddr:
                    errors.append(f"SPILL_IN节点{node_id}执行前BufId不在DDR")
                offset = event.new_offset
                ddr.discard(node.buf_id)
            allocator = allocators[buffer.memory_type]
            if not allocator.reserve(offset, buffer.size):
                errors.append(
                    f"位置{pos}的BufId {node.buf_id}地址非法或冲突：[{offset},{offset + buffer.size})"
                )
                continue
            previous_releases = set(
                last_release_by_address[buffer.memory_type][offset : offset + buffer.size]
            )
            for previous_release in previous_releases:
                if previous_release is not None:
                    reuse_edges.add((previous_release, node_id))
            segment_index = segment_counts[node.buf_id]
            segment_counts[node.buf_id] += 1
            resident[node.buf_id] = ActiveSegment(node.buf_id, node_id, offset, segment_index)
            if enforce_l0_single and buffer.memory_type.startswith("L0"):
                count = sum(
                    1
                    for active_buf in resident
                    if graph.buffers[active_buf].memory_type == buffer.memory_type
                )
                if count > 1:
                    errors.append(f"位置{pos}违反可选{buffer.memory_type}单驻留开关")
        elif node.is_free or node.is_spill_out:
            assert node.buf_id is not None
            buffer = graph.buffers[node.buf_id]
            active = resident.get(node.buf_id)
            if active is None:
                errors.append(f"位置{pos}释放未驻留BufId {node.buf_id}")
                continue
            allocators[buffer.memory_type].release(active.offset, buffer.size)
            last_release_by_address[buffer.memory_type][
                active.offset : active.offset + buffer.size
            ] = [node_id] * buffer.size
            segments.append(
                ResidentSegment(
                    node.buf_id,
                    active.segment_index,
                    buffer.memory_type,
                    buffer.size,
                    active.acquire_node,
                    node_id,
                    position[active.acquire_node],
                    pos,
                    active.offset,
                    active.acquire_node >= graph.node_count,
                )
            )
            segment_key = (node.buf_id, active.segment_index)
            spill_edges.add((active.acquire_node, node_id))
            for use_node in use_by_segment[segment_key]:
                spill_edges.add((active.acquire_node, use_node))
                spill_edges.add((use_node, node_id))
            del resident[node.buf_id]
            if node.is_spill_out:
                ddr.add(node.buf_id)
                event = event_by_out.get(node_id)
                if event is None:
                    errors.append(f"SPILL_OUT节点{node_id}没有事件")
                else:
                    spill_edges.add((node_id, event.in_id))
        else:
            for buf_id in node.bufs:
                active = resident.get(buf_id)
                if active is None:
                    errors.append(f"位置{pos}操作节点{node_id}使用未驻留BufId {buf_id}")
                else:
                    use_by_segment[(buf_id, active.segment_index)].append(node_id)
        if len(errors) >= 50:
            break

    if resident:
        errors.append(f"结束后仍有驻留Buffer：{sorted(resident)[:20]}")
    if ddr:
        errors.append(f"结束后仍有未换回Buffer：{sorted(ddr)[:20]}")
    if set(solution.initial_offsets) != set(graph.buffers):
        errors.append("memory中的BufId集合与原图Buffer集合不一致")

    segments.sort(key=lambda s: (s.memory_type, s.acquire_position, s.buf_id, s.segment_index))
    all_edges = set(graph.original_edges) | spill_edges | reuse_edges
    for source, target in all_edges:
        if position[source] >= position[target]:
            errors.append(f"最终schedule违反扩展边：{source}->{target}")
            if len(errors) >= 50:
                break
    if _has_cycle(set(schedule), all_edges):
        errors.append("最终扩展图存在有向环")

    movement = sum(spill_cost(graph.buffers[event.buf_id]) for event in solution.spill_events)
    if movement != solution.movement:
        errors.append(f"搬移量不一致：重新计算={movement}，报告={solution.movement}")
    return ValidationResult(
        not errors,
        tuple(errors),
        movement if not errors else None,
        tuple(segments),
        tuple(sorted(spill_edges)),
        tuple(sorted(reuse_edges)),
    )


def _read_mapping(path: Path) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError(f"{path.name}第{line_no}行格式错误")
        result.append((int(parts[0]), int(parts[1])))
    return result


def validate_submission_files(
    graph: Graph,
    solution: Problem2Solution,
    schedule_path: str | Path,
    memory_path: str | Path,
    spill_path: str | Path,
) -> None:
    schedule = tuple(
        int(line.strip())
        for line in Path(schedule_path).read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    )
    memory = dict(_read_mapping(Path(memory_path)))
    spill = _read_mapping(Path(spill_path))
    if schedule != solution.schedule:
        raise ValueError("schedule.txt回读结果与内存方案不一致")
    if memory != dict(solution.initial_offsets):
        raise ValueError("memory.txt回读结果与内存方案不一致")
    expected_spill = [(event.buf_id, event.new_offset) for event in solution.spill_events]
    if spill != expected_spill:
        raise ValueError("spill.txt回读顺序或内容与内存方案不一致")
    validate_problem2(graph, solution).require_valid()
