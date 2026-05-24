package com.hmdp.controller;

import cn.hutool.core.util.StrUtil;
import com.hmdp.ai.remote.AiRemoteProperties;
import com.hmdp.dto.ai.internal.AiInternalShopSearchRequest;
import com.hmdp.service.AiInternalBusinessService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import javax.annotation.Resource;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/internal/v1/business")
public class AiInternalBusinessController {

    @Resource
    private AiInternalBusinessService aiInternalBusinessService;
    @Resource
    private AiRemoteProperties aiRemoteProperties;

    @PostMapping("/shops/search")
    public ResponseEntity<?> searchShops(
            @RequestHeader(value = "x-internal-token", required = false) String internalToken,
            @RequestBody(required = false) AiInternalShopSearchRequest request
    ) {
        if (!authorized(internalToken)) {
            return unauthorized();
        }
        return ResponseEntity.ok(aiInternalBusinessService.searchShops(request));
    }

    @GetMapping("/shops/{shopId}/detail")
    public ResponseEntity<?> getShopDetail(
            @RequestHeader(value = "x-internal-token", required = false) String internalToken,
            @PathVariable("shopId") Long shopId,
            @RequestParam(value = "userId", required = false) Long userId,
            @RequestParam(value = "voucherLimit", required = false) Integer voucherLimit,
            @RequestParam(value = "blogLimit", required = false) Integer blogLimit
    ) {
        if (!authorized(internalToken)) {
            return unauthorized();
        }
        return ResponseEntity.ok(aiInternalBusinessService.getShopDetail(shopId, userId, voucherLimit, blogLimit));
    }

    @GetMapping("/shops/{shopId}/vouchers")
    public ResponseEntity<?> listShopVouchers(
            @RequestHeader(value = "x-internal-token", required = false) String internalToken,
            @PathVariable("shopId") Long shopId,
            @RequestParam(value = "limit", required = false) Integer limit
    ) {
        if (!authorized(internalToken)) {
            return unauthorized();
        }
        return ResponseEntity.ok(aiInternalBusinessService.listShopVouchers(shopId, limit));
    }

    @GetMapping("/shops/{shopId}/blogs")
    public ResponseEntity<?> listShopBlogs(
            @RequestHeader(value = "x-internal-token", required = false) String internalToken,
            @PathVariable("shopId") Long shopId,
            @RequestParam(value = "limit", required = false) Integer limit
    ) {
        if (!authorized(internalToken)) {
            return unauthorized();
        }
        return ResponseEntity.ok(aiInternalBusinessService.listShopBlogs(shopId, limit));
    }

    @GetMapping("/orders/{orderId}/status")
    public ResponseEntity<?> getOrderStatus(
            @RequestHeader(value = "x-internal-token", required = false) String internalToken,
            @PathVariable("orderId") Long orderId
    ) {
        if (!authorized(internalToken)) {
            return unauthorized();
        }
        return ResponseEntity.ok(aiInternalBusinessService.getOrderState(orderId));
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
