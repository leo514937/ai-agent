package com.hmdp.service;

import cn.hutool.core.util.StrUtil;
import com.hmdp.ai.query.AiBusinessQueryFacade;
import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.ai.query.AiRouteType;
import com.hmdp.ai.query.dto.AiShopDetailDigest;
import com.hmdp.dto.UserDTO;
import com.hmdp.dto.ai.AiShopCard;
import com.hmdp.dto.ai.AiVoucherCard;
import com.hmdp.dto.ai.internal.AiInternalOrderStateResponse;
import com.hmdp.dto.ai.internal.AiInternalBlogCard;
import com.hmdp.dto.ai.internal.AiInternalShopBlogListResponse;
import com.hmdp.dto.ai.internal.AiInternalShopDetailResponse;
import com.hmdp.dto.ai.internal.AiInternalShopSearchRequest;
import com.hmdp.dto.ai.internal.AiInternalShopSearchResponse;
import com.hmdp.dto.ai.internal.AiInternalVoucherListResponse;
import com.hmdp.entity.Shop;
import com.hmdp.entity.Voucher;
import com.hmdp.entity.VoucherOrder;
import com.hmdp.entity.Blog;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.annotation.Resource;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.stream.Collectors;

@Service
@Transactional(readOnly = true)
public class AiInternalBusinessService {

    private static final ZoneId DEFAULT_TIME_ZONE = ZoneId.of("Asia/Shanghai");
    private static final String DEFAULT_LOCATION_NAME = "北京邮电大学海淀校区";
    private static final String DEFAULT_LOCATION_ADDRESS = "北京市海淀区西土城路10号";
    private static final String DEFAULT_LOCATION_CITY = "北京";
    private static final String DEFAULT_LOCATION_DISTRICT = "海淀区";
    private static final Double DEFAULT_LOCATION_LAT = 39.961554d;
    private static final Double DEFAULT_LOCATION_LNG = 116.358104d;

    @Resource
    private AiBusinessQueryFacade aiBusinessQueryFacade;
    @Resource
    private IVoucherOrderService voucherOrderService;

