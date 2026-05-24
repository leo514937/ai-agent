package com.hmdp.service;

import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.hmdp.ai.remote.AiRemoteProperties;
import org.springframework.stereotype.Service;

import javax.annotation.Resource;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

@Service
public class AiPythonProxyService {

    private static final int DEFAULT_CONNECT_TIMEOUT_MS = 3000;
    private static final int DEFAULT_READ_TIMEOUT_MS = 8000;

    @Resource
    private AiRemoteProperties properties;
    @Resource
    private ObjectMapper objectMapper;

    public Map<String, Object> reportFeedback(Map<String, Object> payload) {
        return invokeJson("POST", "/internal/v1/feedback/report", normalizeFeedbackPayload(payload));
    }

    public Map<String, Object> submitApproval(Map<String, Object> payload) {
        return invokeJson("POST", "/internal/v1/approval/submit", normalizeApprovalPayload(payload));
    }

    public Map<String, Object> getSessionState(String sessionId) {
        if (StrUtil.isBlank(sessionId)) {
            throw new IllegalArgumentException("sessionId 不能为空");
        }
        return invokeJson("GET", "/internal/v1/session/" + sessionId + "/state", null);
    }

    private Map<String, Object> invokeJson(String method, String path, Object body) {
        if (properties == null || !properties.isAvailable()) {
            throw new AiAssistantUnavailableException("远端 AI 未启用");
        }

        HttpURLConnection connection = null;
        try {
            String endpoint = properties.resolveBaseUrl() + path;
            connection = (HttpURLConnection) new URL(endpoint).openConnection();
            connection.setRequestMethod(method);
            connection.setConnectTimeout(DEFAULT_CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(DEFAULT_READ_TIMEOUT_MS);
            connection.setRequestProperty("Accept", "application/json");
            if (StrUtil.isNotBlank(properties.getInternalToken())) {
                connection.setRequestProperty("x-internal-token", properties.getInternalToken());
            }

            if ("POST".equalsIgnoreCase(method)) {
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                try (OutputStream outputStream = connection.getOutputStream()) {
                    outputStream.write(objectMapper.writeValueAsBytes(body));
                    outputStream.flush();
                }
            }

            int status = connection.getResponseCode();
            InputStream responseStream = status >= 200 && status < 300 ? connection.getInputStream() : connection.getErrorStream();
            if (responseStream == null) {
                throw new AiAssistantUnavailableException("远端返回空响应(httpStatus=" + status + ")");
            }

            String responseBody = readAll(responseStream);
            if (StrUtil.isBlank(responseBody)) {
                return new LinkedHashMap<>();
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> map = objectMapper.readValue(responseBody, LinkedHashMap.class);
            map.put("httpStatus", status);
            return map;
        } catch (AiAssistantUnavailableException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new AiAssistantUnavailableException(firstNonBlank(ex.getMessage(), "远端代理失败"));
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private Map<String, Object> normalizeFeedbackPayload(Map<String, Object> payload) {
        Map<String, Object> source = payload == null ? new LinkedHashMap<>() : new LinkedHashMap<>(payload);
        Map<String, Object> normalized = new LinkedHashMap<>();
        putIfPresent(normalized, "user_id", firstString(source, "user_id", "userId", "user"));
        putIfPresent(normalized, "session_id", firstString(source, "session_id", "sessionId"));
        putIfPresent(normalized, "turn_id", firstString(source, "turn_id", "turnId"));
        putIfPresent(normalized, "thread_id", firstString(source, "thread_id", "threadId"));
        putIfPresent(normalized, "trace_id", firstString(source, "trace_id", "traceId"));
        putIfPresent(normalized, "issue_type", firstString(source, "issue_type", "issueType"));
        normalized.put("is_helpful", firstValue(source, "is_helpful", "isHelpful"));
        putIfPresent(normalized, "comment", firstString(source, "comment"));
        normalized.put("final_payload", firstMap(source, "final_payload", "finalPayload"));
        normalized.put("timeline", firstList(source, "timeline"));
        normalized.put("retrieval_summary", firstMap(source, "retrieval_summary", "retrievalSummary"));
        normalized.put("memory_used_summary", firstMap(source, "memory_used_summary", "memoryUsedSummary"));
        normalized.put("context", firstMap(source, "context"));
        if (StrUtil.isBlank((String) normalized.get("user_id"))) {
            normalized.put("user_id", "guest");
        }
        if (StrUtil.isBlank((String) normalized.get("issue_type"))) {
            normalized.put("issue_type", Boolean.TRUE.equals(normalized.get("is_helpful")) ? "helpful" : "unhelpful");
        }
        for (Map.Entry<String, Object> entry : source.entrySet()) {
            if (entry.getKey() == null || normalized.containsKey(entry.getKey())) {
                continue;
            }
            normalized.put(entry.getKey(), entry.getValue());
        }
        return normalized;
    }

    private Map<String, Object> normalizeApprovalPayload(Map<String, Object> payload) {
        Map<String, Object> source = payload == null ? new LinkedHashMap<>() : new LinkedHashMap<>(payload);
        Map<String, Object> normalized = new LinkedHashMap<>();
        putIfPresent(normalized, "user_id", firstString(source, "user_id", "userId", "user"));
        putIfPresent(normalized, "session_id", firstString(source, "session_id", "sessionId"));
        putIfPresent(normalized, "turn_id", firstString(source, "turn_id", "turnId"));
        putIfPresent(normalized, "trace_id", firstString(source, "trace_id", "traceId"));
        putIfPresent(normalized, "approval_id", firstString(source, "approval_id", "approvalId"));
        putIfPresent(normalized, "decision", firstString(source, "decision"));
        normalized.put("approval_request", firstMap(source, "approval_request", "approvalRequest"));
        normalized.put("context", firstMap(source, "context"));
        if (StrUtil.isBlank((String) normalized.get("user_id"))) {
            normalized.put("user_id", "guest");
        }
        for (Map.Entry<String, Object> entry : source.entrySet()) {
            if (entry.getKey() == null || normalized.containsKey(entry.getKey())) {
                continue;
            }
            normalized.put(entry.getKey(), entry.getValue());
        }
        return normalized;
    }

    private void putIfPresent(Map<String, Object> target, String key, String value) {
        if (StrUtil.isNotBlank(value)) {
            target.put(key, value);
        }
    }

    private String firstString(Map<String, Object> source, String... keys) {
        Object value = firstValue(source, keys);
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }

    private Object firstValue(Map<String, Object> source, String... keys) {
        if (source == null || keys == null) {
            return null;
        }
        for (String key : keys) {
            if (StrUtil.isBlank(key) || !source.containsKey(key)) {
                continue;
            }
            Object value = source.get(key);
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> firstMap(Map<String, Object> source, String... keys) {
        Object value = firstValue(source, keys);
        if (value instanceof Map<?, ?>) {
            Map<String, Object> normalized = new LinkedHashMap<>();
            ((Map<?, ?>) value).forEach((key, item) -> {
                if (key != null) {
                    normalized.put(String.valueOf(key), item);
                }
            });
            return normalized;
        }
        return new LinkedHashMap<>();
    }

    @SuppressWarnings("unchecked")
    private java.util.List<Object> firstList(Map<String, Object> source, String... keys) {
        Object value = firstValue(source, keys);
        if (value instanceof java.util.List<?>) {
            return new java.util.ArrayList<>((java.util.List<Object>) value);
        }
        return new java.util.ArrayList<>();
    }

    private String readAll(InputStream inputStream) throws IOException {
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(inputStream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
        }
        return builder.toString();
    }

    private String firstNonBlank(String... values) {
        if (values == null) {
            return null;
        }
        for (String value : values) {
            if (StrUtil.isNotBlank(value)) {
                return value;
            }
        }
        return null;
    }
}
