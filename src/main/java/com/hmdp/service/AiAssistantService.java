package com.hmdp.service;

import cn.hutool.core.util.StrUtil;
import com.hmdp.ai.query.AiBusinessQueryFacade;
import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.ai.query.AiRouteType;
import com.hmdp.ai.remote.AiRemoteChatRequest;
import com.hmdp.ai.remote.AiRemoteChatResult;
import com.hmdp.ai.remote.AiRemoteClient;
import com.hmdp.dto.UserDTO;
import com.hmdp.dto.ai.AiChatRequest;
import com.hmdp.dto.ai.AiChatResponse;
import com.hmdp.dto.ai.AiChatSuggestion;
import com.hmdp.dto.ai.AiShopCard;
import com.hmdp.dto.ai.AiVoucherCard;
import com.hmdp.utils.StringUtils;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import javax.annotation.Resource;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 用户端 AI 助手入口。
 *
 * 设计目标：
 * 1. 优先尝试远端 learning-agent-service
 * 2. 远端失败时直接暴露错误，不再拼接本地兼容回答
 * 3. 业务查询能力收口到 AiBusinessQueryFacade
 */
@Slf4j
@Service
public class AiAssistantService {


    @Resource
    private AiBusinessQueryFacade aiBusinessQueryFacade;
    @Resource
    private AiInternalBusinessService aiInternalBusinessService;
    @Resource
    private AiRemoteClient aiRemoteClient;

    public AiChatResponse chat(AiChatRequest request, UserDTO user) {
        String message = normalize(request == null ? null : request.getMessage());
        Map<String, Object> context = normalizeContext(request == null ? null : request.getContext());
        Map<String, Object> enrichedContext = aiInternalBusinessService.enrichRealtimeContext(context);
        String page = StringUtils.firstNonBlank(request == null ? null : request.getPage(), asString(context, "page"), "assistant");

        AiQueryContext queryContext = aiBusinessQueryFacade.resolveContext(enrichedContext, user);
        AiRouteType route = aiBusinessQueryFacade.resolveRoute(message, queryContext);
        log.info("AI 请求路由={}, page={}, userId={}, shopContext={}, blogContext={}, typeContext={}",
                route,
                page,
                queryContext.getUserId(),
                queryContext.hasShopContext(),
                queryContext.hasBlogContext(),
                queryContext.hasTypeContext());

        AiChatResponse remote = tryRemoteAssistant(request, user, queryContext, page, route);
        if (remote != null) {
            log.info("AI 命中远端服务, page={}, topic={}, source={}",
                    page,
                    remote.getCurrentTopic(),
                    remote.getSource());
            return remote;
        }
        throw new AiAssistantUnavailableException(buildAssistantUnavailableMessage(route, page, "远端未返回可用结果"));
    }

    public String buildAssistantUnavailableMessage() {
        String reason = normalize(aiRemoteClient.getAvailabilityReason());
        if (StrUtil.isNotBlank(reason)) {
            return "当前 AI 助手暂时不可用，请稍后再试。原因：" + reason;
        }
        return "当前 AI 助手暂时不可用，请稍后再试。";
    }

    public String buildAssistantUnavailableMessage(AiRouteType route, String page, String reason) {
        StringBuilder builder = new StringBuilder(buildAssistantUnavailableMessage());
        if (route != null) {
            builder.append(" 路由=").append(route.name());
        }
        if (StrUtil.isNotBlank(page)) {
            builder.append(" 页面=").append(page);
        }
        if (StrUtil.isNotBlank(reason)) {
            builder.append(" 原因=").append(reason);
        }
        return builder.toString();
    }

