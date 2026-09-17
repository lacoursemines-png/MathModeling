"""A题第二问：连续地址分配与SPILL搜索。"""

from .io import InputValidationError, load_graph, load_schedule
from .model import (
    AllocationFailure,
    Buffer,
    Graph,
    Node,
    Problem2Solution,
    ResidentSegment,
    SearchConfig,
    SpillEvent,
)
from .solver import SearchResult, solve_problem2
from .validator import ValidationResult, validate_problem2, validate_submission_files

__all__ = [
    "AllocationFailure",
    "Buffer",
    "Graph",
    "InputValidationError",
    "Node",
    "Problem2Solution",
    "ResidentSegment",
    "SearchConfig",
    "SearchResult",
    "SpillEvent",
    "ValidationResult",
    "load_graph",
    "load_schedule",
    "solve_problem2",
    "validate_problem2",
    "validate_submission_files",
]
