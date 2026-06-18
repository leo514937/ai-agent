from __future__ import annotations

import argparse
import importlib
import inspect
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from learning_agent_service.config import Settings, load_settings
from learning_agent_service.domain.utils import clean_text as _clean_text
from learning_agent_service.local_life.answer_planner import EvidencePack as LocalLifeEvidencePack


def _string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = list(value)
    else:
        items = [value]
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return tuple(ordered)


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if hasattr(value, "value"):
        value = getattr(value, "value")
    if isinstance(value, Mapping) and "value" in value:
        value = value.get("value")
    try:
        number = float(value)
    except Exception:
        return None
    if math.isnan(number):
        return None
    return number


def _has_text(value: Any) -> bool:
    return bool(_clean_text(value))


def _all_rows_have(rows: Sequence[Mapping[str, Any]], key: str) -> bool:
    return bool(rows) and all(_has_text(row.get(key)) for row in rows)


def _all_rows_have_list(rows: Sequence[Mapping[str, Any]], key: str) -> bool:
    if not rows:
        return False
    for row in rows:
        values = row.get(key)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)) or not values:
            return False
        if not any(_has_text(item) for item in values):
            return False
    return True


@dataclass(frozen=True)
class RagasEvalCase:
    case_id: str
    query: str
    reference: str = ""
    reference_contexts: tuple[str, ...] = ()
    reference_context_ids: tuple[str, ...] = ()
    turns: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RagasEvalCase":
        raw_turns = raw.get("turns") or []
        if isinstance(raw_turns, str):
            raw_turns = [raw_turns]
        elif not isinstance(raw_turns, Sequence) or isinstance(raw_turns, (bytes, bytearray)):
            raw_turns = [raw_turns]
        turns = tuple(str(text) for item in raw_turns if (text := _clean_text(item)))
        query = _clean_text(raw.get("query") or (turns[-1] if turns else "")) or ""
        metadata = dict(raw)
        return cls(
            case_id=_clean_text(raw.get("case_id") or raw.get("id") or query or "case") or "case",
            query=query,
            reference=_clean_text(raw.get("reference")) or "",
            reference_contexts=_string_list(raw.get("reference_contexts")),
            reference_context_ids=_string_list(raw.get("reference_context_ids")),
            turns=turns,
            metadata=metadata,
        )


@dataclass(frozen=True)
class RagasEvalObservation:
    case_id: str
    query: str
    response: str = ""
    metrics: Mapping[str, Any] = field(default_factory=dict)
    evidence_pack: LocalLifeEvidencePack | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RagasEvalObservation":
        evidence_pack = raw.get("evidence_pack")
        if isinstance(evidence_pack, Mapping):
            evidence_pack = LocalLifeEvidencePack.model_validate(evidence_pack)
        return cls(
            case_id=_clean_text(raw.get("case_id") or raw.get("id")) or "case",
            query=_clean_text(raw.get("query")) or "",
            response=_clean_text(raw.get("response") or raw.get("answer") or raw.get("final_answer")) or "",
            metrics=dict(raw.get("metrics") or {}),
            evidence_pack=evidence_pack if isinstance(evidence_pack, LocalLifeEvidencePack) else None,
        )


@dataclass(frozen=True)
class MetricSpec:
    name: str
    import_candidates: tuple[tuple[str, str], ...]
    required_scalar_fields: tuple[str, ...] = ()
    required_list_fields: tuple[str, ...] = ()
    needs_llm: bool = False
    needs_embeddings: bool = False
    description: str = ""
    lower_is_better: bool = False


@dataclass
class RagasRuntime:
    llm: Any | None = None
    embeddings: Any | None = None
    client: Any | None = None
    warnings: list[str] = field(default_factory=list)


