import asyncio
import json
from learning_agent_service.adapters.java_business import JavaBusinessClient

client = JavaBusinessClient()
print("By name:")
try:
    shops = client.search_shops_by_name(name="卷卷烤肉", current=1)
    for s in shops:
        print(s.model_dump())
except Exception as e:
    print(e)

print("By type:")
try:
    shops = client.search_shops_by_type(type_id=1, current=1)
    for s in shops:
        print(s.name, s.type_name)
except Exception as e:
    print(e)
