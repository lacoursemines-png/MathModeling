"""第二问共享数据对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


CAPACITIES: dict[str, int] = {
    "L1": 4096,
    "UB": 1024,
    "L0A": 256,
    "L0B": 256,
    "L0C": 512,
}
MEMORY_TYPES = frozenset(CAPACITIES)
MANAGEMENT_OPS = frozenset({"ALLOC", "FREE"})
SPILL_OPS = frozenset({"SPILL_OUT", "SPILL_IN"})


@dataclass(frozen=True, slots=True)
class Node:
    id: int
    op: str
    buf_id: int | None = None
    size: int | None = None
    memory_type: str | None = None
    pipe: str | None = None
    cycles: int = 0
    bufs: tuple[int, ...] = ()

    @property
    def is_alloc(self) -> bool:
        return self.op == "ALLOC"

    @property
    def is_free(self) -> bool:
        return self.op == "FREE"

    @property
    def is_spill_out(self) -> bool:
        return self.op == "SPILL_OUT"

    @property
    def is_spill_in(self) -> bool:
        return self.op == "SPILL_IN"

    @property
    def is_operation(self) -> bool:
        return self.op not in MANAGEMENT_OPS and self.op not in SPILL_OPS


@dataclass(frozen=True, slots=True)
class Buffer:
    id: int
    size: int
    memory_type: str
    alloc_node: int
    free_node: int
    use_nodes: tuple[int, ...]
    from_copy_in: bool


@dataclass(frozen=True, slots=True)
class Graph:
    name: str
    nodes: Mapping[int, Node]
    buffers: Mapping[int, Buffer]
    original_edges: tuple[tuple[int, int], ...]
    original_successors: Mapping[int, tuple[int, ...]]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.original_edges)


@dataclass(frozen=True, slots=True)
class ResidentSegment:
    buf_id: int
    segment_index: int
    memory_type: str
    size: int
    acquire_node: int
    release_node: int
    acquire_position: int
    release_position: int
    offset: int
    created_by_spill: bool


@dataclass(frozen=True, slots=True)
class SpillEvent:
    event_index: int
    buf_id: int
    out_id: int
    in_id: int
    new_offset: int
    out_cycles: int
    in_cycles: int


@dataclass(frozen=True, slots=True)
class AllocationFailure:
    schedule_position: int
    acquire_node: int
    buf_id: int
    memory_type: str
    required_size: int
    total_free: int
    largest_hole: int
    resident_buf_ids: tuple[int, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class SearchConfig:
    schedule_policy: str = "capacity_aware"
    allocation_strategies: tuple[str, ...] = ("first_fit", "best_fit")
    spill_candidate_limit: int = 3
    max_states: int = 250
    max_spills: int = 10000
    time_limit_seconds: float = 10.0
    enforce_l0_single: bool = False


@dataclass(frozen=True, slots=True)
class Problem2Solution:
    schedule: tuple[int, ...]
    extended_nodes: Mapping[int, Node]
    initial_offsets: Mapping[int, int]
    spill_events: tuple[SpillEvent, ...]
    resident_segments: tuple[ResidentSegment, ...]
    movement: int
    allocation_strategy: str
    original_schedule: tuple[int, ...]
    reuse_edges: tuple[tuple[int, int], ...] = ()
    spill_edges: tuple[tuple[int, int], ...] = ()


@dataclass(slots=True)
class ActiveSegment:
    buf_id: int
    acquire_node: int
    offset: int
    segment_index: int


@dataclass(slots=True)
class WorkSpillEvent:
    serial: int
    buf_id: int
    out_temp_id: int
    in_temp_id: int
    new_offset: int | None = None


@dataclass(slots=True)
class WorkState:
    schedule: list[int]
    temp_nodes: dict[int, Node]
    index: int
    allocators: dict[str, object]
    resident: dict[int, ActiveSegment]
    ddr: set[int]
    initial_offsets: dict[int, int]
    events: list[WorkSpillEvent]
    movement: int
    next_serial: int
    segment_counts: dict[int, int] = field(default_factory=dict)
    failure_history: list[AllocationFailure] = field(default_factory=list)


def spill_cost(buffer: Buffer) -> int:
    return buffer.size if buffer.from_copy_in else 2 * buffer.size


def spill_cycles(buffer: Buffer) -> tuple[int, int]:
    common = 2 * buffer.size + 150
    return (0 if buffer.from_copy_in else common, common)
