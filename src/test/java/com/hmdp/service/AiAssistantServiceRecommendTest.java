package com.hmdp.service;

import com.hmdp.ai.query.AiBusinessQueryFacade;
import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.ai.query.AiRouteType;
import com.hmdp.ai.remote.AiRemoteChatResult;
import com.hmdp.ai.remote.AiRemoteClient;
import com.hmdp.dto.UserDTO;
import com.hmdp.dto.ai.AiChatRequest;
import com.hmdp.dto.ai.AiChatResponse;
import com.hmdp.entity.Shop;
import com.hmdp.service.AiAssistantUnavailableException;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AiAssistantServiceRecommendTest {

    @Test
    void shouldMapRemoteStructuredPayloadToResponseCardsAndSteps() {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        AiRemoteClient remoteClient = mock(AiRemoteClient.class);
        AiAssistantService service = new AiAssistantService();
        ReflectionTestUtils.setField(service, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(service, "aiRemoteClient", remoteClient);

        Map<String, Object> contextMap = new HashMap<>();
        contextMap.put("page", "home");
        contextMap.put("location", "杭州");
        contextMap.put("typeName", "火锅");

        AiQueryContext queryContext = AiQueryContext.from(contextMap, buildUser());

        AiRemoteChatResult remoteResult = new AiRemoteChatResult();
        remoteResult.setSuccess(true);
        remoteResult.setAnswer("我按你的条件筛了一下。");
        remoteResult.setMode("recommend");
        remoteResult.setSource("learning-agent-service");
        remoteResult.setPage("home");
        remoteResult.setCurrentTopic("示例粤菜馆");
        remoteResult.getMetadata().put("next_steps", Arrays.asList("查看第一家详情", "看优惠券"));
        remoteResult.getMetadata().put("task_chain", Collections.singletonList(linkedMap(
                "step", "search",
                "label", "已完成候选店搜索",
                "status", "done"
        )));
        remoteResult.getMetadata().put("suggested_replies", Collections.singletonList(linkedMap(
                "label", "看第二家",
                "prompt", "看第二家"
        )));
        remoteResult.getMetadata().put("cards", Collections.singletonList(linkedMap(
                "type", "shop_card",
                "shop_id", 1001,
                "title", "示例粤菜馆",
                "subtitle", "1.2km · 人均148元 · 评分4.8",
                "badges", Arrays.asList("安静", "适合家庭"),
                "reason", "环境安静，适合家庭聚餐.",
                "actions", Arrays.asList(
                        linkedMap("type", "open_shop", "label", "查看详情", "payload", linkedMap("shop_id", 1001)),
                        linkedMap("type", "claim_coupon", "label", "领券", "payload", linkedMap("shop_id", 1001))
                )
        )));
        remoteResult.getMetadata().put("shops", Collections.singletonList(linkedMap(
                "id", 1001,
                "name", "示例粤菜馆",
                "area", "西湖区",
                "address", "杭州西湖区文三路",
                "avgPrice", 148,
                "score", 4.8,
                "comments", 256,
                "openHours", "10:00-22:00",
                "image", "https://example.com/shop.png",
                "distance", 1.2,
                "reason", "环境安静，适合家庭聚餐。"
        )));
        remoteResult.getMetadata().put("vouchers", Collections.singletonList(linkedMap(
                "id", 2001,
                "shopId", 1001,
                "shopName", "示例粤菜馆",
                "title", "满100减20",
                "subTitle", "家庭聚餐券",
                "payValue", 100,
                "actualValue", 80
        )));

        when(remoteClient.isEnabled()).thenReturn(true);
        when(queryFacade.resolveContext(any(Map.class), any(UserDTO.class))).thenReturn(queryContext);
        when(queryFacade.resolveRoute(anyString(), any(AiQueryContext.class))).thenReturn(AiRouteType.RECOMMEND);
        when(remoteClient.chat(any())).thenReturn(remoteResult);

        AiChatRequest request = new AiChatRequest();
        request.setMessage("推荐附近餐厅");
        request.setContext(contextMap);
        request.setPage("home");

        AiChatResponse response = service.chat(request, buildUser());

        assertNotNull(response);
        assertFalse(response.isFallback());
        assertEquals("recommend", response.getMode());
        assertEquals("learning-agent-service", response.getSource());
        assertEquals(1, response.getShops().size());
        assertEquals(1, response.getVouchers().size());
        assertEquals(1, response.getCards().size());
        assertEquals(2, response.getNextSteps().size());
        assertEquals("查看第一家详情", response.getNextSteps().get(0));
        assertEquals(1, response.getTaskChain().size());
        assertTrue(response.getSuggestions().stream().anyMatch(s -> "看第二家".equals(s.getLabel())));
    }

    @Test
    void shouldFailFaqWhenRemoteAssistantUnavailable() {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        AiRemoteClient remoteClient = mock(AiRemoteClient.class);
        AiAssistantService service = new AiAssistantService();
        ReflectionTestUtils.setField(service, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(service, "aiRemoteClient", remoteClient);

        Map<String, Object> contextMap = new HashMap<>();
        contextMap.put("page", "ai");
        AiQueryContext queryContext = AiQueryContext.from(contextMap, buildUser());

        when(remoteClient.isEnabled()).thenReturn(false);
        when(remoteClient.getAvailabilityReason()).thenReturn("learning-agent-service disabled");
        when(queryFacade.resolveContext(any(Map.class), any(UserDTO.class))).thenReturn(queryContext);
        when(queryFacade.resolveRoute(anyString(), any(AiQueryContext.class))).thenReturn(AiRouteType.FAQ);

        AiChatRequest request = new AiChatRequest();
        request.setMessage("今天天气怎么样");
        request.setContext(contextMap);
        request.setPage("ai");

        AiAssistantUnavailableException error = assertThrows(
                AiAssistantUnavailableException.class,
                () -> service.chat(request, buildUser())
        );
        assertTrue(error.getMessage().contains("当前 AI 助手暂时不可用"));
        assertTrue(error.getMessage().contains("FAQ"));
        assertTrue(error.getMessage().contains("ai"));
        assertTrue(error.getMessage().contains("learning-agent-service disabled"));
    }

    private UserDTO buildUser() {
        UserDTO user = new UserDTO();
        user.setId(1L);
        user.setNickName("小明");
        return user;
    }

    private Map<String, Object> linkedMap(Object... entries) {
        Map<String, Object> map = new java.util.LinkedHashMap<>();
        for (int i = 0; i + 1 < entries.length; i += 2) {
            map.put(String.valueOf(entries[i]), entries[i + 1]);
        }
        return map;
    }
}
