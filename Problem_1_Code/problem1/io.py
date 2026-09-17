"""JSON读取、输入体检和第一问结果写出。"""

from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from .model import Buffer, Graph, MANAGEMENT_OPS, MEMORY_TYPES, Node


class InputValidationError(ValueError):
    """输入不符合赛题数据约定。"""

    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(errors)
        preview = "\n".join(f"- {item}" for item in self.errors[:30])
        if len(self.errors) > 30:
            preview += f"\n- ……另有 {len(self.errors) - 30} 项"
        super().__init__(f"输入体检失败：\n{preview}")


def _require_int(value: Any, field: str, errors: list[str], *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{field} 必须是整数，实际为 {value!r}")
        return None
    if value < minimum:
        errors.append(f"{field} 必须不小于 {minimum}，实际为 {value}")
        return None
    return value


def _parse_node(raw: Any, index: int, errors: list[str]) -> Node | None:
    location = f"Nodes[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{location} 必须是对象")
        return None

    node_id = _require_int(raw.get("Id"), f"{location}.Id", errors)
    op = raw.get("Op")
    if not isinstance(op, str) or not op.strip():
        errors.append(f"{location}.Op 必须是非空字符串")
        return None
    op = op.strip()
    if node_id is None:
        return None

    if op in MANAGEMENT_OPS:
        buf_id = _require_int(raw.get("BufId"), f"{location}.BufId", errors)
        size = _require_int(raw.get("Size"), f"{location}.Size", errors, minimum=1)
        memory_type = raw.get("Type")
        if memory_type not in MEMORY_TYPES:
            errors.append(
                f"{location}.Type 必须属于 {sorted(MEMORY_TYPES)}，实际为 {memory_type!r}"
            )
            memory_type = None
        if buf_id is None or size is None or memory_type is None:
            return None
        return Node(
            id=node_id,
            op=op,
            buf_id=buf_id,
            size=size,
            memory_type=memory_type,
        )

    pipe = raw.get("Pipe")
    cycles = _require_int(raw.get("Cycles"), f"{location}.Cycles", errors)
    bufs_raw = raw.get("Bufs")
    if not isinstance(pipe, str) or not pipe.strip():
        errors.append(f"{location}.Pipe 必须是非空字符串")
        pipe = None
    if not isinstance(bufs_raw, list):
        errors.append(f"{location}.Bufs 必须是列表")
        bufs_raw = []
    bufs: list[int] = []
    for j, value in enumerate(bufs_raw):
        buf_id = _require_int(value, f"{location}.Bufs[{j}]", errors)
        if buf_id is not None:
            bufs.append(buf_id)
    if len(bufs) != len(set(bufs)):
        errors.append(f"{location}.Bufs 不应包含重复BufId")
    if pipe is None or cycles is None:
        return None
    return Node(id=node_id, op=op, pipe=pipe.strip(), cycles=cycles, bufs=tuple(bufs))


def _topological_order(
    node_ids: Iterable[int], successors: dict[int, list[int]], indegree: dict[int, int]
) -> tuple[int, ...] | None:
    ready = deque(sorted(node_id for node_id in node_ids if indegree[node_id] == 0))
    work_indegree = dict(indegree)
    order: list[int] = []
    while ready:
        node_id = ready.popleft()
        order.append(node_id)
        for nxt in successors[node_id]:
            work_indegree[nxt] -= 1
            if work_indegree[nxt] == 0:
                ready.append(nxt)
    return tuple(order) if len(order) == len(work_indegree) else None


