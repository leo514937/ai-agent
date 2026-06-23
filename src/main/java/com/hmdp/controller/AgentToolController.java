package com.hmdp.controller;

import com.hmdp.dto.agent.*;
import com.hmdp.service.AgentToolService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import javax.annotation.Resource;

/**
 * Agent tool API — dedicated endpoints for the Python Agent.
 *
 * These endpoints are consumed exclusively by local_life_agent/tools/java_client.py.
 * They do NOT replace or modify the existing frontend-facing controllers
 * (ShopController, VoucherController, etc.).
 *
 * All responses use AgentToolResponse wrapper which maps directly to
 * the Python ToolResult expected structure.
 */
@RestController
@RequestMapping("/internal/agent/tools")
public class AgentToolController {

    @Resource
    private AgentToolService agentToolService;

    /**
     * POST /internal/agent/tools/resolve-shop
     * Resolve a shop mention to a known shop_id.
     */
    @PostMapping("/resolve-shop")
    public ResponseEntity<AgentToolResponse> resolveShop(@RequestBody AgentResolveShopRequest request) {
        return ResponseEntity.ok(agentToolService.resolveShop(request));
    }

    /**
     * POST /internal/agent/tools/search-shops
     * Search shops by keyword/category/location.
     */
    @PostMapping("/search-shops")
    public ResponseEntity<AgentToolResponse> searchShops(@RequestBody AgentSearchShopsRequest request) {
        return ResponseEntity.ok(agentToolService.searchShops(request));
    }

    /**
     * GET /internal/agent/tools/shops/{shopId}
     * Get detailed information for a shop by ID.
     */
    @GetMapping("/shops/{shopId}")
    public ResponseEntity<AgentToolResponse> getShopDetail(@PathVariable Long shopId) {
        return ResponseEntity.ok(agentToolService.getShopDetail(shopId));
    }

    /**
     * GET /internal/agent/tools/shops/{shopId}/coupons
     * Get available coupons for a shop.
     */
    @GetMapping("/shops/{shopId}/coupons")
    public ResponseEntity<AgentToolResponse> getCouponList(@PathVariable Long shopId) {
        return ResponseEntity.ok(agentToolService.getCouponList(shopId));
    }

    /**
     * POST /internal/agent/tools/shops/{shopId}/open-status
     * Check whether a shop is currently open (dynamically computed from open_hours + now).
     */
    @PostMapping("/shops/{shopId}/open-status")
    public ResponseEntity<AgentToolResponse> checkOpenStatus(
            @PathVariable Long shopId,
            @RequestBody AgentOpenStatusRequest request) {
        String now = request != null ? request.getNow() : null;
        return ResponseEntity.ok(agentToolService.checkOpenStatus(shopId, now));
    }

    /**
     * POST /internal/agent/tools/shops/{shopId}/distance-eta
     * Calculate distance and ETA from user location to shop (dynamically computed via haversine).
     */
    @PostMapping("/shops/{shopId}/distance-eta")
    public ResponseEntity<AgentToolResponse> getDistanceEta(
            @PathVariable Long shopId,
            @RequestBody AgentDistanceEtaRequest request) {
        AgentLocation location = request != null ? request.getLocation() : null;
        return ResponseEntity.ok(agentToolService.getDistanceEta(shopId, location));
    }

    /**
     * POST /internal/agent/tools/shop-cards
     * Batch fetch lightweight facts for multiple shops.
     */
    @PostMapping("/shop-cards")
    public ResponseEntity<AgentToolResponse> getShopCards(@RequestBody AgentShopCardsRequest request) {
        return ResponseEntity.ok(agentToolService.getShopCards(request));
    }

    /**
     * POST /internal/agent/tools/shop-review-summary
     * Batch fetch structured review summaries.
     */
    @PostMapping("/shop-review-summary")
    public ResponseEntity<AgentToolResponse> getShopReviewSummary(@RequestBody AgentReviewSummaryRequest request) {
        return ResponseEntity.ok(agentToolService.getShopReviewSummary(request));
    }

    /**
     * POST /internal/agent/tools/shops/{shopId}/deals
     * Get deal / group-buy facts for one shop.
     */
    @PostMapping("/shops/{shopId}/deals")
    public ResponseEntity<AgentToolResponse> getDealList(
            @PathVariable Long shopId,
            @RequestBody(required = false) AgentDealListRequest request) {
        return ResponseEntity.ok(agentToolService.getDealList(shopId, request));
    }
}
