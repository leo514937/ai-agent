package com.hmdp.controller;

import com.hmdp.dto.Result;
import com.hmdp.dto.ai.AiChatRequest;
import com.hmdp.dto.ai.AiChatResponse;
import com.hmdp.service.AiAssistantUnavailableException;
import com.hmdp.service.AiAssistantService;
import com.hmdp.service.AiAssistantStreamService;
import com.hmdp.service.AiPythonProxyService;
import com.hmdp.utils.UserHolder;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import javax.annotation.Resource;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/ai")
public class AiAssistantController {

    @Resource
    private AiAssistantService aiAssistantService;
    @Resource
    private AiAssistantStreamService aiAssistantStreamService;
    @Resource
    private AiPythonProxyService aiPythonProxyService;

    @PostMapping("/chat")
    public Result chat(@RequestBody AiChatRequest request) {
        if (request == null || request.getMessage() == null || request.getMessage().trim().isEmpty()) {
            return Result.fail("请输入想咨询的问题");
        }
        try {
            AiChatResponse response = aiAssistantService.chat(request, UserHolder.getUser());
            return Result.ok(response);
        } catch (AiAssistantUnavailableException ex) {
            return Result.fail(ex.getMessage());
        }
    }

    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<StreamingResponseBody> chatStream(@RequestBody(required = false) AiChatRequest request) {
        StreamingResponseBody body = outputStream -> aiAssistantStreamService.stream(request, UserHolder.getUser(), outputStream);
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(body);
    }

    @PostMapping("/feedback/report")
    public Result reportFeedback(@RequestBody(required = false) Map<String, Object> request) {
        try {
            return Result.ok(aiPythonProxyService.reportFeedback(request == null ? new LinkedHashMap<String, Object>() : request));
        } catch (AiAssistantUnavailableException ex) {
            return Result.fail(ex.getMessage());
        }
    }

    @PostMapping("/approval/submit")
    public Result submitApproval(@RequestBody(required = false) Map<String, Object> request) {
        try {
            return Result.ok(aiPythonProxyService.submitApproval(request == null ? new LinkedHashMap<String, Object>() : request));
        } catch (AiAssistantUnavailableException ex) {
            return Result.fail(ex.getMessage());
        }
    }

    @GetMapping("/session/{sessionId}/state")
    public Result getSessionState(@PathVariable("sessionId") String sessionId) {
        try {
            return Result.ok(aiPythonProxyService.getSessionState(sessionId));
        } catch (AiAssistantUnavailableException ex) {
            return Result.fail(ex.getMessage());
        }
    }
}
