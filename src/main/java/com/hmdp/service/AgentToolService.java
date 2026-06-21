package com.hmdp.service;

import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.hmdp.dto.agent.*;
import com.hmdp.entity.Shop;
import com.hmdp.entity.Voucher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.annotation.Resource;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.*;
import java.util.stream.Collectors;

/**
 * Service for Agent tool API — 6 tools that the Python Agent calls.
 *
 * All queries go directly to MySQL via MyBatis Plus.
 * No dependency on mock JSON or AiBusinessQueryFacade.
 */
@Service
@Transactional(readOnly = true)
public class AgentToolService {

    @Resource
    private IShopService shopService;

    @Resource
    private IVoucherService voucherService;

    private static final double EARTH_RADIUS_KM = 6371.0;
    private static final int DEFAULT_SEARCH_LIMIT = 20;

    // ── 1. resolve_shop ─────────────────────────────────────────────

    public AgentToolResponse resolveShop(AgentResolveShopRequest request) {
        if (request == null || StrUtil.isBlank(request.getQuery())) {
            return buildResolveNotFound("查询不能为空");
        }

        String query = request.getQuery().trim();
        List<Shop> matched = new ArrayList<>();

        // Strategy 1: exact name match
        matched.addAll(shopService.lambdaQuery()
                .eq(Shop::getName, query)
                .list());

        // Strategy 2: if no exact match, try LIKE
        if (matched.isEmpty()) {
            matched.addAll(shopService.lambdaQuery()
                    .like(Shop::getName, query)
                    .list());
        }

        // Strategy 3: strip parentheses and try again
        if (matched.isEmpty() && query.contains("(") || query.contains("（")) {
            String stripped = query.replaceAll("[（(].*?[）)]", "").trim();
            if (StrUtil.isNotBlank(stripped) && !stripped.equals(query)) {
                matched.addAll(shopService.lambdaQuery()
                        .like(Shop::getName, stripped)
                        .list());
            }
        }

        // Strategy 4: session shop IDs hint
        if (matched.isEmpty() && request.getSessionShopIds() != null && !request.getSessionShopIds().isEmpty()) {
            for (String sid : request.getSessionShopIds()) {
                try {
                    Shop shop = shopService.getById(Long.parseLong(sid));
                    if (shop != null) {
                        matched.add(shop);
                    }
                } catch (NumberFormatException ignored) {
                }
            }
        }

        if (matched.isEmpty()) {
            return buildResolveNotFound("未匹配到店铺");
        }

        if (matched.size() == 1) {
            return buildResolveResolved(matched.get(0));
        }

        // Multiple matches: return AMBIGUOUS with candidates
        return buildResolveAmbiguous(matched);
    }

    // ── 2. search_shops ─────────────────────────────────────────────

    public AgentToolResponse searchShops(AgentSearchShopsRequest request) {
        if (request == null || StrUtil.isBlank(request.getQuery())) {
            return AgentToolResponse.ok(Collections.emptyList());
        }

        String query = request.getQuery().trim();
        int limit = (request.getLimit() == null || request.getLimit() <= 0) ? DEFAULT_SEARCH_LIMIT : request.getLimit();

        // Search by name LIKE
        List<Shop> shops = shopService.lambdaQuery()
                .like(Shop::getName, query)
                .last("LIMIT " + limit)
                .list();

        // If nothing found, try type_id based on category
        if (shops.isEmpty() && StrUtil.isNotBlank(request.getCategory())) {
            shops = shopService.lambdaQuery()
                    .eq(Shop::getTypeId, 1L)  // Food category
                    .last("LIMIT " + limit)
                    .list();
        }

        List<AgentShopDTO> dtos = shops.stream()
                .map(shop -> toAgentShopDTO(shop, request.getLocation()))
                .collect(Collectors.toList());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("data", dtos);
        result.put("total", dtos.size());
        return AgentToolResponse.ok(result);
    }

    // ── 3. get_shop_detail ──────────────────────────────────────────

    public AgentToolResponse getShopDetail(Long shopId) {
        if (shopId == null) {
            return AgentToolResponse.failed("INVALID_ARGUMENT", "shopId is required");
        }

        Shop shop = shopService.getById(shopId);
        if (shop == null) {
            return AgentToolResponse.failed("SHOP_NOT_FOUND", "Shop not found: " + shopId);
        }

        return AgentToolResponse.ok(toAgentShopDTO(shop, null));
    }

    // ── 4. get_coupon_list ──────────────────────────────────────────

