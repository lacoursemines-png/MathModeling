"""第三问候选生成、预算筛选和非支配筛选。"""

from __future__ import annotations

import math
import time

from problem2.model import SearchConfig
from problem2.solver import solve_problem2

from .model import (
    BudgetSelection,
    CandidateRecord,
    Problem3CaseResult,
    Problem3Config,
)
from .scheduler import generate_resource_aware_schedule, local_earlier_moves
from .timing import evaluate_timing
from .validator import validate_problem3


def _candidate_key(candidate: CandidateRecord) -> tuple[int, int, int, bool, str]:
    # 指标完全相同时保留问题二基线，避免无收益地改动提交文件。
    return (
        candidate.timing.total_time,
        candidate.movement,
        candidate.spill_count,
        candidate.name != "problem2_baseline",
        candidate.name,
    )


def nondominated_candidates(
    candidates: tuple[CandidateRecord, ...],
) -> tuple[CandidateRecord, ...]:
    unique: dict[tuple[int, int], CandidateRecord] = {}
    for candidate in candidates:
        point = (candidate.movement, candidate.timing.total_time)
        current = unique.get(point)
        if current is None or candidate.name < current.name:
            unique[point] = candidate
    values = list(unique.values())
    result = []
    for candidate in values:
        dominated = any(
            other.movement <= candidate.movement
            and other.timing.total_time <= candidate.timing.total_time
            and (
                other.movement < candidate.movement
                or other.timing.total_time < candidate.timing.total_time
            )
            for other in values
        )
        if not dominated:
            result.append(candidate)
    return tuple(sorted(result, key=lambda item: (item.movement, item.timing.total_time, item.name)))


def _materialize(graph, schedule, name: str, config: Problem3Config) -> CandidateRecord:
    started = time.perf_counter()
    q2_config = SearchConfig(
        schedule_policy="reference",
        allocation_strategies=config.q2_allocation_strategies,
        spill_candidate_limit=config.q2_spill_candidate_limit,
        max_states=config.q2_max_states,
        max_spills=config.q2_max_spills,
        time_limit_seconds=config.q2_time_limit_seconds,
        enforce_l0_single=config.enforce_l0_single,
    )
    result = solve_problem2(graph, schedule, q2_config)
    timing = evaluate_timing(graph, result.solution)
    return CandidateRecord(
        name,
        result.solution,
        timing,
        time.perf_counter() - started,
        schedule,
    )


def solve_problem3_case(graph, problem2_solution, config: Problem3Config) -> Problem3CaseResult:
    started = time.perf_counter()
    baseline_timing = evaluate_timing(graph, problem2_solution)
    baseline = CandidateRecord(
        "problem2_baseline",
        problem2_solution,
        baseline_timing,
        0.0,
        problem2_solution.original_schedule,
    )
    validate_problem3(
        graph,
        baseline.solution,
        baseline.timing,
        baseline.movement,
        config.enforce_l0_single,
    ).require_valid()
    candidates: list[CandidateRecord] = [baseline]
    failures: list[dict[str, object]] = []
    schedules: list[tuple[str, tuple[int, ...]]] = []
    seen = {problem2_solution.original_schedule}
    for strategy in config.scheduling_strategies:
        schedule = generate_resource_aware_schedule(
            graph, problem2_solution.original_schedule, strategy
        )
        if schedule not in seen:
            seen.add(schedule)
            schedules.append((strategy, schedule))

    for name, schedule in schedules[: config.max_candidate_schedules]:
        try:
            candidates.append(_materialize(graph, schedule, name, config))
        except Exception as exc:
            failures.append({"candidate": name, "reason": str(exc)})

    # 从当前时间最优候选的代表关键路径生成少量确定性局部前移方案。
    current_best = min(candidates, key=_candidate_key)
    original_critical = tuple(
        node_id
        for node_id in current_best.timing.representative_critical_path
        if node_id < graph.node_count
    )
    remaining_slots = max(0, config.max_candidate_schedules - len(schedules))
    for window in config.local_window_sizes:
        if remaining_slots <= 0:
            break
        local_schedules = local_earlier_moves(
            graph,
            current_best.solution.original_schedule,
            original_critical,
            window,
            min(config.local_candidates_per_window, remaining_slots),
        )
        for index, schedule in enumerate(local_schedules, 1):
            if schedule in seen:
                continue
            seen.add(schedule)
            name = f"local_w{window}_{index}"
            try:
                candidates.append(_materialize(graph, schedule, name, config))
            except Exception as exc:
                failures.append({"candidate": name, "reason": str(exc)})
            remaining_slots -= 1

    candidate_tuple = tuple(candidates)
    budgets: list[BudgetSelection] = []
    for alpha in config.alphas:
        d_max = math.floor((1.0 + alpha) * baseline.movement)
        feasible = [candidate for candidate in candidate_tuple if candidate.movement <= d_max]
        if not feasible:
            raise RuntimeError(f"内部错误：alpha={alpha}没有可行候选，baseline应始终可行")
        selected = min(feasible, key=_candidate_key)
        validation = validate_problem3(
            graph, selected.solution, selected.timing, d_max, config.enforce_l0_single
        )
        validation.require_valid()
        budgets.append(
            BudgetSelection(
                alpha,
                d_max,
                baseline.movement,
                baseline.timing.total_time,
                selected,
                selected.timing.total_time < baseline.timing.total_time,
            )
        )
    return Problem3CaseResult(
        baseline,
        candidate_tuple,
        tuple(failures),
        tuple(budgets),
        nondominated_candidates(candidate_tuple),
        time.perf_counter() - started,
        config,
    )
