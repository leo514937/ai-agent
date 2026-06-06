import sys
import unittest
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient

TESTS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"
for candidate in (str(TESTS_DIR), str(PROJECT_ROOT), str(SRC_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import _bootstrap
from chat_test_client import ChatStreamTestClient
from learning_agent_service.app import app as fastapi_app
from learning_agent_service.domain.contracts import PlanStep, StepResult
from learning_agent_service.domain.state import GraphState

class Day3ReplayInterruptRetryTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = ChatStreamTestClient()
        cls.api_client = TestClient(fastapi_app)
        cls.headers = {"X-Internal-Token": "local-learning-agent-token"}

    def test_day3_state_history_replay_and_fork(self) -> None:
        session_id = f"day3-replay-fork-{uuid4().hex[:8]}"
        # Send first message
        result = self.client.post_message(
            message="海底捞水晶店有券吗？",
            session_id=session_id,
            extra_payload={
                "shopName": "海底捞水晶店",
                "shopId": 5,
            },
        )
        self.assertTrue(result.final_answer)

        # 1. Get history
        response = self.api_client.get(
            f"/internal/v1/session/{session_id}/state/history",
            headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        history_data = response.json()
        self.assertEqual(history_data["session_id"], session_id)
        history = history_data["history"]
        self.assertGreater(len(history), 0)

        # Capture a valid checkpoint
        checkpoint_id = history[0]["checkpoint_id"]
        self.assertIsNotNone(checkpoint_id)

        # 2. Replay state
        replay_resp = self.api_client.post(
            f"/internal/v1/session/{session_id}/state/replay",
            json={"checkpoint_id": checkpoint_id},
            headers=self.headers
        )
        self.assertEqual(replay_resp.status_code, 200)
        
        # 3. Fork state to a new session with modified routing contracts
        target_session_id = f"fork-session-{uuid4().hex[:8]}"
        fork_resp = self.api_client.post(
            f"/internal/v1/session/{session_id}/state/fork",
            json={
                "checkpoint_id": checkpoint_id,
                "target_session_id": target_session_id,
                "state_patch": {
                    "turn": {
                        "routing_contract": {
                            "required_action": "direct_answer",
                            "compose_allowed_facets": ["coupon"],
                            "forbidden_facets": ["environment"]
                        }
                    }
                }
            },
            headers=self.headers
        )
        self.assertEqual(fork_resp.status_code, 200)
        forked_data = fork_resp.json()
        self.assertEqual(forked_data["session_id"], target_session_id)

    def test_day3_flow_interrupt_and_resume(self) -> None:
        session_id = f"day3-interrupt-{uuid4().hex[:8]}"
        self.client.post_message(
            message="海底捞水晶店怎么样？",
            session_id=session_id
        )
        
        # Get latest checkpoint_id
        history_resp = self.api_client.get(
            f"/internal/v1/session/{session_id}/state/history",
            headers=self.headers
        )
        checkpoint_id = history_resp.json()["history"][0]["checkpoint_id"]
        
        target_session_id = f"fork-interrupt-{uuid4().hex[:8]}"
        
        # Define step requiring approval
        step = PlanStep(
            step_id="step-approval-needed",
            goal="需要人工审批的高风险任务",
            expected_output="高风险任务结论",
            risk_level="high",
            requires_approval=True,
            allowed_tools=["get_coupon_list"]
        )
        
        patch_payload = {
            "turn": {
                "execution_mode": "plan_execute",
                "task_complexity": "complex",
                "plan": [step.model_dump(mode="json")],
                "current_step_index": 0,
                "current_step": step.model_dump(mode="json"),
                "need_human_approval": True,
                "step_results": []
            }
        }
        
        # Forking will invoke the target session graph up to the plan_execute interrupt
        fork_resp = self.api_client.post(
            f"/internal/v1/session/{session_id}/state/fork",
            json={
                "checkpoint_id": checkpoint_id,
                "target_session_id": target_session_id,
                "state_patch": patch_payload
            },
            headers=self.headers
        )
        self.assertEqual(fork_resp.status_code, 200)
        
        # Check current session state, it should be blocked on approval
        state_resp = self.api_client.get(
            f"/internal/v1/session/{target_session_id}/state",
            headers=self.headers
        )
        state_data = state_resp.json()
        self.assertEqual(state_data["current_stage"], "plan_execute")
        self.assertEqual(state_data["stage_status"], "blocked")
        
        # Submit approval to resume execution
        approval_resp = self.api_client.post(
            "/internal/v1/approval/submit",
            json={
                "user_id": f"test-user-{target_session_id}",
                "session_id": target_session_id,
                "trace_id": f"trace-interrupt-{uuid4().hex[:8]}",
                "turn_id": f"turn-interrupt-{uuid4().hex[:8]}",
                "decision": "approved",
                "approval_request": {"step_id": "step-approval-needed"}
            },
            headers=self.headers
        )
        self.assertEqual(approval_resp.status_code, 200)
        
        # Verify the session has resumed and reached emit_final stage successfully
        final_state_resp = self.api_client.get(
            f"/internal/v1/session/{target_session_id}/state",
            headers=self.headers
        )
        final_state_data = final_state_resp.json()
        self.assertEqual(final_state_data["current_stage"], "emit_final")
        self.assertEqual(final_state_data["stage_status"], "completed")

    def test_day3_tool_degradation(self) -> None:
        from unittest.mock import patch
        session_id = f"day3-degrade-{uuid4().hex[:8]}"
        
        # Mock JavaBusinessClient to fail, triggering tool degradation
        with patch("learning_agent_service.adapters.java_business.JavaBusinessClient.get_coupon_list", side_effect=Exception("Java Tool API Offline")):
            result = self.client.post_message(
                message="海底捞水晶店有券吗？",
                session_id=session_id,
                extra_payload={
                    "shopName": "海底捞水晶店",
                    "shopId": 5,
                },
            )
            
            print("\n=== Degraded Answer ===")
            print(result.final_answer)
            print("=========================")
            
            self.assertIn("实时券信息暂不可用，请稍后再试。", result.final_answer)
            self.assertTrue(result.metrics.get("tool_degraded") or result.metrics.get("tool_results_degraded_total", 0) > 0 or "degraded" in str(result.events))

if __name__ == "__main__":
    unittest.main()
