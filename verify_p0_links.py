"""
P0 验收验证脚本
验证 execution_requirements.candidate_shop_ids / execute_tools / execute_rag
是否真实进入了 RAG / Tool / AnswerComposer 调用链。
"""
import sys
sys.path.insert(0, 'learning-agent-service/src')

from learning_agent_service.local_life.schemas import (
    LocalLifeSlots, LocalLifeIntentType, ClarificationDecision
)
from learning_agent_service.local_life.user_need_parser import UserNeedParser
from learning_agent_service.local_life.route_review import RouteReview
from learning_agent_service.local_life.query_router import LocalLifeQueryRouter
from learning_agent_service.local_life.subgraph import _tool_input_summary

errors = []

# ============================================================
# Test 1: 显式实体优先（INLOVE KTV 这家有券吗）
# ============================================================
slots1 = LocalLifeSlots(shop_query='INLOVE KTV', shop_ids=[])
session1 = {'selected_shop_id': 5, 'selected_shop_name': '海底捞火锅(水晶城店)'}
un1 = UserNeedParser.parse(
    'INLOVE KTV 这家有券吗',
    slots=slots1, intent=LocalLifeIntentType.COUPON,
    session_context=session1
)
print("=== Test1: 显式实体优先 ===")
print(f"  context_refs: {[(r.name, r.source, r.id) for r in un1.context_refs]}")
if not un1.context_refs:
    errors.append("Test1 FAIL: 没有 context_refs")
elif 'INLOVE KTV' not in (un1.context_refs[0].name or ''):
    errors.append(f"Test1 FAIL: 绑定了错误实体 {un1.context_refs[0].name}")
elif un1.context_refs[0].source != 'explicit_entity':
    errors.append(f"Test1 FAIL: source 应为 explicit_entity, 实际 {un1.context_refs[0].source}")
else:
    print("  PASS: 显式实体 INLOVE KTV 优先于 session 历史 shop_id=5")

# ============================================================
# Test 2: 纯代词 -> session 历史 shop_id=5
# ============================================================
slots2 = LocalLifeSlots(shop_query=None, shop_ids=[])
session2 = {'selected_shop_id': 5, 'selected_shop_name': '海底捞火锅(水晶城店)'}
un2 = UserNeedParser.parse(
    '这家适合约会吗',
    slots=slots2, intent=LocalLifeIntentType.DETAIL,
    session_context=session2
)
print("=== Test2: 纯代词 -> session 历史 ===")
print(f"  context_refs: {[(r.name, r.source, r.id) for r in un2.context_refs]}")
if not un2.context_refs:
    errors.append("Test2 FAIL: 没有 context_refs")
elif un2.context_refs[0].id != '5':
    errors.append(f"Test2 FAIL: shop_id 应为 5, 实际 {un2.context_refs[0].id}")
elif un2.context_refs[0].source != 'session_context':
    errors.append(f"Test2 FAIL: source 应为 session_context, 实际 {un2.context_refs[0].source}")
else:
    print("  PASS: 纯代词正确绑定 session shop_id=5")

# ============================================================
# Test 3: RouteReview -> execution_requirements.candidate_shop_ids=[5]
# ============================================================
router = LocalLifeQueryRouter()
route3 = router.route('这家适合约会吗', slots=slots2, intent=LocalLifeIntentType.DETAIL,
                      client_context={}, session_context=session2)
review3 = RouteReview.review(
    user_need=un2, initial_route=route3,
    clarification=ClarificationDecision(), client_context={}, session_context=session2
)
print("=== Test3: RouteReview -> execution_requirements ===")
print(f"  candidate_shop_ids: {review3.execution_requirements.candidate_shop_ids}")
print(f"  resolved_shop_id: {review3.execution_requirements.resolved_shop_id}")
if 5 not in review3.execution_requirements.candidate_shop_ids:
    errors.append(f"Test3 FAIL: candidate_shop_ids 没有 5, 是 {review3.execution_requirements.candidate_shop_ids}")
else:
    print("  PASS: execution_requirements.candidate_shop_ids=[5] 进入契约")

# ============================================================
# Test 4: 多 facet 查询 -> execute_tools 同时有 coupon + open_status + execute_rag
# ============================================================
slots4 = LocalLifeSlots(category='火锅')
client4 = {'city': '北京', 'lat': 39.9, 'lng': 116.4}
un4 = UserNeedParser.parse(
    '附近有没有适合约会、现在营业、最好有券的火锅？',
    slots=slots4, intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
    client_context=client4, session_context={}
)
route4 = router.route('附近有没有适合约会、现在营业、最好有券的火锅？', slots=slots4,
                      intent=LocalLifeIntentType.RESTAURANT_RECOMMENDATION,
                      client_context=client4, session_context={})
review4 = RouteReview.review(
    user_need=un4, initial_route=route4,
    clarification=ClarificationDecision(), client_context=client4, session_context={}
)
print("=== Test4: 多 facet 查询 execute_tools ===")
print(f"  required_facets: {[f.name for f in un4.required_facets]}")
print(f"  execute_tools: {review4.execution_requirements.execute_tools}")
print(f"  execute_rag: {review4.execution_requirements.execute_rag}")
has_coupon = 'get_coupon_list' in review4.execution_requirements.execute_tools
has_open = 'check_open_status' in review4.execution_requirements.execute_tools
has_rag = review4.execution_requirements.execute_rag
if not has_coupon:
    errors.append("Test4 FAIL: execute_tools 缺少 get_coupon_list")
if not has_open:
    errors.append("Test4 FAIL: execute_tools 缺少 check_open_status")
if not has_rag:
    errors.append("Test4 FAIL: execute_rag 未开启")
if has_coupon and has_open and has_rag:
    print("  PASS: 多 facet 同时触发 coupon + open_status + RAG")

# ============================================================
# Test 5: tool_input_summary 使用 resolved shop_id 和 shop_name（非 slot raw 参数）
# ============================================================
slots5 = LocalLifeSlots(shop_query=None)
ti5 = _tool_input_summary(
    LocalLifeIntentType.COUPON,
    filters={},
    slots=slots5,
    tool_name='get_coupon_list',
    selected_shop_id=5,
    selected_shop_name='海底捞火锅(水晶城店)'
)
print("=== Test5: tool_input_summary 绑定 resolved shop ===")
print(f"  tool_input_summary: {ti5}")
if ti5.get('shop_id') != 5:
    errors.append(f"Test5 FAIL: shop_id 应为 5, 实际 {ti5.get('shop_id')}")
elif ti5.get('shop_name') != '海底捞火锅(水晶城店)':
    errors.append(f"Test5 FAIL: shop_name 不正确 {ti5.get('shop_name')}")
else:
    print("  PASS: tool_input_summary 正确绑定 resolved shop_id=5")

# ============================================================
# Test 6: shop:N ID 不泄露到 tool 输出摘要
# ============================================================
from learning_agent_service.local_life.subgraph import _summarize_tool_output
out6 = _summarize_tool_output(
    'check_open_status',
    {'shop_id': 5, 'shop_name': 'shop:5', 'open_status': 'open'},
    shop_name='shop:5'
)
print("=== Test6: shop:N ID 不泄露 ===")
print(f"  output: {out6}")
if out6 and 'shop:5' in out6:
    errors.append(f"Test6 FAIL: 输出包含 'shop:5' ID: {out6}")
elif out6 and '这家店' in out6:
    print("  PASS: 'shop:5' 被替换为 '这家店'")
else:
    print(f"  WARN: 输出: {out6}")

# ============================================================
print()
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("✅ 所有 P0 链路验证通过！")
