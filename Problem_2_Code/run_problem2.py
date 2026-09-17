#!/usr/bin/env python3
"""A题第二问命令行入口。"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from problem2.io import load_graph, load_schedule, write_problem2_files
from problem2.model import SearchConfig
from problem2.solver import solve_problem2
from problem2.validator import validate_problem2, validate_submission_files


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A题第二问连续地址分配与SPILL搜索")
    parser.add_argument("--input", required=True, help="单个JSON或JSON目录")
    parser.add_argument("--schedule-dir", required=True, help="第一问schedule所在目录")
    parser.add_argument("--output", required=True, help="第二问输出根目录")
    parser.add_argument("--allocation-strategies", default="first_fit,best_fit")
    parser.add_argument(
        "--schedule-policy",
        choices=("capacity_aware", "reference"),
        default="capacity_aware",
        help="第二问拓扑序策略；reference仅用于对照",
    )
    parser.add_argument("--spill-candidates", type=int, default=3)
    parser.add_argument("--max-states", type=int, default=250)
    parser.add_argument("--max-spills", type=int, default=10000)
    parser.add_argument("--time-limit", type=float, default=10.0, help="每种分配策略的秒数上限")
    parser.add_argument("--enforce-l0-single", action="store_true", help="仅用于对照实验，默认关闭")
    return parser.parse_args()


def _files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() == ".json":
        return [path]
    if path.is_dir():
        result = sorted(path.glob("*.json"))
        if result:
            return result
    raise ValueError(f"输入路径不是JSON文件或含JSON的目录：{path}")


def main() -> int:
    args = _args()
    try:
        strategies = tuple(x.strip() for x in args.allocation_strategies.split(",") if x.strip())
        config = SearchConfig(
            schedule_policy=args.schedule_policy,
            allocation_strategies=strategies,
            spill_candidate_limit=args.spill_candidates,
            max_states=args.max_states,
            max_spills=args.max_spills,
            time_limit_seconds=args.time_limit,
            enforce_l0_single=args.enforce_l0_single,
        )
        if min(args.spill_candidates, args.max_states, args.max_spills) <= 0 or args.time_limit <= 0:
            raise ValueError("搜索上限参数必须为正数")
        output = Path(args.output)
        all_results: list[dict[str, object]] = []
        for json_path in _files(Path(args.input)):
            print(f"[开始] {json_path.name}", flush=True)
            graph = load_graph(json_path)
            schedule_path = Path(args.schedule_dir) / f"{graph.name}_schedule.txt"
            original_schedule = load_schedule(schedule_path, graph)
            result = solve_problem2(graph, original_schedule, config)
            solution = result.solution
            validation = validate_problem2(graph, solution, config.enforce_l0_single)
            validation.require_valid()
            summary: dict[str, object] = {
                "task": graph.name,
                "nodes": graph.node_count,
                "edges": graph.edge_count,
                "buffers": len(graph.buffers),
                "spill_count": len(solution.spill_events),
                "movement": solution.movement,
                "allocation_strategy": solution.allocation_strategy,
                "resident_segments": len(solution.resident_segments),
                "reuse_edges": len(solution.reuse_edges),
                "spill_edges": len(solution.spill_edges),
                "runtime_seconds": round(result.runtime_seconds, 6),
                "valid": validation.valid,
                "algorithm": "capacity_aware_topological+belady_spill+bounded_best_first",
                "deterministic": True,
                "random_seed": None,
                "objective_order": ["movement", "spill_count", "allocation_strategy_name"],
                "lookahead_window": "exact_next_use_or_free_no_fixed_window",
                "frontier_policy": "best_first_bounded_by_max_states_not_fixed_beam",
                "config": {
                    "schedule_policy": config.schedule_policy,
                    "allocation_strategies": list(config.allocation_strategies),
                    "spill_candidate_limit": config.spill_candidate_limit,
                    "max_states": config.max_states,
                    "max_spills": config.max_spills,
                    "time_limit_seconds_per_strategy": config.time_limit_seconds,
                    "enforce_l0_single": config.enforce_l0_single,
                },
                "attempts": [
                    {
                        "allocation_strategy": attempt.allocation_strategy,
                        "success": attempt.success,
                        "movement": attempt.movement,
                        "spill_count": attempt.spill_count,
                        "expanded_states": attempt.expanded_states,
                        "runtime_seconds": round(attempt.runtime_seconds, 6),
                        "stop_reason": attempt.stop_reason,
                        "last_failure": None
                        if attempt.failure is None
                        else {
                            "position": attempt.failure.schedule_position,
                            "buf_id": attempt.failure.buf_id,
                            "memory_type": attempt.failure.memory_type,
                            "required_size": attempt.failure.required_size,
                            "total_free": attempt.failure.total_free,
                            "largest_hole": attempt.failure.largest_hole,
                        },
                    }
                    for attempt in result.attempts
                ],
                "python": platform.python_version(),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "result_claim": "best_known_feasible_not_global_optimum",
            }
            paths = write_problem2_files(output, graph, solution, summary)
            validate_submission_files(
                graph,
                solution,
                paths["schedule"],
                paths["memory"],
                paths["spill"],
            )
            item = {
                "task": graph.name,
                "movement": solution.movement,
                "spill_count": len(solution.spill_events),
                "strategy": solution.allocation_strategy,
                "runtime_seconds": round(result.runtime_seconds, 6),
            }
            all_results.append(item)
            print(
                f"[完成] {graph.name}: D={solution.movement}, SPILL={len(solution.spill_events)}, "
                f"strategy={solution.allocation_strategy}, time={result.runtime_seconds:.3f}s",
                flush=True,
            )
        log_dir = output / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        aggregate_json = log_dir / "problem2_all_cases_summary.json"
        aggregate_csv = log_dir / "problem2_all_cases_summary.csv"
        aggregate_json.write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with aggregate_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("task", "movement", "spill_count", "strategy", "runtime_seconds"),
            )
            writer.writeheader()
            writer.writerows(all_results)
        print(json.dumps(all_results, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
