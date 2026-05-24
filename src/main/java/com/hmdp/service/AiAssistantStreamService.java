package com.hmdp.service;

import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.hmdp.ai.query.AiBusinessQueryFacade;
import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.ai.query.AiRouteType;
import com.hmdp.ai.remote.AiRemoteChatRequest;
import com.hmdp.ai.remote.AiRemoteClient;
import com.hmdp.ai.remote.AiRemoteStreamProxyClient;
import com.hmdp.dto.UserDTO;
import com.hmdp.dto.ai.AiChatRequest;
import com.hmdp.dto.ai.AiChatResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import javax.annotation.Resource;
import java.io.IOException;
import java.io.OutputStream;
import java.net.SocketException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

@Slf4j
@Service
public class AiAssistantStreamService {

    private static final String WORKFLOW_VERSION = "hm-dianping-java/v1";

    @Resource
    private AiBusinessQueryFacade aiBusinessQueryFacade;
    @Resource
    private AiRemoteClient aiRemoteClient;
    @Resource
    private AiRemoteStreamProxyClient aiRemoteStreamProxyClient;
    @Resource
    private AiAssistantService aiAssistantService;
    @Resource
    private ObjectMapper objectMapper;

    public void stream(AiChatRequest request, UserDTO user, OutputStream outputStream) throws IOException {
        AiChatRequest normalizedRequest = normalizeRequest(request);
        if (StrUtil.isBlank(normalizedRequest.getMessage())) {
            writeErrorEvent(outputStream, normalizedRequest, "AI_STREAM_INVALID_REQUEST", "请输入想咨询的问题", false, "request_validation");
            return;
        }

        AiQueryContext queryContext = aiBusinessQueryFacade.resolveContext(normalizedRequest.getContext(), user);
        AiRouteType route = aiBusinessQueryFacade.resolveRoute(normalizedRequest.getMessage(), queryContext);

        try {
            if (aiRemoteClient.isEnabled()) {
                try {
                    aiRemoteStreamProxyClient.stream(buildRemoteRequest(normalizedRequest, user, queryContext), outputStream);
                    return;
                } catch (IOException ex) {
                    if (isClientDisconnect(ex)) {
                        log.debug(
                                "AI stream cancelled by client disconnect route={} session={} turn={} reason={}",
                                route,
                                normalizedRequest.getSessionId(),
                                normalizedRequest.getTurnId(),
                                ex.getMessage()
                        );
                        return;
                    }
                    log.debug("AI stream 远端代理失败，route={}，message={}", route, ex.getMessage());
                    writeAckEvent(outputStream, normalizedRequest, route);
                    writeErrorEvent(outputStream, normalizedRequest, "AI_STREAM_REMOTE_ERROR", firstNonBlank(ex.getMessage(), "远端流式调用失败"), true, "remote_stream");
                    return;
                } catch (Exception ex) {
                    log.debug("AI stream 远端代理失败，route={}，message={}", route, ex.getMessage());
                    writeAckEvent(outputStream, normalizedRequest, route);
                    writeErrorEvent(outputStream, normalizedRequest, "AI_STREAM_REMOTE_ERROR", firstNonBlank(ex.getMessage(), "远端流式调用失败"), true, "remote_stream");
                    return;
                }
            }
            writeAckEvent(outputStream, normalizedRequest, route);
            writeErrorEvent(outputStream, normalizedRequest, "AI_STREAM_REMOTE_UNAVAILABLE", aiAssistantService.buildAssistantUnavailableMessage(route, normalizedRequest.getPage(), "远端未启用或健康检查未通过"), true, "remote_unavailable");
        } catch (IOException ex) {
            if (isClientDisconnect(ex)) {
                log.debug(
                        "AI stream cancelled by client disconnect route={} session={} turn={} reason={}",
                        route,
                        normalizedRequest.getSessionId(),
                        normalizedRequest.getTurnId(),
                        ex.getMessage()
                );
                return;
            }
            throw ex;
        }
    }

    private boolean isBusinessRoute(AiRouteType route) {
        return AiRouteType.RECOMMEND == route
                || AiRouteType.COMPARE == route
                || AiRouteType.DETAIL == route
                || AiRouteType.VOUCHER == route;
    }

    private AiRemoteChatRequest buildRemoteRequest(AiChatRequest request, UserDTO user, AiQueryContext queryContext) {
        AiRemoteChatRequest remoteRequest = new AiRemoteChatRequest();
        remoteRequest.setUserId(user == null || user.getId() == null ? "guest" : String.valueOf(user.getId()));
        remoteRequest.setSessionId(request.getSessionId());
        remoteRequest.setTraceId(request.getTraceId());
        remoteRequest.setTurnId(request.getTurnId());
        remoteRequest.setPage(request.getPage());
        remoteRequest.setMessage(request.getMessage());
        remoteRequest.setResponseMode("stream");
        remoteRequest.setTopicHint(firstNonBlank(queryContext.getShopName(), queryContext.getTypeName(), queryContext.getBlogTitle(), request.getPage()));
        remoteRequest.setHistorySummary(asString(queryContext.getRawContext(), "historySummary"));
        remoteRequest.setClientContext(new LinkedHashMap<>(queryContext.getRawContext()));
        return remoteRequest;
    }

