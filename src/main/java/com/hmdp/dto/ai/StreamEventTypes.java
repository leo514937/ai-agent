package com.hmdp.dto.ai;

/**
 * SSE 事件类型常量（协议表 v1）。
 *
 * <p>对应 {@code todo/06_Streaming_Event协议表.md} 第 2 节事件协议表。
 * 所有常量在此统一声明，避免拼写散落各处。
 */
public final class StreamEventTypes {

    private StreamEventTypes() {}

    /** 回合初始化完成，SSE 首个事件。ack 的兼容别名 */
    public static final String TRACE_STARTED = "trace_started";

    /** 输入规范化完成 */
    public static final String INPUT_NORMALIZED = "input_normalized";

    /** 读取澄清状态后 */
    public static final String PENDING_CLARIFICATION_CHECKED = "pending_clarification_checked";

    /** 命中硬拦截 */
    public static final String HARD_GUARD_HIT = "hard_guard_hit";

    /** 顶层意图识别完成 */
    public static final String INTENT_DETECTED = "intent_detected";

    /** 语义帧解析完成 */
    public static final String SEMANTIC_FRAME_READY = "semantic_frame_ready";

    /** 商户解析完成 */
    public static final String TARGET_RESOLVED = "target_resolved";

    /** 需要用户澄清 */
    public static final String CLARIFY_REQUESTED = "clarify_requested";

    /** 执行计划生成完成 */
    public static final String TASK_PLANNED = "task_planned";

    /** 工具开始执行 */
    public static final String TOOL_CALL_STARTED = "tool_call_started";

    /** 工具执行结束 */
    public static final String TOOL_CALL_FINISHED = "tool_call_finished";

    /** 证据包生成完成 */
    public static final String EVIDENCE_BUILT = "evidence_built";

    /** 回答计划生成完成 */
    public static final String ANSWER_PLAN_BUILT = "answer_plan_built";

    /** 文本增量输出 */
    public static final String ANSWER_DELTA = "answer_delta";

    /** 最终回答完成 */
    public static final String FINAL = "final";

    /** 任一阶段出错 */
    public static final String ERROR = "error";

    // ── 兼容别名 ─────────────────────────────────────────

    /** ack 作为 trace_started 的兼容别名 */
    public static final String ACK = "ack";
}
