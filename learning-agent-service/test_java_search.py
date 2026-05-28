import asyncio
import json
from learning_agent_service.adapters.java_business import JavaBusinessClient

client = JavaBusinessClient()

payload = client._request_json(
    "POST",
    "/internal/v1/business/shops/search",
    json_body={
        "message": "卷卷烤肉",
        "limit": 5,
        "context": {
            "shopName": "卷卷烤肉",
            "shopQuery": "卷卷烤肉",
        },
    },
)

print("POST /internal/v1/business/shops/search result:")
print(json.dumps(payload, ensure_ascii=False, indent=2))
