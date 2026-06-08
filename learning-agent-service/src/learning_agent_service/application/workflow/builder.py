from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Monkeypatch JsonPlusSerializer for compatibility with newer langgraph-checkpoint releases
try:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    import ormsgpack

    if not hasattr(JsonPlusSerializer, "dumps"):
        def _jsonplus_dumps(self, obj):
            type_, data = self.dumps_typed(obj)
            return ormsgpack.packb((type_, data))
        JsonPlusSerializer.dumps = _jsonplus_dumps

    if not hasattr(JsonPlusSerializer, "loads"):
        def _jsonplus_loads(self, data):
            if not data:
                return {}
            type_, data_ = ormsgpack.unpackb(data)
            return self.loads_typed((type_, data_))
        JsonPlusSerializer.loads = _jsonplus_loads
except Exception:
    pass

from .runner import SequentialWorkflowRunner, _update_phase5_trace
from .services import WorkflowServices
from ...domain.errors import TerminalEvent
from ...domain.state import GraphState, clone_graph_state
from ...domain import ChatTurnCommand, build_initial_state
from ...domain.contracts import PersistentSessionContext
from ...api.contracts import SseEnvelope
from collections.abc import Iterable
from .subgraphs import (
    run_load_context_node,
    run_rag_subgraph,
    run_recommendation_subgraph,
    run_tool_subgraph,
    run_understand_turn,
    route_after_rag,
    route_after_understand,
    route_gate,
)

StateGraph: Any = None
END: Any = "__end__"
try:
    from langgraph.graph import END as _END, StateGraph as _StateGraph  # type: ignore[import-not-found, import]
    END = _END
    StateGraph = _StateGraph
except ImportError:  # pragma: no cover - optional dependency
    END = "__end__"
    StateGraph = None


LANGGRAPH_AVAILABLE = StateGraph is not None
_CHECKPOINT_FALLBACKS: dict[str, dict[str, Any]] = {}


@dataclass
class _CheckpointSnapshot:
    values: dict[str, Any]


class _CheckpointAwareGraphProxy:
    def __init__(self, graph) -> None:
        self._graph = graph

    def invoke(self, state, config=None):
        thread_id = _thread_id_from_config(config) or _thread_id_from_state(state)
        if thread_id:
            _CHECKPOINT_FALLBACKS[thread_id] = deepcopy(state)
        result = self._graph.invoke(state, config=config)
        if thread_id:
            _CHECKPOINT_FALLBACKS[thread_id] = deepcopy(result)
        return result

    def get_state(self, config=None):
        getter = getattr(self._graph, "get_state", None)
        if callable(getter):
            try:
                snapshot = getter(config)
                if snapshot is not None and getattr(snapshot, "values", None):
                    return snapshot
            except Exception:
                pass
        thread_id = _thread_id_from_config(config)
        if thread_id and thread_id in _CHECKPOINT_FALLBACKS:
            return _CheckpointSnapshot(values=deepcopy(_CHECKPOINT_FALLBACKS[thread_id]))
        return _CheckpointSnapshot(values={})

    def __getattr__(self, item):
        return getattr(self._graph, item)


def _thread_id_from_config(config: Any) -> str | None:
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    thread_id = configurable.get("thread_id")
    text = str(thread_id or "").strip()
    return text or None


def _thread_id_from_state(state: Any) -> str | None:
    if not isinstance(state, dict):
        return None
    runtime = state.get("runtime")
    session_id = getattr(runtime, "session_id", None) if runtime is not None else None
    text = str(session_id or "").strip()
    return text or None