    private AiChatResponse tryRemoteAssistant(AiChatRequest request, UserDTO user, AiQueryContext queryContext, String page, AiRouteType route) {
        if (!aiRemoteClient.isEnabled()) {
            log.debug("远端 AI 不可用，准备抛出详细错误：{}", aiRemoteClient.getAvailabilityReason());
            throw new AiAssistantUnavailableException(buildAssistantUnavailableMessage(route, page, aiRemoteClient.getAvailabilityReason()));
        }

        AiRemoteChatRequest remoteRequest = new AiRemoteChatRequest();
        remoteRequest.setUserId(user == null || user.getId() == null ? "guest" : String.valueOf(user.getId()));
        remoteRequest.setSessionId(StringUtils.firstNonBlank(request == null ? null : request.getSessionId(), String.valueOf(System.currentTimeMillis())));
        remoteRequest.setTraceId(StringUtils.firstNonBlank(request == null ? null : request.getTraceId(), "trace-" + System.currentTimeMillis()));
        remoteRequest.setPage(page);
        remoteRequest.setMessage(normalize(request == null ? null : request.getMessage()));
        remoteRequest.setResponseMode("default");
        remoteRequest.setTopicHint(StringUtils.firstNonBlank(queryContext.getShopName(), queryContext.getTypeName(), queryContext.getBlogTitle(), page));
        remoteRequest.setHistorySummary(asString(queryContext.getRawContext(), "historySummary"));
        remoteRequest.setClientContext(new LinkedHashMap<>(queryContext.getRawContext()));

        AiRemoteChatResult remoteResult = aiRemoteClient.chat(remoteRequest);
        if (remoteResult == null) {
            throw new AiAssistantUnavailableException(buildAssistantUnavailableMessage(route, page, "远端返回空结果"));
        }
        if (!remoteResult.isSuccess() || StrUtil.isBlank(remoteResult.getAnswer())) {
            String remoteReason = StringUtils.firstNonBlank(
                    remoteResult.getErrorMessage(),
                    asString(remoteResult.getMetadata(), "errorMessage"),
                    asString(remoteResult.getMetadata(), "message"),
                    "远端响应未解析成功"
            );
            throw new AiAssistantUnavailableException(buildAssistantUnavailableMessage(route, page, remoteReason));
        }

        AiChatResponse response = new AiChatResponse();
        response.setAnswer(remoteResult.getAnswer());
        response.setMode(StringUtils.firstNonBlank(remoteResult.getMode(), "remote"));
        response.setSource(StringUtils.firstNonBlank(remoteResult.getSource(), "learning-agent-service"));
        response.setFallback(false);
        response.setPage(StringUtils.firstNonBlank(remoteResult.getPage(), page));
        response.setCurrentTopic(remoteResult.getCurrentTopic());
        response.setSuggestions(extractSuggestions(remoteResult.getMetadata()));
        response.setShops(extractShopCards(remoteResult.getMetadata()));
        response.setVouchers(extractVoucherCards(remoteResult.getMetadata()));
        response.setCards(extractCards(remoteResult.getMetadata()));
        response.setNextSteps(extractNextSteps(remoteResult.getMetadata(), response.getSuggestions()));
        response.setTaskChain(extractTaskChain(remoteResult.getMetadata()));
        response.setContext(new LinkedHashMap<>(queryContext.getRawContext()));
        return response;
    }

    private List<AiChatSuggestion> extractSuggestions(Map<String, Object> metadata) {
        List<AiChatSuggestion> suggestions = new ArrayList<>();
        for (Map<String, Object> item : asMapList(firstMetadataValue(metadata, "suggested_replies", "suggestedReplies", "suggestions"))) {
            String label = StringUtils.firstNonBlank(asString(item, "label"), asString(item, "prompt"), asString(item, "value"));
            String prompt = StringUtils.firstNonBlank(asString(item, "prompt"), asString(item, "value"), label);
            if (StrUtil.isBlank(label) || StrUtil.isBlank(prompt)) {
                continue;
            }
            suggestions.add(new AiChatSuggestion(label, prompt));
        }
        return suggestions;
    }

