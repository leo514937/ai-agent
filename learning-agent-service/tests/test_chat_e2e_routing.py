from __future__ import annotations

import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any

# Add the src directory to the Python path
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

import _bootstrap  # noqa: F401

from learning_agent_service.application.workflow.adapters.helpers import build_initial_routing_decision
from learning_agent_service.domain.contracts import PersistentSessionContext


@dataclass
class RoutingTestCase:
    query: str
    expected_action: str
    description: str
    persistent: PersistentSessionContext | None = None


def run_tests():
    test_cases = [
        # 本地生活查询 - 应该路由到 recommendation / tool_call
        RoutingTestCase("海底捞怎么样？", "tool_call", "单店详情查询"),
        RoutingTestCase("附近有什么好吃的火锅？", "recommendation", "推荐查询"),
        RoutingTestCase("海底捞和巴奴哪个好？", "recommendation", "比较查询"),
        RoutingTestCase("海底捞有券吗？", "tool_call", "优惠券查询"),
        RoutingTestCase("海底捞营业时间是什么？", "tool_call", "营业时间查询"),
        RoutingTestCase("海底捞离我多远？", "tool_call", "距离查询"),
        
        # 问候/闲聊 - 应该路由到 direct_answer
        RoutingTestCase("你好", "direct_answer", "问候语"),
        RoutingTestCase("谢谢", "direct_answer", "感谢语"),
        
        # 身份/能力查询 - 应该路由到 direct_answer
        RoutingTestCase("你是谁", "direct_answer", "身份查询"),
        RoutingTestCase("你能做什么", "direct_answer", "能力查询"),
        RoutingTestCase("怎么用你", "direct_answer", "使用说明"),
        
        # 超出范围 - 应该路由到 direct_answer
        RoutingTestCase("今天天气怎么样？", "direct_answer", "天气查询"),
        RoutingTestCase("帮我写代码", "direct_answer", "编程查询"),
        
        # 带上下文的查询
        RoutingTestCase(
            "有券吗？",
            "clarify",
            "缺少店名的优惠券查询",
            PersistentSessionContext(),
        ),
        RoutingTestCase(
            "有券吗？",
            "tool_call",
            "有当前店铺的优惠券查询",
            PersistentSessionContext(current_shop="海底捞"),
        ),
        RoutingTestCase(
            "地址在哪？",
            "clarify",
            "缺少店名的地址查询",
            PersistentSessionContext(),
        ),
        RoutingTestCase(
            "地址在哪？",
            "tool_call",
            "有当前店铺的地址查询",
            PersistentSessionContext(current_shop="海底捞"),
        ),
    ]
    
    total = len(test_cases)
    correct = 0
    incorrect = []
    
    start_time = time.time()
    
    for case in test_cases:
        try:
            routing = build_initial_routing_decision(
                case.query,
                case.persistent or PersistentSessionContext(),
            )
            
            if routing.required_action == case.expected_action:
                correct += 1
            else:
                incorrect.append({
                    "query": case.query,
                    "expected": case.expected_action,
                    "actual": routing.required_action,
                    "description": case.description,
                })
        except Exception as e:
            incorrect.append({
                "query": case.query,
                "expected": case.expected_action,
                "actual": f"ERROR: {str(e)}",
                "description": case.description,
            })
    
    elapsed = time.time() - start_time
    accuracy = correct / total * 100 if total > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"Chat Workflow End-to-End Test")
    print(f"{'='*60}")
    print(f"Total cases: {total}")
    print(f"Correct: {correct}")
    print(f"Incorrect: {total - correct}")
    print(f"Accuracy: {accuracy:.1f}%")
    print(f"Average latency: {elapsed/total*1000:.1f}ms per query")
    print(f"{'='*60}")
    
    if incorrect:
        print(f"\nIncorrect cases ({len(incorrect)}):")
        for item in incorrect:
            print(f"  [{item['description']}] {item['query']}")
            print(f"    Expected: {item['expected']}, Actual: {item['actual']}")
    
    return accuracy >= 90


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
