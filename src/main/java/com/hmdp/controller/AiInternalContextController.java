package com.hmdp.controller;

import cn.hutool.core.util.StrUtil;
import com.hmdp.ai.remote.AiRemoteProperties;
import com.hmdp.service.AiInternalBusinessService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import javax.annotation.Resource;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/internal/v1/context")
public class AiInternalContextController {

    @Resource
    private AiInternalBusinessService aiInternalBusinessService;
    @Resource
    private AiRemoteProperties aiRemoteProperties;

    @GetMapping("/time")
    public ResponseEntity<?> getCurrentTime(
            @RequestHeader(value = "x-internal-token", required = false) String internalToken
    ) {
        if (!authorized(internalToken)) {
            return unauthorized();
        }
        return ResponseEntity.ok(aiInternalBusinessService.buildCurrentTimeContext());
    }

    @GetMapping("/location")
    public ResponseEntity<?> getDefaultLocation(
            @RequestHeader(value = "x-internal-token", required = false) String internalToken
    ) {
        if (!authorized(internalToken)) {
            return unauthorized();
        }
        return ResponseEntity.ok(aiInternalBusinessService.buildDefaultLocationContext());
    }

    private boolean authorized(String internalToken) {
        String configuredToken = aiRemoteProperties == null ? null : aiRemoteProperties.getInternalToken();
        return StrUtil.isBlank(configuredToken) || StrUtil.equals(configuredToken, internalToken);
    }

    private ResponseEntity<Map<String, Object>> unauthorized() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", "unauthorized");
        body.put("message", "internal token invalid");
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(body);
    }
}