    private void writeFinalEvent(OutputStream outputStream, AiChatRequest request, AiChatResponse response) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("answer_text", response.getAnswer());
        payload.put("mode", response.getMode());
        payload.put("source", response.getSource());
        payload.put("page", response.getPage());
        payload.put("current_topic", response.getCurrentTopic());
        payload.put("fallback", response.isFallback());
        payload.put("suggested_replies", response.getSuggestions());
        payload.put("shops", response.getShops());
        payload.put("vouchers", response.getVouchers());
        payload.put("cards", response.getCards());
        payload.put("next_steps", response.getNextSteps());
        payload.put("task_chain", response.getTaskChain());
        payload.put("context", response.getContext());

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("event_type", "final");
        envelope.put("trace_id", request.getTraceId());
        envelope.put("session_id", request.getSessionId());
        envelope.put("turn_id", request.getTurnId());
        envelope.put("workflow_version", WORKFLOW_VERSION);
        envelope.put("payload", payload);
        writeEvent(outputStream, "final", envelope);
    }

    private void writeAckEvent(OutputStream outputStream, AiChatRequest request, AiRouteType route) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("message", "accepted");
        payload.put("current_stage", "accepted");
        payload.put("stage_status", "completed");
        if (route != null) {
            payload.put("route_decision", route.name().toLowerCase());
        }
        payload.put("route_reason", "java_stream_fallback");

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("event_type", "ack");
        envelope.put("trace_id", request.getTraceId());
        envelope.put("session_id", request.getSessionId());
        envelope.put("turn_id", request.getTurnId());
        envelope.put("workflow_version", WORKFLOW_VERSION);
        envelope.put("payload", payload);
        writeEvent(outputStream, "ack", envelope);
    }

    private void writeErrorEvent(
            OutputStream outputStream,
            AiChatRequest request,
            String code,
            String message,
            boolean retryable,
            String stage
    ) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("code", code);
        payload.put("message", message);
        payload.put("retryable", retryable);
        payload.put("stage", stage);

        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("event_type", "error");
        envelope.put("trace_id", request.getTraceId());
        envelope.put("session_id", request.getSessionId());
        envelope.put("turn_id", request.getTurnId());
        envelope.put("workflow_version", WORKFLOW_VERSION);
        envelope.put("payload", payload);
        writeEvent(outputStream, "error", envelope);
    }

    private void writeEvent(OutputStream outputStream, String event, Map<String, Object> envelope) throws IOException {
        try {
            outputStream.write(("event: " + event + "\n").getBytes(StandardCharsets.UTF_8));
            outputStream.write(("data: " + objectMapper.writeValueAsString(envelope) + "\n\n").getBytes(StandardCharsets.UTF_8));
            outputStream.flush();
        } catch (IOException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new IOException(firstNonBlank(ex.getMessage(), "写入 SSE 事件失败"), ex);
        }
    }

    private boolean isClientDisconnect(Throwable throwable) {
        Throwable current = throwable;
        while (current != null) {
            if (current instanceof SocketException) {
                return true;
            }
            String message = current.getMessage();
            if (message != null) {
                String lower = message.toLowerCase();
                if (lower.contains("broken pipe")
                        || lower.contains("connection reset")
                        || lower.contains("stream closed")
                        || lower.contains("socket closed")
                        || lower.contains("forcibly closed")
                        || lower.contains("pipe closed")) {
                    return true;
                }
            }
            current = current.getCause();
        }
        return false;
    }

    private AiChatRequest normalizeRequest(AiChatRequest request) {
        AiChatRequest normalized = request == null ? new AiChatRequest() : request;
        Map<String, Object> context = normalized.getContext() == null ? new LinkedHashMap<String, Object>() : new LinkedHashMap<>(normalized.getContext());
        normalized.setContext(context);
        normalized.setMessage(normalize(normalized.getMessage()));
        normalized.setPage(firstNonBlank(normalized.getPage(), asString(context, "page"), "assistant"));
        long now = System.currentTimeMillis();
        normalized.setSessionId(firstNonBlank(normalized.getSessionId(), String.valueOf(now)));
        normalized.setTraceId(firstNonBlank(normalized.getTraceId(), "trace-" + now));
        normalized.setTurnId(firstNonBlank(normalized.getTurnId(), "turn-" + now));
        return normalized;
    }

    private String normalize(String value) {
        return value == null ? "" : value.trim();
    }

    private String asString(Map<String, Object> context, String key) {
        if (context == null) {
            return null;
        }
        Object value = context.get(key);
        return value == null ? null : String.valueOf(value);
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
