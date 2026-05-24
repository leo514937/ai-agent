package com.hmdp.ai.remote;

import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Component
public class AiRemoteStreamParser {

    @Resource
    private ObjectMapper objectMapper;

    public AiRemoteChatResult parse(InputStream inputStream) throws IOException {
        if (inputStream == null) {
            return AiRemoteChatResult.failure("远端响应为空");
        }
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(inputStream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line).append('\n');
            }
        }
        return parse(builder.toString());
    }

    public AiRemoteChatResult parse(String rawResponse) throws IOException {
        if (StrUtil.isBlank(rawResponse)) {
            return AiRemoteChatResult.failure("远端响应为空");
        }

        List<AiRemoteStreamEvent> events = new ArrayList<>();
        StringBuilder blockBuilder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new StringReader(rawResponse))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.trim().isEmpty()) {
                    flushEvent(blockBuilder.toString(), events);
                    blockBuilder.setLength(0);
                    continue;
                }
                if (blockBuilder.length() > 0) {
                    blockBuilder.append('\n');
                }
                blockBuilder.append(line);
            }
        }
        flushEvent(blockBuilder.toString(), events);

        AiRemoteChatResult result = new AiRemoteChatResult();
        result.setRawResponse(rawResponse);
        result.setEvents(events);

        if (events.isEmpty()) {
            result.setSuccess(false);
            result.setFallbackSuggested(true);
            result.setErrorMessage("未解析到任何 SSE 事件");
            result.getMetadata().put("eventCount", 0);
            return result;
        }

        ParsedOutcome outcome = extractOutcome(events);
        result.setAnswer(outcome.answer);
        result.setMode(firstNonBlank(outcome.mode, "remote"));
        result.setSource(firstNonBlank(outcome.source, "learning-agent-service"));
        result.setPage(outcome.page);
        result.setCurrentTopic(outcome.currentTopic);
        result.setSessionId(outcome.sessionId);
        result.setTraceId(outcome.traceId);
        result.setFinishReason(outcome.finishReason);
        result.setFinalEvent(outcome.finalEvent);
        result.getMetadata().putAll(outcome.metadata);
        result.getMetadata().put("eventCount", events.size());

        boolean hasAnswer = StrUtil.isNotBlank(result.getAnswer());
        result.setSuccess(hasAnswer);
        result.setFallbackSuggested(!hasAnswer);
        if (!hasAnswer) {
            result.setErrorMessage("未解析到最终回答");
        }
        return result;
    }

    private void flushEvent(String block, List<AiRemoteStreamEvent> events) throws IOException {
        if (StrUtil.isBlank(block)) {
            return;
        }

        String eventName = null;
        String eventId = null;
        StringBuilder dataBuilder = new StringBuilder();

        try (BufferedReader reader = new BufferedReader(new StringReader(block))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.startsWith("event:")) {
                    eventName = line.substring("event:".length()).trim();
                } else if (line.startsWith("id:")) {
                    eventId = line.substring("id:".length()).trim();
                } else if (line.startsWith("data:")) {
                    String value = line.substring("data:".length()).trim();
                    if (dataBuilder.length() > 0) {
                        dataBuilder.append('\n');
                    }
                    dataBuilder.append(value);
                }
            }
        }

        String data = dataBuilder.toString();
        if (StrUtil.isBlank(eventName) && StrUtil.isBlank(eventId) && StrUtil.isBlank(data)) {
            return;
        }

        AiRemoteStreamEvent event = new AiRemoteStreamEvent();
        event.setEvent(eventName);
        event.setId(eventId);
        event.setData(data);
        event.setPayload(toPayloadMap(data));
        events.add(event);
    }

    private ParsedOutcome extractOutcome(List<AiRemoteStreamEvent> events) {
        ParsedOutcome outcome = new ParsedOutcome();
        for (int i = 0; i < events.size(); i++) {
            AiRemoteStreamEvent event = events.get(i);
            String eventName = event.getEvent();
            Map<String, Object> payload = flattenPayload(event.getPayload());
            String answer = extractAnswer(payload, event.getData());
            if (StrUtil.isNotBlank(answer)) {
                outcome.lastAnswer = answer;
                outcome.lastEventIndex = i;
            }
            mergeMetadata(outcome.metadata, payload);
            if (isFinalEvent(eventName, payload, event.getData())) {
                outcome.finalEvent = firstNonBlank(eventName, outcome.finalEvent);
                outcome.answer = firstNonBlank(answer, outcome.lastAnswer);
                fillCoreMetadata(outcome, payload, eventName);
            }
        }

        if (StrUtil.isBlank(outcome.answer)) {
            outcome.answer = outcome.lastAnswer;
        }
        if (StrUtil.isBlank(outcome.finalEvent) && !events.isEmpty()) {
            AiRemoteStreamEvent lastEvent = events.get(events.size() - 1);
            outcome.finalEvent = lastEvent.getEvent();
            Map<String, Object> payload = flattenPayload(lastEvent.getPayload());
            fillCoreMetadata(outcome, payload, lastEvent.getEvent());
            if (StrUtil.isBlank(outcome.answer)) {
                outcome.answer = extractAnswer(payload, lastEvent.getData());
            }
        }
        if (StrUtil.isBlank(outcome.mode)) {
            outcome.mode = "remote";
        }
        if (StrUtil.isBlank(outcome.source)) {
            outcome.source = "learning-agent-service";
        }
        outcome.metadata.put("lastAnswerEventIndex", outcome.lastEventIndex);
        return outcome;
    }

    private void fillCoreMetadata(ParsedOutcome outcome, Map<String, Object> payload, String eventName) {
        outcome.mode = firstNonBlank(asString(payload, "mode"), asString(payload, "response_mode"), outcome.mode);
        outcome.source = firstNonBlank(asString(payload, "source"), outcome.source);
        outcome.page = firstNonBlank(asString(payload, "page"), outcome.page);
        outcome.currentTopic = firstNonBlank(
                asString(payload, "resolved_topic"),
                asString(payload, "current_topic"),
                asString(payload, "topic"),
                asString(payload, "topic_hint"),
                outcome.currentTopic
        );
        outcome.sessionId = firstNonBlank(asString(payload, "session_id"), asString(payload, "sessionId"), outcome.sessionId);
        outcome.traceId = firstNonBlank(asString(payload, "trace_id"), asString(payload, "traceId"), outcome.traceId);
        outcome.finishReason = firstNonBlank(asString(payload, "finish_reason"), asString(payload, "reason"), outcome.finishReason);
        outcome.metadata.put("finalEventType", eventName);
        putIfNotBlank(outcome.metadata, "mode", outcome.mode);
        putIfNotBlank(outcome.metadata, "source", outcome.source);
        putIfNotBlank(outcome.metadata, "page", outcome.page);
        putIfNotBlank(outcome.metadata, "currentTopic", outcome.currentTopic);
        putIfNotBlank(outcome.metadata, "sessionId", outcome.sessionId);
        putIfNotBlank(outcome.metadata, "traceId", outcome.traceId);
        putIfNotBlank(outcome.metadata, "finishReason", outcome.finishReason);
    }

    private void mergeMetadata(Map<String, Object> metadata, Map<String, Object> payload) {
        if (payload == null || payload.isEmpty()) {
            return;
        }
        for (Map.Entry<String, Object> entry : payload.entrySet()) {
            String key = entry.getKey();
            if (metadata.containsKey(key) || entry.getValue() == null) {
                continue;
            }
            if (entry.getValue() instanceof String && StrUtil.isBlank((String) entry.getValue())) {
                continue;
            }
            metadata.put(key, entry.getValue());
        }
    }

    private String extractAnswer(Map<String, Object> payload, String rawData) {
        if (payload != null) {
            String answer = firstNonBlank(
                    asString(payload, "answer_text"),
                    asString(payload, "answer"),
                    asString(payload, "content"),
                    asString(payload, "text"),
                    asString(payload, "message")
            );
            if (StrUtil.isNotBlank(answer)) {
                return answer;
            }
            Object nestedPayload = payload.get("payload");
            if (nestedPayload instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> nestedMap = (Map<String, Object>) nestedPayload;
                answer = firstNonBlank(
                        asString(nestedMap, "answer_text"),
                        asString(nestedMap, "answer"),
                        asString(nestedMap, "content"),
                        asString(nestedMap, "text"),
                        asString(nestedMap, "message")
                );
                if (StrUtil.isNotBlank(answer)) {
                    return answer;
                }
            }
        }
        return isDoneMarker(rawData) ? "" : trimToNull(rawData);
    }

    private boolean isFinalEvent(String eventName, Map<String, Object> payload, String rawData) {
        if (StrUtil.isNotBlank(eventName)) {
            String normalized = eventName.trim().toLowerCase();
            if ("final".equals(normalized) || "done".equals(normalized) || "complete".equals(normalized) || "completed".equals(normalized) || "finish".equals(normalized) || "end".equals(normalized)) {
                return true;
            }
        }
        if (payload != null) {
            Object finish = payload.get("is_final");
            if (finish instanceof Boolean && (Boolean) finish) {
                return true;
            }
            String finishReason = firstNonBlank(asString(payload, "finish_reason"), asString(payload, "status"));
            if (StrUtil.isNotBlank(finishReason) && ("final".equalsIgnoreCase(finishReason) || "done".equalsIgnoreCase(finishReason) || "complete".equalsIgnoreCase(finishReason))) {
                return true;
            }
        }
        return isDoneMarker(rawData);
    }

    private boolean isDoneMarker(String rawData) {
        if (StrUtil.isBlank(rawData)) {
            return false;
        }
        String trimmed = rawData.trim();
        return "[DONE]".equalsIgnoreCase(trimmed) || "DONE".equalsIgnoreCase(trimmed);
    }

    private Map<String, Object> toPayloadMap(String data) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        if (StrUtil.isBlank(data) || isDoneMarker(data)) {
            return payload;
        }
        JsonNode node;
        try {
            node = objectMapper.readTree(data);
        } catch (Exception ex) {
            payload.put("value", trimToNull(data));
            return payload;
        }

        if (node == null || node.isNull()) {
            return payload;
        }
        if (node.isObject()) {
            @SuppressWarnings("unchecked")
            Map<String, Object> map = objectMapper.convertValue(node, Map.class);
            return map == null ? payload : new LinkedHashMap<>(map);
        }
        if (node.isArray()) {
            payload.put("items", objectMapper.convertValue(node, List.class));
            return payload;
        }
        payload.put("value", node.asText());
        return payload;
    }

    private Map<String, Object> flattenPayload(Map<String, Object> payload) {
        Map<String, Object> flattened = new LinkedHashMap<>();
        mergeFlattenedPayload(flattened, payload);
        return flattened;
    }

    @SuppressWarnings("unchecked")
    private void mergeFlattenedPayload(Map<String, Object> target, Map<String, Object> payload) {
        if (payload == null || payload.isEmpty()) {
            return;
        }
        for (Map.Entry<String, Object> entry : payload.entrySet()) {
            String key = entry.getKey();
            Object value = entry.getValue();
            if (value == null) {
                continue;
            }
            if (value instanceof String && StrUtil.isBlank((String) value)) {
                continue;
            }
            if ("payload".equals(key) && value instanceof Map) {
                if (!target.containsKey("payload")) {
                    target.put("payload", value);
                }
                mergeFlattenedPayload(target, (Map<String, Object>) value);
                continue;
            }
            if (!target.containsKey(key)) {
                target.put(key, value);
            }
        }
    }

    private String asString(Map<String, Object> payload, String key) {
        if (payload == null) {
            return null;
        }
        Object value = payload.get(key);
        return value == null ? null : trimToNull(String.valueOf(value));
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

    private void putIfNotBlank(Map<String, Object> map, String key, String value) {
        if (StrUtil.isNotBlank(value)) {
            map.put(key, value);
        }
    }

    private String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private static class ParsedOutcome {
        private String answer;
        private String mode;
        private String source;
        private String page;
        private String currentTopic;
        private String sessionId;
        private String traceId;
        private String finishReason;
        private String finalEvent;
        private String lastAnswer;
        private int lastEventIndex = -1;
        private Map<String, Object> metadata = new LinkedHashMap<>();
    }
}
