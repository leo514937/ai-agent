# RAGAS 接入说明

## 1. 目标

本次接入采用“在现有评测体系上叠加 RAGAS”的方式，不替换仓库中已有的：

- 检索层离线指标
- 本地生活 RAG 合同指标
- golden cases 回放评测

新增目标是补齐标准化生成评测，尤其是：

- 回答是否忠于检索证据
- 回答是否真正回答了问题
- 检索上下文是否足够
- 检索上下文是否噪声过多

## 2. 本次落地内容

### 2.1 新增代码

- `learning-agent-service/src/learning_agent_service/rag/ragas_eval.py`
  - RAGAS case / observation 数据结构
  - case + observation + evidence_pack -> RAGAS row 转换
  - 按样本能力自动选择可执行指标
  - OpenAI / OpenAI-compatible evaluator runtime 构建
  - RAGAS 执行与结果汇总
  - CLI `main()`

- `learning-agent-service/scripts/run_ragas_eval.py`
  - 命令行启动入口

### 2.2 新增评测数据

- `learning-agent-service/eval/local_life/rag_eval_cases.jsonl`
  - 补齐原有测试依赖的数据文件
  - 同时加入 RAGAS 所需字段：
    - `reference`
    - `reference_contexts`
    - `reference_context_ids`

### 2.3 新增测试

- `learning-agent-service/tests/local_life/rag/test_ragas_eval.py`
  - 验证 RAGAS row 转换
  - 验证指标自动选择
  - 验证结果汇总与报告输出

### 2.4 依赖与脚本

- `learning-agent-service/pyproject.toml`
  - 新增可选依赖：
    - `ragas>=0.4.0`
    - `rapidfuzz>=3.9.0`
  - 新增 script：
    - `run-ragas-eval`

## 3. 安装方式

在 `learning-agent-service` 目录下安装：

```bash
pip install -e .[ragas]
```

如果只需要现有项目运行，不跑 RAGAS，可以不安装这个 extra。

## 4. 运行前准备

### 4.1 环境变量

RAGAS 中依赖 LLM / Embeddings 的指标默认使用项目现有 OpenAI 配置：

- `LEARNING_AGENT_OPENAI_API_KEY`
- `OPENAI_API_KEY`
- `AI_API_KEY`
- `LEARNING_AGENT_OPENAI_BASE_URL`
- `OPENAI_BASE_URL`
- `LEARNING_AGENT_OPENAI_RESPONSES_MODEL`
- `LEARNING_AGENT_OPENAI_EMBEDDING_MODEL`

如果是 OpenAI-compatible 服务，也可以只设置 `BASE_URL + API_KEY`。

### 4.2 评测输入

RAGAS CLI 需要两类文件：

1. `cases`
2. `observations`

#### cases 文件

当前推荐使用：

`learning-agent-service/eval/local_life/rag_eval_cases.jsonl`

核心字段：

- `case_id`
- `query`
- `reference`
- `reference_contexts`
- `reference_context_ids`

最小样例：

```json
{
  "case_id": "single_shop_scene_fit_001",
  "query": "海底捞水晶城店适合约会吗？",
  "reference": "海底捞水晶城店环境安静，氛围不错，适合约会。",
  "reference_contexts": ["环境安静，适合约会。", "氛围不错。"],
  "reference_context_ids": ["ctx-5-1", "ctx-5-2"]
}
```

#### observations 文件

需要是 JSONL，每行一个 observation。

核心字段：

- `case_id`
- `query`
- `response`
- `metrics`
- `evidence_pack`

最小样例：

```json
{
  "case_id": "single_shop_scene_fit_001",
  "query": "海底捞水晶城店适合约会吗？",
  "response": "海底捞水晶城店环境安静，氛围不错，适合约会。",
  "metrics": {
    "rag_mode": "single_shop_rag"
  },
  "evidence_pack": {
    "raw_query": "海底捞水晶城店适合约会吗？",
    "rag_mode": "single_shop_rag",
    "target_shop_id": 5,
    "items": [
      {
        "evidence_id": "e-5-1",
        "chunk_id": "e-5-1",
        "source_type": "scene_fit",
        "shop_id": 5,
        "claim": "环境安静，适合约会。",
        "confidence": 0.92,
        "metadata": {"shop_id": 5}
      }
    ]
  }
}
```

