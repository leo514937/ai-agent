# Phase 6 Closure / Phase 7 Preflight Report

## 1. Conclusion
- PHASE_6_COMPLETE: true
- LLM_MAIN_PATH_VERIFICATION_PASS: true
- COMPARISON_FLOW_PASS: true
- CHAT_E2E_SKIPPED_BLOCKS_PHASE_7: false
- SEMANTIC_CONSTRAINTS_STILL_HOLD: true
- CAN_ENTER_PHASE_7: true
- Main conclusion: Phase 6 remaining blockers have been repaired without weakening grounded-only answer behavior. The two failing comparison-flow follow-ups now pass, and the LLM failure fallback test preserves the original diagnostic semantic failure reason in trace observability. `test_chat_interface_full_e2e.py` still has 17 skipped cases, but they are environment-gated and do not block Phase 7 preflight.

## 2. Scope
This round only closed the remaining Phase 6 blockers and performed a Phase 7 preflight check.
No Phase 7 entity grounding / target resolution implementation was added.

## 3. Files Changed
| File | Change | Reason | Risk |
| --- | --- | --- | --- |
| `local_life_agent/observability/trace.py` | Preserved the more specific semantic parse fallback reason when the final state only had generic `low_confidence` / `missing_required_slot`. | Keep LLM timeout / diagnostic fallback visible in trace. | Low |
| `local_life_agent/engine/subgraphs/response_subgraph.py` | Stopped overwriting an existing fallback reason with later answer-generation metadata. | Avoid erasing semantic failure provenance. | Low |
| `local_life_agent/planning/orchestration_router.py` | Tightened exploration routing so `workflow_hint=exploration_planning` alone no longer forces exploration without actual `exploration_stages`. | Prevent plain discovery / recommendation queries from being misrouted into exploration clarification. | Low |
| `local_life_agent/target/clarification.py` | Removed workflow-hint-only exploration clarification fallback and softened the generic location ask for nearby recommendations. | Keep nearby recommendation queries from turning into exploration missing-location clarification. | Medium |
| `local_life_agent/semantic/intent_parser.py` | Phase 6 pre-existing fix: preserved diagnostic fallback source / reason during semantic parse recovery. | Ensure semantic parse failure metadata remains observable. | Low |
| `local_life_agent/semantic/slot_extractor.py` | Phase 6 pre-existing fix: reduced over-aggressive exploration missing-location labeling for generic nearby recommendation text. | Avoid false exploration typing. | Low |
| `local_life_agent/tests/conftest.py` | Phase 6 pre-existing fix: robustly extracted the actual user text from prompts. | Prevent spy backend from reading the wrong prompt segment. | Low |

## 4. Failure Closure
### `local_life_agent/tests/test_llm_main_path_verification.py`
- Root cause: the semantic parse failed with `LLM_TIMEOUT`, but later trace aggregation preferred a generic `low_confidence` fallback reason from the clarification path.
- Fix: preserve the more specific semantic fallback reason in trace construction when the final state fallback reason is only a generic low-confidence / missing-slot label.
- Result: the test now sees `semantic_source = diagnostic_rules` and `turn_trace.fallback_reason = LLM_TIMEOUT`.

### `local_life_agent/tests/test_comparison_flow.py`
- Root cause: the plain query `附近推荐火锅` was being pushed into exploration clarification on the spy-backed path, so `last_recommendation_list` never got populated and comparison follow-ups could not resolve correctly.
- Fix: tighten exploration routing so `workflow_hint=exploration_planning` is not enough without actual `exploration_stages`, and stop clarification fallback from treating a nearby recommendation as exploration missing-location by default.
- Result: both previously failing graph-level comparison follow-ups now pass, and recommendation history remains intact.

### `local_life_agent/tests/test_chat_interface_full_e2e.py`
- Current status: 17 skipped.
- Why it does not block Phase 7:
  - The skips are environment-gated, not assertion failures.
  - Core semantic routing, clarification resume, comparison flow, verifier, review, and verbalizer regression suites all pass.
  - The remaining skipped cases belong to broader E2E coverage that Phase 7 / Phase 8 can continue to own.

## 5. Semantic Constraint Check
The Phase 6 constraints still hold:
- unknown is not collapsed into false.
- failed is not collapsed into no.
- partial is not collapsed into complete.
- comparison winner remains blocked when evidence is insufficient.
- answer generation remains grounded-only.
- exploration stage partial / failed / unknown remain conservatively expressed.
- no hardcoded shop facts, coupons,营业状态,评分, or距离 were introduced.

## 6. Regression Commands Run
### Core commands
- `python -m compileall local_life_agent -q` -> passed
- `python -m pytest local_life_agent/tests/test_answer_verifier.py -q` -> passed, 21 passed
- `python -m pytest local_life_agent/tests/test_evidence_review.py -q` -> passed, 21 passed
- `python -m pytest local_life_agent/tests/test_llm_verbalizer.py -q` -> passed, 13 passed
- `python -m pytest local_life_agent/tests/test_p4_evidence_decision_answer_protocol.py -q` -> passed, 4 passed
- `python -m pytest local_life_agent/tests/test_exploration_planning_workflow.py -q` -> passed, 11 passed
- `python -m pytest local_life_agent/tests/test_llm_main_path_verification.py -q` -> passed, 13 passed
- `python -m pytest local_life_agent/tests/test_comparison_flow.py -q` -> passed, 24 passed
- `python -m pytest local_life_agent/tests/test_e2e_context_and_verifier.py -q` -> passed, 5 passed
- `python -m pytest local_life_agent/tests/test_semantic_parser.py -q` -> passed, 38 passed
- `python -m pytest local_life_agent/tests/test_router_rule_policy_guard.py -q` -> passed, 46 passed
- `python -m pytest local_life_agent/tests/test_chat_clarification_resume_e2e.py -q` -> passed, 11 passed
- `python -m pytest local_life_agent/tests/test_orchestration_router.py -q` -> passed, 9 passed
- `python -m pytest local_life_agent/tests/test_workflow_runner.py -q` -> passed, 3 passed
- `python -m pytest local_life_agent/tests/test_workflow_registry.py -q` -> passed, 5 passed
- `python -m pytest local_life_agent/tests/test_candidate_resolver.py -q` -> passed, 23 passed
- `python -m pytest local_life_agent/tests/test_chat_interface_full_e2e.py -q` -> passed with 17 skipped

## 7. Known Remaining Issues
- Phase 7 still needs the正式 entity grounding / target resolution收口.
- Phase 8 still needs the full chat E2E gate to be completed.
- `test_chat_interface_full_e2e.py` remains partially skipped by design in the current test environment.

## 8. Final Gate
- PHASE_6_COMPLETE: true
- LLM_MAIN_PATH_VERIFICATION_PASS: true
- COMPARISON_FLOW_PASS: true
- CHAT_E2E_SKIPPED_BLOCKS_PHASE_7: false
- SEMANTIC_CONSTRAINTS_STILL_HOLD: true
- CAN_ENTER_PHASE_7: true