    private List<AiShopCard> extractShopCards(Map<String, Object> metadata) {
        List<AiShopCard> cards = new ArrayList<>();
        for (Map<String, Object> item : asMapList(firstMetadataValue(metadata, "shops", "shop_cards", "shopCards"))) {
            cards.add(toShopCard(item));
        }
        return cards;
    }

    private List<AiVoucherCard> extractVoucherCards(Map<String, Object> metadata) {
        List<AiVoucherCard> cards = new ArrayList<>();
        for (Map<String, Object> item : asMapList(firstMetadataValue(metadata, "vouchers", "voucher_cards", "voucherCards"))) {
            cards.add(toVoucherCard(item));
        }
        return cards;
    }

    private List<Map<String, Object>> extractCards(Map<String, Object> metadata) {
        List<Map<String, Object>> cards = new ArrayList<>();
        for (Map<String, Object> item : asMapList(firstMetadataValue(metadata, "cards", "card_list", "cardList"))) {
            cards.add(item);
        }
        return cards;
    }

    private List<String> extractNextSteps(Map<String, Object> metadata, List<AiChatSuggestion> suggestions) {
        List<String> nextSteps = asStringList(firstMetadataValue(metadata, "next_steps", "nextSteps"));
        if (!nextSteps.isEmpty()) {
            return nextSteps;
        }
        for (AiChatSuggestion suggestion : suggestions) {
            if (suggestion == null || StrUtil.isBlank(suggestion.getPrompt())) {
                continue;
            }
            nextSteps.add(suggestion.getPrompt());
        }
        return nextSteps;
    }

    private List<Map<String, Object>> extractTaskChain(Map<String, Object> metadata) {
        List<Map<String, Object>> taskChain = new ArrayList<>();
        for (Map<String, Object> item : asMapList(firstMetadataValue(metadata, "task_chain", "taskChain"))) {
            taskChain.add(item);
        }
        return taskChain;
    }

    private Object firstMetadataValue(Map<String, Object> metadata, String... keys) {
        if (metadata == null || keys == null) {
            return null;
        }
        for (String key : keys) {
            if (StrUtil.isBlank(key) || !metadata.containsKey(key)) {
                continue;
            }
            Object value = metadata.get(key);
            if (value == null) {
                continue;
            }
            if (value instanceof String && StrUtil.isBlank((String) value)) {
                continue;
            }
            return value;
        }
        return null;
    }

    private List<Map<String, Object>> asMapList(Object value) {
        List<Map<String, Object>> items = new ArrayList<>();
        if (value instanceof Iterable<?>) {
            for (Object item : (Iterable<?>) value) {
                Map<String, Object> map = asMap(item);
                if (!map.isEmpty()) {
                    items.add(map);
                }
            }
        } else {
            Map<String, Object> map = asMap(value);
            if (!map.isEmpty()) {
                items.add(map);
            }
        }
        return items;
    }

    private Map<String, Object> asMap(Object value) {
        Map<String, Object> map = new LinkedHashMap<>();
        if (!(value instanceof Map<?, ?>)) {
            return map;
        }
        Map<?, ?> rawMap = (Map<?, ?>) value;
        for (Map.Entry<?, ?> entry : rawMap.entrySet()) {
            if (entry.getKey() == null) {
                continue;
            }
            Object entryValue = entry.getValue();
            if (entryValue == null) {
                continue;
            }
            if (entryValue instanceof String && StrUtil.isBlank((String) entryValue)) {
                continue;
            }
            map.put(String.valueOf(entry.getKey()), entryValue);
        }
        return map;
    }

    private List<String> asStringList(Object value) {
        List<String> items = new ArrayList<>();
        if (value instanceof Iterable<?>) {
            for (Object item : (Iterable<?>) value) {
                String text = normalize(item == null ? null : String.valueOf(item));
                if (StrUtil.isBlank(text) || items.contains(text)) {
                    continue;
                }
                items.add(text);
            }
            return items;
        }
        if (value != null) {
            String text = normalize(String.valueOf(value));
            if (StrUtil.isNotBlank(text)) {
                items.add(text);
            }
        }
        return items;
    }

