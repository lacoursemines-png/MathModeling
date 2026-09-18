"""第三问独立验证器。"""

from __future__ import annotations

from dataclasses import dataclass

from problem2.model import Graph, Problem2Solution
from problem2.validator import validate_problem2

from .model import TimingResult
from .timing import build_pipe_edges, evaluate_timing


@dataclass(frozen=True, slots=True)
class Problem3Validation:
    valid: bool
    errors: tuple[str, ...]

    def require_valid(self) -> None:
        if not self.valid:
            raise ValueError("第三问验证失败：\n" + "\n".join(f"- {e}" for e in self.errors[:30]))


def validate_problem3(
    graph: Graph,
    solution: Problem2Solution,
    timing: TimingResult,
    d_max: int,
    enforce_l0_single: bool = False,
) -> Problem3Validation:
    errors: list[str] = []
    q2 = validate_problem2(graph, solution, enforce_l0_single)
    if not q2.valid:
        errors.extend(f"问题二条件：{item}" for item in q2.errors[:20])
    if solution.movement > d_max:
        errors.append(f"实际搬移量{solution.movement}超过预算{d_max}")
    expected_pipe = build_pipe_edges(solution)
    if tuple(timing.pipe_edges) != expected_pipe:
        errors.append("Pipe顺序边与最终提交序列不一致")
    for source, target in expected_pipe:
        source_pipe = solution.extended_nodes[source].pipe
        target_pipe = solution.extended_nodes[target].pipe
        if not source_pipe or source_pipe != target_pipe:
            errors.append(f"非法跨Pipe顺序边：{source}->{target}")
    try:
        rebuilt = evaluate_timing(graph, solution)
    except Exception as exc:
        errors.append(f"无法独立重算时间：{exc}")
        return Problem3Validation(False, tuple(errors))
    if rebuilt.total_time != timing.total_time:
        errors.append("报告总时间与独立重算结果不一致")
    if dict(rebuilt.start_time) != dict(timing.start_time):
        errors.append("节点开始时间与独立重算结果不一致")
    if dict(rebuilt.finish_time) != dict(timing.finish_time):
        errors.append("节点结束时间与独立重算结果不一致")
    for pipe, intervals in timing.pipe_intervals.items():
        previous_end = 0
        for node_id, start, finish in intervals:
            if start < previous_end:
                errors.append(f"Pipe {pipe}存在执行区间重叠，节点{node_id}")
            previous_end = finish
    if timing.total_time != max(timing.finish_time.values(), default=0):
        errors.append("总时间不是全部节点结束时间最大值")
    return Problem3Validation(not errors, tuple(errors))
