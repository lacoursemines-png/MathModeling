from __future__ import annotations

import unittest

from problem1.evaluator import compute_peak, validate_problem1
from problem1.io import InputValidationError, build_graph
from problem1.scheduler import solve_problem1


def alloc(node_id: int, buf_id: int, size: int, memory_type: str) -> dict[str, object]:
    return {"Id": node_id, "Op": "ALLOC", "BufId": buf_id, "Size": size, "Type": memory_type}


def free(node_id: int, buf_id: int, size: int, memory_type: str) -> dict[str, object]:
    return {"Id": node_id, "Op": "FREE", "BufId": buf_id, "Size": size, "Type": memory_type}


def op(node_id: int, bufs: list[int], name: str = "CALC") -> dict[str, object]:
    return {"Id": node_id, "Op": name, "Pipe": "VECTOR", "Cycles": 1, "Bufs": bufs}


class Problem1Tests(unittest.TestCase):
    def test_peak_and_lifecycle(self) -> None:
        data = {
            "Nodes": [
                alloc(0, 0, 10, "L1"),
                alloc(1, 1, 7, "UB"),
                op(2, [0, 1]),
                free(3, 0, 10, "L1"),
                free(4, 1, 7, "UB"),
            ],
            "Edges": [[0, 2], [1, 2], [2, 3], [2, 4]],
        }
        graph = build_graph(data, "peak")
        schedule = (0, 1, 2, 3, 4)
        self.assertTrue(validate_problem1(graph, schedule).valid)
        self.assertEqual(compute_peak(graph, schedule).peak, 17)
        self.assertEqual(compute_peak(graph, schedule).trace, (10, 17, 17, 7, 0))

    def test_validator_rejects_l0_overlap(self) -> None:
        data = {
            "Nodes": [
                alloc(0, 0, 8, "L0A"),
                alloc(1, 1, 8, "L0A"),
                op(2, [0]),
                op(3, [1]),
                free(4, 0, 8, "L0A"),
                free(5, 1, 8, "L0A"),
            ],
            "Edges": [[0, 2], [2, 4], [1, 3], [3, 5]],
        }
        graph = build_graph(data, "l0")
        result = validate_problem1(graph, (0, 1, 2, 3, 4, 5))
        self.assertFalse(result.valid)
        self.assertTrue(any("L0A" in error for error in result.errors))

    def test_scheduler_closes_l0_before_next_alloc(self) -> None:
        data = {
            "Nodes": [
                alloc(0, 0, 8, "L0A"),
                alloc(1, 1, 8, "L0A"),
                op(2, [0]),
                op(3, [1]),
                free(4, 0, 8, "L0A"),
                free(5, 1, 8, "L0A"),
            ],
            "Edges": [[0, 2], [2, 4], [1, 3], [3, 5]],
        }
        graph = build_graph(data, "l0_schedule")
        result = solve_problem1(graph, local_window_radius=0, local_passes=0)
        self.assertTrue(validate_problem1(graph, result.schedule).valid)

    def test_derived_lifecycle_edges_prevent_early_free(self) -> None:
        data = {
            "Nodes": [alloc(0, 0, 4, "L1"), free(1, 0, 4, "L1"), op(2, [0])],
            # 故意不提供生命周期边；调度增强图必须补齐ALLOC->use->FREE。
            "Edges": [],
        }
        graph = build_graph(data, "derived")
        result = solve_problem1(graph, strategies=("id",), local_window_radius=0, local_passes=0)
        self.assertEqual(result.schedule, (0, 2, 1))
        self.assertTrue(validate_problem1(graph, result.schedule).valid)

    def test_input_rejects_mismatched_free(self) -> None:
        data = {
            "Nodes": [alloc(0, 0, 4, "L1"), free(1, 0, 5, "L1")],
            "Edges": [[0, 1]],
        }
        with self.assertRaises(InputValidationError):
            build_graph(data, "bad")


if __name__ == "__main__":
    unittest.main()
