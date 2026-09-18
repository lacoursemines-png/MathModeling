"""第三问共享数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from problem2.model import Problem2Solution


@dataclass(frozen=True, slots=True)
class TimingResult:
    total_time: int
    start_time: Mapping[int, int]
    finish_time: Mapping[int, int]
    latest_start: Mapping[int, int]
    slack: Mapping[int, int]
    critical_predecessor: Mapping[int, int | None]
    representative_critical_path: tuple[int, ...]
    all_critical_nodes: frozenset[int]
    pipe_edges: tuple[tuple[int, int], ...]
    all_edges: tuple[tuple[int, int], ...]
    pipe_intervals: Mapping[str, tuple[tuple[int, int, int], ...]]
    pipe_busy_cycles: Mapping[str, int]
    pipe_utilization: Mapping[str, float]
    dependency_lower_bound: int
    pipe_load_lower_bound: int


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    name: str
    solution: Problem2Solution
    timing: TimingResult
    runtime_seconds: float
    source_schedule: tuple[int, ...]

    @property
    def movement(self) -> int:
        return self.solution.movement

    @property
    def spill_count(self) -> int:
        return len(self.solution.spill_events)


@dataclass(frozen=True, slots=True)
class BudgetSelection:
    alpha: float
    d_max: int
    baseline_d: int
    baseline_t: int
    selected: CandidateRecord
    improved_time: bool


@dataclass(frozen=True, slots=True)
class Problem3Config:
    alphas: tuple[float, ...] = (0.0, 0.02, 0.05, 0.10)
    scheduling_strategies: tuple[str, ...] = (
        "critical_path",
        "earliest_finish",
        "pipe_balance",
        "memory_controlled",
        "hybrid",
    )
    q2_allocation_strategies: tuple[str, ...] = ("first_fit", "best_fit")
    q2_spill_candidate_limit: int = 1
    q2_max_states: int = 1
    q2_max_spills: int = 50000
    q2_time_limit_seconds: float = 20.0
    local_window_sizes: tuple[int, ...] = (16, 64)
    local_candidates_per_window: int = 2
    max_candidate_schedules: int = 12
    enforce_l0_single: bool = False
    deterministic: bool = True
    random_seed: int | None = None


@dataclass(frozen=True, slots=True)
class Problem3CaseResult:
    baseline: CandidateRecord
    candidates: tuple[CandidateRecord, ...]
    failures: tuple[dict[str, object], ...]
    budgets: tuple[BudgetSelection, ...]
    nondominated: tuple[CandidateRecord, ...]
    runtime_seconds: float
    config: Problem3Config
