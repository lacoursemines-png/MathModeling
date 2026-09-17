"""第二问输入、提交文件和分析文件读写。"""

from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from .model import (
    Buffer,
    CAPACITIES,
    Graph,
    MANAGEMENT_OPS,
    MEMORY_TYPES,
    Node,
    Problem2Solution,
)


class InputValidationError(ValueError):
    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(errors)
        detail = "\n".join(f"- {item}" for item in self.errors[:30])
        super().__init__(f"输入体检失败：\n{detail}")


def _as_int(value: Any, field: str, errors: list[str], minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{field}必须是整数，实际为{value!r}")
        return None
    if value < minimum:
        errors.append(f"{field}必须不小于{minimum}，实际为{value}")
        return None
    return value


def _parse_node(raw: Any, index: int, errors: list[str]) -> Node | None:
    where = f"Nodes[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where}必须是对象")
        return None
    node_id = _as_int(raw.get("Id"), f"{where}.Id", errors)
    op = raw.get("Op")
    if node_id is None or not isinstance(op, str) or not op:
        if not isinstance(op, str) or not op:
            errors.append(f"{where}.Op必须是非空字符串")
        return None
    if op in MANAGEMENT_OPS:
        buf_id = _as_int(raw.get("BufId"), f"{where}.BufId", errors)
        size = _as_int(raw.get("Size"), f"{where}.Size", errors, 1)
        memory_type = raw.get("Type")
        if memory_type not in MEMORY_TYPES:
            errors.append(f"{where}.Type非法：{memory_type!r}")
            memory_type = None
        if buf_id is None or size is None or memory_type is None:
            return None
        if size > CAPACITIES[memory_type]:
            errors.append(
                f"{where}申请长度{size}超过{memory_type}容量{CAPACITIES[memory_type]}"
            )
        return Node(node_id, op, buf_id, size, memory_type)

    pipe = raw.get("Pipe")
    cycles = _as_int(raw.get("Cycles"), f"{where}.Cycles", errors)
    raw_bufs = raw.get("Bufs")
    if not isinstance(pipe, str) or not pipe:
        errors.append(f"{where}.Pipe必须是非空字符串")
        pipe = None
    if not isinstance(raw_bufs, list):
        errors.append(f"{where}.Bufs必须是列表")
        raw_bufs = []
    bufs: list[int] = []
    for j, value in enumerate(raw_bufs):
        buf_id = _as_int(value, f"{where}.Bufs[{j}]", errors)
        if buf_id is not None:
            bufs.append(buf_id)
    if len(bufs) != len(set(bufs)):
        errors.append(f"{where}.Bufs含重复BufId")
    if pipe is None or cycles is None:
        return None
    return Node(node_id, op, pipe=pipe, cycles=cycles, bufs=tuple(bufs))