class LangGraphWorkflowRunner(SequentialWorkflowRunner):
    def __init__(
        self,
        services: WorkflowServices,
        workflow_version: str = "learn-agent/v1",
        checkpointer: Any = None,
    ) -> None:
        super().__init__(services=services, workflow_version=workflow_version, runner_kind="langgraph")
        self._checkpointer = checkpointer
        self._graph = _CheckpointAwareGraphProxy(_build_langgraph_runner(services, checkpointer=checkpointer))

    def run_state(self, state):
        state = self._annotate_runner_context(state)
        if self._is_terminal(state):
            result = self._finalize_terminal(state)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)

        try:
            result = self._graph.invoke(state, config=_build_graph_config(state))
        except Exception as exc:
            result = self._record_unexpected_error(state, "langgraph.invoke", exc)
            result = self._finalize_terminal(result)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)

        runtime = result["runtime"]
        if runtime.emitted_events:
            if runtime.terminal_event is None:
                default_terminal = TerminalEvent.ERROR if runtime.errors else TerminalEvent.FINAL
                result["runtime"] = runtime.model_copy(update={"terminal_event": default_terminal})
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)

        if result["runtime"].terminal_event == TerminalEvent.ERROR:
            result = self._finalize_terminal(result)
            self._record_checkpoint_fallback(result)
            return self._annotate_runner_context(result)
        result = self._finalize_terminal(result, default_terminal=TerminalEvent.FINAL)
        self._record_checkpoint_fallback(result)
        return self._annotate_runner_context(result)

    def run_stream(
        self,
        command: ChatTurnCommand,
        persistent_context: PersistentSessionContext | None = None,
    ) -> Iterable[SseEnvelope]:
        state = build_initial_state(
            command=command,
            workflow_version=self.workflow_version,
            persistent=persistent_context,
        )
        state = self._annotate_runner_context(state)
        state = clone_graph_state(state)

        if hasattr(self._graph, "stream"):
            try:
                yield from self._run_graph_stream(state)
                return
            except Exception:
                pass
        
        try:
            result = self._graph.invoke(state, config=_build_graph_config(state))
        except Exception as exc:
            result = self._record_unexpected_error(state, "langgraph.invoke", exc)
            result = self._finalize_terminal(result)
            self._record_checkpoint_fallback(result)
            yield from self._normalize_emitted_events(result["runtime"].emitted_events, result)
            return

        yield from self._normalize_emitted_events(result["runtime"].emitted_events, result)

    @staticmethod
    def _normalize_emitted_events(events, state):
        turn = state.get("turn") if isinstance(state, dict) else None
        final_answer = str(getattr(turn, "final_answer", "") or "").strip() if turn is not None else ""
        for event in events:
            yield LangGraphWorkflowRunner._normalize_emitted_event(event, final_answer)

    def _run_graph_stream(self, state):
        emitted_count = 0

        def drain_emitted_events():
            nonlocal emitted_count
            events = list(state["runtime"].emitted_events)
            for event in events[emitted_count:]:
                yield self._normalize_emitted_event(event, str(state.get("turn").final_answer or "").strip())
            emitted_count = len(events)

        stream = self._graph.stream(state, config=_build_graph_config(state), stream_mode="values")
        for chunk in stream:
            if isinstance(chunk, dict) and "runtime" in chunk:
                state = chunk
                yield from drain_emitted_events()
        yield from drain_emitted_events()

    @staticmethod
    def _normalize_emitted_event(event, final_answer: str):
        if not final_answer:
            return event
        event_type = getattr(event, "event_type", None)
        if event_type != "final":
            return event
        payload = getattr(event, "payload", None)
        payload_dict = None
        if hasattr(payload, "model_dump"):
            payload_dict = payload.model_dump(mode="json")
        elif isinstance(payload, dict):
            payload_dict = dict(payload)
        if not isinstance(payload_dict, dict):
            return event
        payload_dict["answer_text"] = final_answer
        metrics = payload_dict.get("metrics")
        if isinstance(metrics, dict):
            answer_quality = dict(metrics.get("answer_quality") or {})
            answer_quality["final_answer"] = final_answer
            metrics["answer_quality"] = answer_quality
            payload_dict["metrics"] = metrics
        if hasattr(event, "model_copy"):
            return event.model_copy(update={"payload": payload_dict})
        if isinstance(event, dict):
            new_event = dict(event)
            new_event["payload"] = payload_dict
            return new_event
        return event

    def _annotate_runner_context(self, state):
        state = _update_phase5_trace(
            state,
            runner_kind=self.runner_kind,
            runner_backend="langgraph",
            graph_runtime="langgraph",
            runner_class=self.__class__.__name__,
            compare_ready=True,
        )
        runtime_context = dict(state.get("runtime_context", {}) or {})
        runtime_context.update(
            {
                "runner_kind": self.runner_kind,
                "runner_backend": "langgraph",
                "graph_runtime": "langgraph",
                "runner_class": self.__class__.__name__,
                "compare_ready": True,
            }
        )
        state["runtime_context"] = runtime_context
        return state

    def _record_checkpoint_fallback(self, state):
        if self._checkpointer is None:
            return
        thread_id = _thread_id_from_state(state)
        if thread_id:
            _CHECKPOINT_FALLBACKS[thread_id] = deepcopy(state)