    private AiShopCard toShopCard(Map<String, Object> item) {
        AiShopCard card = new AiShopCard();
        card.setId(toLong(item.get("id"), item.get("shop_id"), item.get("shopId")));
        card.setName(StringUtils.firstNonBlank(asString(item, "name"), asString(item, "title")));
        card.setArea(StringUtils.firstNonBlank(asString(item, "area")));
        card.setAddress(StringUtils.firstNonBlank(asString(item, "address")));
        card.setAvgPrice(toLong(item.get("avgPrice"), item.get("avg_price"), item.get("avg_price_yuan")));
        card.setScore(toDouble(item.get("score")));
        card.setComments(toInteger(item.get("comments")));
        card.setOpenHours(StringUtils.firstNonBlank(asString(item, "openHours"), asString(item, "open_hours")));
        card.setImage(StringUtils.firstNonBlank(asString(item, "image"), asString(item, "cover")));
        card.setDistance(toDouble(item.get("distance"), item.get("distance_km")));
        card.setReason(StringUtils.firstNonBlank(asString(item, "reason"), asString(item, "explanation")));
        return card;
    }

    private AiVoucherCard toVoucherCard(Map<String, Object> item) {
        AiVoucherCard card = new AiVoucherCard();
        card.setId(toLong(item.get("id")));
        card.setShopId(toLong(item.get("shopId"), item.get("shop_id")));
        card.setShopName(StringUtils.firstNonBlank(asString(item, "shopName"), asString(item, "shop_name")));
        card.setTitle(StringUtils.firstNonBlank(asString(item, "title")));
        card.setSubTitle(StringUtils.firstNonBlank(asString(item, "subTitle"), asString(item, "sub_title")));
        card.setPayValue(toLong(item.get("payValue"), item.get("pay_value")));
        card.setActualValue(toLong(item.get("actualValue"), item.get("actual_value")));
        card.setStock(toInteger(item.get("stock")));
        card.setBeginTime(StringUtils.firstNonBlank(asString(item, "beginTime"), asString(item, "begin_time")));
        card.setEndTime(StringUtils.firstNonBlank(asString(item, "endTime"), asString(item, "end_time")));
        card.setRules(StringUtils.firstNonBlank(asString(item, "rules")));
        return card;
    }

    private Long toLong(Object... values) {
        if (values == null) {
            return null;
        }
        for (Object value : values) {
            if (value == null) {
                continue;
            }
            if (value instanceof Number) {
                return ((Number) value).longValue();
            }
            String text = normalize(String.valueOf(value));
            if (StrUtil.isBlank(text)) {
                continue;
            }
            try {
                return Long.parseLong(text);
            } catch (NumberFormatException ignore) {
                try {
                    return Math.round(Double.parseDouble(text));
                } catch (NumberFormatException ignored) {
                    // continue
                }
            }
        }
        return null;
    }

    private Integer toInteger(Object... values) {
        Long value = toLong(values);
        return value == null ? null : value.intValue();
    }

    private Double toDouble(Object... values) {
        if (values == null) {
            return null;
        }
        for (Object value : values) {
            if (value == null) {
                continue;
            }
            if (value instanceof Number) {
                return ((Number) value).doubleValue();
            }
            String text = normalize(String.valueOf(value));
            if (StrUtil.isBlank(text)) {
                continue;
            }
            try {
                return Double.parseDouble(text);
            } catch (NumberFormatException ignore) {
                // continue
            }
        }
        return null;
    }


    private String normalize(String message) {
        return message == null ? "" : message.trim();
    }

    private Map<String, Object> normalizeContext(Map<String, Object> context) {
        return context == null ? new LinkedHashMap<>() : new LinkedHashMap<>(context);
    }

    private String asString(Map<String, Object> context, String key) {
        if (context == null) {
            return null;
        }
        Object value = context.get(key);
        return value == null ? null : String.valueOf(value);
    }
}
