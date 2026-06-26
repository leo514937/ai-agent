param(
    [string]$Profile = "local_life_agent/eval/profiles/real_e2e.yaml",
    [string]$OutputDir = "local_life_agent/eval/reports"
)

$ErrorActionPreference = "Stop"

$env:LOCAL_LIFE_LLM_BACKEND = "real_llm"
if (-not $env:LOCAL_LIFE_TOOL_BACKEND) {
    $env:LOCAL_LIFE_TOOL_BACKEND = "db"
}
$env:ENABLE_REAL_LLM = "true"
$env:ENABLE_LLM_VERBALIZER = "true"
$env:DEBUG_ENABLED = "true"

python -m local_life_agent.eval.run_eval --profile $Profile --output-dir $OutputDir
exit $LASTEXITCODE
