"""Debug script: test recommendation follow-up flow."""
import sys
sys.path.insert(0, "D:\\javacode\\hm-dianping\\local_life_agent")

from local_life_agent.agent import run_agent_graph
from local_life_agent.session.store import get_session_store, reset_session_store

# Reset session store
from session.store import reset_session_store
reset_session_store()

# First: run recommendation
resp1 = run_agent_graph("附近推荐火锅", "test_diag_followup")
print("=== FIRST CALL (recommendation) ===")
print(f"answer: {resp1.answer_text[:100] if resp1.answer_text else '(empty)'}")

# Check session store
store = get_session_store()
ss = store.load("test_diag_followup")
last_rec = getattr(ss, "last_recommendation_list", []) or []
print(f"last_recommendation_list has {len(last_rec)} items")
if last_rec:
    for item in last_rec[:3]:
        print(f"  shop: {item.get('shop_name')} id={item.get('shop_id')}")
else:
    print("  (empty!)")

# Second: follow-up
resp2 = run_agent_graph("第一家有券吗", "test_diag_followup")
print()
print("=== SECOND CALL (follow-up) ===")
print(f"answer: {resp2.answer_text[:100] if resp2.answer_text else '(empty)'}")

# Check debug info
if resp2.debug:
    sf = resp2.debug.semantic_frame or {}
    print(f"semantic_frame.task_type: {sf.get('task_type')}")
    print(f"ordinal_references: {sf.get('ordinal_references')}")
    from planning.plans.state_update_planner import plan_state_update
    tool_results = resp2.debug.tool_results or {}
    print(f"tool_results keys: {list(tool_results.keys())[:5]}")
    tool_names = []
    for k, v in tool_results.items():
        if isinstance(v, dict):
            tn = v.get("tool_name", "")
            if tn:
                tool_names.append(tn)
    print(f"tool_names: {tool_names}")
    print(f"evidence_pack.ranking: {resp2.debug.evidence_pack.get('ranking_snapshot', {}).get('ranked', []) if resp2.debug.evidence_pack else 'N/A'}")
