package com.hmdp.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.hmdp.ai.query.AiBusinessQueryFacade;
import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.ai.query.AiRouteType;
import com.hmdp.ai.remote.AiRemoteClient;
import com.hmdp.ai.remote.AiRemoteStreamProxyClient;
import com.hmdp.dto.UserDTO;
import com.hmdp.dto.ai.AiChatRequest;
import com.hmdp.dto.ai.AiChatResponse;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.net.SocketException;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AiAssistantStreamServiceTest {

    @Test
    void shouldEmitRemoteUnavailableErrorForFaq() throws Exception {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        AiRemoteClient remoteClient = mock(AiRemoteClient.class);
        AiRemoteStreamProxyClient streamProxyClient = mock(AiRemoteStreamProxyClient.class);
        AiAssistantService aiAssistantService = mock(AiAssistantService.class);

        AiAssistantStreamService streamService = new AiAssistantStreamService();
        ReflectionTestUtils.setField(streamService, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(streamService, "aiRemoteClient", remoteClient);
        ReflectionTestUtils.setField(streamService, "aiRemoteStreamProxyClient", streamProxyClient);
        ReflectionTestUtils.setField(streamService, "aiAssistantService", aiAssistantService);
        ReflectionTestUtils.setField(streamService, "objectMapper", new ObjectMapper());

        Map<String, Object> context = new HashMap<>();
        context.put("page", "assistant");
        AiQueryContext queryContext = AiQueryContext.from(context, buildUser());

        AiChatResponse fallbackResponse = new AiChatResponse();
        when(remoteClient.isEnabled()).thenReturn(false);
        when(remoteClient.getAvailabilityReason()).thenReturn("learning-agent-service disabled");
        when(queryFacade.resolveContext(anyMap(), any(UserDTO.class))).thenReturn(queryContext);
        when(queryFacade.resolveRoute(anyString(), any(AiQueryContext.class))).thenReturn(AiRouteType.FAQ);
        when(aiAssistantService.buildAssistantUnavailableMessage(any(), anyString(), anyString()))
                .thenReturn("当前 AI 助手暂时不可用，请稍后再试。原因：learning-agent-service disabled 路由=FAQ 页面=assistant");

        AiChatRequest request = new AiChatRequest();
        request.setMessage("今天天气怎么样");
        request.setPage("assistant");
        request.setContext(context);
        request.setTraceId("trace-1");
        request.setSessionId("session-1");
        request.setTurnId("turn-1");

        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        streamService.stream(request, buildUser(), outputStream);

        String body = new String(outputStream.toByteArray(), StandardCharsets.UTF_8);
        assertTrue(body.contains("event: error"));
        assertTrue(body.contains("AI_STREAM_REMOTE_UNAVAILABLE"));
        assertTrue(body.contains("learning-agent-service disabled"));
        assertTrue(body.contains("\"stage\":\"remote_unavailable\""));
        assertTrue(body.contains("\"trace_id\":\"trace-1\""));
        assertTrue(body.contains("\"session_id\":\"session-1\""));
        assertTrue(body.contains("\"turn_id\":\"turn-1\""));
    }

    @Test
    void shouldEmitRemoteUnavailableErrorForBusinessRoute() throws Exception {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        AiRemoteClient remoteClient = mock(AiRemoteClient.class);
        AiRemoteStreamProxyClient streamProxyClient = mock(AiRemoteStreamProxyClient.class);
        AiAssistantService aiAssistantService = mock(AiAssistantService.class);

        AiAssistantStreamService streamService = new AiAssistantStreamService();
        ReflectionTestUtils.setField(streamService, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(streamService, "aiRemoteClient", remoteClient);
        ReflectionTestUtils.setField(streamService, "aiRemoteStreamProxyClient", streamProxyClient);
        ReflectionTestUtils.setField(streamService, "aiAssistantService", aiAssistantService);
        ReflectionTestUtils.setField(streamService, "objectMapper", new ObjectMapper());

        Map<String, Object> context = new HashMap<>();
        context.put("page", "home");
        context.put("typeName", "火锅");
        AiQueryContext queryContext = AiQueryContext.from(context, buildUser());

        when(remoteClient.isEnabled()).thenReturn(false);
        when(queryFacade.resolveContext(anyMap(), any(UserDTO.class))).thenReturn(queryContext);
        when(queryFacade.resolveRoute(anyString(), any(AiQueryContext.class))).thenReturn(AiRouteType.RECOMMEND);
        when(aiAssistantService.buildAssistantUnavailableMessage(any(), anyString(), anyString()))
                .thenReturn("当前 AI 助手暂时不可用，请稍后再试。原因：learning-agent-service disabled 路由=RECOMMEND 页面=home");

        AiChatRequest request = new AiChatRequest();
        request.setMessage("推荐附近火锅");
        request.setPage("home");
        request.setContext(context);
        request.setTraceId("trace-2");
        request.setSessionId("session-2");
        request.setTurnId("turn-2");

        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        streamService.stream(request, buildUser(), outputStream);

        String body = new String(outputStream.toByteArray(), StandardCharsets.UTF_8);
        assertTrue(body.contains("event: error"));
        assertTrue(body.contains("AI_STREAM_REMOTE_UNAVAILABLE"));
        assertTrue(body.contains("learning-agent-service disabled"));
        assertTrue(body.contains("\"stage\":\"remote_unavailable\""));
        assertTrue(body.contains("\"turn_id\":\"turn-2\""));
    }

    @Test
    void shouldPassThroughRemoteSseEnvelopeWhenRemoteAvailable() throws Exception {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        AiRemoteClient remoteClient = mock(AiRemoteClient.class);
        AiRemoteStreamProxyClient streamProxyClient = mock(AiRemoteStreamProxyClient.class);
        AiAssistantService aiAssistantService = mock(AiAssistantService.class);

        AiAssistantStreamService streamService = new AiAssistantStreamService();
        ReflectionTestUtils.setField(streamService, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(streamService, "aiRemoteClient", remoteClient);
        ReflectionTestUtils.setField(streamService, "aiRemoteStreamProxyClient", streamProxyClient);
        ReflectionTestUtils.setField(streamService, "aiAssistantService", aiAssistantService);
        ReflectionTestUtils.setField(streamService, "objectMapper", new ObjectMapper());

        Map<String, Object> context = new HashMap<>();
        context.put("page", "home");
        AiQueryContext queryContext = AiQueryContext.from(context, buildUser());
        String rawSse = "event: ack\n"
                + "data: {\"event_type\":\"ack\"}\n\n"
                + "event: final\n"
                + "data: {\"event_type\":\"final\",\"payload\":{\"answer_text\":\"远端已响应\"}}\n\n";

        when(remoteClient.isEnabled()).thenReturn(true);
        when(queryFacade.resolveContext(anyMap(), any(UserDTO.class))).thenReturn(queryContext);
        when(queryFacade.resolveRoute(anyString(), any(AiQueryContext.class))).thenReturn(AiRouteType.RECOMMEND);
        doAnswer(invocation -> {
            ByteArrayOutputStream outputStream = invocation.getArgument(1);
            outputStream.write(rawSse.getBytes(StandardCharsets.UTF_8));
            return null;
        }).when(streamProxyClient).stream(any(), any(ByteArrayOutputStream.class));

        AiChatRequest request = new AiChatRequest();
        request.setMessage("推荐附近餐厅");
        request.setPage("home");
        request.setContext(context);
        request.setTraceId("trace-3");
        request.setSessionId("session-3");
        request.setTurnId("turn-3");

        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        streamService.stream(request, buildUser(), outputStream);

        String body = new String(outputStream.toByteArray(), StandardCharsets.UTF_8);
        assertTrue(body.contains(rawSse));
    }

    @Test
    void shouldTreatClientDisconnectAsCancellationWithoutWritingErrorEvent() throws Exception {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        AiRemoteClient remoteClient = mock(AiRemoteClient.class);
        AiRemoteStreamProxyClient streamProxyClient = mock(AiRemoteStreamProxyClient.class);
        AiAssistantService aiAssistantService = mock(AiAssistantService.class);

        AiAssistantStreamService streamService = new AiAssistantStreamService();
        ReflectionTestUtils.setField(streamService, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(streamService, "aiRemoteClient", remoteClient);
        ReflectionTestUtils.setField(streamService, "aiRemoteStreamProxyClient", streamProxyClient);
        ReflectionTestUtils.setField(streamService, "aiAssistantService", aiAssistantService);
        ReflectionTestUtils.setField(streamService, "objectMapper", new ObjectMapper());

        Map<String, Object> context = new HashMap<>();
        context.put("page", "assistant");
        AiQueryContext queryContext = AiQueryContext.from(context, buildUser());

        when(remoteClient.isEnabled()).thenReturn(true);
        when(queryFacade.resolveContext(anyMap(), any(UserDTO.class))).thenReturn(queryContext);
        when(queryFacade.resolveRoute(anyString(), any(AiQueryContext.class))).thenReturn(AiRouteType.FAQ);
        doThrow(new SocketException("Broken pipe")).when(streamProxyClient).stream(any(), any(ByteArrayOutputStream.class));

        AiChatRequest request = new AiChatRequest();
        request.setMessage("今天天气怎么样");
        request.setPage("assistant");
        request.setContext(context);
        request.setTraceId("trace-4");
        request.setSessionId("session-4");
        request.setTurnId("turn-4");

        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        streamService.stream(request, buildUser(), outputStream);

        String body = new String(outputStream.toByteArray(), StandardCharsets.UTF_8);
        assertEquals("", body);
    }

    private UserDTO buildUser() {
        UserDTO user = new UserDTO();
        user.setId(1L);
        user.setNickName("小明");
        return user;
    }
}
