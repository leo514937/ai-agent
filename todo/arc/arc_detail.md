flowchart TD
    A[start] --> B[load_context]
    B --> C[hard_guard]

    C -->|invalid / low_info| Z1[clarification_or_reject]
    C -->|valid| D[understand_turn]

    Z1 --> Y[final_answer]

    D --> E[resolve_target_shop]
    E --> F[build_answer_contract]
    F --> G[build_source_contract]
    G --> H[complexity_router]

    H -->|clarify| C1[clarification_node]
    H -->|simple| S1[direct_executor]
    H -->|standard| W1[workflow_executor]
    H -->|complex| P1[planner_node]

    %% Clarify path
    C1 --> Y

    %% Simple path
    S1 --> S2[rule_review]
    S2 -->|pass| Y
    S2 -->|repair_answer| R1[repair_answer]
    S2 -->|degrade| D1[final_with_limitations]

    %% Standard path
    W1 --> W2[select_required_sources]

    W2 -->|need tool| TOOL[tool_executor]
    W2 -->|need recommendation| REC[recommendation_executor]
    W2 -->|otherwise| TOOL2[tool_executor_complex]

    TOOL --> W3
    REC --> W3
    TOOL2 --> P4[collect_step_result]

    W3 --> W4[contract_review]
    W4 -->|pass| Y
    W4 -->|repair_answer| R1
    W4 -->|retry_tool and count_ok| TOOL
    W4 -->|degrade or count_limit| D1

    %% Complex path
    P1 --> P2[plan_executor]
    P2 --> P3[execute_plan_step]

    P3 -->|tool_step| TOOL2[tool_executor_complex]
    P3 -->|recommendation_step| REC2[recommendation_executor_complex]
    P3 -->|rank_step| RK[rank_executor]
    P3 -->|merge_step| MG[merge_executor]
    P3 -->|compose_step| CP[compose_draft]

    TOOL2 --> P4
    REC2 --> P4
    RK --> P4
    MG --> P4
    CP --> P4

    P4 --> P5{all_steps_done?}
    P5 -->|no| P3
    P5 -->|yes| V[complex_review]

    V -->|pass| Y
    V -->|repair_answer| R1
    V -->|retry_step and count_ok| P3
    V -->|replan and count_ok| P1
    V -->|degrade or count_limit| D1

    %% Unified exits
    R1 --> Y
    D1 --> Y

    Y --> PS[persist_session]
    PS --> EF[emit_final]
    EF --> END[end]
