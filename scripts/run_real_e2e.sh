#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-local_life_agent/eval/profiles/real_e2e.yaml}"
OUTPUT_DIR="${2:-local_life_agent/eval/reports}"

export LOCAL_LIFE_LLM_BACKEND=real_llm
export LOCAL_LIFE_TOOL_BACKEND="${LOCAL_LIFE_TOOL_BACKEND:-db}"
export ENABLE_REAL_LLM=true
export ENABLE_LLM_VERBALIZER=true
export DEBUG_ENABLED=true

python -m local_life_agent.eval.run_eval --profile "$PROFILE" --output-dir "$OUTPUT_DIR"
