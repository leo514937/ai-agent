package com.hmdp.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.hmdp.ai.remote.AiRemoteProperties;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AiPythonProxyServiceTest {

    @Test
    void shouldProxyFeedbackAndSessionRequestsToPython() throws Exception {
        AtomicReference<String> feedbackToken = new AtomicReference<>();
        AtomicReference<String> feedbackBody = new AtomicReference<>();
        AtomicReference<String> approvalToken = new AtomicReference<>();
        AtomicReference<String> approvalBody = new AtomicReference<>();
        AtomicReference<String> sessionToken = new AtomicReference<>();
        HttpServer server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/internal/v1/feedback/report", exchange -> {
            feedbackToken.set(exchange.getRequestHeaders().getFirst("x-internal-token"));
            feedbackBody.set(readBody(exchange.getRequestBody()));
            respond(exchange, 200, "{\"accepted\":true}");
        });
        server.createContext("/internal/v1/approval/submit", exchange -> {
            approvalToken.set(exchange.getRequestHeaders().getFirst("x-internal-token"));
            approvalBody.set(readBody(exchange.getRequestBody()));
            respond(exchange, 200, "{\"accepted\":true,\"approval_state\":\"approved\"}");
        });
        server.createContext("/internal/v1/session/session-7/state", exchange -> {
            sessionToken.set(exchange.getRequestHeaders().getFirst("x-internal-token"));
            respond(exchange, 200, "{\"session_id\":\"session-7\",\"status\":\"active\"}");
        });
        server.start();

        try {
            AiPythonProxyService service = new AiPythonProxyService();
            AiRemoteProperties properties = new AiRemoteProperties();
            properties.setEnabled(true);
            properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            properties.setInternalToken("python-token");
            ReflectionTestUtils.setField(service, "properties", properties);
            ReflectionTestUtils.setField(service, "objectMapper", new ObjectMapper());

            Map<String, Object> feedback = service.reportFeedback(Collections.<String, Object>singletonMap("rating", 5));
            Map<String, Object> approval = service.submitApproval(Collections.<String, Object>singletonMap("decision", "approved"));
            Map<String, Object> sessionState = service.getSessionState("session-7");

            assertEquals("python-token", feedbackToken.get());
            assertEquals("python-token", approvalToken.get());
            assertEquals("python-token", sessionToken.get());
            assertTrue(feedbackBody.get().contains("\"rating\":5"));
            assertTrue(approvalBody.get().contains("\"decision\":\"approved\""));
            assertEquals(Boolean.TRUE, feedback.get("accepted"));
            assertEquals("approved", approval.get("approval_state"));
            assertEquals("active", sessionState.get("status"));
        } finally {
            server.stop(0);
        }
    }

    private String readBody(InputStream inputStream) throws IOException {
        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        byte[] buffer = new byte[256];
        int read;
        while ((read = inputStream.read(buffer)) >= 0) {
            outputStream.write(buffer, 0, read);
        }
        return new String(outputStream.toByteArray(), StandardCharsets.UTF_8);
    }

    private void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream outputStream = exchange.getResponseBody()) {
            outputStream.write(bytes);
        } finally {
            exchange.close();
        }
    }
}