def build_graph(data: Any, name: str) -> Graph:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise InputValidationError(["JSON顶层必须是对象"])
    raw_nodes = data.get("Nodes")
    raw_edges = data.get("Edges")
    if not isinstance(raw_nodes, list):
        errors.append("Nodes必须是列表")
        raw_nodes = []
    if not isinstance(raw_edges, list):
        errors.append("Edges必须是列表")
        raw_edges = []

    nodes: dict[int, Node] = {}
    for i, raw in enumerate(raw_nodes):
        node = _parse_node(raw, i, errors)
        if node is None:
            continue
        if node.id in nodes:
            errors.append(f"节点Id重复：{node.id}")
        nodes[node.id] = node
    if set(nodes) != set(range(len(raw_nodes))):
        errors.append("原始节点Id必须从0开始连续编号")

    edges: list[tuple[int, int]] = []
    edge_set: set[tuple[int, int]] = set()
    for i, raw in enumerate(raw_edges):
        if not isinstance(raw, list) or len(raw) != 2:
            errors.append(f"Edges[{i}]必须是两个节点Id组成的列表")
            continue
        source = _as_int(raw[0], f"Edges[{i}][0]", errors)
        target = _as_int(raw[1], f"Edges[{i}][1]", errors)
        if source is None or target is None:
            continue
        if source not in nodes or target not in nodes or source == target:
            errors.append(f"非法依赖边：({source},{target})")
            continue
        if (source, target) in edge_set:
            errors.append(f"重复依赖边：({source},{target})")
            continue
        edge_set.add((source, target))
        edges.append((source, target))

    allocs: dict[int, Node] = {}
    frees: dict[int, Node] = {}
    uses: dict[int, list[int]] = defaultdict(list)
    copy_in_count: dict[int, int] = defaultdict(int)
    for node in nodes.values():
        if node.is_alloc:
            assert node.buf_id is not None
            if node.buf_id in allocs:
                errors.append(f"BufId {node.buf_id}存在多个ALLOC")
            allocs[node.buf_id] = node
        elif node.is_free:
            assert node.buf_id is not None
            if node.buf_id in frees:
                errors.append(f"BufId {node.buf_id}存在多个FREE")
            frees[node.buf_id] = node
        else:
            for buf_id in node.bufs:
                uses[buf_id].append(node.id)
                if node.op == "COPY_IN":
                    copy_in_count[buf_id] += 1

    buffers: dict[int, Buffer] = {}
    for buf_id in sorted(set(allocs) | set(frees) | set(uses)):
        alloc = allocs.get(buf_id)
        free = frees.get(buf_id)
        if alloc is None or free is None:
            errors.append(f"BufId {buf_id}缺少ALLOC或FREE")
            continue
        if alloc.size != free.size or alloc.memory_type != free.memory_type:
            errors.append(f"BufId {buf_id}的ALLOC/FREE属性不一致")
            continue
        if copy_in_count[buf_id] > 1:
            errors.append(f"BufId {buf_id}被多个COPY_IN节点使用")
        buffers[buf_id] = Buffer(
            buf_id,
            alloc.size or 0,
            alloc.memory_type or "",
            alloc.id,
            free.id,
            tuple(sorted(uses.get(buf_id, []))),
            copy_in_count[buf_id] == 1,
        )

    if errors:
        raise InputValidationError(errors)

    successors: dict[int, list[int]] = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}
    for source, target in edges:
        successors[source].append(target)
        indegree[target] += 1
    ready = deque(node_id for node_id in sorted(nodes) if indegree[node_id] == 0)
    seen = 0
    while ready:
        node_id = ready.popleft()
        seen += 1
        for target in successors[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if seen != len(nodes):
        raise InputValidationError(["原始计算图不是DAG"])
    return Graph(
        name,
        nodes,
        buffers,
        tuple(edges),
        {node_id: tuple(sorted(values)) for node_id, values in successors.items()},
    )


def load_graph(path: str | Path) -> Graph:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig") as handle:
        return build_graph(json.load(handle), source.stem)


def load_schedule(path: str | Path, graph: Graph) -> tuple[int, ...]:
    source = Path(path)
    values: list[int] = []
    for line_no, line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            values.append(int(text))
        except ValueError as exc:
            raise InputValidationError([f"{source.name}第{line_no}行不是整数：{text!r}"]) from exc
    expected = set(graph.nodes)
    if len(values) != graph.node_count or len(set(values)) != len(values) or set(values) != expected:
        raise InputValidationError([f"{source.name}不是全部原始节点的无重复完整排列"])
    position = {node_id: i for i, node_id in enumerate(values)}
    violations = [edge for edge in graph.original_edges if position[edge[0]] >= position[edge[1]]]
    if violations:
        raise InputValidationError([f"第一问schedule违反原始依赖边：{violations[:10]}"])
    return tuple(values)


def write_problem2_files(
    output_root: str | Path,
    graph: Graph,
    solution: Problem2Solution,
    summary: dict[str, Any],
) -> dict[str, Path]:
    root = Path(output_root)
    problem_dir = root / "Problem2"
    log_dir = root / "logs"
    problem_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    schedule_path = problem_dir / f"{graph.name}_schedule.txt"
    memory_path = problem_dir / f"{graph.name}_memory.txt"
    spill_path = problem_dir / f"{graph.name}_spill.txt"
    segments_path = log_dir / f"{graph.name}_resident_segments.csv"
    summary_path = log_dir / f"{graph.name}_summary.json"

    schedule_path.write_text("".join(f"{node_id}\n" for node_id in solution.schedule), encoding="utf-8")
    memory_path.write_text(
        "".join(f"{buf_id}:{solution.initial_offsets[buf_id]}\n" for buf_id in sorted(graph.buffers)),
        encoding="utf-8",
    )
    spill_path.write_text(
        "".join(f"{event.buf_id}:{event.new_offset}\n" for event in solution.spill_events),
        encoding="utf-8",
    )
    with segments_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "buf_id",
                "segment_index",
                "memory_type",
                "size",
                "acquire_node",
                "release_node",
                "acquire_position",
                "release_position",
                "offset",
                "created_by_spill",
            ]
        )
        for segment in solution.resident_segments:
            writer.writerow(
                [
                    segment.buf_id,
                    segment.segment_index,
                    segment.memory_type,
                    segment.size,
                    segment.acquire_node,
                    segment.release_node,
                    segment.acquire_position,
                    segment.release_position,
                    segment.offset,
                    int(segment.created_by_spill),
                ]
            )
    with summary_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "schedule": schedule_path,
        "memory": memory_path,
        "spill": spill_path,
        "segments": segments_path,
        "summary": summary_path,
    }