_METRIC_REGISTRY: dict[str, MetricSpec] = {
    "answer_relevancy": MetricSpec(
        name="answer_relevancy",
        import_candidates=(
            ("ragas.metrics._answer_relevance", "AnswerRelevancy"),
            ("ragas.metrics.collections", "AnswerRelevancy"),
        ),
        required_scalar_fields=("user_input", "response"),
        needs_llm=True,
        needs_embeddings=True,
        description="回答与用户问题的相关性",
    ),
    "faithfulness": MetricSpec(
        name="faithfulness",
        import_candidates=(
            ("ragas.metrics._faithfulness", "Faithfulness"),
            ("ragas.metrics.collections", "Faithfulness"),
        ),
        required_scalar_fields=("user_input", "response"),
        required_list_fields=("retrieved_contexts",),
        needs_llm=True,
        description="回答是否忠于检索上下文",
    ),
    "context_precision": MetricSpec(
        name="context_precision",
        import_candidates=(
            ("ragas.metrics._context_precision", "ContextPrecision"),
            ("ragas.metrics.collections", "ContextPrecision"),
        ),
        required_scalar_fields=("user_input", "reference"),
        required_list_fields=("retrieved_contexts",),
        needs_llm=True,
        description="带 reference 的上下文精确率",
    ),
    "context_utilization": MetricSpec(
        name="context_utilization",
        import_candidates=(
            ("ragas.metrics._context_precision", "ContextUtilization"),
            ("ragas.metrics.collections", "ContextUtilization"),
        ),
        required_scalar_fields=("user_input", "response"),
        required_list_fields=("retrieved_contexts",),
        needs_llm=True,
        description="无 reference 时上下文是否被有效利用",
    ),
    "context_recall": MetricSpec(
        name="context_recall",
        import_candidates=(
            ("ragas.metrics._context_recall", "ContextRecall"),
            ("ragas.metrics.collections", "ContextRecall"),
        ),
        required_scalar_fields=("user_input", "reference"),
        required_list_fields=("retrieved_contexts",),
        needs_llm=True,
        description="上下文召回率",
    ),
    "context_entity_recall": MetricSpec(
        name="context_entity_recall",
        import_candidates=(
            ("ragas.metrics._context_entities_recall", "ContextEntityRecall"),
            ("ragas.metrics.collections", "ContextEntityRecall"),
        ),
        required_scalar_fields=("reference",),
        required_list_fields=("retrieved_contexts",),
        needs_llm=True,
        description="基于 reference 实体的召回率",
    ),
    "noise_sensitivity": MetricSpec(
        name="noise_sensitivity",
        import_candidates=(
            ("ragas.metrics._noise_sensitivity", "NoiseSensitivity"),
            ("ragas.metrics.collections", "NoiseSensitivity"),
        ),
        required_scalar_fields=("user_input", "reference", "response"),
        required_list_fields=("retrieved_contexts",),
        needs_llm=True,
        lower_is_better=True,
        description="噪声敏感度，越低越好",
    ),
    "answer_correctness": MetricSpec(
        name="answer_correctness",
        import_candidates=(
            ("ragas.metrics._answer_correctness", "AnswerCorrectness"),
            ("ragas.metrics.collections", "AnswerCorrectness"),
        ),
        required_scalar_fields=("reference", "response"),
        needs_llm=True,
        needs_embeddings=True,
        description="综合 factual correctness 与 semantic similarity 的答案正确性",
    ),
    "factual_correctness": MetricSpec(
        name="factual_correctness",
        import_candidates=(
            ("ragas.metrics._factual_correctness", "FactualCorrectness"),
            ("ragas.metrics.collections", "FactualCorrectness"),
        ),
        required_scalar_fields=("reference", "response"),
        needs_llm=True,
        description="回答与标准答案的事实一致性",
    ),
    "semantic_similarity": MetricSpec(
        name="semantic_similarity",
        import_candidates=(
            ("ragas.metrics._answer_similarity", "SemanticSimilarity"),
            ("ragas.metrics.collections", "SemanticSimilarity"),
        ),
        required_scalar_fields=("reference", "response"),
        needs_embeddings=True,
        description="回答与标准答案的语义相似度",
    ),
    "nonllm_context_precision": MetricSpec(
        name="nonllm_context_precision",
        import_candidates=(("ragas.metrics._context_precision", "NonLLMContextPrecisionWithReference"),),
        required_list_fields=("retrieved_contexts", "reference_contexts"),
        description="基于 reference_contexts 的非 LLM 上下文精确率",
    ),
    "id_based_context_precision": MetricSpec(
        name="id_based_context_precision",
        import_candidates=(("ragas.metrics._context_precision", "IDBasedContextPrecision"),),
        required_list_fields=("retrieved_context_ids", "reference_context_ids"),
        description="基于 context id 的精确率",
    ),
    "id_based_context_recall": MetricSpec(
        name="id_based_context_recall",
        import_candidates=(("ragas.metrics._context_recall", "IDBasedContextRecall"),),
        required_list_fields=("retrieved_context_ids", "reference_context_ids"),
        description="基于 context id 的召回率",
    ),
    "bleu_score": MetricSpec(
        name="bleu_score",
        import_candidates=(
            ("ragas.metrics._bleu_score", "BleuScore"),
            ("ragas.metrics.collections", "BleuScore"),
        ),
        required_scalar_fields=("reference", "response"),
        description="BLEU 传统文本指标",
    ),
    "rouge_score": MetricSpec(
        name="rouge_score",
        import_candidates=(
            ("ragas.metrics._rouge_score", "RougeScore"),
            ("ragas.metrics.collections", "RougeScore"),
        ),
        required_scalar_fields=("reference", "response"),
        description="ROUGE 传统文本指标",
    ),
    "string_presence": MetricSpec(
        name="string_presence",
        import_candidates=(
            ("ragas.metrics._string", "StringPresence"),
            ("ragas.metrics.collections", "StringPresence"),
        ),
        required_scalar_fields=("reference", "response"),
        description="回答是否包含参考关键词",
    ),
    "exact_match": MetricSpec(
        name="exact_match",
        import_candidates=(
            ("ragas.metrics._string", "ExactMatch"),
            ("ragas.metrics.collections", "ExactMatch"),
        ),
        required_scalar_fields=("reference", "response"),
        description="回答与标准答案是否完全一致",
    ),
    "chrf_score": MetricSpec(
        name="chrf_score",
        import_candidates=(
            ("ragas.metrics._chrf_score", "ChrfScore"),
            ("ragas.metrics.collections", "ChrfScore"),
        ),
        required_scalar_fields=("reference", "response"),
        description="字符级 F-score",
    ),
}