def build_graph(data: Any, name: str = "task") -> Graph:
    """从已经反序列化的JSON对象构造并严格验证Graph。"""

    errors: list[str] = []
    if not isinstance(data, dict):
        raise InputValidationError(["JSON顶层必须是对象"])
    if set(data) != {"Nodes", "Edges"}:
        missing = {"Nodes", "Edges"} - set(data)
        extra = set(data) - {"Nodes", "Edges"}
        if missing:
            errors.append(f"缺少顶层字段：{sorted(missing)}")
        if extra:
            errors.append(f"存在未识别的顶层字段：{sorted(extra)}")

    raw_nodes = data.get("Nodes")
    raw_edges = data.get("Edges")
    if not isinstance(raw_nodes, list):
        errors.append("Nodes 必须是列表")
        raw_nodes = []
    if not isinstance(raw_edges, list):
        errors.append("Edges 必须是列表")
        raw_edges = []

    nodes: dict[int, Node] = {}
    for i, raw in enumerate(raw_nodes):
        node = _parse_node(raw, i, errors)
        if node is None:
            continue
        if node.id in nodes:
            errors.append(f"节点Id重复：{node.id}")
        else:
            nodes[node.id] = node

    expected_ids = set(range(len(raw_nodes)))
    actual_ids = set(nodes)
    if len(nodes) == len(raw_nodes) and actual_ids != expected_ids:
        errors.append(
            "原始节点Id必须从0开始连续编号；"
            f"缺少={sorted(expected_ids - actual_ids)[:10]}，多出={sorted(actual_ids - expected_ids)[:10]}"
        )

    edge_set: set[tuple[int, int]] = set()
    original_edges: list[tuple[int, int]] = []
    for i, raw in enumerate(raw_edges):
        location = f"Edges[{i}]"
        if not isinstance(raw, list) or len(raw) != 2:
            errors.append(f"{location} 必须是[源节点Id, 目标节点Id]")
            continue
        source = _require_int(raw[0], f"{location}[0]", errors)
        target = _require_int(raw[1], f"{location}[1]", errors)
        if source is None or target is None:
            continue
        if source not in nodes or target not in nodes:
            errors.append(f"{location} 引用了不存在的节点：({source}, {target})")
            continue
        if source == target:
            errors.append(f"{location} 是自环：({source}, {target})")
            continue
        edge = (source, target)
        if edge in edge_set:
            errors.append(f"依赖边重复：{edge}")
            continue
        edge_set.add(edge)
        original_edges.append(edge)

    alloc_nodes: dict[int, Node] = {}
    free_nodes: dict[int, Node] = {}
    uses: dict[int, list[int]] = defaultdict(list)
    copy_in_count: dict[int, int] = defaultdict(int)
    for node in nodes.values():
        if node.is_alloc:
            assert node.buf_id is not None
            if node.buf_id in alloc_nodes:
                errors.append(f"BufId {node.buf_id} 存在多个ALLOC节点")
            else:
                alloc_nodes[node.buf_id] = node
        elif node.is_free:
            assert node.buf_id is not None
            if node.buf_id in free_nodes:
                errors.append(f"BufId {node.buf_id} 存在多个FREE节点")
            else:
                free_nodes[node.buf_id] = node
        else:
            for buf_id in node.bufs:
                uses[buf_id].append(node.id)
                if node.op == "COPY_IN":
                    copy_in_count[buf_id] += 1

    all_buf_ids = set(alloc_nodes) | set(free_nodes) | set(uses)
    buffers: dict[int, Buffer] = {}
    for buf_id in sorted(all_buf_ids):
        alloc = alloc_nodes.get(buf_id)
        free = free_nodes.get(buf_id)
        if alloc is None:
            errors.append(f"BufId {buf_id} 缺少ALLOC节点")
        if free is None:
            errors.append(f"BufId {buf_id} 缺少FREE节点")
        if alloc is None or free is None:
            continue
        if alloc.size != free.size or alloc.memory_type != free.memory_type:
            errors.append(
                f"BufId {buf_id} 的ALLOC/FREE属性不一致："
                f"ALLOC=({alloc.size},{alloc.memory_type})，FREE=({free.size},{free.memory_type})"
            )
            continue
        if copy_in_count[buf_id] > 1:
            errors.append(f"BufId {buf_id} 被 {copy_in_count[buf_id]} 个COPY_IN节点使用，超过题意上限1")
        buffers[buf_id] = Buffer(
            id=buf_id,
            size=alloc.size or 0,
            memory_type=alloc.memory_type or "",
            alloc_node=alloc.id,
            free_node=free.id,
            use_nodes=tuple(sorted(uses.get(buf_id, []))),
            from_copy_in=copy_in_count[buf_id] == 1,
        )

    if errors:
        raise InputValidationError(errors)

    original_successors_list: dict[int, list[int]] = {node_id: [] for node_id in nodes}
    original_indegree = {node_id: 0 for node_id in nodes}
    for source, target in original_edges:
        original_successors_list[source].append(target)
        original_indegree[target] += 1
    for values in original_successors_list.values():
        values.sort()
    original_topo = _topological_order(nodes, original_successors_list, original_indegree)
    if original_topo is None:
        raise InputValidationError(["原始依赖图不是DAG，无法进行拓扑调度"])

    # 将生命周期约束显式加入调度DAG。这样搜索只需生成增强DAG的拓扑序，
    # 仍由独立验证器检查最终结果，避免把搜索内部状态当作正确性依据。
    schedule_edge_set = set(original_edges)
    for buffer in buffers.values():
        schedule_edge_set.add((buffer.alloc_node, buffer.free_node))
        for use_node in buffer.use_nodes:
            schedule_edge_set.add((buffer.alloc_node, use_node))
            schedule_edge_set.add((use_node, buffer.free_node))
    schedule_edges = sorted(schedule_edge_set)
    schedule_successors_list: dict[int, list[int]] = {node_id: [] for node_id in nodes}
    schedule_indegree = {node_id: 0 for node_id in nodes}
    for source, target in schedule_edges:
        schedule_successors_list[source].append(target)
        schedule_indegree[target] += 1
    for values in schedule_successors_list.values():
        values.sort()
    schedule_topo = _topological_order(nodes, schedule_successors_list, schedule_indegree)
    if schedule_topo is None:
        raise InputValidationError(["原始依赖与Buffer生命周期约束合并后成环，第一问不存在合法调度"])

    return Graph(
        name=name,
        nodes=nodes,
        buffers=buffers,
        original_edges=tuple(original_edges),
        original_successors={k: tuple(v) for k, v in original_successors_list.items()},
        schedule_edges=tuple(schedule_edges),
        schedule_successors={k: tuple(v) for k, v in schedule_successors_list.items()},
        schedule_indegree=schedule_indegree,
        topological_order=schedule_topo,
    )


