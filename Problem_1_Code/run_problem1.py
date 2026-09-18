#!/usr/bin/env python3
"""A题第一问命令行入口。仅使用Python标准库。更改"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from problem1 import load_graph, solve_problem1, validate_problem1, write_problem1_result
from problem1.scheduler import DEFAULT_STRATEGIES


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="为一个JSON文件或一个目录中的全部JSON文件生成A题第一问低峰值拓扑序。"
    )
    parser.add_argument("--input", required=True, help="单个.json文件，或包含.json文件的目录")
    parser.add_argument("--output", required=True, help="输出根目录；程序会在其中创建Problem1和logs")
    parser.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGIES),
        help=f"逗号分隔策略，默认={','.join(DEFAULT_STRATEGIES)}",
    )
    parser.add_argument(
        "--local-window-radius",
        type=int,
        default=100,
        help="峰值窗口向前/向后的节点数；0表示关闭局部改进",
    )
    parser.add_argument("--local-passes", type=int, default=2, help="局部窗口最大改进轮数")
    parser.add_argument("--trace", action="store_true", help="额外输出逐节点L1+UB驻留曲线CSV")
    return parser.parse_args()


def _input_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() != ".json":
            raise ValueError(f"输入文件必须是.json：{path}")
        return [path]
    if path.is_dir():
        files = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".json")
        if not files:
            raise ValueError(f"目录中没有.json文件：{path}")
        return files
    raise FileNotFoundError(f"找不到输入路径：{path}")


def _solve_one(path: Path, output: Path, args: argparse.Namespace) -> dict[str, object]:
    graph = load_graph(path)
    strategies = tuple(item.strip() for item in args.strategies.split(",") if item.strip())
    result = solve_problem1(
        graph,
        strategies,
        local_window_radius=args.local_window_radius,
        local_passes=args.local_passes,
    )
    validation = validate_problem1(graph, result.schedule)
    validation.require_valid()

    baseline_peak = next(
        (run.peak for run in result.strategy_runs if run.strategy == "id" and run.success),
        None,
    )
    summary: dict[str, object] = {
        "task": graph.name,
        "nodes": graph.node_count,
        "edges": graph.edge_count,
        "buffers": len(graph.buffers),
        "baseline_peak": baseline_peak,
        "best_peak": result.evaluation.peak,
        "improvement": None if baseline_peak is None else baseline_peak - result.evaluation.peak,
        "selected_strategy": result.selected_strategy,
        "local_improvements": result.local_improvements,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "valid": validation.valid,
        "algorithm_config": {
            "strategies": list(strategies),
            "local_window_radius": args.local_window_radius,
            "local_passes": args.local_passes,
            "deterministic_tie_break": "node_id",
        },
        "strategy_runs": [
            {
                "strategy": run.strategy,
                "success": run.success,
                "peak": run.peak,
                "runtime_seconds": round(run.runtime_seconds, 6),
                "failure_reason": run.failure_reason,
            }
            for run in result.strategy_runs
        ],
        "python": platform.python_version(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "result_claim": "best_known_feasible_not_global_optimum",
    }
    schedule_path, summary_path, trace_path = write_problem1_result(
        output,
        graph,
        result.schedule,
        summary,
        result.evaluation.trace if args.trace else None,
    )

    # 写出后回读，防止编码、换行或截断造成提交文件损坏。
    reloaded = tuple(
        int(line.strip())
        for line in schedule_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    )
    validate_problem1(graph, reloaded).require_valid()
    return {
        "task": graph.name,
        "peak": result.evaluation.peak,
        "baseline_peak": baseline_peak,
        "runtime_seconds": round(result.runtime_seconds, 6),
        "schedule": str(schedule_path),
        "summary": str(summary_path),
        "trace": None if trace_path is None else str(trace_path),
    }


def main() -> int:
    args = _parse_args()
    if args.local_window_radius < 0 or args.local_passes < 0:
        print("错误：局部窗口和轮数不能为负数", file=sys.stderr)
        return 2
    try:
        files = _input_files(Path(args.input))
        output = Path(args.output)
        results = []
        for path in files:
            print(f"[开始] {path.name}", flush=True)
            item = _solve_one(path, output, args)
            results.append(item)
            print(
                f"[完成] {item['task']}: Pmax={item['peak']}, "
                f"baseline={item['baseline_peak']}, 用时={item['runtime_seconds']}s",
                flush=True,
            )
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # 命令行入口需要给出明确错误并返回非零状态。
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