_METRIC_ALIASES = {
    "response_relevancy": "answer_relevancy",
    "response_relevance": "answer_relevancy",
    "answer_relevance": "answer_relevancy",
    "context_precision_with_reference": "context_precision",
    "llm_context_precision_with_reference": "context_precision",
    "context_precision_without_reference": "context_utilization",
    "llm_context_precision_without_reference": "context_utilization",
}

_BASIC_PROFILE = ("answer_relevancy", "faithfulness", "context_precision", "context_utilization", "context_recall")
_FULL_PROFILE = (
    "answer_relevancy",
    "faithfulness",
    "context_precision",
    "context_utilization",
    "context_recall",
    "context_entity_recall",
    "noise_sensitivity",
    "answer_correctness",
    "factual_correctness",
    "semantic_similarity",
    "nonllm_context_precision",
    "id_based_context_precision",
    "id_based_context_recall",
    "bleu_score",
    "rouge_score",
    "string_presence",
    "exact_match",
    "chrf_score",
)


def load_ragas_eval_cases(path: str | Path) -> tuple[RagasEvalCase, ...]:
    return tuple(RagasEvalCase.from_mapping(item) for item in _load_jsonl(path))


def load_ragas_eval_observations(path: str | Path) -> tuple[RagasEvalObservation, ...]:
    return tuple(RagasEvalObservation.from_mapping(item) for item in _load_jsonl(path))


