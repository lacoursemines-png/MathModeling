"""A题第三问：搬移预算约束下的真实执行时间优化。"""

from .model import CandidateRecord, Problem3Config, TimingResult
from .solver import solve_problem3_case
from .timing import evaluate_timing

__all__ = [
    "CandidateRecord",
    "Problem3Config",
    "TimingResult",
    "evaluate_timing",
    "solve_problem3_case",
]
