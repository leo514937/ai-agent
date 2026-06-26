# Eval Report

- total_cases: 7
- passed: 2
- failed: 5
- skipped: 0
- pass_rate: 0.2857
- fallback_rate: 0.2857
- rewrite_rate: 0.5714
- template_fallback_rate: 0.0
- raw_text_fallback_rate: 0.4286
- real_e2e_veto_count: 10

## Cases
- real_e2e_generated_001_direct_answer: passed terminal=final_answer llm=None tool=None
- real_e2e_generated_002_single_shop_detail: passed terminal=final_answer llm=real_llm tool=db
- real_e2e_generated_003_single_shop_coupon: failed terminal=final_answer llm=real_llm tool=db
  failures: expect_answer_source: expected='llm_verbalizer' observed='llm_verbalizer_rewrite', expect_fallback_used: expected=False observed=True
- real_e2e_generated_004_nearby_recommend: failed terminal=final_answer llm=real_llm tool=db
  failures: expect_answer_source: expected='llm_verbalizer' observed='trusted_failure_message', expect_fallback_used: expected=False observed=True
- real_e2e_generated_005_ambiguous_clarify: failed terminal=trusted_failure llm=real_llm tool=None
  failures: expect_fallback_used: expected=False observed=True, expect_terminal: expected='clarify' observed='trusted_failure', require_clarify_on_ambiguous_candidates: terminal=trusted_failure, require_clarify_on_ambiguous_candidates: clarify_reason='tool_empty_or_not_found'
- real_e2e_generated_006_empty_result_trusted_failure: failed terminal=trusted_failure llm=openrouter/deepseek/deepseek-v4-flash tool=None
  failures: expect_evidence_incomplete: expected=False observed=True
- real_e2e_generated_007_multi_turn_context: failed terminal=final_answer llm=real_llm tool=db
  failures: expect_fallback_used: expected=False observed=True
