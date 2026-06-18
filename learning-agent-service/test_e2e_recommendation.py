# 端到端测试脚本：验证推荐功能
from learning_agent_service.local_life.prompt_engine import get_prompt_engine

engine = get_prompt_engine()

# 模拟店铺数据
shop_data = [
    {"name": "海底捞(望京店)", "score": 4.8, "avg_price": 120, "distance": 1.2, "特色": ["服务好", "有宝宝椅"], "comments": 856},
    {"name": "巴奴毛肚火锅(三里屯店)", "score": 4.7, "avg_price": 150, "distance": 2.3, "特色": ["毛肚鲜嫩", "牛油锅底"], "comments": 623},
    {"name": "小龙坎(国贸店)", "score": 4.5, "avg_price": 100, "distance": 0.8, "特色": ["性价比高", "麻辣过瘾"], "comments": 412},
]

evidence_lines = ["候选店铺:"]
for i, shop in enumerate(shop_data, 1):
    evidence_lines.append(f"{i}. {shop['name']} - 评分{shop['score']}, 人均{shop['avg_price']}元, 距离{shop['distance']}km, 特色:{', '.join(shop['特色'])}, 评价数{shop['comments']}")

evidence_context = "\n".join(evidence_lines)

messages = engine.build_messages("multi_shop_recommendation", "推荐火锅", evidence_context)
print("Messages count:", len(messages))
print("System prompt preview:", messages[0]["content"][:200])
print("\n--- Few-shot examples ---")
for i, msg in enumerate(messages[1:7], 1):
    print(f"Message {i}: role={msg['role']}, content_length={len(msg['content'])}")
print("\n--- User message ---")
print(messages[-1]["content"][:300])
