from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from problem2.allocator import IntervalAllocator
from problem2.io import build_graph, write_problem2_files
from problem2.model import SearchConfig
from problem2.solver import solve_problem2
from problem2.validator import validate_problem2, validate_submission_files


def alloc(i: int, b: int, size: int, t: str) -> dict[str, object]:
    return {"Id": i, "Op": "ALLOC", "BufId": b, "Size": size, "Type": t}


def free(i: int, b: int, size: int, t: str) -> dict[str, object]:
    return {"Id": i, "Op": "FREE", "BufId": b, "Size": size, "Type": t}


def op(i: int, bufs: list[int], name: str = "CALC") -> dict[str, object]:
    return {"Id": i, "Op": name, "Pipe": "VECTOR", "Cycles": 1, "Bufs": bufs}


class AllocatorTests(unittest.TestCase):
    def test_adjacent_release_merges(self) -> None:
        allocator = IntervalAllocator.empty(10)
        self.assertEqual(allocator.allocate(4, "first_fit"), 0)
        self.assertEqual(allocator.allocate(6, "first_fit"), 4)
        allocator.release(0, 4)
        allocator.release(4, 6)
        self.assertEqual(allocator.free_intervals, [(0, 10)])

    def test_best_fit(self) -> None:
        allocator = IntervalAllocator(20, [(0, 8), (10, 15)])
        self.assertEqual(allocator.allocate(4, "best_fit"), 10)


class Problem2Tests(unittest.TestCase):
    def test_no_spill_solution(self) -> None:
        data = {
            "Nodes": [alloc(0, 0, 4, "UB"), op(1, [0]), free(2, 0, 4, "UB")],
            "Edges": [[0, 1], [1, 2]],
        }
        graph = build_graph(data, "no_spill")
        result = solve_problem2(graph, (0, 1, 2), SearchConfig(max_states=20, time_limit_seconds=2))
        self.assertEqual(result.solution.movement, 0)
        self.assertEqual(len(result.solution.spill_events), 0)
        self.assertTrue(validate_problem2(graph, result.solution).valid)

    def test_spill_copy_in_cost(self) -> None:
        # UB容量1024：两个600大小Buffer不能同时驻留，需要SPILL Buf0后申请Buf1。
        data = {
            "Nodes": [
                alloc(0, 0, 600, "UB"),
                op(1, [0], "COPY_IN"),
                alloc(2, 1, 600, "UB"),
                op(3, [1]),
                free(4, 1, 600, "UB"),
                op(5, [0]),
                free(6, 0, 600, "UB"),
            ],
            "Edges": [[0, 1], [1, 5], [5, 6], [2, 3], [3, 4]],
        }
        graph = build_graph(data, "spill")
        config = SearchConfig(
            schedule_policy="reference",
            spill_candidate_limit=2,
            max_states=30,
            max_spills=5,
            time_limit_seconds=2,
        )
        result = solve_problem2(graph, (0, 1, 2, 3, 4, 5, 6), config)
        self.assertEqual(result.solution.movement, 600)
        self.assertEqual(len(result.solution.spill_events), 1)
        self.assertTrue(validate_problem2(graph, result.solution).valid)

    def test_l0_multiple_residency_allowed_by_default(self) -> None:
        data = {
            "Nodes": [
                alloc(0, 0, 64, "L0A"),
                alloc(1, 1, 64, "L0A"),
                op(2, [0, 1]),
                free(3, 0, 64, "L0A"),
                free(4, 1, 64, "L0A"),
            ],
            "Edges": [[0, 2], [1, 2], [2, 3], [2, 4]],
        }
        graph = build_graph(data, "l0")
        result = solve_problem2(graph, (0, 1, 2, 3, 4), SearchConfig(max_states=20, time_limit_seconds=2))
        self.assertTrue(validate_problem2(graph, result.solution, False).valid)
        self.assertFalse(validate_problem2(graph, result.solution, True).valid)

    def test_can_spill_buffer_with_no_future_use_until_free(self) -> None:
        data = {
            "Nodes": [
                alloc(0, 0, 8, "UB"),
                op(1, [0]),
                alloc(2, 1, 1024, "UB"),
                free(3, 0, 8, "UB"),
                free(4, 1, 1024, "UB"),
            ],
            "Edges": [[0, 1], [1, 3], [2, 4]],
        }
        graph = build_graph(data, "spill_until_free")
        result = solve_problem2(
            graph,
            (0, 1, 2, 3, 4),
            SearchConfig(
                schedule_policy="reference",
                allocation_strategies=("first_fit",),
                spill_candidate_limit=1,
                max_states=20,
                max_spills=10,
                time_limit_seconds=2,
            ),
        )
        # Buf0换回前需暂时换出占满UB的Buf1，因此会连续产生两对SPILL。
        self.assertEqual(len(result.solution.spill_events), 2)
        self.assertTrue(validate_problem2(graph, result.solution).valid)
        base = graph.node_count
        self.assertEqual(
            [(event.out_id, event.in_id) for event in result.solution.spill_events],
            [(base, base + 1), (base + 2, base + 3)],
        )
        with TemporaryDirectory() as directory:
            paths = write_problem2_files(Path(directory), graph, result.solution, {"test": True})
            validate_submission_files(
                graph,
                result.solution,
                paths["schedule"],
                paths["memory"],
                paths["spill"],
            )
            spill_lines = paths["spill"].read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(spill_lines), 2)


if __name__ == "__main__":
    unittest.main()
