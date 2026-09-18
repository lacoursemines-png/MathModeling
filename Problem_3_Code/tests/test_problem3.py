from __future__ import annotations

import sys
import unittest
from pathlib import Path

Q2_DIR = Path(r"D:\MathModeling\04_模拟训练\Problem_2_Code")
sys.path.insert(0, str(Q2_DIR))

from problem2.io import build_graph
from problem2.model import Problem2Solution
from problem2.solver import solve_problem2
from problem2.model import SearchConfig

from problem3.scheduler import generate_resource_aware_schedule
from problem3.solver import nondominated_candidates
from problem3.timing import evaluate_timing
from problem3.validator import validate_problem3


def make_solution(data, schedule):
    graph = build_graph(data, "tiny")
    result = solve_problem2(
        graph,
        tuple(schedule),
        SearchConfig(
            schedule_policy="reference",
            allocation_strategies=("first_fit",),
            max_states=10,
            max_spills=20,
            time_limit_seconds=2,
        ),
    )
    return graph, result.solution


class TimingTests(unittest.TestCase):
    def test_different_pipes_run_in_parallel(self):
        data = {
            "Nodes": [
                {"Id": 0, "Op": "A", "Pipe": "P0", "Cycles": 5, "Bufs": []},
                {"Id": 1, "Op": "B", "Pipe": "P1", "Cycles": 7, "Bufs": []},
            ],
            "Edges": [],
        }
        graph, solution = make_solution(data, (0, 1))
        timing = evaluate_timing(graph, solution)
        self.assertEqual(timing.total_time, 7)
        self.assertTrue(validate_problem3(graph, solution, timing, 0).valid)

    def test_same_pipe_is_serial(self):
        data = {
            "Nodes": [
                {"Id": 0, "Op": "A", "Pipe": "P0", "Cycles": 5, "Bufs": []},
                {"Id": 1, "Op": "B", "Pipe": "P0", "Cycles": 7, "Bufs": []},
            ],
            "Edges": [],
        }
        graph, solution = make_solution(data, (0, 1))
        timing = evaluate_timing(graph, solution)
        self.assertEqual(timing.total_time, 12)
        self.assertEqual(timing.pipe_edges, ((0, 1),))

    def test_dependency_across_pipes_is_respected(self):
        data = {
            "Nodes": [
                {"Id": 0, "Op": "A", "Pipe": "P0", "Cycles": 5, "Bufs": []},
                {"Id": 1, "Op": "B", "Pipe": "P1", "Cycles": 7, "Bufs": []},
            ],
            "Edges": [[0, 1]],
        }
        graph, solution = make_solution(data, (0, 1))
        timing = evaluate_timing(graph, solution)
        self.assertEqual(timing.start_time[1], 5)
        self.assertEqual(timing.total_time, 12)

    def test_resource_aware_schedule_is_topological(self):
        data = {
            "Nodes": [
                {"Id": 0, "Op": "A", "Pipe": "P0", "Cycles": 2, "Bufs": []},
                {"Id": 1, "Op": "B", "Pipe": "P1", "Cycles": 3, "Bufs": []},
                {"Id": 2, "Op": "C", "Pipe": "P0", "Cycles": 4, "Bufs": []},
            ],
            "Edges": [[0, 2], [1, 2]],
        }
        graph = build_graph(data, "order")
        for strategy in (
            "critical_path", "earliest_finish", "pipe_balance", "memory_controlled", "hybrid"
        ):
            schedule = generate_resource_aware_schedule(graph, (0, 1, 2), strategy)
            position = {node_id: index for index, node_id in enumerate(schedule)}
            self.assertLess(position[0], position[2])
            self.assertLess(position[1], position[2])


if __name__ == "__main__":
    unittest.main()
