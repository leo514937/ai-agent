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
import com.hmdp.dto.ai.StreamEventEnvelope;
import com.hmdp.dto.ai.StreamEventTypes;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import javax.annotation.Resource;
import java.io.IOException;
import java.io.OutputStream;
import java.net.SocketException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
public class AiAssistantStreamService {

    private static final String WORKFLOW_VERSION = "hm-dianping-java/v1";

    @Resource
    private AiBusinessQueryFacade aiBusinessQueryFacade;
    @Resource
    private AiInternalBusinessService aiInternalBusinessService;
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
            writeTraceStartedEvent(outputStream, normalizedRequest, null);
            writeErrorEvent(outputStream, normalizedRequest, "AI_STREAM_INVALID_REQUEST", "请输入想咨询的问题", false, "request_validation");
            return;
        }

        Map<String, Object> enrichedContext = aiInternalBusinessService.enrichRealtimeContext(normalizedRequest.getContext());
        AiQueryContext queryContext = aiBusinessQueryFacade.resolveContext(enrichedContext, user);
        AiRouteType route = aiBusinessQueryFacade.resolveRoute(normalizedRequest.getMessage(), queryContext);

        // 新协议：trace_started + input_normalized + intent_detected 在远端调用前发出
        writeTraceStartedEvent(outputStream, normalizedRequest, route);
        writeInputNormalizedEvent(outputStream, normalizedRequest, normalizedRequest.getMessage(), "text");
        if (route != null) {
            writeIntentDetectedEvent(outputStream, normalizedRequest, route);
        }

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
                    writeErrorEvent(outputStream, normalizedRequest, "AI_STREAM_REMOTE_ERROR", firstNonBlank(ex.getMessage(), "远端流式调用失败"), true, "remote_stream");
                    return;
                } catch (Exception ex) {
                    log.debug("AI stream 远端代理失败，route={}，message={}", route, ex.getMessage());
                    writeErrorEvent(outputStream, normalizedRequest, "AI_STREAM_REMOTE_ERROR", firstNonBlank(ex.getMessage(), "远端流式调用失败"), true, "remote_stream");
                    return;
                }
            }
            // 远端未启用 — 发送 final 降级响应
            AiChatResponse fallbackResponse = new AiChatResponse();
            fallbackResponse.setAnswer(aiAssistantService.buildAssistantUnavailableMessage(route, normalizedRequest.getPage(), "远端未启用或健康检查未通过"));
            fallbackResponse.setMode("fallback");
            fallbackResponse.setSource("local");
            fallbackResponse.setFallback(true);
            fallbackResponse.setPage(normalizedRequest.getPage());
            writeFinalEvent(outputStream, normalizedRequest, fallbackResponse);
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

    // ─────────────────────────────────────────────────────────
    // 统一事件发射基础设施
    // ─────────────────────────────────────────────────────────

    /**
     * 构建 {@link StreamEventEnvelope} — wire 格式的单一来源。
     *
     * <p>所有事件发射方法必须通过此方法构造信封，保证
     * {@code trace_id / session_id / turn_id / workflow_version} 一致。</p>
     */
    private StreamEventEnvelope buildEnvelope(String eventType, AiChatRequest request,
                                              Map<String, Object> payload) {
        return StreamEventEnvelope.of(
                eventType,
                request.getTraceId(),
                request.getSessionId(),
                request.getTurnId(),
                WORKFLOW_VERSION,
                payload
        );
    }

    /**
     * 统一的 SSE 事件发射入口。
     * <p>构造 {@link StreamEventEnvelope} 并序列化为 SSE 格式写出。</p>
     */
    private void emitEvent(OutputStream outputStream, String eventType,
                           AiChatRequest request, Map<String, Object> payload) throws IOException {
        StreamEventEnvelope envelope = buildEnvelope(eventType, request, payload);
        writeEvent(outputStream, eventType, envelope.toMap());
    }

    // ─────────────────────────────────────────────────────────
    // §2 事件协议表 — 全部 14 种事件的本地发射器
    // ─────────────────────────────────────────────────────────

    // --- 1. trace_started ---

    /**
     * 发射 {@code trace_started} 事件（SSE 首个事件）。
     * <p>同时以 {@code ack} 事件作为兼容别名发出，避免前端一次性改动过大。</p>
     */
    private void writeTraceStartedEvent(OutputStream outputStream, AiChatRequest request,
                                        AiRouteType route) throws IOException {
        // 新协议事件：trace_started
        Map<String, Object> tracePayload = new LinkedHashMap<>();
        if (StrUtil.isNotBlank(request.getPage())) {
            tracePayload.put("page", request.getPage());
        }
        emitEvent(outputStream, StreamEventTypes.TRACE_STARTED, request, tracePayload);

        // 兼容别名：ack（保持与旧前端兼容）
        Map<String, Object> ackPayload = new LinkedHashMap<>();
        ackPayload.put("message", "accepted");
        ackPayload.put("current_stage", "trace_started");
        ackPayload.put("stage_status", "completed");
        if (route != null) {
            ackPayload.put("route_decision", route.name().toLowerCase());
        }
        ackPayload.put("route_reason", "java_stream_fallback");
        emitEvent(outputStream, StreamEventTypes.ACK, request, ackPayload);
    }

    // --- 2. input_normalized ---

    /**
     * 发射 {@code input_normalized} 事件（输入规范化完成）。
     *
     * @param normalizedText 规范化后的文本
     * @param inputType      输入类型（可选，默认 "text"）
     */
    public void writeInputNormalizedEvent(OutputStream outputStream, AiChatRequest request,
                                          String normalizedText, String inputType) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("normalized_text", normalizedText);
        if (StrUtil.isNotBlank(inputType)) {
            payload.put("input_type", inputType);
        }
        emitEvent(outputStream, StreamEventTypes.INPUT_NORMALIZED, request, payload);
    }

    // --- 3. pending_clarification_checked ---

    /**
     * 发射 {@code pending_clarification_checked} 事件（读取澄清状态后）。
     *
     * @param hasPending     是否存在挂起的澄清
     * @param pendingId      挂起澄清 ID
     * @param candidateCount 候选数量（可选）
     */
    public void writePendingClarificationCheckedEvent(OutputStream outputStream, AiChatRequest request,
                                                      boolean hasPending, String pendingId,
                                                      Integer candidateCount) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("has_pending", hasPending);
        payload.put("pending_id", pendingId != null ? pendingId : "");
        if (candidateCount != null) {
            payload.put("candidate_count", candidateCount);
        }
        emitEvent(outputStream, StreamEventTypes.PENDING_CLARIFICATION_CHECKED, request, payload);
    }

    // --- 4. hard_guard_hit ---

    /**
     * 发射 {@code hard_guard_hit} 事件（命中硬拦截）。
     *
     * @param guardType  拦截类型（如 "invalid", "greeting"）
     * @param message    拦截消息
     * @param reasonCode 原因代码（可选）
     */
    public void writeHardGuardHitEvent(OutputStream outputStream, AiChatRequest request,
                                       String guardType, String message,
                                       String reasonCode) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("guard_type", guardType);
        payload.put("message", message);
        if (StrUtil.isNotBlank(reasonCode)) {
            payload.put("reason_code", reasonCode);
        }
        emitEvent(outputStream, StreamEventTypes.HARD_GUARD_HIT, request, payload);
    }

    // --- 5. intent_detected ---

    /**
     * 发射 {@code intent_detected} 事件（顶层意图识别完成）。
     */
    private void writeIntentDetectedEvent(OutputStream outputStream, AiChatRequest request,
                                          AiRouteType route) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("top_intent", route != null ? route.name().toLowerCase() : "unknown");
        payload.put("confidence", 1.0);
        emitEvent(outputStream, StreamEventTypes.INTENT_DETECTED, request, payload);
    }

    // --- 6. semantic_frame_ready ---

    /**
     * 发射 {@code semantic_frame_ready} 事件（语义帧解析完成）。
     *
     * @param topIntent        顶层意图
     * @param taskType         任务类型
     * @param merchantMentions 商户提及列表（可选）
     * @param facets           facet 列表（可选）
     * @param confidence       置信度（可选）
     */
    public void writeSemanticFrameReadyEvent(OutputStream outputStream, AiChatRequest request,
                                             String topIntent, String taskType,
                                             List<String> merchantMentions, List<String> facets,
                                             Double confidence) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("top_intent", topIntent);
        payload.put("task_type", taskType);
        if (merchantMentions != null && !merchantMentions.isEmpty()) {
            payload.put("merchant_mentions", merchantMentions);
        }
        if (facets != null && !facets.isEmpty()) {
            payload.put("facets", facets);
        }
        if (confidence != null) {
            payload.put("confidence", confidence);
        }
        emitEvent(outputStream, StreamEventTypes.SEMANTIC_FRAME_READY, request, payload);
    }

    // --- 7. target_resolved ---

    /**
     * 发射 {@code target_resolved} 事件（商户解析完成）。
     *
     * @param resolveStatus 解析状态（RESOLVED / AMBIGUOUS / LOW_CONFIDENCE / NOT_FOUND）
     * @param resolvedShop  已解析的商户信息（仅 RESOLVED 时非空）
     * @param candidates    候选列表（仅 AMBIGUOUS 时非空）
     */
    public void writeTargetResolvedEvent(OutputStream outputStream, AiChatRequest request,
                                         String resolveStatus,
                                         Map<String, Object> resolvedShop,
                                         List<Map<String, Object>> candidates) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("resolve_status", resolveStatus);
        if (resolvedShop != null && "RESOLVED".equals(resolveStatus)) {
            payload.put("resolved_shop", resolvedShop);
        }
        if (candidates != null && !candidates.isEmpty()) {
            payload.put("candidates", candidates);
        }
        emitEvent(outputStream, StreamEventTypes.TARGET_RESOLVED, request, payload);
    }

    // --- 8. clarify_requested ---

    /**
     * 发射 {@code clarify_requested} 事件（需要用户澄清）。
     *
     * @param pendingId     挂起澄清 ID
     * @param question      澄清问题
     * @param candidateText 候选文本（可选）
     */
    public void writeClarifyRequestedEvent(OutputStream outputStream, AiChatRequest request,
                                           String pendingId, String question,
                                           String candidateText) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("pending_id", pendingId);
        payload.put("question", question);
        if (StrUtil.isNotBlank(candidateText)) {
            payload.put("candidate_text", candidateText);
        }
        emitEvent(outputStream, StreamEventTypes.CLARIFY_REQUESTED, request, payload);
    }

    // --- 9. task_planned ---

    /**
     * 发射 {@code task_planned} 事件（执行计划生成完成）。
     *
     * @param executionPlanId 执行计划 ID
     * @param taskType        任务类型
     * @param toolCallCount   工具调用数量（可选）
     * @param maxConcurrency  最大并发数（可选）
     */
    public void writeTaskPlannedEvent(OutputStream outputStream, AiChatRequest request,
                                      String executionPlanId, String taskType,
                                      Integer toolCallCount, Integer maxConcurrency) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("execution_plan_id", executionPlanId);
        payload.put("task_type", taskType);
        if (toolCallCount != null) {
            payload.put("tool_call_count", toolCallCount);
        }
        if (maxConcurrency != null) {
            payload.put("max_concurrency", maxConcurrency);
        }
        emitEvent(outputStream, StreamEventTypes.TASK_PLANNED, request, payload);
    }

    // --- 10. tool_call_started ---

    /**
     * 发射 {@code tool_call_started} 事件（工具开始执行）。
     *
     * @param callId       调用 ID
     * @param toolName     工具名称
     * @param targetShopId 目标商户 ID（可选）
     * @param required     是否必选（可选）
     * @param facet        facet（可选）
     */
    public void writeToolCallStartedEvent(OutputStream outputStream, AiChatRequest request,
                                          String callId, String toolName,
                                          String targetShopId, Boolean required,
                                          String facet) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("call_id", callId);
        payload.put("tool_name", toolName);
        if (StrUtil.isNotBlank(targetShopId)) {
            payload.put("target_shop_id", targetShopId);
        }
        if (required != null) {
            payload.put("required", required);
        }
        if (StrUtil.isNotBlank(facet)) {
            payload.put("facet", facet);
        }
        emitEvent(outputStream, StreamEventTypes.TOOL_CALL_STARTED, request, payload);
    }

    // --- 11. tool_call_finished ---

    /**
     * 发射 {@code tool_call_finished} 事件（工具执行结束）。
     *
     * @param callId       调用 ID
     * @param toolName     工具名称
     * @param status       状态（ok / empty / unknown / failed / circuit_open）
     * @param resultStatus 结果状态（可选）
     * @param errorCode    错误代码（可选）
     * @param degraded     是否降级（可选）
     */
    public void writeToolCallFinishedEvent(OutputStream outputStream, AiChatRequest request,
                                           String callId, String toolName, String status,
                                           String resultStatus, String errorCode,
                                           Boolean degraded) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("call_id", callId);
        payload.put("tool_name", toolName);
        payload.put("status", status);
        if (StrUtil.isNotBlank(resultStatus)) {
            payload.put("result_status", resultStatus);
        }
        if (StrUtil.isNotBlank(errorCode)) {
            payload.put("error_code", errorCode);
        }
        if (degraded != null) {
            payload.put("degraded", degraded);
        }
        emitEvent(outputStream, StreamEventTypes.TOOL_CALL_FINISHED, request, payload);
    }

    // --- 12. evidence_built ---

    /**
     * 发射 {@code evidence_built} 事件（证据包生成完成）。
     *
     * @param evidencePackId 证据包 ID
     * @param targetShopIds  目标商户 ID 列表
     * @param evidenceCount  证据条数（可选）
     * @param unknownCount   未知条数（可选）
     */
    public void writeEvidenceBuiltEvent(OutputStream outputStream, AiChatRequest request,
                                        String evidencePackId, List<String> targetShopIds,
                                        Integer evidenceCount, Integer unknownCount) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("evidence_pack_id", evidencePackId);
        payload.put("target_shop_ids", targetShopIds != null ? targetShopIds : List.of());
        if (evidenceCount != null) {
            payload.put("evidence_count", evidenceCount);
        }
        if (unknownCount != null) {
            payload.put("unknown_count", unknownCount);
        }
        emitEvent(outputStream, StreamEventTypes.EVIDENCE_BUILT, request, payload);
    }

    // --- 13. answer_plan_built ---

    /**
     * 发射 {@code answer_plan_built} 事件（回答计划生成完成）。
     *
     * @param answerPlanId        回答计划 ID
     * @param answerType          回答类型（single_shop / recommendation / comparison / clarification / error）
     * @param allowedClaimCount   允许声明数量（可选）
     * @param forbiddenClaimCount 禁止声明数量（可选）
     */
    public void writeAnswerPlanBuiltEvent(OutputStream outputStream, AiChatRequest request,
                                          String answerPlanId, String answerType,
                                          Integer allowedClaimCount,
                                          Integer forbiddenClaimCount) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("answer_plan_id", answerPlanId);
        payload.put("answer_type", answerType);
        if (allowedClaimCount != null) {
            payload.put("allowed_claim_count", allowedClaimCount);
        }
        if (forbiddenClaimCount != null) {
            payload.put("forbidden_claim_count", forbiddenClaimCount);
        }
        emitEvent(outputStream, StreamEventTypes.ANSWER_PLAN_BUILT, request, payload);
    }

    // --- 14. answer_delta ---

    /**
     * 发射 {@code answer_delta} 事件（文本增量输出）。
     *
     * <p>只能在不违反事实锁定前提下输出。</p>
     *
     * @param deltaText      增量文本
     * @param sequence       序列号（可选）
     * @param partialSection 部分段落标识（可选）
     */
    public void writeAnswerDeltaEvent(OutputStream outputStream, AiChatRequest request,
                                      String deltaText, Integer sequence,
                                      String partialSection) throws IOException {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("delta_text", deltaText);
        if (sequence != null) {
            payload.put("sequence", sequence);
        }
        if (StrUtil.isNotBlank(partialSection)) {
            payload.put("partial_section", partialSection);
        }
        emitEvent(outputStream, StreamEventTypes.ANSWER_DELTA, request, payload);
    }

    // --- 15. final ---

    /**
     * 发射 {@code final} 事件（最终回答完成）。
     */
    public void writeFinalEvent(OutputStream outputStream, AiChatRequest request, AiChatResponse response) throws IOException {
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

        emitEvent(outputStream, StreamEventTypes.FINAL, request, payload);
    }

    // --- 16. error ---

    /**
     * 发射 {@code error} 事件（统一错误出口）。
     */
    public void writeErrorEvent(
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

        emitEvent(outputStream, StreamEventTypes.ERROR, request, payload);
    }

    // ─────────────────────────────────────────────────────────
    // 底层 SSE 写出
    // ─────────────────────────────────────────────────────────

    /**
     * 底层的 SSE 格式写出。
     * <p>保持 {@code event: <type>\ndata: <json>\n\n} 标准格式。</p>
     */
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

    // ─────────────────────────────────────────────────────────
    // 工具方法
    // ─────────────────────────────────────────────────────────

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
