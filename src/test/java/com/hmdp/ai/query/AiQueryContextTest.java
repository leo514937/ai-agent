package com.hmdp.ai.query;

import com.hmdp.dto.UserDTO;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AiQueryContextTest {

    @Test
    void shouldNormalizeUserAndShopContext() {
        Map<String, Object> context = new HashMap<>();
        context.put("page", "shop-detail");
        context.put("shopId", "12");
        context.put("shopName", "海底捞");
        context.put("typeName", "火锅");

        UserDTO user = new UserDTO();
        user.setId(1L);
        user.setNickName("小明");

        AiQueryContext queryContext = AiQueryContext.from(context, user);

        assertEquals("shop-detail", queryContext.getPage());
        assertEquals(Long.valueOf(12L), queryContext.getShopId());
        assertEquals("海底捞", queryContext.getShopName());
        assertEquals("火锅", queryContext.getTypeName());
        assertEquals(Long.valueOf(1L), queryContext.getUserId());
        assertEquals("小明", queryContext.getUserNickName());
        assertTrue(queryContext.hasShopContext());
        assertTrue(queryContext.hasTypeContext());
    }
}