    public AgentToolResponse getCouponList(Long shopId) {
        if (shopId == null) {
            return AgentToolResponse.failed("INVALID_ARGUMENT", "shopId is required");
        }

        List<Voucher> vouchers = voucherService.lambdaQuery()
                .eq(Voucher::getShopId, shopId)
                .eq(Voucher::getStatus, 1)  // Only available coupons
                .list();

        if (vouchers.isEmpty()) {
            return AgentToolResponse.empty();
        }

        List<AgentCouponDTO> dtos = vouchers.stream()
                .map(this::toAgentCouponDTO)
                .collect(Collectors.toList());

        return AgentToolResponse.ok(dtos);
    }

    // ── 5. check_open_status ────────────────────────────────────────

    public AgentToolResponse checkOpenStatus(Long shopId, String nowStr) {
        if (shopId == null) {
            return AgentToolResponse.failed("INVALID_ARGUMENT", "shopId is required");
        }

        Shop shop = shopService.getById(shopId);
        if (shop == null) {
            return AgentToolResponse.failed("SHOP_NOT_FOUND", "Shop not found: " + shopId);
        }

        // Determine current time
        LocalTime now;
        if (StrUtil.isNotBlank(nowStr)) {
            try {
                now = LocalDateTime.parse(nowStr, DateTimeFormatter.ISO_LOCAL_DATE_TIME).toLocalTime();
            } catch (DateTimeParseException e) {
                try {
                    now = LocalTime.parse(nowStr, DateTimeFormatter.ISO_LOCAL_TIME);
                } catch (DateTimeParseException e2) {
                    now = LocalTime.now();
                }
            }
        } else {
            now = LocalTime.now();
        }

        String businessHours = shop.getOpenHours();
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("shop_id", String.valueOf(shopId));
        result.put("shop_name", shop.getName());
        result.put("business_hours", businessHours != null ? businessHours : "");

        if (StrUtil.isBlank(businessHours)) {
            result.put("open_status", "unknown");
            result.put("reason", "无营业时间数据");
        } else {
            OpenStatusInfo statusInfo = computeOpenStatus(businessHours, now);
            result.put("open_status", statusInfo.status);
            result.put("reason", statusInfo.reason);
        }

        return AgentToolResponse.ok(result);
    }

    // ── 6. get_distance_eta ─────────────────────────────────────────

    public AgentToolResponse getDistanceEta(Long shopId, AgentLocation location) {
        if (shopId == null || location == null) {
            return AgentToolResponse.failed("INVALID_ARGUMENT", "shopId and location are required");
        }

        Shop shop = shopService.getById(shopId);
        if (shop == null) {
            return AgentToolResponse.failed("SHOP_NOT_FOUND", "Shop not found: " + shopId);
        }

        double distanceKm = haversine(
                location.getLat(), location.getLng(),
                shop.getY(), shop.getX()  // y=lat, x=lng
        );

        // Rough ETA: assume 30 km/h average speed in city
        int etaMinutes = Math.max(1, (int) Math.ceil(distanceKm / 0.5));

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("shop_id", String.valueOf(shopId));
        result.put("shop_name", shop.getName());
        result.put("distance_km", Math.round(distanceKm * 100.0) / 100.0);
        result.put("eta_minutes", etaMinutes);
        result.put("traffic_level", "unknown");

        return AgentToolResponse.ok(result);
    }

    // ── Internal helpers ────────────────────────────────────────────

    private AgentShopDTO toAgentShopDTO(Shop shop, AgentLocation location) {
        AgentShopDTO dto = new AgentShopDTO();
        dto.setShopId(String.valueOf(shop.getId()));
        dto.setShopName(shop.getName());
        dto.setCategoryId(shop.getTypeId());
        dto.setCategory(String.valueOf(shop.getTypeId()));  // Will map to type name later if needed
        dto.setAddress(shop.getAddress());
        dto.setArea(shop.getArea());
        dto.setLat(shop.getY());           // y → lat
        dto.setLng(shop.getX());           // x → lng
        dto.setRating(shop.getScore() == null ? 0.0 : shop.getScore() / 10.0);
        dto.setAvgPrice(shop.getAvgPrice());
        dto.setBusinessHours(shop.getOpenHours());
        dto.setSold(shop.getSold());
        dto.setComments(shop.getComments());
        return dto;
    }

    private AgentCouponDTO toAgentCouponDTO(Voucher voucher) {
        AgentCouponDTO dto = new AgentCouponDTO();
        dto.setCouponId(String.valueOf(voucher.getId()));
        dto.setShopId(String.valueOf(voucher.getShopId()));
        dto.setTitle(voucher.getTitle());
        dto.setDescription(voucher.getSubTitle());
        dto.setPayValue(voucher.getPayValue());
        dto.setActualValue(voucher.getActualValue());
        dto.setStatus(voucher.getStatus() != null && voucher.getStatus() == 1 ? "available" : "unknown");
        return dto;
    }

