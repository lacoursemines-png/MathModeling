"""第一问的确定性峰值评价器和独立合法性验证器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import Graph, L0_TYPES, PEAK_TYPES


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    peak: int
    trace: tuple[int, ...]
    first_peak_position: int


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]
    peak: int | None

    def require_valid(self) -> None:
        if not self.valid:
            detail = "\n".join(f"- {item}" for item in self.errors[:30])
            raise ValueError(f"第一问结果验证失败：\n{detail}")


def compute_peak(graph: Graph, schedule: Iterable[int]) -> EvaluationResult:
    """按题意在每个节点处理完成后记录L1+UB驻留量。"""

    current = 0
    peak = 0
    first_peak_position = 0
    trace: list[int] = []
    for position, node_id in enumerate(schedule, start=1):
        node = graph.nodes[node_id]
        if node.memory_type in PEAK_TYPES:
            assert node.size is not None
            if node.is_alloc:
                current += node.size
            elif node.is_free:
                current -= node.size
        trace.append(current)
        if current > peak:
            peak = current
            first_peak_position = position
    return EvaluationResult(peak=peak, trace=tuple(trace), first_peak_position=first_peak_position)


def validate_problem1(graph: Graph, schedule: Iterable[int]) -> ValidationResult:
    """不依赖搜索内部缓存，从原图和最终序列重新验证全部硬约束。"""

    values = tuple(schedule)
    errors: list[str] = []
    expected_ids = set(graph.nodes)
    actual_ids = set(values)
    if len(values) != graph.node_count:
        errors.append(f"序列长度应为 {graph.node_count}，实际为 {len(values)}")
    if len(actual_ids) != len(values):
        seen: set[int] = set()
        duplicates: list[int] = []
        for node_id in values:
            if node_id in seen and node_id not in duplicates:
                duplicates.append(node_id)
            seen.add(node_id)
        errors.append(f"序列存在重复节点：{duplicates[:20]}")
    missing = expected_ids - actual_ids
    extra = actual_ids - expected_ids
    if missing:
        errors.append(f"序列缺少节点：{sorted(missing)[:20]}")
    if extra:
        errors.append(f"序列包含非法节点Id：{sorted(extra)[:20]}")
    if errors:
        return ValidationResult(False, tuple(errors), None)

    position = {node_id: index for index, node_id in enumerate(values)}
    for source, target in graph.original_edges:
        if position[source] >= position[target]:
            errors.append(f"违反原始依赖边：{source} -> {target}")
            if len(errors) >= 30:
                break

    resident: set[int] = set()
    allocated: set[int] = set()
    freed: set[int] = set()
    l0_resident: dict[str, int | None] = {memory_type: None for memory_type in L0_TYPES}
    current_peak_memory = 0
    recomputed_peak = 0

    for position_index, node_id in enumerate(values, start=1):
        node = graph.nodes[node_id]
        if node.is_alloc:
            assert node.buf_id is not None and node.size is not None and node.memory_type is not None
            if node.buf_id in allocated:
                errors.append(f"位置{position_index}：BufId {node.buf_id} 被重复ALLOC")
            if node.buf_id in resident:
                errors.append(f"位置{position_index}：BufId {node.buf_id} 在驻留状态下再次ALLOC")
            if node.memory_type in L0_TYPES and l0_resident[node.memory_type] is not None:
                errors.append(
                    f"位置{position_index}：{node.memory_type} 已驻留BufId "
                    f"{l0_resident[node.memory_type]}，不能再ALLOC BufId {node.buf_id}"
                )
            allocated.add(node.buf_id)
            resident.add(node.buf_id)
            if node.memory_type in L0_TYPES:
                l0_resident[node.memory_type] = node.buf_id
            if node.memory_type in PEAK_TYPES:
                current_peak_memory += node.size
                recomputed_peak = max(recomputed_peak, current_peak_memory)
        elif node.is_free:
            assert node.buf_id is not None and node.size is not None and node.memory_type is not None
            if node.buf_id not in resident:
                errors.append(f"位置{position_index}：FREE前BufId {node.buf_id}并未驻留")
            else:
                resident.remove(node.buf_id)
            if node.buf_id in freed:
                errors.append(f"位置{position_index}：BufId {node.buf_id} 被重复FREE")
            freed.add(node.buf_id)
            if node.memory_type in L0_TYPES:
                if l0_resident[node.memory_type] != node.buf_id:
                    errors.append(
                        f"位置{position_index}：{node.memory_type}当前驻留状态与FREE节点不一致"
                    )
                l0_resident[node.memory_type] = None
            if node.memory_type in PEAK_TYPES:
                current_peak_memory -= node.size
                if current_peak_memory < 0:
                    errors.append(f"位置{position_index}：L1+UB驻留量变为负数")
        else:
            missing_bufs = [buf_id for buf_id in node.bufs if buf_id not in resident]
            if missing_bufs:
                errors.append(
                    f"位置{position_index}：操作节点{node.id}使用了未驻留Buffer {missing_bufs}"
                )
        if len(errors) >= 30:
            break

    if resident:
        errors.append(f"扫描结束后仍有未释放Buffer：{sorted(resident)[:20]}")
    if current_peak_memory != 0:
        errors.append(f"扫描结束后L1+UB驻留量应为0，实际为{current_peak_memory}")

    # 再用显式位置检查生命周期，避免状态扫描的错误被其他异常遮蔽。
    for buffer in graph.buffers.values():
        alloc_pos = position[buffer.alloc_node]
        free_pos = position[buffer.free_node]
        if alloc_pos >= free_pos:
            errors.append(f"BufId {buffer.id} 的ALLOC不在FREE之前")
        for use_node in buffer.use_nodes:
            if not alloc_pos < position[use_node] < free_pos:
                errors.append(
                    f"BufId {buffer.id} 的使用节点{use_node}不在ALLOC与FREE之间"
                )
                break
        if len(errors) >= 30:
            break

    return ValidationResult(not errors, tuple(errors), recomputed_peak if not errors else None)
