package com.hmdp.ai.remote;

import com.fasterxml.jackson.databind.ObjectMapper;
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
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AiRemoteStreamProxyClientTest {

    @Test
    void shouldForwardTurnIdAndRawSseBody() throws Exception {
        AtomicReference<String> requestBody = new AtomicReference<>();
        AtomicReference<String> internalToken = new AtomicReference<>();
        HttpServer server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/internal/v1/chat/stream", exchange -> {
            internalToken.set(exchange.getRequestHeaders().getFirst("x-internal-token"));
            requestBody.set(readBody(exchange.getRequestBody()));
            String sse = "event: final\n"
                    + "data: {\"event_type\":\"final\",\"turn_id\":\"turn-9\",\"payload\":{\"answer_text\":\"ok\"}}\n\n";
            respond(exchange, 200, "text/event-stream; charset=utf-8", sse);
        });
        server.start();

        try {
            AiRemoteStreamProxyClient client = new AiRemoteStreamProxyClient();
            AiRemoteProperties properties = new AiRemoteProperties();
            properties.setEnabled(true);
            properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            properties.setInternalToken("token-123");
            ReflectionTestUtils.setField(client, "properties", properties);
            ReflectionTestUtils.setField(client, "objectMapper", new ObjectMapper());

            AiRemoteChatRequest request = new AiRemoteChatRequest();
            request.setUserId("1");
            request.setSessionId("session-9");
            request.setTraceId("trace-9");
            request.setTurnId("turn-9");
            request.setMessage("推荐火锅");

            ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
            client.stream(request, outputStream);

            String body = new String(outputStream.toByteArray(), StandardCharsets.UTF_8);
            assertEquals("token-123", internalToken.get());
            assertTrue(requestBody.get().contains("\"turn_id\":\"turn-9\""));
            assertTrue(body.contains("\"turn_id\":\"turn-9\""));
            assertTrue(body.contains("\"answer_text\":\"ok\""));
        } finally {
            server.stop(0);
        }
    }

    @Test
    void shouldCloseUpstreamConnectionWhenDownstreamOutputFails() throws Exception {
        CountDownLatch writeAttempted = new CountDownLatch(1);
        HttpServer server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/internal/v1/chat/stream", exchange -> {
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream; charset=utf-8");
            exchange.sendResponseHeaders(200, 0);
            try (OutputStream response = exchange.getResponseBody()) {
                response.write(("event: ack\n" +
                        "data: {\"event_type\":\"ack\",\"payload\":{\"message\":\"accepted\"}}\n\n").getBytes(StandardCharsets.UTF_8));
                response.flush();
                try {
                    Thread.sleep(120);
                } catch (InterruptedException interruptedException) {
                    Thread.currentThread().interrupt();
                }
                for (int index = 0; index < 20; index++) {
                    try {
                        response.write(("event: delta\n" +
                                "data: {\"event_type\":\"answer_delta\",\"payload\":{\"delta\":\"chunk-" + index + "\"}}\n\n").getBytes(StandardCharsets.UTF_8));
                        response.flush();
                        Thread.sleep(40);
                    } catch (InterruptedException interruptedException) {
                        Thread.currentThread().interrupt();
                        break;
                    }
                }
            } finally {
                writeAttempted.countDown();
                exchange.close();
            }
        });
        server.start();

        try {
            AiRemoteStreamProxyClient client = new AiRemoteStreamProxyClient();
            AiRemoteProperties properties = new AiRemoteProperties();
            properties.setEnabled(true);
            properties.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
            ReflectionTestUtils.setField(client, "properties", properties);
            ReflectionTestUtils.setField(client, "objectMapper", new ObjectMapper());

            AiRemoteChatRequest request = new AiRemoteChatRequest();
            request.setUserId("1");
            request.setSessionId("session-10");
            request.setTraceId("trace-10");
            request.setTurnId("turn-10");
            request.setMessage("推荐火锅");

            OutputStream outputStream = new OutputStream() {
                private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();
                private int writeCount = 0;

                @Override
                public synchronized void write(int b) throws IOException {
                    buffer.write(b);
                }

                @Override
                public synchronized void write(byte[] b, int off, int len) throws IOException {
                    writeCount++;
                    if (writeCount > 1) {
                        throw new IOException("client aborted");
                    }
                    buffer.write(b, off, len);
                }
            };

            assertDoesNotThrow(() -> client.stream(request, outputStream));
            assertTrue(writeAttempted.await(4, TimeUnit.SECONDS));
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

    private void respond(HttpExchange exchange, int status, String contentType, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", contentType);
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream outputStream = exchange.getResponseBody()) {
            outputStream.write(bytes);
        } finally {
            exchange.close();
        }
    }
}
