package com.hmdp.dto.ai;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 统一的 SSE 事件信封 — wire 格式的单一来源。
 *
 * <p>适配 {@code todo/06_Streaming_Event协议表.md} 第 6.3 节：
 * <ul>
 *   <li>所有事件共用此结构，保证 {@code trace_id / session_id / turn_id} 三联动</li>
 *   <li>{@code payload} 承载各事件特有的业务字段</li>
 *   <li>序列化字段名使用 snake_case 与协议保持一致</li>
 * </ul>
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class StreamEventEnvelope {

    /** 事件类型，取值见 {@link StreamEventTypes} */
    @JsonProperty("event_type")
    private String eventType;

    /** 追踪链 ID */
    @JsonProperty("trace_id")
    private String traceId;

    /** 会话 ID */
    @JsonProperty("session_id")
    private String sessionId;

    /** 轮次 ID */
    @JsonProperty("turn_id")
    private String turnId;

    /** 流程版本，如 "hm-dianping-java/v1" */
    @JsonProperty("workflow_version")
    private String workflowVersion;

    /** 各事件的专有负载 */
    @JsonProperty("payload")
    private Map<String, Object> payload = new LinkedHashMap<>();

    // ─────────────────────────────────────────────────────────
    // 工厂方法
    // ─────────────────────────────────────────────────────────

    /**
     * 静态工厂：快速构造事件信封。
     */
    public static StreamEventEnvelope of(String eventType, String traceId,
                                         String sessionId, String turnId,
                                         String workflowVersion,
                                         Map<String, Object> payload) {
        StreamEventEnvelope envelope = new StreamEventEnvelope();
        envelope.setEventType(eventType);
        envelope.setTraceId(traceId);
        envelope.setSessionId(sessionId);
        envelope.setTurnId(turnId);
        envelope.setWorkflowVersion(workflowVersion);
        envelope.setPayload(payload != null ? payload : new LinkedHashMap<>());
        return envelope;
    }

    /**
     * 转为扁平 Map，兼容现有 {@code writeEvent(OutputStream, String, Map)} 签名。
     *
     * <p>输出的 key 使用 snake_case，与协议保持一致。</p>
     */
    public Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("event_type", eventType);
        map.put("trace_id", traceId);
        map.put("session_id", sessionId);
        map.put("turn_id", turnId);
        map.put("workflow_version", workflowVersion);
        map.put("payload", payload != null ? payload : new LinkedHashMap<>());
        return map;
    }
}