    private AgentToolResponse buildResolveResolved(Shop shop) {
        Map<String, Object> shopData = new LinkedHashMap<>();
        shopData.put("shop_id", String.valueOf(shop.getId()));
        shopData.put("shop_name", shop.getName());
        shopData.put("address", shop.getAddress());
        shopData.put("lat", shop.getY());
        shopData.put("lng", shop.getX());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "RESOLVED");
        result.put("shop", shopData);
        result.put("candidates", Collections.emptyList());
        result.put("confidence", 0.95);

        return AgentToolResponse.ok(result);
    }

    private AgentToolResponse buildResolveNotFound(String reason) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "NOT_FOUND");
        result.put("shop", null);
        result.put("candidates", Collections.emptyList());
        result.put("confidence", 0.0);
        result.put("error_code", "SHOP_NOT_FOUND");
        return AgentToolResponse.ok(result);
    }

    private AgentToolResponse buildResolveAmbiguous(List<Shop> shops) {
        List<Map<String, Object>> candidates = shops.stream()
                .limit(5)
                .map(shop -> {
                    Map<String, Object> c = new LinkedHashMap<>();
                    c.put("shop_id", String.valueOf(shop.getId()));
                    c.put("shop_name", shop.getName());
                    c.put("address", shop.getAddress());
                    return c;
                })
                .collect(Collectors.toList());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "AMBIGUOUS");
        result.put("shop", null);
        result.put("candidates", candidates);
        result.put("confidence", 0.5);
        result.put("error_code", "AMBIGUOUS_SHOP");

        return AgentToolResponse.ok(result);
    }

    /**
     * Compute open status from business hours string and current time.
     * Supports formats: "HH:mm-HH:mm", "HH:mm-HH:mm,HH:mm-HH:mm", "HH:mm-次日HH:mm"
     */
    private OpenStatusInfo computeOpenStatus(String businessHours, LocalTime now) {
        String[] ranges = businessHours.split(",");
        boolean allUnknown = true;

        for (String range : ranges) {
            range = range.trim();
            if (StrUtil.isBlank(range)) continue;

            String[] parts = range.split("-");
            if (parts.length != 2) continue;

            try {
                LocalTime start = parseTime(parts[0].trim());
                LocalTime end = parseTime(parts[1].trim().replace("次日", "").trim());

                // Handle overnight hours (e.g., 18:00-次日02:00)
                if (parts[1].contains("次日") || end.isBefore(start)) {
                    // Overnight: current time >= start OR current time < end
                    if (!now.isBefore(start) || now.isBefore(end)) {
                        return new OpenStatusInfo("open", "当前时间在营业时间内（跨日）");
                    }
                } else {
                    // Normal: start <= current < end
                    if (!now.isBefore(start) && now.isBefore(end)) {
                        return new OpenStatusInfo("open", "当前时间在营业时间内");
                    }
                }
                allUnknown = false;
            } catch (DateTimeParseException ignored) {
            }
        }

        if (allUnknown) {
            return new OpenStatusInfo("unknown", "无法解析营业时间: " + businessHours);
        }
        return new OpenStatusInfo("closed", "当前时间不在营业时间内");
    }

    private LocalTime parseTime(String timeStr) {
        if (timeStr.length() == 4) {
            // e.g., "0730" → "07:30"
            timeStr = timeStr.substring(0, 2) + ":" + timeStr.substring(2);
        } else if (timeStr.length() == 3) {
            // e.g., "730" → "07:30"
            timeStr = "0" + timeStr.substring(0, 1) + ":" + timeStr.substring(1);
        }
        return LocalTime.parse(timeStr, DateTimeFormatter.ofPattern("HH:mm"));
    }

    /**
     * Haversine distance calculation.
     */
    private double haversine(double lat1, double lng1, double lat2, double lng2) {
        double dLat = Math.toRadians(lat2 - lat1);
        double dLng = Math.toRadians(lng2 - lng1);
        double a = Math.sin(dLat / 2) * Math.sin(dLat / 2)
                + Math.cos(Math.toRadians(lat1)) * Math.cos(Math.toRadians(lat2))
                * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        double c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return EARTH_RADIUS_KM * c;
    }

    private static class OpenStatusInfo {
        final String status;
        final String reason;

        OpenStatusInfo(String status, String reason) {
            this.status = status;
            this.reason = reason;
        }
    }
}
