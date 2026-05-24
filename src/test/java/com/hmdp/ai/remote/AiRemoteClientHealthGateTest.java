package com.hmdp.ai.remote;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AiRemoteClientHealthGateTest {

    @Test
    void shouldTreatConfiguredRemoteAsEnabledEvenBeforeHealthProbe() {
        AiRemoteClient client = new AiRemoteClient();
        AiRemoteProperties properties = new AiRemoteProperties();
        properties.setEnabled(true);
        properties.setBaseUrl("http://127.0.0.1:18080");
        ReflectionTestUtils.setField(client, "properties", properties);
        ReflectionTestUtils.setField(client, "lastHealthProbeHealthy", false);

        assertTrue(client.isEnabled());
    }

    @Test
    void shouldStillChatWhenHealthProbeFails() throws Exception {
        AtomicInteger healthCalls = new AtomicInteger();
        AtomicInteger streamCalls = new AtomicInteger();
        HttpServer server = createServer(exchange -> {
            healthCalls.incrementAndGet();
            respond(exchange, 503, "{\"status\":\"down\"}");
        }, exchange -> {
            streamCalls.incrementAndGet();
            respond(exchange, 200, sseBody("远端不应该被调用"));
        });

        try {
            AiRemoteClient client = newClient(server);
            AiRemoteChatResult result = client.chat(AiRemoteChatRequest.of("user-1", "session-1", "trace-1", "推荐附近餐厅"));

            assertTrue(result.isSuccess());
            assertFalse(result.isFallbackSuggested());
            assertEquals("远端不应该被调用", result.getAnswer());
            assertEquals(0, healthCalls.get());
            assertEquals(1, streamCalls.get());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void shouldChatWithoutHealthProbeWhenRemoteIsConfigured() throws Exception {
        AtomicInteger healthCalls = new AtomicInteger();
        AtomicInteger streamCalls = new AtomicInteger();
        HttpServer server = createServer(exchange -> {
            healthCalls.incrementAndGet();
            respond(exchange, 200, "{\"status\":\"ok\"}");
        }, exchange -> {
            streamCalls.incrementAndGet();
            respond(exchange, 200, sseBody("远端已就绪"));
        });

        try {
            AiRemoteClient client = newClient(server);
            AiRemoteChatResult result = client.chat(AiRemoteChatRequest.of("user-1", "session-1", "trace-1", "推荐附近餐厅"));

            assertTrue(result.isSuccess());
            assertFalse(result.isFallbackSuggested());
            assertEquals("远端已就绪", result.getAnswer());
            assertEquals(0, healthCalls.get());
            assertEquals(1, streamCalls.get());
        } finally {
            server.stop(0);
        }
    }

    private AiRemoteClient newClient(HttpServer server) {
        AiRemoteClient client = new AiRemoteClient();
        AiRemoteProperties properties = new AiRemoteProperties();
        properties.setEnabled(true);
        properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        ReflectionTestUtils.setField(client, "properties", properties);
        AiRemoteStreamParser streamParser = new AiRemoteStreamParser();
        ReflectionTestUtils.setField(streamParser, "objectMapper", new ObjectMapper());
        ReflectionTestUtils.setField(client, "streamParser", streamParser);
        ReflectionTestUtils.setField(client, "objectMapper", new ObjectMapper());
        return client;
    }

    private HttpServer createServer(ExchangeHandler healthHandler, ExchangeHandler streamHandler) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/health", exchange -> healthHandler.handle(exchange));
        server.createContext("/internal/v1/chat/stream", exchange -> streamHandler.handle(exchange));
        server.start();
        return server;
    }

    private void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", exchange.getHttpContext().getPath().contains("stream")
                ? "text/event-stream; charset=utf-8"
                : "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream outputStream = exchange.getResponseBody()) {
            outputStream.write(bytes);
        } finally {
            exchange.close();
        }
    }

    private String sseBody(String answerText) {
        return "event: ack\n"
                + "data: {\"event_type\":\"ack\",\"trace_id\":\"trace-1\",\"session_id\":\"session-1\",\"turn_id\":\"turn-1\",\"workflow_version\":\"learn-agent/v1\",\"payload\":{\"message\":\"accepted\"}}\n\n"
                + "event: final\n"
                + "data: {\"event_type\":\"final\",\"trace_id\":\"trace-1\",\"session_id\":\"session-1\",\"turn_id\":\"turn-1\",\"workflow_version\":\"learn-agent/v1\",\"payload\":{\"answer_text\":\""
                + answerText
                + "\",\"mode\":\"remote\",\"source\":\"learning-agent-service\",\"page\":\"home\"}}\n\n";
    }

    @FunctionalInterface
    private interface ExchangeHandler {
        void handle(HttpExchange exchange) throws IOException;
    }
}