def summarize_ragas_observation(
    *,
    case: RagasEvalCase,
    response: str = "",
    metrics: Mapping[str, Any] | None = None,
    evidence_pack: LocalLifeEvidencePack | Mapping[str, Any] | None = None,
) -> RagasEvalObservation:
    pack = evidence_pack
    if isinstance(pack, Mapping):
        pack = LocalLifeEvidencePack.model_validate(pack)
    return RagasEvalObservation(
        case_id=case.case_id,
        query=case.query,
        response=_clean_text(response) or "",
        metrics=dict(metrics or {}),
        evidence_pack=pack if isinstance(pack, LocalLifeEvidencePack) else None,
    )


def build_ragas_rows(
    cases: Sequence[RagasEvalCase],
    observations: Sequence[RagasEvalObservation],
) -> list[dict[str, Any]]:
    case_map = {case.case_id: case for case in cases}
    rows: list[dict[str, Any]] = []
    for observation in observations:
        case = case_map.get(observation.case_id)
        if case is None:
            continue
        contexts, context_ids = _observation_contexts(observation)
        row: dict[str, Any] = {
            "case_id": case.case_id,
            "user_input": observation.query or case.query,
            "response": observation.response,
        }
        if case.reference:
            row["reference"] = case.reference
        if contexts:
            row["retrieved_contexts"] = contexts
        if context_ids:
            row["retrieved_context_ids"] = context_ids
        if case.reference_contexts:
            row["reference_contexts"] = list(case.reference_contexts)
        if case.reference_context_ids:
            row["reference_context_ids"] = list(case.reference_context_ids)
        if observation.metrics:
            row["metadata"] = dict(observation.metrics)
        rows.append(row)
    return rows


def select_ragas_metric_specs(
    rows: Sequence[Mapping[str, Any]],
    *,
    profile: str = "full",
    requested_metrics: Sequence[str] | None = None,
) -> list[MetricSpec]:
    if requested_metrics:
        names = [_normalize_metric_name(item) for item in requested_metrics]
    elif str(profile).lower() == "basic":
        names = list(_BASIC_PROFILE)
    else:
        names = list(_FULL_PROFILE)

    selected: list[MetricSpec] = []
    for name in names:
        spec = _METRIC_REGISTRY.get(name)
        if spec is None:
            continue
        if spec.required_scalar_fields and not all(_all_rows_have(rows, key) for key in spec.required_scalar_fields):
            continue
        if spec.required_list_fields and not all(_all_rows_have_list(rows, key) for key in spec.required_list_fields):
            continue
        selected.append(spec)
    return selected


def build_ragas_runtime(
    *,
    settings: Settings | None = None,
    llm_model: str | None = None,
    embedding_model: str | None = None,
    needs_llm: bool,
    needs_embeddings: bool,
) -> RagasRuntime:
    runtime = RagasRuntime()
    if not (needs_llm or needs_embeddings):
        return runtime
    settings_value = settings or load_settings()
    api_key = _clean_text(settings_value.openai.api_key)
    if not api_key:
        runtime.warnings.append("未检测到 OpenAI API Key；仅能运行不依赖 LLM/Embeddings 的 RAGAS 指标。")
        return runtime

    try:
        from openai import AsyncOpenAI
        from ragas.embeddings.base import embedding_factory
        from ragas.llms import llm_factory
    except ImportError as exc:  # pragma: no cover - exercised in runtime env
        raise RuntimeError(
            "缺少 RAGAS/OpenAI 运行依赖，请先安装 `pip install -e .[ragas]`。"
        ) from exc

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=_clean_text(settings_value.openai.base_url) or None,
        organization=settings_value.openai.organization,
        project=settings_value.openai.project,
        timeout=float(settings_value.openai.timeout_seconds),
        max_retries=int(settings_value.openai.max_retries),
    )
    runtime.client = client
    if needs_llm:
        runtime.llm = llm_factory(
            llm_model or settings_value.openai.responses_model,
            client=client,
        )
    if needs_embeddings:
        runtime.embeddings = embedding_factory(
            "openai",
            model=embedding_model or settings_value.openai.embedding_model,
            client=client,
        )
        # 旧式 Metric 类（如 AnswerRelevancy）依赖 embed_query()，
        # 而 ragas 0.4.3 的现代 OpenAIEmbeddings（openai_provider）只有 embed_text()。
        # 若缺少 embed_query，包装一层兼容垫片。
        if not hasattr(runtime.embeddings, "embed_query") or not hasattr(runtime.embeddings, "embed_documents"):
            _inner = runtime.embeddings

            def _embed_query(text: str, **kwargs: Any) -> list[float]:
                return _inner.embed_text(text, **kwargs)

            def _embed_documents(texts: list[str], **kwargs: Any) -> list[list[float]]:
                return _inner.embed_texts(texts, **kwargs)

            runtime.embeddings.embed_query = _embed_query  # type: ignore[attr-defined]
            runtime.embeddings.embed_documents = _embed_documents  # type: ignore[attr-defined]
    return runtime


