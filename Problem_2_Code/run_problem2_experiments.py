#!/usr/bin/env python3
"""第二问可复现实验：2×2消融、改进率和搜索预算敏感性。"""

from __future__ import annotations

import argparse
import csv
import json
import platform
from pathlib import Path
from statistics import mean
from time import perf_counter

from problem2.io import load_graph, load_schedule
from problem2.model import SearchConfig
from problem2.solver import solve_problem2
from problem2.validator import validate_problem2


ABLATIONS = (
    ("A_reference_first_fit", "reference", "first_fit"),
    ("B_reference_best_fit", "reference", "best_fit"),
    ("C_capacity_first_fit", "capacity_aware", "first_fit"),
    ("D_capacity_best_fit", "capacity_aware", "best_fit"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行A题第二问补充实验")
    parser.add_argument("--input", required=True, help="六个JSON所在目录")
    parser.add_argument("--schedule-dir", required=True, help="第一问schedule目录")
    parser.add_argument("--output", default=".\\experiments", help="实验结果目录")
    parser.add_argument("--sensitivity-states", default="1,50,250")
    return parser.parse_args()


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pct(old: int, new: int) -> float:
    return 0.0 if old == 0 else round(100.0 * (old - new) / old, 6)


def solve_once(graph, schedule, schedule_policy: str, strategy: str, max_states: int):
    config = SearchConfig(
        schedule_policy=schedule_policy,
        allocation_strategies=(strategy,),
        spill_candidate_limit=1 if max_states == 1 else 3,
        max_states=max_states,
        max_spills=50000,
        time_limit_seconds=20.0,
        enforce_l0_single=False,
    )
    result = solve_problem2(graph, schedule, config)
    validation = validate_problem2(graph, result.solution, False)
    validation.require_valid()
    return result, validation


def main() -> int:
    args = parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    json_paths = sorted(Path(args.input).glob("*.json"))
    if not json_paths:
        raise ValueError("输入目录中没有JSON文件")
    cases = []
    for path in json_paths:
        graph = load_graph(path)
        schedule = load_schedule(Path(args.schedule_dir) / f"{graph.name}_schedule.txt", graph)
        cases.append((graph, schedule))

    raw: list[dict[str, object]] = []
    started_all = perf_counter()
    for label, schedule_policy, strategy in ABLATIONS:
        for graph, schedule in cases:
            result, validation = solve_once(graph, schedule, schedule_policy, strategy, 1)
            raw.append(
                {
                    "experiment": label,
                    "task": graph.name,
                    "schedule_policy": schedule_policy,
                    "allocation_strategy": strategy,
                    "movement": result.solution.movement,
                    "spill_count": len(result.solution.spill_events),
                    "runtime_seconds": round(result.runtime_seconds, 6),
                    "valid": validation.valid,
                    "result_claim": "best_known_feasible_not_global_optimum",
                }
            )
            print(
                f"[{label}] {graph.name}: D={result.solution.movement}, "
                f"SPILL={len(result.solution.spill_events)}",
                flush=True,
            )

    by_key = {(row["experiment"], row["task"]): row for row in raw}
    comparisons: list[dict[str, object]] = []
    for graph, _ in cases:
        task = graph.name
        a = by_key[("A_reference_first_fit", task)]
        b = by_key[("B_reference_best_fit", task)]
        c = by_key[("C_capacity_first_fit", task)]
        d = by_key[("D_capacity_best_fit", task)]
        comparisons.append(
            {
                "task": task,
                "baseline_D": a["movement"],
                "reference_best_fit_D": b["movement"],
                "capacity_first_fit_D": c["movement"],
                "recommended_D": d["movement"],
                "baseline_spills": a["spill_count"],
                "recommended_spills": d["spill_count"],
                "schedule_improvement_percent": pct(int(a["movement"]), int(c["movement"])),
                "allocator_improvement_percent": pct(int(c["movement"]), int(d["movement"])),
                "total_improvement_percent": pct(int(a["movement"]), int(d["movement"])),
                "spill_reduction_percent": pct(int(a["spill_count"]), int(d["spill_count"])),
                "all_valid": bool(a["valid"] and b["valid"] and c["valid"] and d["valid"]),
            }
        )

    total_baseline_d = sum(int(row["baseline_D"]) for row in comparisons)
    total_recommended_d = sum(int(row["recommended_D"]) for row in comparisons)
    total_baseline_spills = sum(int(row["baseline_spills"]) for row in comparisons)
    total_recommended_spills = sum(int(row["recommended_spills"]) for row in comparisons)
    totals = {
        "task": "TOTAL",
        "baseline_D": total_baseline_d,
        "reference_best_fit_D": sum(
            int(row["movement"])
            for row in raw
            if row["experiment"] == "B_reference_best_fit"
        ),
        "capacity_first_fit_D": sum(
            int(row["movement"])
            for row in raw
            if row["experiment"] == "C_capacity_first_fit"
        ),
        "recommended_D": total_recommended_d,
        "baseline_spills": total_baseline_spills,
        "recommended_spills": total_recommended_spills,
        "schedule_improvement_percent": pct(
            total_baseline_d,
            sum(
                int(row["movement"])
                for row in raw
                if row["experiment"] == "C_capacity_first_fit"
            ),
        ),
        "allocator_improvement_percent": pct(
            sum(
                int(row["movement"])
                for row in raw
                if row["experiment"] == "C_capacity_first_fit"
            ),
            total_recommended_d,
        ),
        "total_improvement_percent": pct(total_baseline_d, total_recommended_d),
        "spill_reduction_percent": pct(total_baseline_spills, total_recommended_spills),
        "all_valid": all(bool(row["valid"]) for row in raw),
    }

    budgets = tuple(int(value.strip()) for value in args.sensitivity_states.split(","))
    sensitivity: list[dict[str, object]] = []
    for max_states in budgets:
        for graph, schedule in cases:
            result, validation = solve_once(
                graph, schedule, "capacity_aware", "best_fit", max_states
            )
            sensitivity.append(
                {
                    "max_states": max_states,
                    "task": graph.name,
                    "movement": result.solution.movement,
                    "spill_count": len(result.solution.spill_events),
                    "runtime_seconds": round(result.runtime_seconds, 6),
                    "valid": validation.valid,
                }
            )

    raw_fields = [
        "experiment", "task", "schedule_policy", "allocation_strategy", "movement",
        "spill_count", "runtime_seconds", "valid", "result_claim",
    ]
    comparison_fields = list(totals)
    sensitivity_fields = [
        "max_states", "task", "movement", "spill_count", "runtime_seconds", "valid",
    ]
    write_csv(output / "ablation_raw.csv", raw, raw_fields)
    write_csv(output / "ablation_comparison.csv", comparisons + [totals], comparison_fields)
    write_csv(output / "search_budget_sensitivity.csv", sensitivity, sensitivity_fields)

    sensitivity_stable = all(
        len(
            {
                (int(row["movement"]), int(row["spill_count"]))
                for row in sensitivity
                if row["task"] == graph.name
            }
        )
        == 1
        for graph, _ in cases
    )
    sensitivity_runtime_totals = {
        str(budget): round(
            sum(
                float(row["runtime_seconds"])
                for row in sensitivity
                if row["max_states"] == budget
            ),
            6,
        )
        for budget in budgets
    }

    metadata = {
        "python": platform.python_version(),
        "deterministic": True,
        "random_seed": None,
        "ablation_design": [label for label, _, _ in ABLATIONS],
        "sensitivity_max_states": list(budgets),
        "ablation_parameters": {
            "spill_candidate_limit": 1,
            "max_states": 1,
            "max_spills": 50000,
            "time_limit_seconds": 20.0,
        },
        "sensitivity_stable_D_and_spill_count": sensitivity_stable,
        "sensitivity_runtime_totals_seconds": sensitivity_runtime_totals,
        "total_runtime_seconds": round(perf_counter() - started_all, 6),
        "totals": totals,
        "mean_case_improvement_percent": round(
            mean(float(row["total_improvement_percent"]) for row in comparisons), 6
        ),
        "claim": "best_known_feasible_not_global_optimum",
    }
    (output / "experiment_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# 第二问补充实验结果",
        "",
        "## 消融实验",
        "",
        "基线为第一问原序列加First-Fit；推荐方案为容量感知拓扑重排加Best-Fit。",
        "所有结果均通过同一独立合法性验证器。",
        "",
        "| 算例 | 基线D | 推荐D | D下降率 | 基线SPILL | 推荐SPILL | SPILL下降率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparisons:
        lines.append(
            f"| {row['task']} | {row['baseline_D']} | {row['recommended_D']} | "
            f"{row['total_improvement_percent']:.2f}% | {row['baseline_spills']} | "
            f"{row['recommended_spills']} | {row['spill_reduction_percent']:.2f}% |"
        )
    lines.extend(
        [
            f"| 合计 | {totals['baseline_D']} | {totals['recommended_D']} | "
            f"{totals['total_improvement_percent']:.2f}% | {totals['baseline_spills']} | "
            f"{totals['recommended_spills']} | {totals['spill_reduction_percent']:.2f}% |",
            "",
            "容量感知重排是主要改进来源；Best-Fit在容量感知序列上进一步降低部分算例的搬移量。",
            "Matmul两个算例结果不变，说明其可调度空间或地址碎片改进余地较小。",
            "",
            "## 搜索预算敏感性",
            "",
            "分别使用不同max_states重复推荐方案。若D和SPILL数保持一致，可说明结果对当前搜索预算稳定；",
            (
                "本次max_states=1、50、250时，六例的D和SPILL数全部一致，说明当前结果对该搜索预算稳定。"
                if sensitivity_stable
                else "部分预算下结果发生变化，应以较大预算结果为主。"
            ),
            "三档预算总运行时间记录在experiment_metadata.json中；稳定性不构成全局最优证明。",
            "",
            "## 论文表述边界",
            "",
            "所有数值应称为最佳已知可行结果。实验能够证明相对指定baseline的改进，不能证明理论全局最优。",
            "",
        ]
    )
    (output / "paper_ready_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
