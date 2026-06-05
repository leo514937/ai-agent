package com.hmdp.ai.query;

import cn.hutool.core.util.StrUtil;
import com.hmdp.dto.UserDTO;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * AI 业务查询的归一化上下文。
 *
 * 只保留读请求需要的字段，避免把查询层做成大而全的业务对象。
 */
@Data
@NoArgsConstructor
public class AiQueryContext {

    private String page;
    private Long shopId;
    private Long blogId;
    private Long typeId;
    private String typeName;
    private String shopName;
    private String blogTitle;
    private Long userId;
    private String userNickName;
    private Long targetUserId;
    private String targetUserName;
    private Double x;
    private Double y;
    private String location;
    private Map<String, Object> rawContext = new LinkedHashMap<>();

    public static AiQueryContext from(Map<String, Object> context, UserDTO currentUser) {
        AiQueryContext result = new AiQueryContext();
        Map<String, Object> source = context == null ? new LinkedHashMap<>() : new LinkedHashMap<>(context);
        result.setRawContext(source);
        result.setPage(firstNonBlank(asString(source, "page"), asString(source, "currentPage"), "assistant"));
        result.setShopId(firstLong(source, "shopId", "currentShopId", "shop_id"));
        result.setBlogId(firstLong(source, "blogId", "currentBlogId", "blog_id"));
        result.setTypeId(firstLong(source, "typeId", "currentTypeId", "shopTypeId"));
        result.setTypeName(firstNonBlank(asString(source, "typeName"), asString(source, "currentTypeName")));
        result.setShopName(firstNonBlank(asString(source, "shopName"), asString(source, "currentShopName")));
        result.setBlogTitle(firstNonBlank(asString(source, "blogTitle"), asString(source, "currentBlogTitle")));
        result.setUserId(firstLong(source, "userId", "currentUserId"));
        result.setUserNickName(firstNonBlank(asString(source, "userNickName"), asString(source, "currentUserName")));
        result.setTargetUserId(firstLong(source, "targetUserId", "authorUserId", "blogAuthorId"));
        result.setTargetUserName(firstNonBlank(asString(source, "targetUserName"), asString(source, "authorUserName")));
        result.setX(firstDouble(source, "x", "longitude", "lng"));
        result.setY(firstDouble(source, "y", "latitude", "lat"));
        result.setLocation(firstNonBlank(
                asString(source, "location"),
                asString(source, "current_location"),
                asString(source, "location_name"),
                asString(source, "address"),
                asString(source, "city"),
                asString(source, "area")
        ));

        if (currentUser != null) {
            if (result.getUserId() == null) {
                result.setUserId(currentUser.getId());
            }
            if (StrUtil.isBlank(result.getUserNickName())) {
                result.setUserNickName(currentUser.getNickName());
            }
        }
        return result;
    }

    public boolean hasShopContext() {
        return shopId != null || StrUtil.isNotBlank(shopName);
    }

    public boolean hasBlogContext() {
        return blogId != null || StrUtil.isNotBlank(blogTitle);
    }

    public boolean hasTypeContext() {
        return typeId != null || StrUtil.isNotBlank(typeName);
    }

    private static String asString(Map<String, Object> source, String key) {
        Object value = source.get(key);
        return value == null ? null : String.valueOf(value);
    }

    private static Long firstLong(Map<String, Object> source, String... keys) {
        for (String key : keys) {
            Long value = extractLong(source.get(key));
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private static Double firstDouble(Map<String, Object> source, String... keys) {
        for (String key : keys) {
            Double value = extractDouble(source.get(key));
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private static Long extractLong(Object value) {
        if (value instanceof Number) {
            return ((Number) value).longValue();
        }
        if (value instanceof String && StrUtil.isNotBlank((String) value)) {
            try {
                return Long.parseLong((String) value);
            } catch (NumberFormatException ignored) {
            }
        }
        return null;
    }

    private static Double extractDouble(Object value) {
        if (value instanceof Number) {
            return ((Number) value).doubleValue();
        }
        if (value instanceof String && StrUtil.isNotBlank((String) value)) {
            try {
                return Double.parseDouble((String) value);
            } catch (NumberFormatException ignored) {
            }
        }
        return null;
    }

    private static String firstNonBlank(String... values) {
        for (String value : values) {
            if (StrUtil.isNotBlank(value)) {
                return value;
            }
        }
        return null;
    }
}
