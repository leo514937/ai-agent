import os

content = """
### 4. 彻底解决“卷卷烤肉”被错误推荐为“海底捞”的幻觉缺陷
- **问题描述**: 当用户提问“卷卷烤肉这家店怎么样？”时，系统并未回复找不到该店铺，而是错误地强行推荐了“海底捞火锅(水晶城购物中心店)”，且给出的信息（如人均104元，评分0.5，营业时间10:00-07:00）完全是海底捞的属性。
- **根因分析**: 
  1. 用户的查询词“卷卷烤肉”被 Python 底层的 `slot_extractor` 正确提取为 `{"shop_query": "卷卷烤肉", "category": "烧烤"}`。
  2. `subgraph` 将提取的槽位传入 `java_business.py` 中的 `search_candidates` 方法，并触发按名称搜索的方法 `search_shops_by_name`。
  3. **Java Mock 接口降级幻觉**：`search_shops_by_name` 优先调用了 Java 后端 AI 智能大网关的 `POST /internal/v1/business/shops/search` 接口。由于数据库中不存在“卷卷烤肉”，该接口底层方法 `recommendCandidates` 在找不到具体店铺时，不是返回空列表，而是**隐式降级**，返回了数据库里“按评分和销量倒排”的头部候选店铺列表（包含 Mamala 和 海底捞 等）。
  4. **Python Agent 过滤兜底失效**：Python 层的 `subgraph` 在拿到候选列表后，尝试用类别“烧烤”进行校验。由于 Mamala 和 海底捞 均不含“烧烤”，过滤后的 `filtered_list` 变成了空列表。然而代码逻辑中存在缺陷 `if filtered_list: structured_candidates = filtered_list`，这意味着如果过滤结果为空，它**反而保留了全部的无效结果**（即保留了 Mamala 和 海底捞），并打包塞给了 RAG 进行意图作答，最终导致 LLM 据此“瞎编”出了海底捞的详情。
- **修复方案部署**: 
  - 修改 `learning_agent_service/src/learning_agent_service/local_life/subgraph.py` 中的过滤校验逻辑。
  - **精准拦截与清空**：如果 `slots.category` 过滤结果为空，现在会显式清空 `structured_candidates` 以避免残留无关数据。
  - **Shop Query 强制约束校验**：加入对特定商户名的精准拦截器：当 `slots.shop_query`（用户明确指定的搜索店名）存在时，在候选集中进行强制二次名称碰撞校验。若没有任何候选店铺的名字包含该搜索词，立刻将大模型上下文强行切断并重置为空。
  - **效果**: 如今问询不存在的“卷卷烤肉”等虚构门店时，大模型将正确回复“未找到该店铺的相关信息”，彻底根治了本地生活问答链路中的指鹿为马（幻觉推荐）故障。
"""

with open('doc/progress.md', 'a', encoding='utf-8') as f:
    f.write(content)