def _build_graph_config(state):
    runtime = state["runtime"]
    runtime_context = dict(state.get("runtime_context", {}) or {})
    recursion_limit = int(runtime_context.get("graph_recursion_limit") or 50)
    return {
        "configurable": {"thread_id": runtime.session_id},
        "recursion_limit": max(1, recursion_limit),
    }


_LANGGRAPH_TOPOLOGY = {
    "entry_point": "load_context",
    "terminal": "END",
    "nodes": [
        "load_context",
        "understand_turn",
        "route_gate",
        "rag_subgraph",
        "recommendation_subgraph",
        "tool_subgraph",
        "compose_answer",
        "persist_session",
        "emit_final",
    ],
    "edges": [
        ("START", "load_context"),
        ("load_context", "understand_turn"),
        ("load_context", "compose_answer"),
        ("understand_turn", "route_gate"),
        ("understand_turn", "compose_answer"),
        ("understand_turn", "rag_subgraph"),
        ("understand_turn", "tool_subgraph"),
        ("route_gate", "compose_answer"),
        ("route_gate", "tool_subgraph"),
        ("route_gate", "rag_subgraph"),
        ("route_gate", "recommendation_subgraph"),
        ("rag_subgraph", "tool_subgraph"),
        ("rag_subgraph", "compose_answer"),
        ("recommendation_subgraph", "compose_answer"),
        ("tool_subgraph", "compose_answer"),
        ("compose_answer", "persist_session"),
        ("persist_session", "emit_final"),
        ("emit_final", "END"),
    ],
}


def describe_langgraph_topology() -> dict[str, Any]:
    return {
        "entry_point": _LANGGRAPH_TOPOLOGY["entry_point"],
        "terminal": _LANGGRAPH_TOPOLOGY["terminal"],
        "nodes": list(_LANGGRAPH_TOPOLOGY["nodes"]),
        "edges": [tuple(edge) for edge in _LANGGRAPH_TOPOLOGY["edges"]],
    }


def export_langgraph_mermaid() -> str:
    lines = ["graph TD"]
    for left, right in _LANGGRAPH_TOPOLOGY["edges"]:
        lines.append(f"  {left} --> {right}")
    return "\n".join(lines)