def instantiate_ragas_metrics(
    specs: Sequence[MetricSpec],
    *,
    runtime: RagasRuntime,
) -> tuple[list[Any], list[str]]:
    metrics: list[Any] = []
    skipped: list[str] = []
    for spec in specs:
        if spec.needs_llm and runtime.llm is None:
            skipped.append(f"{spec.name}:missing_llm")
            continue
        if spec.needs_embeddings and runtime.embeddings is None:
            skipped.append(f"{spec.name}:missing_embeddings")
            continue
        cls = _import_metric_class(spec)
        if cls is None:
            skipped.append(f"{spec.name}:import_failed")
            continue
        kwargs: dict[str, Any] = {}
        signature = inspect.signature(cls)
        if "llm" in signature.parameters and runtime.llm is not None:
            kwargs["llm"] = runtime.llm
        if "embeddings" in signature.parameters and runtime.embeddings is not None:
            kwargs["embeddings"] = runtime.embeddings
        try:
            metrics.append(cls(**kwargs))
        except Exception:
            skipped.append(f"{spec.name}:init_failed")
    return metrics, skipped


def evaluate_ragas_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric_specs: Sequence[MetricSpec],
    settings: Settings | None = None,
    llm_model: str | None = None,
    embedding_model: str | None = None,
    show_progress: bool = False,
    experiment_name: str | None = None,
) -> dict[str, Any]:
    try:
        from ragas import EvaluationDataset, evaluate
        from ragas.run_config import RunConfig
    except ImportError as exc:  # pragma: no cover - exercised in runtime env
        raise RuntimeError("当前环境未安装 ragas，请先安装 `pip install -e .[ragas]`。") from exc

    runtime = build_ragas_runtime(
        settings=settings,
        llm_model=llm_model,
        embedding_model=embedding_model,
        needs_llm=any(spec.needs_llm for spec in metric_specs),
        needs_embeddings=any(spec.needs_embeddings for spec in metric_specs),
    )
    metrics, skipped_metrics = instantiate_ragas_metrics(metric_specs, runtime=runtime)
    if not metrics:
        raise RuntimeError(
            "没有可执行的 RAGAS 指标。可能原因：未安装 ragas、缺少 LLM/Embeddings 凭证，或当前样本缺少必要字段。"
        )
    dataset = EvaluationDataset.from_list([dict(row) for row in rows])
    run_config = RunConfig(
        timeout=300,
        max_retries=5,
        max_wait=120,
    )
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        raise_exceptions=False,
        show_progress=show_progress,
        experiment_name=experiment_name,
        run_config=run_config,
    )
    score_rows = _extract_score_rows(result)
    # 将 score_rows 中的 metric 内部名称映射为 spec 名称，确保 summarizer 能找到
    _spec_map: dict[str, str] = {}
    for metric in metrics:
        mname = _metric_name(metric)
        # 按 import class 推断对应哪个 spec
        for spec in metric_specs:
            cls = _import_metric_class(spec)
            if cls is not None and mname == getattr(cls, "name", mname):
                pass  # 精确匹配，不重映射
            if cls is not None and isinstance(metric, cls):
                if mname != spec.name:
                    _spec_map[mname] = spec.name
                break
    if _spec_map:
        remapped: list[dict[str, Any]] = []
        for row in score_rows:
            row_map = dict(row)
            for old_key, new_key in _spec_map.items():
                if old_key in row_map and new_key not in row_map:
                    row_map[new_key] = row_map.pop(old_key)
            remapped.append(row_map)
        score_rows = remapped
    summary = summarize_ragas_results(
        rows=rows,
        score_rows=score_rows,
        metric_specs=metric_specs,
        skipped_metrics=skipped_metrics + runtime.warnings,
        evaluation_backend="ragas",
    )
    return {
        "rows": list(rows),
        "score_rows": score_rows,
        "summary": summary,
        "selected_metrics": [spec.name for spec in metric_specs],
        "executed_metrics": [_metric_name(metric) for metric in metrics],
        "skipped_metrics": list(skipped_metrics),
        "runtime_warnings": list(runtime.warnings),
    }


