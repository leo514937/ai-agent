import json
from local_life_agent import config
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
res = backend(prompt='Reply with exactly OK', system_prompt='You are a helpful assistant.', temperature=0.0, timeout_ms=config.LLM_TIMEOUT_MS)
print(json.dumps({k: res.get(k) for k in ['ok','provider','model','transport','llm_backend','content','raw']}, ensure_ascii=False))
