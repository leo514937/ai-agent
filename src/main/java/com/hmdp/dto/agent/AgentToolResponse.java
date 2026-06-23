package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Unified response wrapper for Agent tool API.
 * Mirrors the Python ToolResult structure so the JavaToolClient
 * can parse it directly without per-tool custom mapping.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentToolResponse {
    private boolean success;
    private String resultStatus;  // "ok" | "empty" | "failed" | "unknown"
    private Object data;
    private String errorCode;
    private String errorMessage;
    private String backendSource = "java_api";

    public static AgentToolResponse ok(Object data) {
        AgentToolResponse r = new AgentToolResponse();
        r.success = true;
        r.resultStatus = data != null ? "ok" : "empty";
        r.data = data;
        r.backendSource = "java_api";
        return r;
    }

    public static AgentToolResponse partial(Object data) {
        AgentToolResponse r = new AgentToolResponse();
        r.success = true;
        r.resultStatus = "partial";
        r.data = data;
        r.backendSource = "java_api";
        return r;
    }

    public static AgentToolResponse empty() {
        AgentToolResponse r = new AgentToolResponse();
        r.success = true;
        r.resultStatus = "empty";
        r.data = null;
        r.backendSource = "java_api";
        return r;
    }

    public static AgentToolResponse failed(String errorCode, String errorMessage) {
        AgentToolResponse r = new AgentToolResponse();
        r.success = false;
        r.resultStatus = "failed";
        r.errorCode = errorCode;
        r.errorMessage = errorMessage;
        r.backendSource = "java_api";
        return r;
    }

    public static AgentToolResponse error(String errorCode, String errorMessage) {
        AgentToolResponse r = new AgentToolResponse();
        r.success = false;
        r.resultStatus = "error";
        r.errorCode = errorCode;
        r.errorMessage = errorMessage;
        r.backendSource = "java_api";
        return r;
    }
}
