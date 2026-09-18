#!/usr/bin/env python3
"""A题第三问命令行入口。"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def _bootstrap_problem2() -> Path:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--problem2-code-dir")
    known, _ = pre.parse_known_args()
    default = Path(__file__).resolve().parent.parent / "Problem_2_Code"
    path = Path(known.problem2_code_dir) if known.problem2_code_dir else default
    if not (path / "problem2" / "__init__.py").exists():
        raise FileNotFoundError(
            f"找不到问题二代码包：{path}。请使用--problem2-code-dir指定Problem_2_Code。"
        )
    sys.path.insert(0, str(path.resolve()))
    return path.resolve()


PROBLEM2_CODE_DIR = _bootstrap_problem2()

from problem2.io import load_graph  # noqa: E402
from problem3.io import load_problem2_solution, write_case_outputs  # noqa: E402
from problem3.model import Problem3Config  # noqa: E402
from problem3.solver import solve_problem3_case  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A题第三问真实执行时间优化")
    parser.add_argument("--problem2-code-dir", default=str(PROBLEM2_CODE_DIR))
    parser.add_argument("--input", required=True, help="单个JSON或JSON目录")
    parser.add_argument("--problem2-output", required=True, help="问题二Problem2结果目录")
    parser.add_argument("--output", required=True, help="第三问输出根目录")
    parser.add_argument("--alphas", default="0,0.02,0.05,0.10")
    parser.add_argument(
        "--strategies",
        default="critical_path,earliest_finish,pipe_balance,memory_controlled,hybrid",
    )
    parser.add_argument("--q2-allocation-strategies", default="first_fit,best_fit")
    parser.add_argument("--q2-spill-candidates", type=int, default=1)
    parser.add_argument("--q2-max-states", type=int, default=1)
    parser.add_argument("--q2-max-spills", type=int, default=50000)
    parser.add_argument("--q2-time-limit", type=float, default=20.0)
    parser.add_argument("--local-windows", default="16,64")
    parser.add_argument("--local-candidates-per-window", type=int, default=2)
    parser.add_argument("--max-candidate-schedules", type=int, default=12)
    parser.add_argument("--enforce-l0-single", action="store_true")
    return parser.parse_args()


def input_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() == ".json":
        return [path]
    if path.is_dir():
        values = sorted(path.glob("*.json"))
        if values:
            return values
    raise ValueError(f"输入路径不是JSON文件或含JSON的目录：{path}")


def csv_tuple(text: str, cast):
    values = tuple(cast(value.strip()) for value in text.split(",") if value.strip())
    if not values:
        raise ValueError("配置列表不能为空")
    return values


def main() -> int:
    args = parse_args()
    try:
        config = Problem3Config(
            alphas=csv_tuple(args.alphas, float),
            scheduling_strategies=csv_tuple(args.strategies, str),
            q2_allocation_strategies=csv_tuple(args.q2_allocation_strategies, str),
            q2_spill_candidate_limit=args.q2_spill_candidates,
            q2_max_states=args.q2_max_states,
            q2_max_spills=args.q2_max_spills,
            q2_time_limit_seconds=args.q2_time_limit,
            local_window_sizes=csv_tuple(args.local_windows, int),
            local_candidates_per_window=args.local_candidates_per_window,
            max_candidate_schedules=args.max_candidate_schedules,
            enforce_l0_single=args.enforce_l0_single,
        )
        if any(alpha < 0 for alpha in config.alphas) or 0.0 not in config.alphas:
            raise ValueError("alphas必须包含0且全部非负")
        if min(
            config.q2_spill_candidate_limit,
            config.q2_max_states,
            config.q2_max_spills,
            config.local_candidates_per_window,
            config.max_candidate_schedules,
        ) <= 0:
            raise ValueError("搜索上限参数必须为正数")
        output = Path(args.output)
        aggregate: list[dict[str, object]] = []
        for json_path in input_files(Path(args.input)):
            print(f"[开始] {json_path.name}", flush=True)
            graph = load_graph(json_path)
            q2_solution = load_problem2_solution(graph, args.problem2_output)
            result = solve_problem3_case(graph, q2_solution, config)
            write_case_outputs(output, graph, result)
            baseline_t = result.baseline.timing.total_time
            for budget in result.budgets:
                aggregate.append(
                    {
                        "task": graph.name,
                        "alpha": budget.alpha,
                        "Dmax": budget.d_max,
                        "actual_D": budget.selected.movement,
                        "T": budget.selected.timing.total_time,
                        "baseline_T": baseline_t,
                        "time_improvement_percent": round(
                            100.0 * (baseline_t - budget.selected.timing.total_time) / baseline_t,
                            6,
                        )
                        if baseline_t
                        else 0.0,
                        "candidate": budget.selected.name,
                        "status": "improved"
                        if budget.improved_time
                        else "在当前搜索设置下未改善",
                    }
                )
            main_budget = next(item for item in result.budgets if item.alpha == 0.0)
            print(
                f"[完成] {graph.name}: baseline T={baseline_t}, main T={main_budget.selected.timing.total_time}, "
                f"D={main_budget.selected.movement}/{main_budget.d_max}, "
                f"candidate={main_budget.selected.name}",
                flush=True,
            )

        log_dir = output / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fields = list(aggregate[0])
        with (log_dir / "problem3_all_cases_budgets.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(aggregate)
        (log_dir / "problem3_all_cases_budgets.json").write_text(
            json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(aggregate, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