def load_graph(path: str | Path) -> Graph:
    """读取一个赛题JSON文件。"""

    input_path = Path(path)
    with input_path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return build_graph(data, input_path.stem)


def write_problem1_result(
    output_root: str | Path,
    graph: Graph,
    schedule: Iterable[int],
    summary: dict[str, Any],
    trace: Iterable[int] | None = None,
) -> tuple[Path, Path, Path | None]:
    """写出比赛附件格式及可复现实验日志。"""

    root = Path(output_root)
    problem_dir = root / "Problem1"
    log_dir = root / "logs"
    problem_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    schedule_path = problem_dir / f"{graph.name}_schedule.txt"
    summary_path = log_dir / f"{graph.name}_summary.json"
    schedule_values = tuple(schedule)
    schedule_path.write_text("".join(f"{node_id}\n" for node_id in schedule_values), encoding="utf-8")
    with summary_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    trace_path: Path | None = None
    if trace is not None:
        trace_values = tuple(trace)
        trace_path = log_dir / f"{graph.name}_memory_trace.csv"
        with trace_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["position", "node_id", "l1_ub_live", "running_peak"])
            running_peak = 0
            for position, (node_id, current) in enumerate(zip(schedule_values, trace_values), start=1):
                running_peak = max(running_peak, current)
                writer.writerow([position, node_id, current, running_peak])

    return schedule_path, summary_path, trace_path
