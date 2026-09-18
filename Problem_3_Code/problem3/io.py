"""问题二结果读取及第三问文件输出。"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from problem2.model import Node, Problem2Solution, SpillEvent, spill_cycles, spill_cost
from problem2.validator import validate_problem2

from .model import BudgetSelection, CandidateRecord, Problem3CaseResult
from .timing import evaluate_timing
from .validator import validate_problem3


def _read_int_lines(path: Path) -> tuple[int, ...]:
    return tuple(
        int(line.strip())
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    )


def _read_mapping_lines(path: Path) -> list[tuple[int, int]]:
    values: list[tuple[int, int]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        text = line.strip()
        if not text:
            continue
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError(f"{path.name}第{line_no}行格式错误")
        values.append((int(parts[0]), int(parts[1])))
    return values


def load_problem2_solution(graph, problem2_dir: str | Path) -> Problem2Solution:
    root = Path(problem2_dir)
    schedule_path = root / f"{graph.name}_schedule.txt"
    memory_path = root / f"{graph.name}_memory.txt"
    spill_path = root / f"{graph.name}_spill.txt"
    for path in (schedule_path, memory_path, spill_path):
        if not path.exists():
            raise FileNotFoundError(f"缺少问题二文件：{path}")

    schedule = _read_int_lines(schedule_path)
    memory_pairs = _read_mapping_lines(memory_path)
    if len(memory_pairs) != len(dict(memory_pairs)):
        raise ValueError(f"{memory_path.name}含重复BufId")
    initial_offsets = dict(memory_pairs)
    spill_pairs = _read_mapping_lines(spill_path)
    extra = len(schedule) - graph.node_count
    if extra < 0 or extra % 2:
        raise ValueError("问题二schedule长度不能表示完整SPILL事件对")
    if extra // 2 != len(spill_pairs):
        raise ValueError("问题二schedule中的SPILL事件数与spill.txt行数不一致")

    extended_nodes = dict(graph.nodes)
    events: list[SpillEvent] = []
    for k, (buf_id, new_offset) in enumerate(spill_pairs, 1):
        if buf_id not in graph.buffers:
            raise ValueError(f"spill.txt第{k}行引用非法BufId {buf_id}")
        out_id = graph.node_count + 2 * k - 2
        in_id = graph.node_count + 2 * k - 1
        buffer = graph.buffers[buf_id]
        out_cycles, in_cycles = spill_cycles(buffer)
        events.append(SpillEvent(k, buf_id, out_id, in_id, new_offset, out_cycles, in_cycles))
        extended_nodes[out_id] = Node(
            out_id,
            "SPILL_OUT",
            buf_id=buf_id,
            size=buffer.size,
            memory_type=buffer.memory_type,
            pipe="MTE3",
            cycles=out_cycles,
            bufs=(buf_id,),
        )
        extended_nodes[in_id] = Node(
            in_id,
            "SPILL_IN",
            buf_id=buf_id,
            size=buffer.size,
            memory_type=buffer.memory_type,
            pipe="MTE2",
            cycles=in_cycles,
            bufs=(buf_id,),
        )
    movement = sum(spill_cost(graph.buffers[event.buf_id]) for event in events)
    original_schedule = tuple(node_id for node_id in schedule if node_id < graph.node_count)
    solution = Problem2Solution(
        schedule=schedule,
        extended_nodes=extended_nodes,
        initial_offsets=initial_offsets,
        spill_events=tuple(events),
        resident_segments=(),
        movement=movement,
        allocation_strategy="loaded_problem2",
        original_schedule=original_schedule,
    )
    validation = validate_problem2(graph, solution, False)
    validation.require_valid()
    return Problem2Solution(
        schedule=solution.schedule,
        extended_nodes=solution.extended_nodes,
        initial_offsets=solution.initial_offsets,
        spill_events=solution.spill_events,
        resident_segments=validation.resident_segments,
        movement=movement,
        allocation_strategy=solution.allocation_strategy,
        original_schedule=solution.original_schedule,
        reuse_edges=validation.reuse_edges,
        spill_edges=validation.spill_edges,
    )


def _write_submission_files(root: Path, graph, candidate: CandidateRecord) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    solution = candidate.solution
    schedule_path = root / f"{graph.name}_schedule.txt"
    memory_path = root / f"{graph.name}_memory.txt"
    spill_path = root / f"{graph.name}_spill.txt"
    schedule_path.write_text(
        "".join(f"{node_id}\n" for node_id in solution.schedule), encoding="utf-8"
    )
    memory_path.write_text(
        "".join(f"{buf_id}:{solution.initial_offsets[buf_id]}\n" for buf_id in sorted(graph.buffers)),
        encoding="utf-8",
    )
    spill_path.write_text(
        "".join(f"{event.buf_id}:{event.new_offset}\n" for event in solution.spill_events),
        encoding="utf-8",
    )
    return {"schedule": schedule_path, "memory": memory_path, "spill": spill_path}


def verify_written_solution(
    graph,
    problem3_dir: str | Path,
    expected: CandidateRecord,
    d_max: int,
    enforce_l0_single: bool = False,
) -> dict[str, Any]:
    """从磁盘回读正式文件，并独立重算D、T及全部硬约束。"""
    loaded = load_problem2_solution(graph, problem3_dir)
    timing = evaluate_timing(graph, loaded)
    validation = validate_problem3(
        graph, loaded, timing, d_max, enforce_l0_single
    )
    validation.require_valid()
    errors: list[str] = []
    if loaded.schedule != expected.solution.schedule:
        errors.append("回读schedule与选中方案不一致")
    if dict(loaded.initial_offsets) != dict(expected.solution.initial_offsets):
        errors.append("回读memory与选中方案不一致")
    expected_spill = tuple(
        (item.buf_id, item.new_offset) for item in expected.solution.spill_events
    )
    loaded_spill = tuple((item.buf_id, item.new_offset) for item in loaded.spill_events)
    if loaded_spill != expected_spill:
        errors.append("回读spill与选中方案不一致")
    if loaded.movement != expected.movement:
        errors.append("回读搬移量与选中方案不一致")
    if timing.total_time != expected.timing.total_time:
        errors.append("回读总周期与选中方案不一致")
    if errors:
        raise ValueError("正式文件回读失败：\n" + "\n".join(f"- {item}" for item in errors))
    return {
        "valid": True,
        "actual_D": loaded.movement,
        "Dmax": d_max,
        "T": timing.total_time,
        "schedule_nodes": len(loaded.schedule),
        "spill_events": len(loaded.spill_events),
        "message": "正式文件已回读，地址、依赖、SPILL、Pipe、预算与总周期验证通过",
    }


def write_case_outputs(output_root: str | Path, graph, result: Problem3CaseResult) -> None:
    root = Path(output_root)
    main = next(item for item in result.budgets if item.alpha == 0.0)
    _write_submission_files(root / "Problem3", graph, main.selected)
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    timing_path = log_dir / f"{graph.name}_node_timing.csv"
    with timing_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "node_id", "op", "pipe", "cycles", "start", "finish", "latest_start",
                "slack", "on_representative_critical_path", "on_any_critical_path",
            ]
        )
        representative = set(main.selected.timing.representative_critical_path)
        for node_id in main.selected.solution.schedule:
            node = main.selected.solution.extended_nodes[node_id]
            writer.writerow(
                [
                    node_id, node.op, node.pipe or "", node.cycles,
                    main.selected.timing.start_time[node_id],
                    main.selected.timing.finish_time[node_id],
                    main.selected.timing.latest_start[node_id],
                    main.selected.timing.slack[node_id],
                    int(node_id in representative),
                    int(node_id in main.selected.timing.all_critical_nodes),
                ]
            )

    pipe_path = log_dir / f"{graph.name}_pipe_intervals.csv"
    with pipe_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["pipe", "node_id", "start", "finish", "cycles"])
        for pipe in sorted(main.selected.timing.pipe_intervals):
            for node_id, start, finish in main.selected.timing.pipe_intervals[pipe]:
                writer.writerow([pipe, node_id, start, finish, finish - start])

    candidate_rows = []
    for candidate in result.candidates:
        candidate_rows.append(
            {
                "name": candidate.name,
                "D": candidate.movement,
                "T": candidate.timing.total_time,
                "spill_count": candidate.spill_count,
                "runtime_seconds": round(candidate.runtime_seconds, 6),
                "nondominated_in_searched_set": candidate in result.nondominated,
            }
        )
    with (log_dir / f"{graph.name}_candidates.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(candidate_rows[0]))
        writer.writeheader()
        writer.writerows(candidate_rows)

    summary: dict[str, Any] = {
        "task": graph.name,
        "baseline": {
            "D": result.baseline.movement,
            "T": result.baseline.timing.total_time,
            "spill_count": result.baseline.spill_count,
        },
        "main_alpha_0": {
            "Dmax": main.d_max,
            "actual_D": main.selected.movement,
            "T": main.selected.timing.total_time,
            "candidate": main.selected.name,
            "improved_time": main.improved_time,
        },
        "budgets": [
            {
                "alpha": item.alpha,
                "Dmax": item.d_max,
                "actual_D": item.selected.movement,
                "T": item.selected.timing.total_time,
                "candidate": item.selected.name,
                "improved_time_vs_problem2_baseline": item.improved_time,
                "no_improvement_statement": None
                if item.improved_time
                else "在当前搜索设置下未改善",
            }
            for item in result.budgets
        ],
        "representative_critical_path": list(main.selected.timing.representative_critical_path),
        "critical_node_count": len(main.selected.timing.all_critical_nodes),
        "dependency_lower_bound": main.selected.timing.dependency_lower_bound,
        "pipe_load_lower_bound": main.selected.timing.pipe_load_lower_bound,
        "pipe_busy_cycles": dict(main.selected.timing.pipe_busy_cycles),
        "pipe_utilization": dict(main.selected.timing.pipe_utilization),
        "candidate_count": len(result.candidates),
        "failure_count": len(result.failures),
        "failures": list(result.failures),
        "nondominated_points_in_searched_set": [
            {"name": item.name, "D": item.movement, "T": item.timing.total_time}
            for item in result.nondominated
        ],
        "runtime_seconds": round(result.runtime_seconds, 6),
        "config": {
            "alphas": list(result.config.alphas),
            "scheduling_strategies": list(result.config.scheduling_strategies),
            "q2_allocation_strategies": list(result.config.q2_allocation_strategies),
            "q2_spill_candidate_limit": result.config.q2_spill_candidate_limit,
            "q2_max_states": result.config.q2_max_states,
            "q2_max_spills": result.config.q2_max_spills,
            "q2_time_limit_seconds": result.config.q2_time_limit_seconds,
            "local_window_sizes": list(result.config.local_window_sizes),
            "local_candidates_per_window": result.config.local_candidates_per_window,
            "max_candidate_schedules": result.config.max_candidate_schedules,
            "enforce_l0_single": result.config.enforce_l0_single,
            "deterministic": result.config.deterministic,
            "random_seed": result.config.random_seed,
        },
        "result_claim": "best_known_feasible_not_global_optimum",
    }
    (log_dir / f"{graph.name}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    scenario_root = root / "scenarios"
    for item in result.budgets:
        label = f"alpha_{int(round(item.alpha * 100)):02d}pct"
        _write_submission_files(scenario_root / label / "Problem3", graph, item.selected)

    verification = verify_written_solution(
        graph,
        root / "Problem3",
        main.selected,
        main.d_max,
        result.config.enforce_l0_single,
    )
    (log_dir / f"{graph.name}_submission_verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
