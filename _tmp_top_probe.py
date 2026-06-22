import json
from local_life_agent import config
from local_life_agent.llm.client import call_llm, set_llm_backend
from local_life_agent.llm.openai_backend import OpenAICompatibleBackend
from local_life_agent.semantic.intent_parser import parse_top_intent
backend = OpenAICompatibleBackend(provider=config.LLM_PROVIDER, model=config.LLM_MODEL, endpoint=config.LLM_ENDPOINT)
set_llm_backend(backend)
for text in ['附近推荐火锅', '海底捞(牡丹园店)和川味轩(知春路店)哪个好？', '便宜一点的呢', '第一家有券吗', '附近有没有适合约会、现在营业、最好有券的火锅？']:
    result = parse_top_intent(text, llm_call=call_llm)
    print(text, json.dumps(result, ensure_ascii=False))
