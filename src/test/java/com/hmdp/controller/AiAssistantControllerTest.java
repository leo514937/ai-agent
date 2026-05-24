package com.hmdp.controller;

import com.hmdp.dto.Result;
import com.hmdp.dto.ai.AiChatRequest;
import com.hmdp.service.AiPythonProxyService;
import com.hmdp.service.AiAssistantService;
import com.hmdp.service.AiAssistantUnavailableException;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AiAssistantControllerTest {

    @Test
    void shouldReturnFailResultWhenAssistantUnavailable() {
        AiAssistantService service = mock(AiAssistantService.class);
        doThrow(new AiAssistantUnavailableException("当前 AI 助手暂时不可用，请稍后再试。"))
                .when(service)
                .chat(any(AiChatRequest.class), any());

        AiAssistantController controller = new AiAssistantController();
        ReflectionTestUtils.setField(controller, "aiAssistantService", service);

        AiChatRequest request = new AiChatRequest();
        request.setMessage("你好");

        Result result = controller.chat(request);

        assertFalse(Boolean.TRUE.equals(result.getSuccess()));
        assertEquals("当前 AI 助手暂时不可用，请稍后再试。", result.getErrorMsg());
    }

    @Test
    void shouldProxyApprovalSubmission() {
        AiAssistantController controller = new AiAssistantController();
        AiPythonProxyService proxyService = mock(AiPythonProxyService.class);
        ReflectionTestUtils.setField(controller, "aiPythonProxyService", proxyService);

        when(proxyService.submitApproval(any())).thenReturn(Collections.<String, Object>singletonMap("accepted", true));

        Result result = controller.submitApproval(Collections.<String, Object>singletonMap("decision", "approved"));

        assertTrue(Boolean.TRUE.equals(result.getSuccess()));
        Map<?, ?> data = (Map<?, ?>) result.getData();
        assertEquals(Boolean.TRUE, data.get("accepted"));
    }
}