def summarize_ragas_results(
    *,
    rows: Sequence[Mapping[str, Any]],
    score_rows: Sequence[Mapping[str, Any]],
    metric_specs: Sequence[MetricSpec],
    skipped_metrics: Sequence[str] = (),
    evaluation_backend: str = "ragas",
) -> dict[str, Any]:
    metric_means: dict[str, float] = {}
    metric_counts: dict[str, int] = {}
    for spec in metric_specs:
        values: list[float] = []
        for row in score_rows:
            value = _coerce_float(row.get(spec.name))
            if value is None:
                continue
            values.append(value)
        if values:
            metric_means[spec.name] = sum(values) / float(len(values))
            metric_counts[spec.name] = len(values)
    return {
        "evaluation_backend": evaluation_backend,
        "case_count": len(rows),
        "scored_case_count": len(score_rows),
        "metric_means": metric_means,
        "metric_counts": metric_counts,
        "lower_is_better_metrics": [spec.name for spec in metric_specs if spec.lower_is_better],
        "skipped_metrics": list(skipped_metrics),
    }


def format_ragas_eval_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "RAGAS Eval Report",
        f"evaluation_backend: {_clean_text(summary.get('evaluation_backend')) or 'ragas'}",
        f"case_count: {int(summary.get('case_count') or 0)}",
        f"scored_case_count: {int(summary.get('scored_case_count') or 0)}",
        "metric_means:",
    ]
    metric_means = summary.get("metric_means") or {}
    for name in sorted(metric_means):
        value = _coerce_float(metric_means.get(name))
        if value is None:
            continue
        lines.append(f"  - {name}: {value:.4f}")
    skipped_metrics = list(summary.get("skipped_metrics") or [])
    if skipped_metrics:
        lines.append("skipped_metrics:")
        for item in skipped_metrics:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation on local RAG observations.")
    parser.add_argument("--cases", required=True, help="Path to rag_eval_cases.jsonl / ragas_eval_cases.jsonl.")
    parser.add_argument("--observations", required=True, help="Path to observation jsonl with response + evidence_pack.")
    parser.add_argument("--output", default=None, help="Optional JSON report output path.")
    parser.add_argument("--profile", default="full", choices=("basic", "full"), help="Metric profile.")
    parser.add_argument("--metric", action="append", default=[], help="Explicit metric name. Can be repeated.")
    parser.add_argument("--llm-model", default=None, help="Override evaluator LLM model.")
    parser.add_argument("--embedding-model", default=None, help="Override evaluator embedding model.")
    parser.add_argument("--json", action="store_true", help="Print summary as JSON.")
    parser.add_argument("--show-progress", action="store_true", help="Show RAGAS progress bar.")
    parser.add_argument("--experiment-name", default=None, help="Optional RAGAS experiment name.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    cases = load_ragas_eval_cases(args.cases)
    observations = load_ragas_eval_observations(args.observations)
    rows = build_ragas_rows(cases, observations)
    specs = select_ragas_metric_specs(
        rows,
        profile=args.profile,
        requested_metrics=args.metric or None,
    )
    result = evaluate_ragas_rows(
        rows,
        metric_specs=specs,
        settings=load_settings(),
        llm_model=args.llm_model,
        embedding_model=args.embedding_model,
        show_progress=bool(args.show_progress),
        experiment_name=args.experiment_name,
    )
    output_payload = {
        "summary": result["summary"],
        "selected_metrics": result["selected_metrics"],
        "executed_metrics": result["executed_metrics"],
        "skipped_metrics": result["skipped_metrics"],
        "runtime_warnings": result["runtime_warnings"],
        "score_rows": result["score_rows"],
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(output_payload, ensure_ascii=False, indent=2))
    else:
        print(format_ragas_eval_report(result["summary"]))
    return 0


def _normalize_metric_name(name: str) -> str:
    normalized = (_clean_text(name) or "").lower().replace("-", "_").replace(" ", "_")
    return _METRIC_ALIASES.get(normalized, normalized)


def _import_metric_class(spec: MetricSpec) -> Any | None:
    for module_name, attr_name in spec.import_candidates:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        metric_cls = getattr(module, attr_name, None)
        if metric_cls is not None:
            return metric_cls
    return None


def _metric_name(metric: Any) -> str:
    text = _clean_text(getattr(metric, "name", None))
    return text or metric.__class__.__name__


def _extract_score_rows(result: Any) -> list[dict[str, Any]]:
    raw_scores = getattr(result, "scores", None)
    if isinstance(raw_scores, list):
        rows = raw_scores
    else:
        rows = list(raw_scores or [])
    normalized: list[dict[str, Any]] = []
    for row in rows:
        row_map = dict(row or {})
        converted: dict[str, Any] = {}
        for key, value in row_map.items():
            if hasattr(value, "value"):
                converted[str(key)] = getattr(value, "value")
            elif isinstance(value, Mapping) and "value" in value:
                converted[str(key)] = value.get("value")
            else:
                converted[str(key)] = value
        normalized.append(converted)
    return normalized


def _observation_contexts(observation: RagasEvalObservation) -> tuple[list[str], list[str]]:
    contexts: list[str] = []
    context_ids: list[str] = []
    seen_contexts: set[str] = set()
    seen_ids: set[str] = set()
    pack = observation.evidence_pack
    if pack is not None:
        for item in getattr(pack, "items", []) or []:
            claim = _clean_text(getattr(item, "claim", None))
            evidence_id = _clean_text(getattr(item, "evidence_id", None) or getattr(item, "chunk_id", None))
            if claim and claim not in seen_contexts:
                seen_contexts.add(claim)
                contexts.append(claim)
            if evidence_id and evidence_id not in seen_ids:
                seen_ids.add(evidence_id)
                context_ids.append(evidence_id)
    metrics = dict(observation.metrics or {})
    for raw_context in metrics.get("retrieved_contexts") or []:
        text = _clean_text(raw_context)
        if text and text not in seen_contexts:
            seen_contexts.add(text)
            contexts.append(text)
    for raw_context_id in metrics.get("retrieved_context_ids") or []:
        text = _clean_text(raw_context_id)
        if text and text not in seen_ids:
            seen_ids.add(text)
            context_ids.append(text)
    return contexts, context_ids


__all__ = [
    "MetricSpec",
    "RagasEvalCase",
    "RagasEvalObservation",
    "RagasRuntime",
    "build_ragas_rows",
    "build_ragas_runtime",
    "evaluate_ragas_rows",
    "format_ragas_eval_report",
    "instantiate_ragas_metrics",
    "load_ragas_eval_cases",
    "load_ragas_eval_observations",
    "main",
    "select_ragas_metric_specs",
    "summarize_ragas_observation",
    "summarize_ragas_results",
]
