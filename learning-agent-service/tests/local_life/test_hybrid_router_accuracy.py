from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from learning_agent_service.local_life.hybrid_router import HybridRouter


def load_golden_cases() -> list[dict]:
    """Load golden cases from JSONL file."""
    cases = []
    project_root = Path(__file__).resolve().parents[2]
    golden_path = project_root / "eval" / "local_life" / "golden_cases.jsonl"
    with open(golden_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def map_expected_intent(case: dict) -> str:
    """Map golden case to expected intent for HybridRouter."""
    query = case.get("query", "")
    description = case.get("description", "")
    expected_metrics = case.get("expected_metrics", {})
    
    # Map based on expected_metrics and description
    if expected_metrics.get("out_of_scope"):
        return "out_of_scope"
    
    if "比较" in description or "comparison" in str(expected_metrics.get("answer_style", "")):
        return "detail"  # HybridRouter groups comparison under detail
    
    if "推荐" in description or "recommendation" in str(expected_metrics.get("recommendation_mode", "")):
        return "recommend"
    
    if "券" in description or "coupon" in str(expected_metrics.get("answer_style", "")):
        return "realtime"  # HybridRouter groups coupon under realtime
    
    if "营业" in description or "open_status" in str(expected_metrics.get("answer_style", "")):
        return "realtime"  # HybridRouter groups open_status under realtime
    
    if "距离" in description or "导航" in description or "distance" in str(expected_metrics.get("answer_style", "")):
        return "realtime"  # HybridRouter groups navigation under realtime
    
    if "澄清" in description or "clarification" in str(expected_metrics.get("answer_style", "")):
        return "clarification"
    
    if "单店" in description or "详情" in description:
        return "detail"
    
    if "问候" in description or "你好" in query:
        return "greeting"
    
    # Default to local_life related intents
    if any(kw in query for kw in ["怎么样", "好吃吗", "评价", "口碑"]):
        return "detail"
    
    if any(kw in query for kw in ["推荐", "附近", "好吃"]):
        return "recommend"
    
    return "local_life"


def test_hybrid_router_accuracy():
    """Test HybridRouter accuracy against golden cases."""
    router = HybridRouter()
    cases = load_golden_cases()
    
    total = len(cases)
    correct = 0
    incorrect = []
    
    start_time = time.time()
    
    for case in cases:
        query = case.get("query", "")
        expected_intent = map_expected_intent(case)
        
        decision, _ = router.route(query)
        actual_intent = decision.intent
        
        if actual_intent == expected_intent:
            correct += 1
        else:
            incorrect.append({
                "case_id": case.get("case_id"),
                "query": query,
                "expected": expected_intent,
                "actual": actual_intent,
                "description": case.get("description"),
            })
    
    elapsed = time.time() - start_time
    accuracy = correct / total * 100 if total > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"HybridRouter Golden Cases Accuracy Test")
    print(f"{'='*60}")
    print(f"Total cases: {total}")
    print(f"Correct: {correct}")
    print(f"Incorrect: {total - correct}")
    print(f"Accuracy: {accuracy:.1f}%")
    print(f"Average latency: {elapsed/total*1000:.1f}ms per query")
    print(f"{'='*60}")
    
    if incorrect:
        print(f"\nIncorrect cases ({len(incorrect)}):")
        for item in incorrect[:10]:  # Show first 10 incorrect cases
            print(f"  [{item['case_id']}] {item['query']}")
            print(f"    Expected: {item['expected']}, Actual: {item['actual']}")
            print(f"    Description: {item['description']}")
    
    return accuracy >= 90


if __name__ == "__main__":
    success = test_hybrid_router_accuracy()
    sys.exit(0 if success else 1)
