package com.hmdp.ai.query;

import com.hmdp.dto.UserDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AiQueryContextNormalizationTest {

    @Test
    void shouldNormalizeAnchorComparisonAndConstraints() {
        Map<String, Object> context = new HashMap<>();
        context.put("currentShopId", "12");
        context.put("currentShopName", "海底捞水晶城店");
        context.put("current_shop_anchor", linkedMap(
                "shop_id", 12L,
                "name", "海底捞水晶城店"
        ));
        context.put("comparisonTargets", Arrays.asList("巴奴", "小龙坎"));
        context.put("currentConstraints", linkedMap("scene", "date"));
        context.put("needsClarification", false);
        context.put("followUpKind", "entity_reference");

        UserDTO currentUser = new UserDTO();
        currentUser.setId(99L);
        currentUser.setNickName("测试用户");

        AiQueryContext queryContext = AiQueryContext.from(context, currentUser);

        assertEquals(Long.valueOf(12L), queryContext.getShopId());
        assertEquals("海底捞水晶城店", queryContext.getShopName());
        assertTrue(queryContext.hasShopContext());
        assertTrue(queryContext.hasComparisonContext());
        assertTrue(queryContext.hasConstraintContext());
        assertFalse(queryContext.requiresClarification());
        assertEquals("entity_reference", queryContext.getFollowUpKind());
        assertEquals("date", queryContext.getCurrentConstraints().get("scene"));
        assertEquals("海底捞水晶城店", queryContext.getCurrentShopAnchor().get("name"));
        assertEquals(Long.valueOf(99L), queryContext.getUserId());
        assertEquals("测试用户", queryContext.getUserNickName());
    }

    private Map<String, Object> linkedMap(Object... entries) {
        Map<String, Object> map = new HashMap<>();
        for (int i = 0; i + 1 < entries.length; i += 2) {
            map.put(String.valueOf(entries[i]), entries[i + 1]);
        }
        return map;
    }
}
