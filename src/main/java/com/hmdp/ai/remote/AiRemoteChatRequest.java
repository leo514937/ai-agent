package com.hmdp.ai.remote;

import cn.hutool.core.util.StrUtil;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.LinkedHashMap;
import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class AiRemoteChatRequest {

    private String userId;
    private String sessionId;
    private String traceId;
    private String turnId;
    private String page;
    private String message;
    private String responseMode = "default";
    private String topicHint;
    private String historySummary;
    private Map<String, Object> clientContext = new LinkedHashMap<>();

    public static AiRemoteChatRequest of(String userId, String sessionId, String traceId, String message) {
        AiRemoteChatRequest request = new AiRemoteChatRequest();
        request.setUserId(userId);
        request.setSessionId(sessionId);
        request.setTraceId(traceId);
        request.setMessage(message);
        return request;
    }

    public Map<String, Object> toPayloadMap() {
        Map<String, Object> payload = new LinkedHashMap<>();
        putIfNotBlank(payload, "user_id", userId);
        putIfNotBlank(payload, "session_id", sessionId);
        putIfNotBlank(payload, "trace_id", traceId);
        putIfNotBlank(payload, "turn_id", turnId);
        putIfNotBlank(payload, "page", page);
        putIfNotBlank(payload, "message", message);
        putIfNotBlank(payload, "response_mode", responseMode);
        putIfNotBlank(payload, "topic_hint", topicHint);
        putIfNotBlank(payload, "history_summary", historySummary);
        if (clientContext != null && !clientContext.isEmpty()) {
            payload.put("client_context", clientContext);
        }
        return payload;
    }

    private void putIfNotBlank(Map<String, Object> payload, String key, String value) {
        if (StrUtil.isNotBlank(value)) {
            payload.put(key, value);
        }
    }
}
