package com.hmdp.dto.ai;

import lombok.Data;

import java.util.LinkedHashMap;
import java.util.Map;

@Data
public class AiChatRequest {
    private String message;
    private String sessionId;
    private String traceId;
    private String turnId;
    private String page;
    private Map<String, Object> context = new LinkedHashMap<>();
}
