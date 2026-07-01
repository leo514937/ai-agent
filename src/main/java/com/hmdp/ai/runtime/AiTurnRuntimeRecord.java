package com.hmdp.ai.runtime;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class AiTurnRuntimeRecord {
    private String sessionId;
    private String turnId;
    private String traceId;
    private AiTurnStatus status = AiTurnStatus.RUNNING;
    private String reason = "";
    private String cancelReason = "";
    private String finalAnswer = "";
    private String errorMessage = "";
    private long startedAtMs;
    private long updatedAtMs;

    public java.util.Map<String, Object> toMap() {
        java.util.Map<String, Object> map = new java.util.LinkedHashMap<>();
        map.put("session_id", sessionId);
        map.put("turn_id", turnId);
        map.put("trace_id", traceId);
        map.put("status", status == null ? "" : status.name());
        map.put("reason", reason);
        map.put("cancel_reason", cancelReason);
        map.put("final_answer", finalAnswer);
        map.put("error_message", errorMessage);
        map.put("started_at_ms", startedAtMs);
        map.put("updated_at_ms", updatedAtMs);
        return map;
    }
}
