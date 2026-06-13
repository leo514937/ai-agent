flowchart TD
    %% =========================
    %% LangGraph Node Architecture Only
    %% 不展开 harness 内部细节
    %% =========================

    START[start] --> LC[load_context]
    LC --> RL[request_legality]
    RL -->|blocked| IR[illegal_request_response]
    RL -->|normal| HG[hard_guard]

    HG -->|invalid / low_info| CRJ[clarification_or_reject]
    HG -->|valid| QS[query_safety]

    QS -->|unsafe| SR[safety_reject_response]
    QS -->|safe| QM[query_merge_for_local_life]

    QM --> MQS[merged_query_safety]
    MQS -->|unsafe| SR
    MQS -->|safe| UT[understand_turn]

    UT --> TLI[top_level_intent_router]

    TLI -->|identity| IDA[identity_answer]
    TLI -->|capability| CAP[capability_answer]
    TLI -->|direct_chat| DCA[direct_chat_answer]
    TLI -->|out_of_scope| OOS[out_of_scope_response]
    TLI -->|unsafe| SR
    TLI -->|direct_answer_fallback| FA[final_answer]
    TLI -->|local_life / recommendation / comparison / planning| RTS[resolve_target_shop]

    RTS -->|missing_target| CL[clarification_node]
    RTS -->|resolved| BAC[build_answer_contract]

    BAC --> BSC[build_source_contract]
    BSC --> CX[complexity_router]

    CX -->|clarify| CL
    CX -->|simple| DE[direct_executor]
    CX -->|standard| WE[workflow_executor]
    CX -->|complex| PN[planner_node]

    %% =========================
    %% Simple Path
    %% =========================
    DE --> RR[rule_review]

    RR -->|pass| FA[final_answer]
    RR -->|repair_answer| RA[repair_answer]
    RR -->|degrade| FWL[final_with_limitations]

    %% =========================
    %% Standard Path
    %% =========================
    WE --> SRS[select_required_sources]

    SRS -->|need_rag| RAG[rag_executor]
    SRS -->|need_tool| TOOL[tool_executor]
    SRS -->|need_recommendation| REC[recommendation_executor]

    RAG --> MOR[merge_or_rank]
    TOOL --> MOR
    REC --> MOR

    MOR --> CR[contract_review]

    CR -->|pass| FA
    CR -->|repair_answer| RA
    CR -->|retry_rag| RAG
    CR -->|retry_tool| TOOL
    CR -->|degrade| FWL

    %% =========================
    %% Complex Path
    %% =========================
    PN --> PV[plan_validator]
    PV --> PE[plan_executor]
    PE --> EPS[execute_plan_step]

    EPS -->|rag_step| RAG2[rag_executor_complex]
    EPS -->|tool_step| TOOL2[tool_executor_complex]
    EPS -->|recommendation_step| REC2[recommendation_executor_complex]
    EPS -->|rank_step| RK[rank_executor]
    EPS -->|merge_step| MG[merge_executor]
    EPS -->|compose_step| CD[compose_draft]

    RAG2 --> CSR[collect_step_result]
    TOOL2 --> CSR
    REC2 --> CSR
    RK --> CSR
    MG --> CSR
    CD --> CSR

    CSR --> ASD{all_steps_done?}

    ASD -->|no| EPS
    ASD -->|yes| CXREV[complex_review]

    CXREV -->|pass| FA
    CXREV -->|repair_answer| RA
    CXREV -->|retry_step| EPS
    CXREV -->|replan| PN
    CXREV -->|degrade| FWL

    %% =========================
    %% Unified Exit
    %% =========================
    IR --> FA
    CRJ --> FA
    SR --> FA
    CL --> FA
    IDA --> FA
    CAP --> FA
    DCA --> FA
    OOS --> FA
    RA --> FA
    FWL --> FA

    FA --> FAS[final_answer_safety]
    FAS -->|unsafe| FSF[final_safety_fallback]
    FAS -->|safe| RB[response_builder]

    FSF --> RB

    RB --> PS[persist_session]
    PS --> EF[emit_final]
    EF --> END[end]
