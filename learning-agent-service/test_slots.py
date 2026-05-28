import asyncio
import json
from learning_agent_service.local_life.slot_extractor import extract_slots
from learning_agent_service.local_life.query_rewriter import normalize_query

query = "卷卷烤肉这家店怎么样"
understanding = normalize_query(query, client_context={}, session_context={}, model_hint=None)
slots, clarification, intent = extract_slots(understanding, query, client_context={}, session_context={}, model_hint=None)

print(json.dumps({
    "slots": slots.model_dump(),
    "intent": intent.value if intent else None
}, ensure_ascii=False, indent=2))
