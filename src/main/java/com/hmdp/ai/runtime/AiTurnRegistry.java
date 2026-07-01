package com.hmdp.ai.runtime;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class AiTurnRegistry {

    private final Map<String, AiTurnRuntimeRecord> turns = new ConcurrentHashMap<>();

    public synchronized AiTurnRuntimeRecord startTurn(String sessionId, String turnId, String traceId) {
        String normalizedSessionId = normalize(sessionId, "session-anon");
        String normalizedTurnId = normalize(turnId, "turn-anon");
        String normalizedTraceId = normalize(traceId, "trace-anon");
        String key = key(normalizedSessionId, normalizedTurnId);
        AiTurnRuntimeRecord existing = turns.get(key);
        if (existing != null) {
            existing.setTraceId(normalizedTraceId);
            existing.setStatus(AiTurnStatus.RUNNING);
            existing.setReason("");
            existing.setCancelReason("");
            existing.setErrorMessage("");
            existing.setUpdatedAtMs(now());
            return existing;
        }

        for (AiTurnRuntimeRecord record : turns.values()) {
            if (normalizedSessionId.equals(record.getSessionId())
                    && record.getStatus() != null
                    && (record.getStatus() == AiTurnStatus.RUNNING || record.getStatus() == AiTurnStatus.CLIENT_DISCONNECTED)
                    && !normalizedTurnId.equals(record.getTurnId())) {
                throw new IllegalStateException("session already has a running turn");
            }
        }

        AiTurnRuntimeRecord record = new AiTurnRuntimeRecord(
                normalizedSessionId,
                normalizedTurnId,
                normalizedTraceId,
                AiTurnStatus.RUNNING,
                "",
                "",
                "",
                "",
                now(),
                now()
        );
        turns.put(key, record);
        return record;
    }

    public AiTurnRuntimeRecord get(String sessionId, String turnId) {
        return turns.get(key(normalize(sessionId, ""), normalize(turnId, "")));
    }

    public AiTurnRuntimeRecord latestForSession(String sessionId) {
        String normalizedSessionId = normalize(sessionId, "");
        return turns.values().stream()
                .filter(record -> normalizedSessionId.equals(record.getSessionId()))
                .max(Comparator.comparingLong(AiTurnRuntimeRecord::getUpdatedAtMs))
                .orElse(null);
    }

    public synchronized AiTurnRuntimeRecord markClientDisconnected(String sessionId, String turnId) {
        return transition(sessionId, turnId, AiTurnStatus.CLIENT_DISCONNECTED, null, null, null);
    }

    public synchronized AiTurnRuntimeRecord markUserCancelled(String sessionId, String turnId, String reason) {
        return transition(sessionId, turnId, AiTurnStatus.USER_CANCELLED, reason, reason, null);
    }

    public synchronized AiTurnRuntimeRecord markFinished(String sessionId, String turnId, String finalAnswer) {
        AiTurnRuntimeRecord record = get(sessionId, turnId);
        if (record == null || record.getStatus() == AiTurnStatus.USER_CANCELLED) {
            return record;
        }
        record.setStatus(AiTurnStatus.FINISHED);
        if (finalAnswer != null) {
            record.setFinalAnswer(finalAnswer);
        }
        record.setUpdatedAtMs(now());
        return record;
    }

    public synchronized AiTurnRuntimeRecord markFailed(String sessionId, String turnId, String errorMessage) {
        return transition(sessionId, turnId, AiTurnStatus.FAILED, errorMessage, null, errorMessage);
    }

    public synchronized void clearTerminal(String sessionId, String turnId) {
        AiTurnRuntimeRecord record = get(sessionId, turnId);
        if (record == null) {
            return;
        }
        if (record.getStatus() == AiTurnStatus.FINISHED
                || record.getStatus() == AiTurnStatus.USER_CANCELLED
                || record.getStatus() == AiTurnStatus.FAILED) {
            turns.remove(key(record.getSessionId(), record.getTurnId()));
        }
    }

    public List<Map<String, Object>> snapshotHistory(String sessionId) {
        String normalizedSessionId = normalize(sessionId, "");
        List<Map<String, Object>> history = new ArrayList<>();
        turns.values().stream()
                .filter(record -> normalizedSessionId.equals(record.getSessionId()))
                .sorted(Comparator.comparingLong(AiTurnRuntimeRecord::getUpdatedAtMs).reversed())
                .forEach(record -> history.add(record.toMap()));
        return history;
    }

    private AiTurnRuntimeRecord transition(
            String sessionId,
            String turnId,
            AiTurnStatus status,
            String reason,
            String cancelReason,
            String errorMessage
    ) {
        String key = key(normalize(sessionId, ""), normalize(turnId, ""));
        AiTurnRuntimeRecord record = turns.get(key);
        if (record == null) {
            return null;
        }
        if (record.getStatus() == AiTurnStatus.USER_CANCELLED && status != AiTurnStatus.USER_CANCELLED) {
            return record;
        }
        record.setStatus(status);
        if (reason != null && !reason.isEmpty()) {
            record.setReason(reason);
        }
        if (cancelReason != null && !cancelReason.isEmpty()) {
            record.setCancelReason(cancelReason);
        }
        if (errorMessage != null && !errorMessage.isEmpty()) {
            record.setErrorMessage(errorMessage);
        }
        record.setUpdatedAtMs(now());
        return record;
    }

    private String normalize(String value, String fallback) {
        if (value == null) {
            return fallback;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? fallback : trimmed;
    }

    private String key(String sessionId, String turnId) {
        return sessionId + "::" + turnId;
    }

    private long now() {
        return System.currentTimeMillis();
    }
}
