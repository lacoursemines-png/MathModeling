#!/usr/bin/env python3
"""回读并独立验证已经写出的第三问主结果。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap() -> Path:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--problem2-code-dir")
    known, _ = pre.parse_known_args()
    default = Path(__file__).resolve().parent.parent / "Problem_2_Code"
    path = Path(known.problem2_code_dir) if known.problem2_code_dir else default
    if not (path / "problem2" / "__init__.py").exists():
        raise FileNotFoundError(
            f"找不到问题二代码包：{path}。请使用--problem2-code-dir指定。"
        )
    sys.path.insert(0, str(path.resolve()))
    return path.resolve()


PROBLEM2_CODE_DIR = _bootstrap()

from problem2.io import load_graph  # noqa: E402
from problem3.io import load_problem2_solution  # noqa: E402
from problem3.timing import evaluate_timing  # noqa: E402
from problem3.validator import validate_problem3  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="验证第三问正式输出")
    parser.add_argument("--problem2-code-dir", default=str(PROBLEM2_CODE_DIR))
    parser.add_argument("--input", required=True, help="原始JSON目录")
    parser.add_argument("--output", required=True, help="第三问output目录")
    args = parser.parse_args()
    try:
        input_root = Path(args.input)
        output_root = Path(args.output)
        rows = []
        for json_path in sorted(input_root.glob("*.json")):
            graph = load_graph(json_path)
            summary_path = output_root / "logs" / f"{graph.name}_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            expected = summary["main_alpha_0"]
            solution = load_problem2_solution(graph, output_root / "Problem3")
            timing = evaluate_timing(graph, solution)
            validation = validate_problem3(graph, solution, timing, int(expected["Dmax"]), False)
            validation.require_valid()
            if solution.movement != int(expected["actual_D"]):
                raise ValueError(f"{graph.name}回读D与汇总不一致")
            if timing.total_time != int(expected["T"]):
                raise ValueError(f"{graph.name}回读T与汇总不一致")
            row = {
                "task": graph.name,
                "valid": True,
                "actual_D": solution.movement,
                "Dmax": int(expected["Dmax"]),
                "T": timing.total_time,
                "schedule_nodes": len(solution.schedule),
                "spill_events": len(solution.spill_events),
            }
            rows.append(row)
            path = output_root / "logs" / f"{graph.name}_submission_verification.json"
            path.write_text(
                json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"[通过] {graph.name}: D={solution.movement}/{expected['Dmax']}, T={timing.total_time}")
        if not rows:
            raise ValueError("输入目录中没有JSON文件")
        return 0
    except Exception as exc:
        print(f"验证失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
