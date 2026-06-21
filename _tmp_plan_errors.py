from local_life_agent import config
from local_life_agent.agent import run_agent_graph
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.llm.client import set_llm_backend, clear_llm_backend
from local_life_agent.session.store import reset_session_store
from local_life_agent.planning.plan_validator import ExecutionPlanValidator
from local_life_agent.domain.schemas import ExecutionPlan

backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
try:
    reset_session_store()
    resp = run_agent_graph('附近有没有适合约会、现在营业、最好有券的火锅？', 'probe_plan_errors')
    plan = ExecutionPlan.model_validate(resp.debug.execution_plan)
    validator = ExecutionPlanValidator()
    report = validator.validate(plan)
    print('ERRORS', report.errors)
    print('PLAN', plan.model_dump())
finally:
    clear_llm_backend()