    public Map<String, Object> buildCurrentTimeContext() {
        OffsetDateTime now = OffsetDateTime.now(DEFAULT_TIME_ZONE);
        Map<String, Object> context = new LinkedHashMap<>();
        String timestamp = now.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME);
        context.put("timestamp", timestamp);
        context.put("current_time", timestamp);
        context.put("request_ts", timestamp);
        context.put("epoch_millis", now.toInstant().toEpochMilli());
        context.put("timezone", DEFAULT_TIME_ZONE.getId());
        context.put("source", "java_system_clock");
        return context;
    }

    public Map<String, Object> buildDefaultLocationContext() {
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("location", DEFAULT_LOCATION_NAME);
        context.put("location_name", DEFAULT_LOCATION_NAME);
        context.put("current_location", DEFAULT_LOCATION_ADDRESS + " " + DEFAULT_LOCATION_NAME);
        context.put("address", DEFAULT_LOCATION_ADDRESS);
        context.put("city", DEFAULT_LOCATION_CITY);
        context.put("current_city", DEFAULT_LOCATION_CITY);
        context.put("area", DEFAULT_LOCATION_DISTRICT);
        context.put("district", DEFAULT_LOCATION_DISTRICT);
        context.put("lat", DEFAULT_LOCATION_LAT);
        context.put("latitude", DEFAULT_LOCATION_LAT);
        context.put("lng", DEFAULT_LOCATION_LNG);
        context.put("longitude", DEFAULT_LOCATION_LNG);
        context.put("radius_km", 3.0d);
        context.put("source", "amap_public_place");
        return context;
    }

    public Map<String, Object> enrichRealtimeContext(Map<String, Object> context) {
        Map<String, Object> result = context == null ? new LinkedHashMap<>() : new LinkedHashMap<>(context);
        mergeContext(result, buildCurrentTimeContext(), "time_source");
        mergeContext(result, buildDefaultLocationContext(), "location_source");
        return result;
    }

    public AiInternalShopSearchResponse searchShops(AiInternalShopSearchRequest request) {
        AiInternalShopSearchRequest safeRequest = request == null ? new AiInternalShopSearchRequest() : request;
        AiQueryContext queryContext = aiBusinessQueryFacade.resolveContext(safeRequest.getContext(), buildUser(safeRequest.getUserId(), safeRequest.getUserNickName()));
        AiRouteType route = aiBusinessQueryFacade.resolveRoute(safeRequest.getMessage(), queryContext);
        int limit = safeRequest.getLimit() == null || safeRequest.getLimit() <= 0 ? 5 : safeRequest.getLimit();

        AiInternalShopSearchResponse response = new AiInternalShopSearchResponse();
        response.setRoute(route == null ? AiRouteType.FAQ.name() : route.name());
        response.setShops(aiBusinessQueryFacade.recommendCandidates(queryContext, limit).stream()
                .map(shop -> toShopCard(shop, "internal-business-api"))
                .collect(Collectors.toList()));
        response.setResolvedContext(toResolvedContext(queryContext));
        return response;
    }

    public AiInternalShopDetailResponse getShopDetail(Long shopId, Long userId, Integer voucherLimit, Integer blogLimit) {
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("shopId", shopId);
        AiQueryContext queryContext = aiBusinessQueryFacade.resolveContext(context, buildUser(userId, null));
        AiShopDetailDigest digest = aiBusinessQueryFacade.buildShopDetailDigest(
                queryContext,
                voucherLimit == null || voucherLimit <= 0 ? 5 : voucherLimit,
                blogLimit == null || blogLimit <= 0 ? 3 : blogLimit
        );

        AiInternalShopDetailResponse response = new AiInternalShopDetailResponse();
        response.setFound(digest.getShop() != null);
        response.setShop(digest.getShop() == null ? null : toShopCard(digest.getShop(), "internal-business-api"));
        response.setVouchers(digest.getVouchers().stream().map(this::toVoucherCard).collect(Collectors.toList()));
        response.setHighlights(digest.getHighlights());
        response.setSummary(digest.getSummary());
        response.setResolvedContext(toResolvedContext(queryContext));
        return response;
    }

    public AiInternalVoucherListResponse listShopVouchers(Long shopId, Integer limit) {
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("shopId", shopId);
        AiQueryContext queryContext = aiBusinessQueryFacade.resolveContext(context, null);

        AiInternalVoucherListResponse response = new AiInternalVoucherListResponse();
        response.setShopId(shopId);
        response.setShopName(queryContext.getShopName());
        response.setVouchers(aiBusinessQueryFacade.listVouchers(queryContext, limit == null || limit <= 0 ? 5 : limit).stream()
                .map(this::toVoucherCard)
                .collect(Collectors.toList()));
        return response;
    }

    public AiInternalShopBlogListResponse listShopBlogs(Long shopId, Integer limit) {
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("shopId", shopId);
        AiQueryContext queryContext = aiBusinessQueryFacade.resolveContext(context, null);
        AiShopDetailDigest digest = aiBusinessQueryFacade.buildShopDetailDigest(
                queryContext,
                1,
                limit == null || limit <= 0 ? 5 : limit
        );

        AiInternalShopBlogListResponse response = new AiInternalShopBlogListResponse();
        response.setShopId(shopId);
        response.setShopName(digest.getShop() == null ? queryContext.getShopName() : digest.getShop().getName());
        response.setBlogs(digest.getBlogs().stream().map(this::toBlogCard).collect(Collectors.toList()));
        return response;
    }

    public AiInternalOrderStateResponse getOrderState(Long orderId) {
        if (orderId == null) {
            return noResult(null, "订单号不能为空");
        }

        VoucherOrder order = voucherOrderService.getById(orderId);
        if (order == null) {
            return noResult(orderId, "未找到订单");
        }

        AiInternalOrderStateResponse response = new AiInternalOrderStateResponse();
        response.setOrderId(orderId);
        response.setFound(true);
        response.setCode("ok");
        response.setMessage("ok");
        response.setStatus(mapOrderStatus(order.getStatus()));
        response.setVoucherId(order.getVoucherId());
        response.setUserId(order.getUserId());
        return response;
    }

    private void mergeContext(Map<String, Object> target, Map<String, Object> source, String sourceKeyAlias) {
        if (target == null || source == null) {
            return;
        }
        Object sourceValue = source.get("source");
        if (sourceKeyAlias != null && sourceValue != null && !target.containsKey(sourceKeyAlias)) {
            target.put(sourceKeyAlias, sourceValue);
        }
        for (Map.Entry<String, Object> entry : source.entrySet()) {
            String key = entry.getKey();
            if (StrUtil.equals(key, "source")) {
                continue;
            }
            Object value = entry.getValue();
            if (value == null) {
                continue;
            }
            if (value instanceof String && StrUtil.isBlank((String) value)) {
                continue;
            }
            if (!target.containsKey(key) || target.get(key) == null || (target.get(key) instanceof String && StrUtil.isBlank((String) target.get(key)))) {
                target.put(key, value);
            }
        }
    }

    private AiInternalOrderStateResponse noResult(Long orderId, String message) {
        AiInternalOrderStateResponse response = new AiInternalOrderStateResponse();
        response.setOrderId(orderId);
        response.setFound(false);
        response.setCode("no_result");
        response.setMessage(message);
        response.setStatus("NO_RESULT");
        return response;
    }

    private UserDTO buildUser(Long userId, String userNickName) {
        if (userId == null && StrUtil.isBlank(userNickName)) {
            return null;
        }
        UserDTO user = new UserDTO();
        user.setId(userId);
        user.setNickName(userNickName);
        return user;
    }

    private Map<String, Object> toResolvedContext(AiQueryContext queryContext) {
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("page", queryContext == null ? "assistant" : queryContext.getPage());
        if (queryContext == null) {
            return context;
        }
        putIfNotNull(context, "shopId", queryContext.getShopId());
        putIfNotNull(context, "shopName", queryContext.getShopName());
        putIfNotNull(context, "typeId", queryContext.getTypeId());
        putIfNotNull(context, "typeName", queryContext.getTypeName());
        putIfNotNull(context, "blogId", queryContext.getBlogId());
        putIfNotNull(context, "x", queryContext.getX());
        putIfNotNull(context, "y", queryContext.getY());
        return context;
    }

    private void putIfNotNull(Map<String, Object> context, String key, Object value) {
        if (value != null) {
            context.put(key, value);
        }
    }

    private AiShopCard toShopCard(Shop shop, String reason) {
        AiShopCard card = new AiShopCard();
        card.setId(shop.getId());
        card.setName(shop.getName());
        card.setArea(shop.getArea());
        card.setAddress(shop.getAddress());
        card.setAvgPrice(shop.getAvgPrice());
        card.setScore(shop.getScore() == null ? 0D : shop.getScore() / 10.0);
        card.setComments(shop.getComments());
        card.setOpenHours(shop.getOpenHours());
        card.setImage(firstImage(shop.getImages()));
        card.setDistance(shop.getDistance());
        card.setReason(reason);
        return card;
    }

    private AiVoucherCard toVoucherCard(Voucher voucher) {
        AiVoucherCard card = new AiVoucherCard();
        card.setId(voucher.getId());
        card.setShopId(voucher.getShopId());
        card.setTitle(voucher.getTitle());
        card.setSubTitle(voucher.getSubTitle());
        card.setPayValue(voucher.getPayValue());
        card.setActualValue(voucher.getActualValue());
        card.setStock(voucher.getStock());
        card.setBeginTime(voucher.getBeginTime() == null ? null : voucher.getBeginTime().toString());
        card.setEndTime(voucher.getEndTime() == null ? null : voucher.getEndTime().toString());
        card.setRules(voucher.getRules());
        return card;
    }

    private AiInternalBlogCard toBlogCard(Blog blog) {
        AiInternalBlogCard card = new AiInternalBlogCard();
        card.setId(blog.getId());
        card.setShopId(blog.getShopId());
        card.setUserId(blog.getUserId());
        card.setTitle(blog.getTitle());
        card.setContent(blog.getContent());
        card.setLiked(blog.getLiked());
        card.setComments(blog.getComments());
        return card;
    }

    private String firstImage(String images) {
        if (StrUtil.isBlank(images)) {
            return null;
        }
        return images.split(",")[0];
    }

    private String mapOrderStatus(Integer status) {
        if (status == null) {
            return "UNKNOWN";
        }
        switch (status) {
            case 1:
                return "UNPAID";
            case 2:
                return "PAID";
            case 3:
                return "USED";
            case 4:
                return "CANCELLED";
            case 5:
                return "REFUNDING";
            case 6:
                return "REFUNDED";
            default:
                return String.valueOf(status).toUpperCase(Locale.ROOT);
        }
    }
}
