package com.hmdp.service;

import cn.hutool.core.util.StrUtil;
import com.hmdp.ai.query.AiBusinessQueryFacade;
import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.ai.query.dto.AiReputationDigest;
import com.hmdp.dto.agent.*;
import com.hmdp.entity.Blog;
import com.hmdp.entity.BlogComments;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopType;
import com.hmdp.entity.SeckillVoucher;
import com.hmdp.entity.Voucher;
import com.hmdp.service.ISeckillVoucherService;
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

    @Resource
    private ISeckillVoucherService seckillVoucherService;

    @Resource
    private IShopTypeService shopTypeService;

    @Resource
    private AiBusinessQueryFacade aiBusinessQueryFacade;

    private static final double EARTH_RADIUS_KM = 6371.0;
    private static final int DEFAULT_SEARCH_LIMIT = 20;
    private static final int DEFAULT_REVIEW_LIMIT = 3;
    private static final Map<Long, List<AgentDealDTO>> DEAL_CATALOG = buildDealCatalog();

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

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("data", dtos);
        result.put("total", dtos.size());
        return AgentToolResponse.ok(result);
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

    // ── 7. get_shop_cards ──────────────────────────────────────────

    public AgentToolResponse getShopCards(AgentShopCardsRequest request) {
        if (request == null || request.getShopIds() == null || request.getShopIds().isEmpty()) {
            return AgentToolResponse.failed("INVALID_ARGUMENT", "shopIds is required");
        }

        long started = System.nanoTime();
        boolean needCouponBrief = request.getNeedCouponBrief() == null || request.getNeedCouponBrief();
        boolean needOpenStatus = request.getNeedOpenStatus() == null || request.getNeedOpenStatus();
        boolean needDistanceEta = request.getNeedDistanceEta() == null || request.getNeedDistanceEta();
        int maxItems = request.getMaxItems() == null || request.getMaxItems() <= 0 ? request.getShopIds().size() : request.getMaxItems();

        List<AgentShopCardDTO> items = new ArrayList<>();
        List<String> missing = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        AgentLocation location = request.getUserLocation();
        if (needDistanceEta && location == null) {
            warnings.add("未提供用户位置，距离和 ETA 返回 null");
        }

        for (String rawId : request.getShopIds()) {
            if (items.size() >= maxItems) {
                break;
            }
            String shopIdStr = StrUtil.trimToNull(rawId);
            if (shopIdStr == null) {
                continue;
            }
            Shop shop = parseShopId(shopIdStr);
            if (shop == null) {
                missing.add(shopIdStr);
                continue;
            }
            items.add(buildShopCard(shop, location, needCouponBrief, needOpenStatus, needDistanceEta));
        }

        String status = items.isEmpty() ? "empty" : (missing.isEmpty() && warnings.isEmpty() ? "ok" : "partial");
        if (items.isEmpty() && !missing.isEmpty()) {
            status = "empty";
        }
        AgentShopCardsResult result = new AgentShopCardsResult(
                status,
                items,
                missing,
                warnings,
                buildTrace(
                        "get_shop_cards",
                        started,
                        status,
                        Map.of(
                                "shop_ids", request.getShopIds(),
                                "need_coupon_brief", needCouponBrief,
                                "need_open_status", needOpenStatus,
                                "need_distance_eta", needDistanceEta,
                                "max_items", maxItems
                        ),
                        items.size(),
                        missing,
                        warnings,
                        null,
                        null
                )
        );
        return buildToolResponse(status, result);
    }

    // ── 8. get_shop_review_summary ────────────────────────────────

    public AgentToolResponse getShopReviewSummary(AgentReviewSummaryRequest request) {
        if (request == null || request.getShopIds() == null || request.getShopIds().isEmpty()) {
            return AgentToolResponse.failed("INVALID_ARGUMENT", "shopIds is required");
        }

        long started = System.nanoTime();
        List<AgentReviewSummaryDTO> items = new ArrayList<>();
        List<String> missing = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        boolean partial = false;
        int limit = request.getMaxReviews() == null || request.getMaxReviews() <= 0 ? request.getShopIds().size() : request.getMaxReviews();
        List<String> aspects = request.getAspects() == null ? Collections.emptyList() : request.getAspects();

        for (String rawId : request.getShopIds()) {
            if (items.size() >= limit) {
                break;
            }
            String shopIdStr = StrUtil.trimToNull(rawId);
            if (shopIdStr == null) {
                continue;
            }
            Long shopId = parseLongId(shopIdStr);
            if (shopId == null) {
                missing.add(shopIdStr);
                continue;
            }
            Map<String, Object> contextMap = new LinkedHashMap<>();
            contextMap.put("shopId", shopId);
            if (StrUtil.isNotBlank(request.getScene())) {
                contextMap.put("scene", request.getScene());
            }
            AiQueryContext aiContext = AiQueryContext.from(contextMap, null);
            Shop shop = shopService.getById(shopId);
            AiReputationDigest digest;
            try {
                digest = aiBusinessQueryFacade.buildReputationDigest(aiContext, DEFAULT_REVIEW_LIMIT, DEFAULT_REVIEW_LIMIT);
            } catch (Exception ex) {
                digest = new AiReputationDigest();
                digest.setShop(shop);
                digest.setShopType(shop == null ? null : shopTypeService.getById(shop.getTypeId()));
                warnings.add("AiBusinessQueryFacade 暂不可用，已回退到评分/标签摘要");
                partial = true;
            }
            if (digest != null && digest.getShop() != null) {
                shop = digest.getShop();
            }
            if (shop == null) {
                missing.add(shopIdStr);
                continue;
            }
            AgentReviewSummaryDTO item = buildReviewSummaryItem(shop, digest, request.getScene(), aspects);
            if (item.getSourceFields().contains("shop_detail") && item.getSourceFields().contains("rating") && item.getSourceFields().contains("shop_tags")
                    && !item.getSourceFields().contains("blog_summary")) {
                partial = true;
            }
            if ((digest.getBlogs() == null || digest.getBlogs().isEmpty()) && (digest.getComments() == null || digest.getComments().isEmpty())) {
                partial = true;
                warnings.add(shop.getName() + " 当前只有评分/标签信息，口碑摘要为回退版");
            }
            items.add(item);
        }

        String status = items.isEmpty() ? "empty" : (partial || !missing.isEmpty() || !warnings.isEmpty() ? "partial" : "ok");
        Map<String, Object> traceInput = new LinkedHashMap<>();
        traceInput.put("shop_ids", request.getShopIds());
        traceInput.put("aspects", aspects);
        traceInput.put("scene", request.getScene());
        traceInput.put("max_reviews", limit);
        AgentReviewSummaryResult result = new AgentReviewSummaryResult(
                status,
                items,
                missing,
                warnings,
                buildTrace(
                        "get_shop_review_summary",
                        started,
                        status,
                        traceInput,
                        items.size(),
                        missing,
                        warnings,
                        null,
                        null
                )
        );
        return buildToolResponse(status, result);
    }

    // ── 9. get_deal_list ───────────────────────────────────────────

    public AgentToolResponse getDealList(Long shopId, AgentDealListRequest request) {
        if (shopId == null) {
            return AgentToolResponse.failed("INVALID_ARGUMENT", "shopId is required");
        }

        long started = System.nanoTime();
        Shop shop = shopService.getById(shopId);
        if (shop == null) {
            AgentDealListResult emptyResult = new AgentDealListResult(
                    "empty",
                    String.valueOf(shopId),
                    null,
                    Collections.emptyList(),
                    Collections.singletonList("shop_id=" + shopId + " 未找到"),
                    buildTrace(
                            "get_deal_list",
                            started,
                            "empty",
                            Map.of("shop_id", shopId),
                            0,
                            Collections.emptyList(),
                            Collections.singletonList("shop_id=" + shopId + " 未找到"),
                            null,
                            null
                    )
            );
            return AgentToolResponse.ok(emptyResult);
        }

        boolean onlyAvailable = request == null || request.getOnlyAvailable() == null || request.getOnlyAvailable();
        String dealType = request == null ? null : request.getDealType();
        Integer peopleCount = request == null ? null : request.getPeopleCount();
        Double budgetPerPerson = request == null ? null : request.getBudgetPerPerson();

        List<AgentDealDTO> items = new ArrayList<>();
        for (AgentDealDTO source : DEAL_CATALOG.getOrDefault(shopId, Collections.emptyList())) {
            if (onlyAvailable && Boolean.FALSE.equals(source.getAvailable())) {
                continue;
            }
            if (StrUtil.isNotBlank(dealType) && !StrUtil.equalsIgnoreCase(dealType, source.getDealType())) {
                continue;
            }

            AgentDealDTO deal = copyDeal(source);
            if (deal.getPrice() != null && deal.getOriginalPrice() != null && deal.getOriginalPrice() > 0) {
                deal.setDiscountRate(Math.round((deal.getPrice() / deal.getOriginalPrice()) * 10000.0) / 10000.0);
            }
            if (peopleCount != null && peopleCount > 0 && deal.getPrice() != null) {
                deal.setAvgPricePerPerson(Math.round((deal.getPrice() / peopleCount) * 100.0) / 100.0);
            } else if (deal.getPrice() != null) {
                int minPeople = deal.getPeopleCountMin() == null ? 1 : deal.getPeopleCountMin();
                int maxPeople = deal.getPeopleCountMax() == null ? minPeople : deal.getPeopleCountMax();
                int estimatedPeople = Math.max(1, Math.round((minPeople + maxPeople) / 2.0f));
                deal.setAvgPricePerPerson(Math.round((deal.getPrice() / estimatedPeople) * 100.0) / 100.0);
            }
            if (budgetPerPerson != null && deal.getAvgPricePerPerson() != null && deal.getAvgPricePerPerson() > budgetPerPerson) {
                continue;
            }
            items.add(deal);
        }

        List<String> warnings = new ArrayList<>();
        if (items.isEmpty()) {
            warnings.add("当前没有查到套餐数据，仅有 coupon 数据时不回退拼接");
        }
        String status = items.isEmpty() ? "empty" : (warnings.isEmpty() ? "ok" : "partial");
        AgentDealListResult result = new AgentDealListResult(
                status,
                String.valueOf(shopId),
                shop.getName(),
                items,
                warnings,
                buildTrace(
                        "get_deal_list",
                        started,
                        status,
                        Map.of(
                                "shop_id", shopId,
                                "people_count", peopleCount,
                                "budget_per_person", budgetPerPerson,
                                "deal_type", dealType,
                                "only_available", onlyAvailable
                        ),
                        items.size(),
                        Collections.emptyList(),
                        warnings,
                        null,
                        null
                )
        );
        return buildToolResponse(status, result);
    }

    // ── Internal helpers ────────────────────────────────────────────

    private AgentToolResponse buildToolResponse(String status, Object data) {
        AgentToolResponse response = new AgentToolResponse();
        response.setSuccess(!"error".equals(status));
        response.setResultStatus(status);
        response.setData(data);
        response.setBackendSource("java_api");
        return response;
    }

    private Long parseLongId(String raw) {
        if (StrUtil.isBlank(raw)) {
            return null;
        }
        try {
            return Long.parseLong(raw.trim());
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private Shop parseShopId(String raw) {
        Long shopId = parseLongId(raw);
        return shopId == null ? null : shopService.getById(shopId);
    }

    private AgentToolTraceDTO buildTrace(
            String toolName,
            long startedNanos,
            String status,
            Map<String, Object> input,
            int itemCount,
            List<String> missingShopIds,
            List<String> warnings,
            String errorType,
            String errorMessage
    ) {
        AgentToolTraceDTO trace = new AgentToolTraceDTO();
        trace.setToolName(toolName);
        trace.setBackendSource("java_api");
        trace.setDurationMs(Math.round((System.nanoTime() - startedNanos) / 1_000_000.0));
        trace.setInput(input);
        trace.setStatus(status);
        trace.setItemCount(itemCount);
        trace.setMissingShopIds(new ArrayList<>(missingShopIds == null ? Collections.emptyList() : missingShopIds));
        trace.setWarnings(new ArrayList<>(warnings == null ? Collections.emptyList() : warnings));
        trace.setErrorType(errorType);
        trace.setErrorMessage(errorMessage);
        return trace;
    }

    private String classifyPriceLevel(Double avgPrice) {
        if (avgPrice == null) {
            return null;
        }
        if (avgPrice <= 30.0) {
            return "low";
        }
        if (avgPrice <= 60.0) {
            return "medium";
        }
        return "high";
    }

    private List<String> deriveSceneTags(String category, Double avgPrice, Double rating, String openStatus, int couponCount) {
        List<String> sceneTags = new ArrayList<>();
        String categoryText = StrUtil.blankToDefault(category, "");
        if (categoryText.contains("咖啡") || categoryText.contains("甜品") || categoryText.contains("烘焙")) {
            sceneTags.add("约会");
        }
        if (categoryText.contains("快餐") || (avgPrice != null && avgPrice <= 30.0)) {
            sceneTags.add("学生党");
        }
        if (rating != null && rating >= 4.3 && "open".equalsIgnoreCase(openStatus)) {
            sceneTags.add("朋友聚餐");
        }
        if (avgPrice != null && avgPrice >= 60.0) {
            sceneTags.add("家庭聚餐");
        }
        if (couponCount > 0) {
            sceneTags.add("有券");
        }
        return sceneTags.stream().distinct().collect(Collectors.toList());
    }

    private List<String> deriveTopTags(String category, Double avgPrice, Double rating, String openStatus, int couponCount, Integer distanceM) {
        List<String> tags = new ArrayList<>();
        if (rating != null && rating >= 4.5) {
            tags.add("口碑好");
        }
        if (avgPrice != null && avgPrice <= 30.0) {
            tags.add("实惠");
        }
        if (avgPrice != null && avgPrice >= 60.0) {
            tags.add("高客单");
        }
        if ("open".equalsIgnoreCase(openStatus)) {
            tags.add("营业中");
        }
        if (couponCount > 0) {
            tags.add("有券");
        }
        if (distanceM != null && distanceM <= 1000) {
            tags.add("离得近");
        }
        if (StrUtil.isNotBlank(category)) {
            tags.add(category);
        }
        return tags.stream().distinct().collect(Collectors.toList());
    }

    private AgentShopCardDTO buildShopCard(
            Shop shop,
            AgentLocation location,
            boolean needCouponBrief,
            boolean needOpenStatus,
            boolean needDistanceEta
    ) {
        AgentShopCardDTO dto = new AgentShopCardDTO();
        ShopType type = shopTypeService.getById(shop.getTypeId());
        List<Voucher> coupons = needCouponBrief
                ? voucherService.lambdaQuery().eq(Voucher::getShopId, shop.getId()).eq(Voucher::getStatus, 1).list()
                : Collections.emptyList();
        String openStatus = "unknown";
        if (needOpenStatus) {
            OpenStatusInfo statusInfo = computeOpenStatus(shop.getOpenHours(), LocalTime.now());
            openStatus = statusInfo.status;
        }
        Integer distanceM = null;
        Integer etaMinutes = null;
        if (needDistanceEta && location != null && shop.getY() != null && shop.getX() != null) {
            double distanceKm = haversine(location.getLat(), location.getLng(), shop.getY(), shop.getX());
            distanceM = (int) Math.round(distanceKm * 1000.0);
            etaMinutes = Math.max(1, (int) Math.ceil(distanceKm / 0.5));
        }
        Double rating = shop.getScore() == null ? null : shop.getScore() / 10.0;
        Double avgPrice = shop.getAvgPrice() == null ? null : shop.getAvgPrice().doubleValue();
        dto.setShopId(String.valueOf(shop.getId()));
        dto.setName(shop.getName());
        dto.setAlias(Collections.emptyList());
        dto.setCategory(type == null ? null : type.getName());
        dto.setAddress(shop.getAddress());
        dto.setRating(rating);
        dto.setAvgPrice(avgPrice);
        dto.setPriceLevel(classifyPriceLevel(avgPrice));
        dto.setDistanceM(distanceM);
        dto.setEtaMinutes(etaMinutes);
        dto.setIsOpen("open".equalsIgnoreCase(openStatus) ? Boolean.TRUE : "closed".equalsIgnoreCase(openStatus) ? Boolean.FALSE : null);
        dto.setOpenStatusText(openStatus);
        dto.setCouponCount(needCouponBrief ? coupons.size() : null);
        dto.setHasCoupon(needCouponBrief ? !coupons.isEmpty() : null);
        dto.setTopCouponTitle(needCouponBrief && !coupons.isEmpty() ? coupons.get(0).getTitle() : null);
        dto.setTopTags(deriveTopTags(dto.getCategory(), avgPrice, rating, openStatus, needCouponBrief ? coupons.size() : 0, distanceM));
        dto.setSceneTags(deriveSceneTags(dto.getCategory(), avgPrice, rating, openStatus, needCouponBrief ? coupons.size() : 0));
        List<String> sourceFields = new ArrayList<>();
        sourceFields.add("detail");
        if (needCouponBrief) {
            sourceFields.add("coupon");
        }
        if (needOpenStatus) {
            sourceFields.add("open_status");
        }
        if (needDistanceEta) {
            sourceFields.add("distance_eta");
        }
        dto.setSourceFields(sourceFields);
        return dto;
    }

    private AgentReviewSummaryDTO buildReviewSummaryItem(Shop shop, AiReputationDigest digest, String scene, List<String> aspects) {
        AgentReviewSummaryDTO dto = new AgentReviewSummaryDTO();
        ShopType type = digest.getShopType() != null ? digest.getShopType() : shopTypeService.getById(shop.getTypeId());
        Double rating = shop.getScore() == null ? null : shop.getScore() / 10.0;
        Integer reviewCount = shop.getComments();
        List<String> commentsText = new ArrayList<>();
        if (digest.getBlogs() != null) {
            for (Blog blog : digest.getBlogs()) {
                if (blog == null) {
                    continue;
                }
                commentsText.add(StrUtil.nullToEmpty(blog.getTitle()));
                commentsText.add(StrUtil.nullToEmpty(blog.getContent()));
            }
        }
        if (digest.getComments() != null) {
            for (BlogComments comment : digest.getComments()) {
                if (comment == null) {
                    continue;
                }
                commentsText.add(StrUtil.nullToEmpty(comment.getContent()));
            }
        }
        List<String> positiveTags = new ArrayList<>();
        List<String> negativeTags = new ArrayList<>();
        String category = type == null ? null : type.getName();
        if (rating != null && rating >= 4.5) {
            positiveTags.add("评分高");
        }
        if (shop.getAvgPrice() != null && shop.getAvgPrice() <= 30) {
            positiveTags.add("价格友好");
        }
        if (category != null && (category.contains("咖啡") || category.contains("甜品"))) {
            positiveTags.add("环境好");
        }
        String joinedText = String.join(" ", commentsText);
        if (joinedText.contains("服务")) {
            positiveTags.add("服务稳定");
        }
        if (joinedText.contains("安静")) {
            positiveTags.add("安静");
        }
        if (joinedText.contains("排队")) {
            negativeTags.add("排队久");
        }
        if (joinedText.contains("吵")) {
            negativeTags.add("高峰期吵");
        }
        if (joinedText.contains("贵")) {
            negativeTags.add("价格偏高");
        }
        List<String> sceneTags = new ArrayList<>(deriveSceneTags(category, shop.getAvgPrice() == null ? null : shop.getAvgPrice().doubleValue(), rating, "open", 0));
        if (scene != null && !scene.trim().isEmpty()) {
            sceneTags.add(scene);
        }
        sceneTags = sceneTags.stream().distinct().collect(Collectors.toList());
        AgentSceneFitDTO sceneFit = buildSceneFit(scene, rating, shop.getAvgPrice() == null ? null : shop.getAvgPrice().doubleValue(), positiveTags, negativeTags, sceneTags);

        List<String> highlights = new ArrayList<>();
        if (digest.getHighlights() != null && !digest.getHighlights().isEmpty()) {
            highlights.addAll(digest.getHighlights());
        }
        if (highlights.isEmpty()) {
            highlights.addAll(positiveTags);
        }
        List<String> risks = new ArrayList<>(negativeTags);
        if (risks.isEmpty() && digest.getSummary() != null && digest.getSummary().contains("排队")) {
            risks.add("排队久");
        }
        List<String> sourceFields = new ArrayList<>();
        sourceFields.add("rating");
        sourceFields.add("shop_tags");
        sourceFields.add("shop_detail");
        if (digest.getBlogs() != null && !digest.getBlogs().isEmpty()) {
            sourceFields.add("blog_summary");
        }
        if (digest.getComments() != null && !digest.getComments().isEmpty()) {
            sourceFields.add("facade_review_summary");
        }
        if (aspects != null && !aspects.isEmpty()) {
            sourceFields.add("aspects");
        }

        String summary = digest.getSummary();
        if (StrUtil.isBlank(summary)) {
            summary = shop.getName() + " 的口碑摘要主要基于评分、标签和博客评论回退生成。";
        }

        dto.setShopId(String.valueOf(shop.getId()));
        dto.setName(shop.getName());
        dto.setRating(rating);
        dto.setReviewCount(reviewCount);
        dto.setTasteScore(rating);
        dto.setEnvironmentScore(rating);
        dto.setServiceScore(rating);
        dto.setPriceScore(shop.getAvgPrice() == null ? null : Math.max(1.0, 5.0 - shop.getAvgPrice() / 30.0));
        dto.setPositiveTags(positiveTags.stream().distinct().collect(Collectors.toList()));
        dto.setNegativeTags(negativeTags.stream().distinct().collect(Collectors.toList()));
        dto.setSceneTags(sceneTags);
        dto.setSceneFit(sceneFit);
        dto.setHighlights(highlights.stream().distinct().collect(Collectors.toList()));
        dto.setRisks(risks.stream().distinct().collect(Collectors.toList()));
        dto.setSummary(summary);
        dto.setSourceFields(sourceFields.stream().distinct().collect(Collectors.toList()));
        return dto;
    }

    private AgentSceneFitDTO buildSceneFit(
            String scene,
            Double rating,
            Double avgPrice,
            List<String> positiveTags,
            List<String> negativeTags,
            List<String> sceneTags
    ) {
        if (StrUtil.isBlank(scene)) {
            return new AgentSceneFitDTO(null, null, null, new ArrayList<>());
        }
        double score = 0.5;
        List<String> reasons = new ArrayList<>();
        String sceneLower = scene.toLowerCase(Locale.ROOT);
        if (sceneLower.contains("date") || sceneLower.contains("约会")) {
            if (sceneTags.contains("约会") || positiveTags.contains("安静") || positiveTags.contains("环境好")) {
                score += 0.25;
                reasons.add("环境和标签更适合约会");
            }
        } else if (sceneLower.contains("family") || sceneLower.contains("elderly") || sceneLower.contains("长辈")) {
            if (sceneTags.contains("带长辈") || sceneTags.contains("家庭聚餐")) {
                score += 0.2;
                reasons.add("适合带长辈或家庭聚餐");
            }
            if (avgPrice != null && avgPrice <= 60.0) {
                score += 0.1;
                reasons.add("价格更平稳");
            }
        } else if (sceneLower.contains("student") || sceneLower.contains("学生")) {
            if (sceneTags.contains("学生党") || (avgPrice != null && avgPrice <= 30.0)) {
                score += 0.25;
                reasons.add("学生党友好");
            }
        } else if (sceneLower.contains("friends") || sceneLower.contains("聚餐")) {
            if (sceneTags.contains("朋友聚餐")) {
                score += 0.2;
                reasons.add("适合朋友聚餐");
            }
        } else if (sceneLower.contains("business") || sceneLower.contains("商务")) {
            if (positiveTags.contains("服务稳定") || positiveTags.contains("环境好")) {
                score += 0.15;
                reasons.add("环境/服务更稳");
            }
        }
        if (rating != null && rating >= 4.5) {
            score += 0.1;
            reasons.add("评分较高");
        }
        if (!negativeTags.isEmpty() && negativeTags.contains("排队久")) {
            score -= 0.1;
            reasons.add("高峰排队风险");
        }
        score = Math.max(0.0, Math.min(1.0, Math.round(score * 100.0) / 100.0));
        String label = score >= 0.75 ? "high" : score >= 0.55 ? "medium" : "low";
        if (reasons.isEmpty()) {
            reasons.add("基于评分、标签和价格信息推断");
        }
        return new AgentSceneFitDTO(scene, score, label, reasons);
    }

    private AgentDealDTO copyDeal(AgentDealDTO source) {
        AgentDealDTO deal = new AgentDealDTO();
        deal.setDealId(source.getDealId());
        deal.setTitle(source.getTitle());
        deal.setDealType(source.getDealType());
        deal.setPrice(source.getPrice());
        deal.setOriginalPrice(source.getOriginalPrice());
        deal.setDiscountRate(source.getDiscountRate());
        deal.setPeopleCountMin(source.getPeopleCountMin());
        deal.setPeopleCountMax(source.getPeopleCountMax());
        deal.setAvgPricePerPerson(source.getAvgPricePerPerson());
        deal.setAvailable(source.getAvailable());
        deal.setValidTimeText(source.getValidTimeText());
        deal.setUseTimeRules(new ArrayList<>(source.getUseTimeRules() == null ? Collections.emptyList() : source.getUseTimeRules()));
        deal.setLimitations(new ArrayList<>(source.getLimitations() == null ? Collections.emptyList() : source.getLimitations()));
        deal.setIncludedItems(new ArrayList<>(source.getIncludedItems() == null ? Collections.emptyList() : source.getIncludedItems()));
        deal.setRecommendTags(new ArrayList<>(source.getRecommendTags() == null ? Collections.emptyList() : source.getRecommendTags()));
        deal.setSourceFields(new ArrayList<>(source.getSourceFields() == null ? Collections.emptyList() : source.getSourceFields()));
        return deal;
    }

    private static Map<Long, List<AgentDealDTO>> buildDealCatalog() {
        Map<Long, List<AgentDealDTO>> catalog = new LinkedHashMap<>();
        catalog.put(1L, Collections.singletonList(
                createDeal("deal_001_1", "双人轻食套餐", "double", 56.0, 68.0, 2, 2, true,
                        "全天可用", Arrays.asList("午市可用", "晚市可用"), Collections.singletonList("不可叠加优惠"),
                        Arrays.asList("饮品*2", "甜品*1"), Arrays.asList("双人餐", "约会"))
        ));
        catalog.put(2L, Collections.singletonList(
                createDeal("deal_002_1", "早餐单人套餐", "single", 18.0, 24.0, 1, 1, true,
                        "06:00-10:30", Collections.singletonList("早餐时段可用"), Collections.singletonList("仅限早餐"),
                        Arrays.asList("主食*1", "饮品*1"), Arrays.asList("单人餐", "学生党"))
        ));
        catalog.put(5L, Collections.singletonList(
                createDeal("deal_005_1", "学生党咖啡组合", "student", 19.9, 29.9, 1, 1, true,
                        "工作日可用", Collections.singletonList("周一至周五"), Collections.singletonList("不可用于节假日"),
                        Arrays.asList("美式咖啡*1", "小食*1"), Arrays.asList("学生党", "性价比"))
        ));
        catalog.put(7L, Collections.singletonList(
                createDeal("deal_007_1", "双人火锅套餐", "double", 168.0, 198.0, 2, 2, true,
                        "午市、晚市可用", Arrays.asList("午市可用", "晚市可用"), Collections.singletonList("节假日高峰不可用"),
                        Arrays.asList("锅底*1", "荤菜*2", "素菜*2"), Arrays.asList("双人餐", "约会", "聚餐"))
        ));
        catalog.put(9L, Collections.singletonList(
                createDeal("deal_009_1", "四人家庭套餐", "family", 228.0, 258.0, 4, 4, false,
                        "周末可用", Collections.singletonList("周末可用"), Collections.singletonList("不可叠加优惠"),
                        Arrays.asList("主食*4", "饮品*4", "小菜*2"), Arrays.asList("多人套餐", "家庭聚餐"))
        ));
        return catalog;
    }

    private static AgentDealDTO createDeal(
            String dealId,
            String title,
            String dealType,
            Double price,
            Double originalPrice,
            Integer peopleCountMin,
            Integer peopleCountMax,
            Boolean available,
            String validTimeText,
            List<String> useTimeRules,
            List<String> limitations,
            List<String> includedItems,
            List<String> recommendTags
    ) {
        AgentDealDTO deal = new AgentDealDTO();
        deal.setDealId(dealId);
        deal.setTitle(title);
        deal.setDealType(dealType);
        deal.setPrice(price);
        deal.setOriginalPrice(originalPrice);
        deal.setPeopleCountMin(peopleCountMin);
        deal.setPeopleCountMax(peopleCountMax);
        deal.setAvailable(available);
        deal.setValidTimeText(validTimeText);
        deal.setUseTimeRules(new ArrayList<>(useTimeRules == null ? Collections.emptyList() : useTimeRules));
        deal.setLimitations(new ArrayList<>(limitations == null ? Collections.emptyList() : limitations));
        deal.setIncludedItems(new ArrayList<>(includedItems == null ? Collections.emptyList() : includedItems));
        deal.setRecommendTags(new ArrayList<>(recommendTags == null ? Collections.emptyList() : recommendTags));
        deal.setSourceFields(Collections.singletonList("deal_catalog"));
        return deal;
    }

    private AgentShopDTO toAgentShopDTO(Shop shop, AgentLocation location) {
        AgentShopDTO dto = new AgentShopDTO();
        ShopType type = shopTypeService.getById(shop.getTypeId());
        Double rating = shop.getScore() == null ? null : shop.getScore() / 10.0;
        Double avgPrice = shop.getAvgPrice() == null ? null : shop.getAvgPrice().doubleValue();
        dto.setShopId(String.valueOf(shop.getId()));
        dto.setShopName(shop.getName());
        dto.setCategoryId(shop.getTypeId());
        dto.setCategory(type == null ? String.valueOf(shop.getTypeId()) : type.getName());
        dto.setAddress(shop.getAddress());
        dto.setArea(shop.getArea());
        dto.setAlias(Collections.emptyList());
        dto.setLat(shop.getY());           // y → lat
        dto.setLng(shop.getX());           // x → lng
        dto.setRating(rating);
        dto.setAvgPrice(shop.getAvgPrice());
        dto.setBusinessHours(shop.getOpenHours());
        dto.setSold(shop.getSold());
        dto.setComments(shop.getComments());
        dto.setTags(deriveTopTags(dto.getCategory(), avgPrice, rating, "unknown", 0, null));
        return dto;
    }

    private AgentCouponDTO toAgentCouponDTO(Voucher voucher) {
        AgentCouponDTO dto = new AgentCouponDTO();
        SeckillVoucher seckillVoucher = null;
        if (voucher.getType() != null && voucher.getType() == 1) {
            seckillVoucher = seckillVoucherService.lambdaQuery()
                    .eq(SeckillVoucher::getVoucherId, voucher.getId())
                    .one();
        }
        dto.setCouponId(String.valueOf(voucher.getId()));
        dto.setShopId(String.valueOf(voucher.getShopId()));
        dto.setTitle(voucher.getTitle());
        dto.setDescription(voucher.getSubTitle());
        dto.setDiscountType("fixed");
        if (voucher.getPayValue() != null && voucher.getActualValue() != null) {
            dto.setDiscountValue(Math.max(0.0, (voucher.getActualValue() - voucher.getPayValue()) / 100.0));
            dto.setMinConsume(voucher.getActualValue() / 100.0);
        }
        if (seckillVoucher != null) {
            dto.setValidFrom(formatDateTime(seckillVoucher.getBeginTime()));
            dto.setValidUntil(formatDateTime(seckillVoucher.getEndTime()));
            dto.setStock(seckillVoucher.getStock());
        }
        dto.setPayValue(voucher.getPayValue());
        dto.setActualValue(voucher.getActualValue());
        dto.setStatus(voucher.getStatus() != null && voucher.getStatus() == 1 ? "available" : "unknown");
        return dto;
    }

    private String formatDateTime(LocalDateTime value) {
        return value == null ? null : value.format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
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