def export_full_langgraph_mermaid() -> str:
    lines = ["graph TD"]
    lines.extend(
        [
            "  subgraph main[Main Graph]",
            "    main_load_context[load_context]",
            "    main_understand_turn[understand_turn]",
            "    main_route_gate[route_gate]",
            "    main_rag_subgraph[rag_subgraph]",
            "    main_recommendation_subgraph[recommendation_subgraph]",
            "    main_tool_subgraph[tool_subgraph]",
            "    main_compose_answer[compose_answer]",
            "    main_persist_session[persist_session]",
            "    main_emit_final[emit_final]",
            "  end",
            "  subgraph rag[RAG Subgraph]",
            "    rag_build_plan[build_retrieval_plan]",
            "    rag_execute[execute_rag_pipeline]",
            "    rag_finalize[finalize_rag]",
            "  end",
            "  subgraph tool[Tool Subgraph]",
            "    tool_plan[tool_plan]",
            "    tool_execute[execute_tool_pipeline]",
            "    tool_finalize[finalize_tool]",
            "  end",
            "  subgraph recommendation[Recommendation Subgraph]",
            "    rec_prepare[prepare_recommendation]",
            "    rec_dispatch[dispatch_shop_analysis]",
            "    rec_analyze[analyze_one_shop]",
            "    rec_reduce[reduce_shop_results]",
            "    rec_finalize[finalize_recommendation]",
            "  end",
            "  subgraph stages[Workflow Stages]",
            "    stage_load_context[load_context]",
            "    stage_parse_intent_slots[parse_intent_slots]",
            "    stage_rag_gate[rag_gate]",
            "    stage_query_rewrite[query_rewrite]",
            "    stage_embedding[embedding]",
            "    stage_qdrant_search[qdrant_search]",
            "    stage_rerank[rerank]",
            "    stage_hybrid_retrieve[hybrid_retrieve]",
            "    stage_evaluate_evidence[evaluate_evidence]",
            "    stage_citation_builder[citation_builder]",
            "    stage_tool_planner[tool_planner]",
            "    stage_tool_executor[tool_executor]",
            "    stage_tool_result_normalizer[tool_result_normalizer]",
            "  end",
            "  main_load_context --> main_understand_turn",
            "  main_understand_turn --> main_route_gate",
            "  main_route_gate --> main_rag_subgraph",
            "  main_route_gate --> main_recommendation_subgraph",
            "  main_route_gate --> main_tool_subgraph",
            "  main_understand_turn --> main_compose_answer",
            "  main_rag_subgraph --> main_compose_answer",
            "  main_recommendation_subgraph --> main_compose_answer",
            "  main_tool_subgraph --> main_compose_answer",
            "  main_compose_answer --> main_persist_session",
            "  main_persist_session --> main_emit_final",
            "  rag_build_plan --> rag_execute",
            "  rag_execute --> rag_finalize",
            "  rag_finalize --> main_compose_answer",
            "  tool_plan --> tool_execute",
            "  tool_execute --> tool_finalize",
            "  tool_finalize --> main_compose_answer",
            "  rec_prepare --> rec_dispatch",
            "  rec_dispatch --> rec_analyze",
            "  rec_analyze --> rec_reduce",
            "  rec_reduce --> rec_finalize",
            "  rec_finalize --> main_compose_answer",
            "  stage_load_context --> stage_parse_intent_slots",
            "  stage_parse_intent_slots --> stage_rag_gate",
            "  stage_rag_gate --> stage_query_rewrite",
            "  stage_query_rewrite --> stage_embedding",
            "  stage_embedding --> stage_qdrant_search",
            "  stage_qdrant_search --> stage_rerank",
            "  stage_rerank --> stage_hybrid_retrieve",
            "  stage_hybrid_retrieve --> stage_evaluate_evidence",
            "  stage_evaluate_evidence --> stage_citation_builder",
            "  stage_citation_builder --> stage_tool_planner",
            "  stage_tool_planner --> stage_tool_executor",
            "  stage_tool_executor --> stage_tool_result_normalizer",
        ]
    )
    return "\n".join(lines)


def _resolve_compiled_graph(graph: Any) -> Any:
    getter = getattr(graph, "get_graph", None)
    if not callable(getter):
        return graph

    for kwargs in ({"xray": True}, {}):
        try:
            return getter(**kwargs)
        except TypeError:
            continue
        except Exception:
            continue
    return graph


def _draw_compiled_graph_mermaid(graph: Any, fallback: str) -> str:
    drawable = _resolve_compiled_graph(graph)
    draw_mermaid = getattr(drawable, "draw_mermaid", None)
    if callable(draw_mermaid):
        try:
            mermaid = draw_mermaid()
            if isinstance(mermaid, str) and mermaid.strip():
                return mermaid
        except Exception:
            pass
    return fallback


