from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


def _normalize_str(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class SubTaskSpec:
    """Single node in a complex orchestration DAG."""

    task_id: str
    workflow_name: str
    depends_on: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workflow_name": self.workflow_name,
            "depends_on": list(self.depends_on),
            "payload": dict(self.payload),
            "description": self.description,
        }


@dataclass
class SubTaskDAG:
    """A tiny immutable-style DAG wrapper for super-complex orchestration."""

    nodes: dict[str, SubTaskSpec] = field(default_factory=dict)
    edges: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_specs(cls, specs: Iterable[dict[str, Any] | SubTaskSpec]) -> "SubTaskDAG":
        dag = cls()
        for spec in specs:
            dag.add(spec)
        return dag

    def add(self, spec: dict[str, Any] | SubTaskSpec) -> None:
        node = self._coerce_spec(spec)
        self.nodes[node.task_id] = node
        self.edges[node.task_id] = tuple(node.depends_on)

    def roots(self) -> list[SubTaskSpec]:
        return [node for node in self.nodes.values() if not self.edges.get(node.task_id)]

    def children(self, task_id: str) -> list[SubTaskSpec]:
        return [node for node in self.nodes.values() if task_id in self.edges.get(node.task_id, ())]

    def topological_sort(self) -> list[SubTaskSpec]:
        ordered: list[SubTaskSpec] = []
        pending = {task_id: set(deps) for task_id, deps in self.edges.items()}
        ready = [task_id for task_id, deps in pending.items() if not deps]
        seen: set[str] = set()

        while ready:
            task_id = ready.pop(0)
            if task_id in seen:
                continue
            seen.add(task_id)
            ordered.append(self.nodes[task_id])
            for child_id, deps in pending.items():
                if task_id in deps:
                    deps.remove(task_id)
                    if not deps and child_id not in seen and child_id not in ready:
                        ready.append(child_id)

        if len(ordered) != len(self.nodes):
            missing = [task_id for task_id in self.nodes if task_id not in {node.task_id for node in ordered}]
            raise ValueError(f"subtask dag contains a cycle or missing dependency: {missing}")
        return ordered

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": {task_id: list(deps) for task_id, deps in self.edges.items()},
        }

    @staticmethod
    def _coerce_spec(spec: dict[str, Any] | SubTaskSpec) -> SubTaskSpec:
        if isinstance(spec, SubTaskSpec):
            return spec
        payload = dict(spec.get("payload") or {})
        depends_on_raw = spec.get("depends_on") or []
        if isinstance(depends_on_raw, str):
            depends_on_raw = [depends_on_raw]
        depends_on = tuple(_normalize_str(item) for item in depends_on_raw if _normalize_str(item))
        task_id = _normalize_str(spec.get("task_id") or spec.get("id") or spec.get("name"))
        workflow_name = _normalize_str(spec.get("workflow_name") or spec.get("workflow") or spec.get("entry"))
        if not task_id:
            raise ValueError("subtask requires task_id")
        if not workflow_name:
            raise ValueError("subtask requires workflow_name")
        return SubTaskSpec(
            task_id=task_id,
            workflow_name=workflow_name,
            depends_on=depends_on,
            payload=payload,
            description=_normalize_str(spec.get("description")),
        )