### 4.3 retrieved_contexts 的来源

当前实现优先从 `evidence_pack.items[].claim` 提取 `retrieved_contexts`，并使用：

- `evidence_id`
- 或 `chunk_id`

生成 `retrieved_context_ids`。

如果 `metrics` 里已经有：

- `retrieved_contexts`
- `retrieved_context_ids`

也会作为补充合并进样本。

## 5. 运行方式

### 5.1 使用脚本

```bash
python scripts/run_ragas_eval.py ^
  --cases eval/local_life/rag_eval_cases.jsonl ^
  --observations var/eval/local_life/ragas_observations.jsonl ^
  --output var/eval/local_life/ragas_report.json ^
  --profile full
```

### 5.2 使用 console script

```bash
run-ragas-eval ^
  --cases eval/local_life/rag_eval_cases.jsonl ^
  --observations var/eval/local_life/ragas_observations.jsonl ^
  --output var/eval/local_life/ragas_report.json ^
  --profile full
```

### 5.3 只看终端报告

```bash
python scripts/run_ragas_eval.py ^
  --cases eval/local_life/rag_eval_cases.jsonl ^
  --observations var/eval/local_life/ragas_observations.jsonl
```

### 5.4 输出 JSON

```bash
python scripts/run_ragas_eval.py ^
  --cases eval/local_life/rag_eval_cases.jsonl ^
  --observations var/eval/local_life/ragas_observations.jsonl ^
  --json
```

## 6. 指标选择规则

### 6.1 `basic` profile

尽量只保留核心 RAG 指标：

- `answer_relevancy`
- `faithfulness`
- `context_precision`
- `context_utilization`
- `context_recall`

### 6.2 `full` profile

在样本字段满足时，会尽可能启用：

- `answer_relevancy`
- `faithfulness`
- `context_precision`
- `context_utilization`
- `context_recall`
- `context_entity_recall`
- `noise_sensitivity`
- `answer_correctness`
- `factual_correctness`
- `semantic_similarity`
- `nonllm_context_precision`
- `id_based_context_precision`
- `id_based_context_recall`
- `bleu_score`
- `rouge_score`
- `string_presence`
- `exact_match`
- `chrf_score`

### 6.3 自动降级策略

如果样本缺少 `reference`：

- 不跑依赖 `reference` 的指标
- 自动保留：
  - `answer_relevancy`
  - `faithfulness`
  - `context_utilization`

如果缺少 `reference_contexts`：

- 不跑 `nonllm_context_precision`

如果缺少 `retrieved_context_ids / reference_context_ids`：

- 不跑 `id_based_context_precision`
- 不跑 `id_based_context_recall`

如果没有 API Key：

- 不跑依赖 LLM / Embeddings 的指标
- 仍可运行传统文本指标，如：
  - `bleu_score`
  - `rouge_score`
  - `string_presence`
  - `exact_match`
  - `chrf_score`

## 7. 报告输出

终端报告包含：

- `case_count`
- `scored_case_count`
- `metric_means`
- `skipped_metrics`

JSON 报告额外包含：

- `selected_metrics`
- `executed_metrics`
- `runtime_warnings`
- `score_rows`

## 8. 与现有评测体系的关系

本次接入不替换现有指标：

- `learning_agent_service.rag.eval`
  - 继续承担检索层 `recall@k / mrr / ndcg`

- `learning_agent_service.rag.local_life_eval`
  - 继续承担业务合同类 RAG 指标

- `learning_agent_service.local_life.eval.run_golden_cases`
  - 继续承担 golden cases 回放验证

RAGAS 是新增的“生成质量与上下文质量”补充层。

## 9. 当前限制

1. 当前接入是单轮样本评测
2. observations 仍需要上游产出 `response + evidence_pack`
3. 当前 evaluator runtime 默认走项目已有 OpenAI / OpenAI-compatible 配置
4. 未直接接入 nightly / CI pipeline，需要后续再挂
5. 未接多轮会话级 RAGAS conversation metrics

## 10. 建议的后续接入顺序

1. 先把 replay / harness 输出稳定成 observation jsonl
2. 把 `run-ragas-eval` 接到 nightly
3. 为 `full` profile 配一套固定 evaluator model
4. 跑出第一版基线分数
5. 再决定哪些指标进入 CI 阈值门禁
