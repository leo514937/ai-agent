# RAGAS 使用说明

本文说明如何在本仓库里使用 RAGAS 评测 local life 的 RAG 能力。

## 入口

- 实现代码：`learning-agent-service/src/learning_agent_service/rag/ragas_eval.py`
- 单测覆盖：`learning-agent-service/tests/local_life/rag/test_ragas_eval.py`

## 评测目标

RAGAS 用来验证下面几类能力：

- 检索到的上下文是否足够
- 回答是否忠实于检索上下文
- 回答是否和用户问题相关
- 在有参考答案时，回答是否接近参考答案

## 数据准备

RAGAS 评测分成两类输入：

1. `RagasEvalCase`
   - 代表待评测样例
   - 至少包含 `case_id`、`query`
   - 推荐额外提供：
     - `reference`
     - `reference_contexts`
     - `reference_context_ids`
     - `turns`
     - `metadata`

2. `RagasEvalObservation`
   - 代表模型实际输出
   - 至少包含 `case_id`、`query`、`response`
   - 推荐额外提供：
     - `metrics`
     - `evidence_pack`

## 典型流程

1. 准备评测样例，通常来自 golden case、回放日志或手工整理 JSONL。
2. 用业务链路跑出回答和检索证据。
3. 调用 `summarize_ragas_observation(...)` 把单条输出整理成 RAGAS 所需结构。
4. 调用 `build_ragas_rows(...)` 汇总成评测行。
5. 调用 `select_ragas_metric_specs(...)` 选择适合当前数据的指标集。
6. 用 `summarize_ragas_results(...)` 汇总分数，再用 `format_ragas_eval_report(...)` 输出报告。

## 常用指标选择

- 有参考答案时，优先看：
  - `answer_relevancy`
  - `faithfulness`
  - `context_precision`
  - `context_recall`
  - `context_entity_recall`
  - `factual_correctness`
  - `semantic_similarity`
- 没有参考答案时，优先看：
  - `answer_relevancy`
  - `faithfulness`
  - `context_utilization`
- 想做轻量回归时，可以先用 `basic` profile。
- 想做完整离线评测时，可以用 `full` profile。

## 示例

```python
from pathlib import Path

from learning_agent_service.local_life.eval import load_golden_cases
from learning_agent_service.rag.ragas_eval import (
    build_ragas_rows,
    format_ragas_eval_report,
    select_ragas_metric_specs,
    summarize_ragas_observation,
    summarize_ragas_results,
)

cases = load_golden_cases(Path("learning-agent-service/eval/local_life/golden_cases.jsonl"))

# observation 通常来自线上回放、chat test client 或离线批处理结果
observation = summarize_ragas_observation(
    case=cases[0],
    response="示例回答",
    metrics={"rag_mode": "single_shop_rag"},
    evidence_pack=None,
)

rows = build_ragas_rows((cases[0],), (observation,))
metric_specs = select_ragas_metric_specs(rows, profile="full")
summary = summarize_ragas_results(
    rows=rows,
    score_rows=[],
    metric_specs=metric_specs,
    skipped_metrics=[],
    evaluation_backend="ragas",
)
report = format_ragas_eval_report(summary)
print(report)
```

## 运行建议

- 本地先跑单测：
  - `python -m pytest -q learning-agent-service/tests/local_life/rag/test_ragas_eval.py`
- 再接真实样例跑一轮小批量评测，确认：
  - `retrieved_contexts` 非空
  - `response` 与 `reference` 对齐
  - `faithfulness` 没有明显掉分

## 注意事项

- 如果只提供 `query` 和 `response`，很多 reference 相关指标会被自动跳过，这是正常的。
- 如果 `evidence_pack` 为空，`faithfulness` 和 `context_precision` 的解释力会变弱。
- 线上评测时要尽量固定同一批样例和同一版本知识库，否则分数不可比。
