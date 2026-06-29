package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertTrue;

class AgentCouponContractTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void couponDtoExposesSnakeCaseContractFields() throws Exception {
        AgentCouponDTO dto = new AgentCouponDTO();
        dto.setCouponId("coupon_1");
        dto.setShopId("shop_1");
        dto.setTitle("满200减30");
        dto.setDescription("周一可用");
        dto.setDiscountType("fixed");
        dto.setDiscountValue(30.0);
        dto.setMinConsume(200.0);
        dto.setValidFrom("2026-06-01T00:00:00");
        dto.setValidUntil("2026-06-30T23:59:59");
        dto.setStock(12);
        dto.setPayValue(17000L);
        dto.setActualValue(20000L);
        dto.setStatus("available");

        String json = mapper.writeValueAsString(dto);

        assertTrue(json.contains("\"coupon_id\""));
        assertTrue(json.contains("\"discount_type\""));
        assertTrue(json.contains("\"discount_value\""));
        assertTrue(json.contains("\"min_consume\""));
        assertTrue(json.contains("\"valid_from\""));
        assertTrue(json.contains("\"valid_until\""));
        assertTrue(json.contains("\"stock\""));
    }
}