def _draw_compiled_graph_png(graph: Any) -> bytes | None:
    drawable = _resolve_compiled_graph(graph)
    for method_name in ("draw_mermaid_png", "draw_png"):
        draw_png = getattr(drawable, method_name, None)
        if not callable(draw_png):
            continue
        try:
            rendered = draw_png()
        except Exception:
            continue
        if isinstance(rendered, bytes) and rendered:
            return rendered
        if hasattr(rendered, "save"):
            from io import BytesIO

            buffer = BytesIO()
            rendered.save(buffer, format="PNG")
            data = buffer.getvalue()
            if data:
                return data
    return None


def _render_full_graph_png(_mermaid_text: str) -> bytes | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None

    def _load_font(size: int = 16):
        font_candidates = [
            Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts" / "arial.ttf",
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/segoeui.ttf"),
        ]
        for candidate in font_candidates:
            if candidate.exists():
                try:
                    return ImageFont.truetype(str(candidate), size=size)
                except Exception:
                    continue
        return ImageFont.load_default()

    font = _load_font(15)
    title_font = _load_font(20)
    small_font = _load_font(13)

    groups = [
        {
            "title": "Main Graph",
            "x": 120,
            "y": 80,
            "width": 1960,
            "nodes": [
                ("main_load_context", "load_context"),
                ("main_understand_turn", "understand_turn"),
                ("main_route_gate", "route_gate"),
                ("main_rag_subgraph", "rag_subgraph"),
                ("main_recommendation_subgraph", "recommendation_subgraph"),
                ("main_tool_subgraph", "tool_subgraph"),
                ("main_compose_answer", "compose_answer"),
                ("main_persist_session", "persist_session"),
                ("main_emit_final", "emit_final"),
            ],
            "fill": (243, 247, 255),
            "outline": (121, 143, 201),
        },
        {
            "title": "RAG Subgraph",
            "x": 120,
            "y": 540,
            "width": 560,
            "nodes": [
                ("rag_build_plan", "build_retrieval_plan"),
                ("rag_execute", "execute_rag_pipeline"),
                ("rag_finalize", "finalize_rag"),
            ],
            "fill": (242, 250, 244),
            "outline": (112, 163, 125),
        },
        {
            "title": "Tool Subgraph",
            "x": 780,
            "y": 540,
            "width": 560,
            "nodes": [
                ("tool_plan", "tool_plan"),
                ("tool_execute", "execute_tool_pipeline"),
                ("tool_finalize", "finalize_tool"),
            ],
            "fill": (255, 248, 240),
            "outline": (204, 149, 90),
        },
        {
            "title": "Recommendation Subgraph",
            "x": 1440,
            "y": 540,
            "width": 640,
            "nodes": [
                ("rec_prepare", "prepare_recommendation"),
                ("rec_dispatch", "dispatch_shop_analysis"),
                ("rec_analyze", "analyze_one_shop"),
                ("rec_reduce", "reduce_shop_results"),
                ("rec_finalize", "finalize_recommendation"),
            ],
            "fill": (249, 242, 255),
            "outline": (160, 121, 201),
        },
        {
            "title": "Workflow Stages",
            "x": 120,
            "y": 980,
            "width": 1960,
            "nodes": [
                ("stage_load_context", "load_context"),
                ("stage_parse_intent_slots", "parse_intent_slots"),
                ("stage_rag_gate", "rag_gate"),
                ("stage_query_rewrite", "query_rewrite"),
                ("stage_embedding", "embedding"),
                ("stage_qdrant_search", "qdrant_search"),
                ("stage_rerank", "rerank"),
                ("stage_hybrid_retrieve", "hybrid_retrieve"),
                ("stage_evaluate_evidence", "evaluate_evidence"),
                ("stage_citation_builder", "citation_builder"),
                ("stage_tool_planner", "tool_planner"),
                ("stage_tool_executor", "tool_executor"),
                ("stage_tool_result_normalizer", "tool_result_normalizer"),
            ],
            "fill": (240, 248, 255),
            "outline": (100, 145, 185),
        },
    ]

    node_w = 320
    node_h = 42
    node_gap = 14
    header_h = 44
    group_pad = 26
    canvas_w = 2200
    canvas_h = 1800
    image = Image.new("RGBA", (canvas_w, canvas_h), (250, 251, 252, 255))
    draw = ImageDraw.Draw(image)

    node_boxes: dict[str, tuple[int, int, int, int]] = {}

    for group in groups:
        nodes = group["nodes"]
        group_height = header_h + group_pad + len(nodes) * (node_h + node_gap) + group_pad - node_gap
        x0 = group["x"]
        y0 = group["y"]
        x1 = x0 + group["width"]
        y1 = y0 + group_height
        draw.rounded_rectangle((x0, y0, x1, y1), radius=18, fill=group["fill"], outline=group["outline"], width=3)
        draw.text((x0 + 18, y0 + 10), group["title"], fill=(30, 30, 30), font=title_font)

        base_y = y0 + header_h
        for index, (node_id, label) in enumerate(nodes):
            center_x = x0 + group["width"] // 2
            top = base_y + group_pad + index * (node_h + node_gap)
            left = center_x - node_w // 2
            right = left + node_w
            bottom = top + node_h
            node_boxes[node_id] = (left, top, right, bottom)
            draw.rounded_rectangle((left, top, right, bottom), radius=12, fill=(255, 255, 255), outline=group["outline"], width=2)
            text_bbox = draw.textbbox((0, 0), label, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
            draw.text(
                (left + (node_w - text_w) / 2, top + (node_h - text_h) / 2 - 1),
                label,
                fill=(25, 25, 25),
                font=font,
            )

    edges = [
        ("main_load_context", "main_understand_turn"),
        ("main_understand_turn", "main_route_gate"),
        ("main_route_gate", "main_rag_subgraph"),
        ("main_route_gate", "main_recommendation_subgraph"),
        ("main_route_gate", "main_tool_subgraph"),
        ("main_understand_turn", "main_compose_answer"),
        ("main_rag_subgraph", "main_compose_answer"),
        ("main_recommendation_subgraph", "main_compose_answer"),
        ("main_tool_subgraph", "main_compose_answer"),
        ("main_compose_answer", "main_persist_session"),
        ("main_persist_session", "main_emit_final"),
        ("rag_build_plan", "rag_execute"),
        ("rag_execute", "rag_finalize"),
        ("rag_finalize", "main_compose_answer"),
        ("tool_plan", "tool_execute"),
        ("tool_execute", "tool_finalize"),
        ("tool_finalize", "main_compose_answer"),
        ("rec_prepare", "rec_dispatch"),
        ("rec_dispatch", "rec_analyze"),
        ("rec_analyze", "rec_reduce"),
        ("rec_reduce", "rec_finalize"),
        ("rec_finalize", "main_compose_answer"),
        ("stage_load_context", "stage_parse_intent_slots"),
        ("stage_parse_intent_slots", "stage_rag_gate"),
        ("stage_rag_gate", "stage_query_rewrite"),
        ("stage_query_rewrite", "stage_embedding"),
        ("stage_embedding", "stage_qdrant_search"),
        ("stage_qdrant_search", "stage_rerank"),
        ("stage_rerank", "stage_hybrid_retrieve"),
        ("stage_hybrid_retrieve", "stage_evaluate_evidence"),
        ("stage_evaluate_evidence", "stage_citation_builder"),
        ("stage_citation_builder", "stage_tool_planner"),
        ("stage_tool_planner", "stage_tool_executor"),
        ("stage_tool_executor", "stage_tool_result_normalizer"),
    ]

    def draw_arrow(src: tuple[int, int, int, int], dst: tuple[int, int, int, int]) -> None:
        sx = (src[0] + src[2]) / 2
        sy = src[3]
        dx = (dst[0] + dst[2]) / 2
        dy = dst[1]
        mid_y = (sy + dy) / 2
        points = [(sx, sy), (sx, mid_y), (dx, mid_y), (dx, dy)]
        draw.line(points, fill=(82, 97, 120), width=3)
        arrow_size = 8
        draw.polygon(
            [
                (dx, dy),
                (dx - arrow_size, dy - arrow_size * 1.6),
                (dx + arrow_size, dy - arrow_size * 1.6),
            ],
            fill=(82, 97, 120),
        )

    for source, target in edges:
        src_box = node_boxes.get(source)
        dst_box = node_boxes.get(target)
        if src_box and dst_box:
            draw_arrow(src_box, dst_box)

    footer = "Combined overview: main graph, compiled subgraphs, and workflow stages"
    footer_bbox = draw.textbbox((0, 0), footer, font=small_font)
    draw.text((24, canvas_h - 40), footer, fill=(96, 104, 116), font=small_font)

    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _write_graph_artifacts(
    target_dir: Path,
    stem: str,
    graph: Any,
    fallback_mermaid: str,
    include_png: bool = True,
    use_compiled_mermaid: bool = True,
    custom_png_renderer: Any = None,
) -> dict[str, str]:
    mermaid_text = _draw_compiled_graph_mermaid(graph, fallback_mermaid) if use_compiled_mermaid else fallback_mermaid
    mermaid_path = target_dir / f"{stem}.mmd"
    mermaid_path.write_text(mermaid_text, encoding="utf-8")

    written = {f"{stem}.mmd": str(mermaid_path)}

    if include_png:
        png_bytes = None
        if callable(custom_png_renderer):
            try:
                png_bytes = custom_png_renderer(mermaid_text)
            except Exception:
                png_bytes = None
        if png_bytes is None:
            png_bytes = _draw_compiled_graph_png(graph)
        if png_bytes:
            png_path = target_dir / f"{stem}.png"
            png_path.write_bytes(png_bytes)
            written[f"{stem}.png"] = str(png_path)

    return written


def write_langgraph_visualizations(
    output_dir: str | Path | None = None,
    services: WorkflowServices | None = None,
) -> dict[str, str]:
    from .graphs import (
        export_rag_graph_mermaid,
        export_recommendation_graph_mermaid,
        export_tool_graph_mermaid,
        describe_rag_graph_topology,
        describe_recommendation_graph_topology,
        describe_tool_graph_topology,
        build_rag_graph,
        build_recommendation_graph,
        build_tool_graph,
    )

    workflow_services = services or WorkflowServices()
    target_dir = Path(output_dir) if output_dir is not None else Path(__file__).resolve().parents[5] / "docs" / "langgraph"
    target_dir.mkdir(parents=True, exist_ok=True)

    main_graph = _build_langgraph_runner(workflow_services)
    rag_graph = build_rag_graph(workflow_services.rag_subgraph)
    tool_graph = build_tool_graph(workflow_services.tool_subgraph)
    recommendation_graph = build_recommendation_graph(workflow_services.rag_subgraph)

    files = {}
    files.update(
        _write_graph_artifacts(
            target_dir,
            "main_graph",
            main_graph,
            export_langgraph_mermaid(),
        )
    )
    files.update(
        _write_graph_artifacts(
            target_dir,
            "full_graph",
            main_graph,
            export_full_langgraph_mermaid(),
            use_compiled_mermaid=False,
            custom_png_renderer=_render_full_graph_png,
        )
    )
    files.update(
        _write_graph_artifacts(
            target_dir,
            "rag_graph",
            rag_graph,
            export_rag_graph_mermaid(),
        )
    )
    files.update(
        _write_graph_artifacts(
            target_dir,
            "tool_graph",
            tool_graph,
            export_tool_graph_mermaid(),
        )
    )
    files.update(
        _write_graph_artifacts(
            target_dir,
            "recommendation_graph",
            recommendation_graph,
            export_recommendation_graph_mermaid(),
        )
    )

    topology_path = target_dir / "langgraph_topology.md"
    topology_path.write_text(
        "\n".join(
            [
                "# LangGraph Topology",
                "",
                "## Main Graph",
                f"- entry_point: {_LANGGRAPH_TOPOLOGY['entry_point']}",
                f"- terminal: {_LANGGRAPH_TOPOLOGY['terminal']}",
                "",
                "```mermaid",
                _draw_compiled_graph_mermaid(main_graph, export_langgraph_mermaid()),
                "```",
                "",
                "## Full Graph",
                "",
                "```mermaid",
                export_full_langgraph_mermaid(),
                "```",
                "",
                "## Rag Graph",
                f"- entry_point: {describe_rag_graph_topology()['entry_point']}",
                "",
                "```mermaid",
                _draw_compiled_graph_mermaid(rag_graph, export_rag_graph_mermaid()),
                "```",
                "",
                "## Tool Graph",
                f"- entry_point: {describe_tool_graph_topology()['entry_point']}",
                "",
                "```mermaid",
                _draw_compiled_graph_mermaid(tool_graph, export_tool_graph_mermaid()),
                "```",
                "",
                "## Recommendation Graph",
                f"- entry_point: {describe_recommendation_graph_topology()['entry_point']}",
                "",
                "```mermaid",
                _draw_compiled_graph_mermaid(recommendation_graph, export_recommendation_graph_mermaid()),
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files["langgraph_topology.md"] = str(topology_path)
    return files


def _build_langgraph_runner(services: WorkflowServices, checkpointer: Any = None):
    if not LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph is not installed")

    from langgraph.types import RetryPolicy

    workflow_retry_policy = RetryPolicy(
        max_attempts=3,
        backoff_factor=2.0,
        initial_interval=1.0,
        retry_on=Exception,
    )

    graph = StateGraph(GraphState)  # type: ignore[type-var]
    graph.add_node("load_context", lambda state: run_load_context_node(state, services.load_context))
    graph.add_node(
        "understand_turn", 
        lambda state: run_understand_turn(state, services.understand_turn),
        retry_policy=workflow_retry_policy
    )
    graph.add_node("route_gate", lambda state: route_gate(state))
    graph.add_node(
        "rag_subgraph", 
        lambda state: run_rag_subgraph(state, services.rag_subgraph),
        retry_policy=workflow_retry_policy
    )
    graph.add_node(
        "recommendation_subgraph", 
        lambda state: run_recommendation_subgraph(state, services.rag_subgraph),
        retry_policy=workflow_retry_policy
    )
    graph.add_node(
        "tool_subgraph", 
        lambda state: run_tool_subgraph(state, services.tool_subgraph),
        retry_policy=workflow_retry_policy
    )
    graph.add_node(
        "compose_answer", 
        lambda state: services.compose_answer(state),
        retry_policy=workflow_retry_policy
    )
    graph.add_node("persist_session", lambda state: services.persist_session(state))
    graph.add_node("emit_final", lambda state: services.emit_final(state))

    graph.set_entry_point("load_context")
    graph.add_edge("recommendation_subgraph", "compose_answer")
    graph.add_edge("tool_subgraph", "compose_answer")
    graph.add_edge("compose_answer", "persist_session")
    graph.add_edge("persist_session", "emit_final")
    graph.add_edge("emit_final", END)
    compiled = graph.compile(checkpointer=checkpointer)
    return compiled



def create_workflow_runner(
    services: WorkflowServices,
    prefer_langgraph: bool = True,
    workflow_version: str = "learn-agent/v1",
    checkpointer: Any = None,
):
    if prefer_langgraph and LANGGRAPH_AVAILABLE:
        return LangGraphWorkflowRunner(
            services=services,
            workflow_version=workflow_version,
            checkpointer=checkpointer,
        )
    return SequentialWorkflowRunner(services=services, workflow_version=workflow_version)
