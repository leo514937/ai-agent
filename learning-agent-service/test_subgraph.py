import asyncio
import json
from learning_agent_service.local_life.slot_extractor import extract_slots
from learning_agent_service.local_life.query_rewriter import normalize_query
from learning_agent_service.local_life.subgraph import LocalLifeSubgraph
from learning_agent_service.local_life.schemas import UserNeed, CommandState
from learning_agent_service.adapters.java_business import JavaBusinessClient

query = "卷卷烤肉这家店怎么样"
understanding = normalize_query(query, client_context={}, session_context={}, model_hint=None)
slots, clarification, intent = extract_slots(understanding, query, client_context={}, session_context={}, model_hint=None)

subgraph = LocalLifeSubgraph(business_client=JavaBusinessClient())
command = CommandState(message=query, trace_id="1", session_id="1", turn_id="1", request_id="1")
user_need = UserNeed(original_query=query, semantic_query=query, slots=slots, intent=intent)

async def test():
    async for event in subgraph.run_stream(command, user_need):
        if event.get("type") == "tool_call":
            print(json.dumps(event, ensure_ascii=False, indent=2))
        if event.get("type") == "message":
            print(json.dumps(event, ensure_ascii=False, indent=2))

asyncio.run(test())
