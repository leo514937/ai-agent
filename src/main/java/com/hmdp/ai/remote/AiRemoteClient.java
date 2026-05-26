package com.hmdp.ai.remote;

import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

@Slf4j
@Component
public class AiRemoteClient {

    private static final String HEALTH_PATH = "/health";
    private static final String STREAM_PATH = "/internal/v1/chat/stream";
    private static final int DEFAULT_CONNECT_TIMEOUT_MS = 3000;
    private static final int DEFAULT_READ_TIMEOUT_MS = 30000;
    private static final int HEALTH_CONNECT_TIMEOUT_MS = 3000;
    private static final int HEALTH_READ_TIMEOUT_MS = 3000;
    private static final long HEALTH_CACHE_TTL_MS = 5000L;

    @Resource
    private AiRemoteProperties properties;
    @Resource
    private AiRemoteStreamParser streamParser;
    @Resource
    private ObjectMapper objectMapper;

    private final Object healthProbeLock = new Object();
    private volatile long lastHealthProbeAtMs = 0L;
    private volatile boolean lastHealthProbeHealthy = false;
    private volatile String lastHealthProbeReason = "远端健康状态未知";

    public boolean isEnabled() {
        return properties != null && properties.isAvailable();
    }

    public AiRemoteChatResult chat(AiRemoteChatRequest request) {
        if (request == null) {
            return AiRemoteChatResult.failure("远端请求不能为空");
        }
        if (!isEnabled()) {
            String availabilityReason = getAvailabilityReason();
            log.debug("远端 AI 不可用，跳过远端 chat：{}", availabilityReason);
            return AiRemoteChatResult.failure(firstNonBlank(availabilityReason, "远端 AI 未启用"));
        }

        HttpURLConnection connection = null;
        try {
            String endpoint = properties.resolveBaseUrl() + STREAM_PATH;
            URL url = new URL(endpoint);
            connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setConnectTimeout(DEFAULT_CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(DEFAULT_READ_TIMEOUT_MS);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Accept", "text/event-stream");
            if (StrUtil.isNotBlank(properties.getInternalToken())) {
                connection.setRequestProperty("x-internal-token", properties.getInternalToken());
            }

            Map<String, Object> payload = new LinkedHashMap<>(request.toPayloadMap());
            try (OutputStream outputStream = connection.getOutputStream()) {
                outputStream.write(objectMapper.writeValueAsBytes(payload));
                outputStream.flush();
            }

            int status = connection.getResponseCode();
            InputStream responseStream = status >= 200 && status < 300 ? connection.getInputStream() : connection.getErrorStream();
            if (responseStream == null) {
                AiRemoteChatResult failure = AiRemoteChatResult.failure("远端没有返回可读取的响应体");
                failure.getMetadata().put("httpStatus", status);
                return failure;
            }

            AiRemoteChatResult result = streamParser.parse(responseStream);
            result.getMetadata().put("httpStatus", status);
            result.getMetadata().put("requestUrl", endpoint);
            result.getMetadata().put("requestMode", request.getResponseMode());
            result.getMetadata().put("topicHint", request.getTopicHint());
            result.getMetadata().put("page", request.getPage());
            result.getMetadata().put("sessionId", request.getSessionId());
            result.getMetadata().put("traceId", request.getTraceId());
            result.setPage(firstNonBlank(result.getPage(), request.getPage()));
            result.setSessionId(firstNonBlank(result.getSessionId(), request.getSessionId()));
            result.setTraceId(firstNonBlank(result.getTraceId(), request.getTraceId()));

            boolean ok = status >= 200 && status < 300 && result.isSuccess() && StrUtil.isNotBlank(result.getAnswer());
            result.setSuccess(ok);
            result.setFallbackSuggested(!ok);
            if (!ok && StrUtil.isBlank(result.getErrorMessage())) {
                result.setErrorMessage("远端响应未解析成功");
            }
            return result;
        } catch (Exception ex) {
            log.debug("远端 AI 调用失败，准备回退本地实现：{}", ex.getMessage());
            AiRemoteChatResult failure = AiRemoteChatResult.failure(firstNonBlank(ex.getMessage(), "远端调用失败"));
            failure.getMetadata().put("requestMode", request.getResponseMode());
            failure.getMetadata().put("topicHint", request.getTopicHint());
            failure.getMetadata().put("page", request.getPage());
            return failure;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
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

    private boolean isHealthy() {
        if (properties == null || !properties.isAvailable()) {
            lastHealthProbeReason = "远端 AI 未启用";
            lastHealthProbeHealthy = false;
            lastHealthProbeAtMs = System.currentTimeMillis();
            return false;
        }

        long now = System.currentTimeMillis();
        if (now - lastHealthProbeAtMs <= HEALTH_CACHE_TTL_MS) {
            return lastHealthProbeHealthy;
        }

        synchronized (healthProbeLock) {
            now = System.currentTimeMillis();
            if (now - lastHealthProbeAtMs <= HEALTH_CACHE_TTL_MS) {
                return lastHealthProbeHealthy;
            }
            return refreshHealthProbe();
        }
    }

    private boolean refreshHealthProbe() {
        HttpURLConnection connection = null;
        String baseUrl = properties == null ? null : properties.resolveBaseUrl();
        if (StrUtil.isBlank(baseUrl)) {
            lastHealthProbeHealthy = false;
            lastHealthProbeReason = "远端 AI 未启用";
            lastHealthProbeAtMs = System.currentTimeMillis();
            return false;
        }

        String endpoint = baseUrl + HEALTH_PATH;
        try {
            URL url = new URL(endpoint);
            connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(HEALTH_CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(HEALTH_READ_TIMEOUT_MS);
            connection.setRequestProperty("Accept", "application/json");

            int status = connection.getResponseCode();
            boolean healthy = status >= 200 && status < 300;
            lastHealthProbeHealthy = healthy;
            lastHealthProbeAtMs = System.currentTimeMillis();
            lastHealthProbeReason = healthy
                    ? "healthy"
                    : "远端健康检查失败(httpStatus=" + status + ")";
            if (!healthy) {
                log.debug("远端 AI 健康检查未通过，status={}", status);
            }
            return healthy;
        } catch (Exception ex) {
            lastHealthProbeHealthy = false;
            lastHealthProbeAtMs = System.currentTimeMillis();
            lastHealthProbeReason = firstNonBlank(ex.getMessage(), "远端健康检查失败");
            log.debug("远端 AI 健康检查失败，准备回退本地实现：{}", ex.getMessage());
            return false;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    public String getAvailabilityReason() {
        if (properties == null || !properties.isAvailable()) {
            return "远端 AI 未启用";
        }
        return firstNonBlank(lastHealthProbeReason, "远端健康检查未通过");
    }
}
